import os
import sys
from fastapi import HTTPException, Response

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

TEST_DB_PATH = os.path.abspath(os.path.join(ROOT_DIR, "rwa_improvements_test.db"))
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from app.main import seed_initial_data
from app.database import SessionLocal
from app.models import User, RealEstate, KYCApplication
from app.services.ipfs import store_encrypted_kyc_document, read_encrypted_kyc_document, KYC_ENCRYPTED_VAULT_DIR
from app.services.signer import SignerService, get_contract_instance
from app.services.w3_compat import Web3
from app.api.kyc import (
    download_decrypted_kyc_document,
    export_kyc_history_csv,
    export_compliance_audit_logs_csv,
)
from app.api.dividends import (
    DividendDistributeRequest,
    distribute_dividend,
    list_dividend_distributions,
    list_my_dividends,
)
from app.api.notifications import (
    list_my_notifications,
    mark_notification_read,
    mark_all_notifications_read,
)
from app.api.system import get_system_sync_status, reconcile_db_with_chain


def run_improvements_e2e():
    print("========================================================================")
    print("KIỂM THỬ CÁC TÍNH NĂNG CẢI TIẾN MỚI (VAULT, DIVIDEND, NOTIF, CSV, SYNC)")
    print("========================================================================")
    seed_initial_data()
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.role_label == "admin").first()
        issuer = db.query(User).filter(User.role_label == "issuer").first()
        compliance = db.query(User).filter(User.role_label == "compliance").first()
        inv_a = db.query(User).filter(User.address == "0x90f79bf6eb2c4f870365e785982e1f101e93b906").first()

        # 1. Kiểm thử mã hóa AES-256-GCM KYC Vault
        secret_doc = b"CCCD MAT TRUOC: NGUYEN VAN AN - 001099012345 - BAO MAT TUYET DOI"
        stored = store_encrypted_kyc_document(secret_doc, "cccd_secret.pdf")
        assert stored["encrypted"] is True
        assert stored["cipher"] == "AES-256-GCM"
        enc_file = os.path.join(KYC_ENCRYPTED_VAULT_DIR, f"{stored['doc_cid']}.enc")
        assert os.path.exists(enc_file)
        with open(enc_file, "rb") as f:
            raw_on_disk = f.read()
        assert secret_doc not in raw_on_disk, "File trên đĩa phải ở dạng mã hóa, không được lộ plaintext!"
        decrypted, was_enc = read_encrypted_kyc_document(stored["doc_cid"])
        assert was_enc is True and decrypted == secret_doc
        print(f"[PASS] 1. Mã hóa & giải mã KYC Vault AES-256-GCM thành công (ID={stored['doc_cid']})")

        # Kiểm tra RBAC khi tải file giải mã
        kyc_row = db.query(KYCApplication).first()
        blocked = False
        try:
            download_decrypted_kyc_document(kyc_id=kyc_row.id, current_user=inv_a, db=db)
        except HTTPException as exc:
            blocked = exc.status_code == 403
        assert blocked, "Investor không được phép giải mã tải tài liệu KYC!"
        dl_resp = download_decrypted_kyc_document(kyc_id=kyc_row.id, current_user=compliance, db=db)
        assert dl_resp.status_code == 200
        print("[PASS] 2. Kiểm soát RBAC giải mã KYC Vault (403 cho Investor, 200 cho Compliance) thành công")

        # 2. Kiểm thử Đồng bộ Chain-DB (System Sync & Reconcile)
        sync_before = get_system_sync_status(db=db)
        assert sync_before["rpc_connected"] is True
        rec = reconcile_db_with_chain(current_user=admin, db=db)
        assert rec["sync_report"]["status"] == "SYNCED", f"Expected SYNCED, got {rec['sync_report']}"
        print(f"[PASS] 3. Chain-DB Sync & Reconcile thành công (Block #{rec['sync_report']['block_number']}, status=SYNCED)")

        # 3. Kiểm thử Phân phối cổ tức mUSDC on-chain (Dividend Distribution)
        est = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).first()
        tok = get_contract_instance("AssetToken", est.token_address)
        usdc = get_contract_instance("MockUSDC")

        # Đảm bảo Investor A có cổ phần của VINH01 để nhận cổ tức
        if tok.functions.balanceOf(Web3.to_checksum_address(inv_a.address)).call() == 0:
            ps = get_contract_instance("PrimarySale")
            SignerService.sign_and_send(
                db=db,
                current_user=admin,
                contract_function=tok.functions.forcedTransfer(ps.address, inv_a.address, 25 * 10**18),
                contract_method_name="forcedTransfer",
                params_summary={"amount": 25, "to": inv_a.address},
            )

        usdc_before = usdc.functions.balanceOf(Web3.to_checksum_address(inv_a.address)).call()
        dist_res = distribute_dividend(
            req=DividendDistributeRequest(
                real_estate_id=est.id,
                total_amount_usdc=1200.0,
                period_label="Q4/2026 - Doanh thu cho thuê Penthouse",
                notes="Phân phối lợi tức thực nghiệm on-chain",
            ),
            current_user=issuer,
            db=db,
        )
        assert dist_res["recipients_count"] >= 1
        assert dist_res["payouts"][0]["tx_hash"].startswith("0x")
        usdc_after = usdc.functions.balanceOf(Web3.to_checksum_address(inv_a.address)).call()
        assert usdc_after > usdc_before, "Số dư mUSDC on-chain của Investor A phải tăng lên sau khi chia cổ tức!"

        all_dists = list_dividend_distributions(db=db)
        assert all_dists["total_distributions"] >= 1
        my_divs = list_my_dividends(current_user=inv_a, db=db)
        assert my_divs["total_received_usdc"] > 0
        print(
            f"[PASS] 4. Phân phối cổ tức {dist_res['total_amount_usdc']} mUSDC on-chain thành công "
            f"(Investor A nhận +{my_divs['total_received_usdc']:,.2f} mUSDC, Tx={dist_res['payouts'][0]['tx_hash'][:18]}...)"
        )

        # 4. Kiểm thử Notification Center
        notifs = list_my_notifications(current_user=inv_a, db=db)
        assert notifs["unread_count"] >= 1
        first_id = notifs["items"][0]["id"]
        mark_notification_read(notif_id=first_id, current_user=inv_a, db=db)
        mark_all_notifications_read(current_user=inv_a, db=db)
        notifs_after = list_my_notifications(current_user=inv_a, db=db)
        assert notifs_after["unread_count"] == 0
        print(f"[PASS] 5. Hệ thống Thông báo (Notifications) hoạt động chính xác ({len(notifs['items'])} thông báo)")

        # 5. Kiểm thử xuất báo cáo CSV UTF-8 BOM
        csv_kyc = export_kyc_history_csv(current_user=compliance, db=db)
        assert csv_kyc.body.startswith(b"\xef\xbb\xbf")
        csv_audit = export_compliance_audit_logs_csv(current_user=compliance, db=db)
        assert csv_audit.body.startswith(b"\xef\xbb\xbf")
        print("[PASS] 6. Xuất báo cáo CSV (KYC Review History & Compliance Audit Logs) UTF-8 BOM thành công")

        print("========================================================================")
        print("KẾT LUẬN: TẤT CẢ 6/6 KIỂM THỬ CẢI TIẾN ĐỀU PASS 100%!")
        print("========================================================================")
    finally:
        db.close()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass


if __name__ == "__main__":
    run_improvements_e2e()
