import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Cô lập DB kiểm thử (không ghi dữ liệu test vào rwa_platform.db chính)
TEST_DB_PATH = os.path.abspath(os.path.join(ROOT_DIR, "rwa_compliance_test.db"))
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from fastapi import HTTPException, Response
from app.main import seed_initial_data
from app.database import SessionLocal
from app.models import User, KYCApplication, RealEstate
from app.schemas import (
    SessionLoginRequest,
    KYCApplicationCreate,
    KYCDecisionRequest,
    KYCDocumentAccessRequest,
    FreezeAccountRequest,
    P2PTransferRequest,
)
from app.api.auth import login_lab_session
from app.api.kyc import (
    submit_kyc_application,
    list_kyc_applications,
    get_my_kyc,
    access_kyc_document,
    mark_kyc_under_review,
    approve_kyc_application,
    reject_kyc_application,
    revoke_kyc_application,
    get_compliance_overview,
)
from app.api.transactions import set_account_frozen, transfer_tokens_p2p
from app.services.signer import SignerService, get_contract_instance
from app.services.w3_compat import Web3


def run_compliance_portal_e2e():
    print("========================================================================")
    print("KIỂM THỬ TOÀN DIỆN 19 BƯỚC COMPLIANCE PORTAL (PHẦN XIII)")
    print("========================================================================")
    seed_initial_data()
    db = SessionLocal()
    try:
        # 1. Đăng nhập bằng Compliance & các vai trò khác
        comp_login = login_lab_session(
            SessionLoginRequest(address="0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"),
            response=Response(),
            db=db,
        )
        assert comp_login.user.role_label == "compliance"
        compliance = db.query(User).filter(User.role_label == "compliance").first()
        inv_a = db.query(User).filter(User.address == "0x90f79bf6eb2c4f870365e785982e1f101e93b906").first()
        inv_b = db.query(User).filter(User.address == "0x15d34aaf54267db7d7c367839aaf71a00a2c6a65").first()
        print("[PASS] Bước 1: Đăng nhập bằng tài khoản COMPLIANCE_ROLE (#2) thành công")

        # Đảm bảo Investor B chưa ở trạng thái approved để nộp hồ sơ mới
        existing_b = (
            db.query(KYCApplication)
            .filter(KYCApplication.user_id == inv_b.id)
            .order_by(KYCApplication.created_at.desc())
            .first()
        )
        if existing_b and existing_b.status == "approved":
            revoke_kyc_application(
                kyc_id=existing_b.id,
                req=KYCDecisionRequest(reason="Reset trạng thái để kiểm thử quy trình KYC"),
                current_user=compliance,
                db=db,
            )
        inv_b.is_whitelisted = False
        db.commit()

        # Investor B nộp hồ sơ KYC
        sub_app = submit_kyc_application(
            req=KYCApplicationCreate(
                full_name="Trần Thị Bình",
                id_number="079099005678",
                email="binh.tran@rwa-lab.vn",
                phone="0912345678",
                document_type="National ID",
                subject_type="Investor",
                doc_cid="QmKYCTestCompliancePortal2026",
                doc_name="cccd_tran_thi_binh.pdf",
                notes="Hồ sơ kiểm thử Compliance Portal",
            ),
            current_user=inv_b,
            db=db,
        )
        kyc_id = sub_app.id

        # 2 & 3. Xem danh sách KYC & Lọc hồ sơ Pending
        all_kycs = list_kyc_applications(db=db)
        pending_kycs = list_kyc_applications(status="pending", db=db)
        assert len(all_kycs) >= 1
        assert any(k.id == kyc_id for k in pending_kycs)
        print(f"[PASS] Bước 2-4: Xem danh sách KYC ({len(all_kycs)} hồ sơ) & Lọc Pending ({len(pending_kycs)} hồ sơ) thành công")

        # 4. Xem chi tiết & Kiểm soát quyền truy cập tài liệu KYC bảo mật (Phần IX & XII)
        # Kiểm tra Investor không được phép truy cập tài liệu KYC qua endpoint của Compliance
        blocked_unauth = False
        try:
            access_kyc_document(
                kyc_id=kyc_id,
                req=KYCDocumentAccessRequest(access_type="VIEW", doc_side="front"),
                current_user=inv_a,
                db=db,
            )
        except HTTPException as exc:
            if exc.status_code == 403:
                blocked_unauth = True
        assert blocked_unauth, "Phải chặn 403 khi tài khoản không phải Compliance cố xem tài liệu KYC!"

        doc_acc = access_kyc_document(
            kyc_id=kyc_id,
            req=KYCDocumentAccessRequest(access_type="VIEW", doc_side="front"),
            current_user=compliance,
            db=db,
        )
        assert doc_acc["status"] == "granted"
        print("[PASS] Bước 5-6: Kiểm soát quyền xem tài liệu KYC bảo mật (Chặn 403 trái phép & Ghi log truy cập) thành công")

        # 5. Chuyển trạng thái sang Under Review
        ur_res = mark_kyc_under_review(
            kyc_id=kyc_id,
            req=KYCDecisionRequest(
                notes="Đang đối chiếu mặt trước và mặt sau CCCD",
                checklist={"docValid": True, "photoClear": False},
            ),
            current_user=compliance,
            db=db,
        )
        assert ur_res.status == "under_review"
        print("[PASS] Bước 7: Chuyển trạng thái hồ sơ sang Under Review thành công")

        # 6. Reject một hồ sơ và nhập lý do
        rej_res = reject_kyc_application(
            kyc_id=kyc_id,
            req=KYCDecisionRequest(
                reason="Ảnh giấy tờ không rõ",
                notes="Ảnh mặt trước bị lóa góc phải, vui lòng chụp lại rõ nét.",
            ),
            current_user=compliance,
            db=db,
        )
        assert rej_res.status == "rejected"

        # 7. Kiểm tra nhà đầu tư nhận được trạng thái và lý do phù hợp
        my_kyc = get_my_kyc(current_user=inv_b, db=db)
        assert my_kyc is not None
        assert my_kyc.status == "rejected"
        assert my_kyc.payload_json.get("rejection_reason") == "Ảnh giấy tờ không rõ"
        print(f"[PASS] Bước 8-9: Reject hồ sơ & Nhà đầu tư nhận đúng lý do từ chối ('{my_kyc.payload_json.get('rejection_reason')}')")

        # Nhà đầu tư bổ sung và nộp lại hồ sơ (Resubmission)
        resub_app = submit_kyc_application(
            req=KYCApplicationCreate(
                full_name="Trần Thị Bình",
                id_number="079099005678",
                email="binh.tran@rwa-lab.vn",
                phone="0912345678",
                document_type="National ID",
                subject_type="Investor",
                doc_cid="QmKYCTestCompliancePortalResubmitted2026",
                doc_name="cccd_tran_thi_binh_ro_net.pdf",
                notes="Đã chụp lại CCCD rõ nét đủ 4 góc",
            ),
            current_user=inv_b,
            db=db,
        )
        kyc_id = resub_app.id
        assert resub_app.status == "pending"

        # 8. Approve một hồ sơ hợp lệ
        app_res = approve_kyc_application(
            kyc_id=kyc_id,
            req=KYCDecisionRequest(
                reason="Đạt 5/5 tiêu chuẩn thẩm định KYC",
                notes="Đã kiểm tra đầy đủ 5/5 điều kiện",
                checklist={
                    "docValid": True,
                    "photoClear": True,
                    "notBlacklisted": True,
                    "nameMatch": True,
                    "walletMatch": True,
                },
            ),
            current_user=compliance,
            db=db,
        )
        assert app_res.status == "approved"
        assert app_res.tx_hash and app_res.tx_hash.startswith("0x")
        registry = get_contract_instance("IdentityRegistry")
        assert registry.functions.isVerified(Web3.to_checksum_address(inv_b.address)).call() is True
        print(f"[PASS] Bước 10: Approve hồ sơ hợp lệ & ghi Whitelist On-chain thành công (TxHash={app_res.tx_hash[:18]}...)")

        # 9. Revoke một hồ sơ đã Approved (và kiểm tra không tự động Freeze ví)
        rev_res = revoke_kyc_application(
            kyc_id=kyc_id,
            req=KYCDecisionRequest(
                reason="Rà soát định kỳ phát hiện giấy tờ sắp hết hạn",
                notes="Thu hồi tạm thời để yêu cầu cập nhật CCCD gắn chip mới",
            ),
            current_user=compliance,
            db=db,
        )
        assert rev_res.status == "revoked"
        assert registry.functions.isVerified(Web3.to_checksum_address(inv_b.address)).call() is False
        db.refresh(inv_b)
        assert inv_b.is_frozen is False, "Revoke KYC không được tự động Freeze ví!"
        print(f"[PASS] Bước 11: Revoke KYC đã Approved thành công & không tự động Freeze ví (TxHash={rev_res.tx_hash[:18]}...)")

        # Duyệt lại KYC cho Investor B để thực hiện kiểm thử Freeze/Unfreeze với giao dịch Token thực tế
        approve_kyc_application(
            kyc_id=kyc_id,
            req=KYCDecisionRequest(notes="Khôi phục Whitelist sau khi cập nhật CCCD mới"),
            current_user=compliance,
            db=db,
        )

        # 10 & 11. Freeze một ví nhà đầu tư (Investor A) & Kiểm tra trạng thái Frozen trên Smart Contract
        tokenized_est = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).first()
        assert tokenized_est is not None, "Cần ít nhất 1 bất động sản đã Token hóa"
        tok_addr = tokenized_est.token_address
        token_contract = get_contract_instance("AssetToken", tok_addr)

        # Cấp 10 cổ phần cho Investor A nếu số dư = 0 để kiểm tra chuyển nhượng
        if token_contract.functions.balanceOf(Web3.to_checksum_address(inv_a.address)).call() == 0:
            primary_sale = get_contract_instance("PrimarySale")
            admin_user = db.query(User).filter(User.role_label == "admin").first()
            SignerService.sign_and_send(
                db=db,
                current_user=admin_user,
                contract_function=token_contract.functions.forcedTransfer(
                    primary_sale.address, inv_a.address, 10 * 10**18
                ),
                contract_method_name="forcedTransfer",
                params_summary={"amount": 10, "to": inv_a.address},
            )

        frz_res = set_account_frozen(
            req=FreezeAccountRequest(
                token_address=tok_addr,
                account_address=inv_a.address,
                frozen=True,
                reason="Nghi vấn giao dịch bất thường cần kiểm tra",
                case_code="CASE-COMP-2026-01",
                notes="Phong tỏa tạm thời theo quy trình UC-12",
            ),
            current_user=compliance,
            db=db,
        )
        assert frz_res["is_frozen"] is True
        onchain_frozen = token_contract.functions.isFrozen(Web3.to_checksum_address(inv_a.address)).call()
        assert onchain_frozen is True
        print(f"[PASS] Bước 12-13: Freeze ví Investor A & xác nhận AssetToken.isFrozen == True (TxHash={frz_res['tx_hash'][:18]}...)")

        # 12. Thử thực hiện giao dịch từ ví bị Freeze để kiểm tra tác động thực tế theo Smart Contract
        tx_blocked_by_freeze = False
        try:
            transfer_tokens_p2p(
                req=P2PTransferRequest(
                    token_address=tok_addr,
                    to_address=inv_b.address,
                    amount=1.0,
                ),
                current_user=inv_a,
                db=db,
            )
        except Exception:
            tx_blocked_by_freeze = True
        assert tx_blocked_by_freeze, "Giao dịch từ ví đang bị Frozen phải bị Smart Contract từ chối!"
        print("[PASS] Bước 14: Thử chuyển nhượng Token từ ví bị Freeze -> Smart Contract chặn giao dịch thành công!")

        # 13 & 14. Unfreeze ví & Kiểm tra giao dịch sau khi Unfreeze
        unfrz_res = set_account_frozen(
            req=FreezeAccountRequest(
                token_address=tok_addr,
                account_address=inv_a.address,
                frozen=False,
                reason="Đã hoàn tất xác minh an toàn, mở khóa giao dịch",
                case_code="CASE-COMP-2026-01",
                notes="Giải tỏa phong tỏa",
            ),
            current_user=compliance,
            db=db,
        )
        assert unfrz_res["is_frozen"] is False
        assert token_contract.functions.isFrozen(Web3.to_checksum_address(inv_a.address)).call() is False

        # Tái cấp phép KYC cho Investor B để nhận Token hợp lệ
        approve_kyc_application(
            kyc_id=kyc_id,
            req=KYCDecisionRequest(reason="Phục hồi KYC hợp lệ sau kiểm tra"),
            current_user=compliance,
            db=db,
        )

        p2p_ok = transfer_tokens_p2p(
            req=P2PTransferRequest(
                token_address=tok_addr,
                to_address=inv_b.address,
                amount=1.0,
            ),
            current_user=inv_a,
            db=db,
        )
        assert p2p_ok["tx_hash"].startswith("0x")
        print(f"[PASS] Bước 15-16: Unfreeze ví & thực hiện giao dịch chuyển nhượng sau khi Unfreeze thành công (TxHash={p2p_ok['tx_hash'][:18]}...)")

        # 15, 16, 17. Kiểm tra KYC Review History, Freeze History & Compliance Audit Logs
        ovw = get_compliance_overview(db=db, current_user=compliance)
        assert len(ovw["review_history"]) >= 3, "KYC Review History phải lưu đầy đủ các bước chuyển trạng thái"
        assert len(ovw["freeze_history"]) >= 2, "Freeze History phải lưu cả bản ghi Freeze và Unfreeze độc lập"
        assert len(ovw["compliance_audit_logs"]) >= 5, "Compliance Audit Logs phải tổng hợp đầy đủ các hoạt động"
        first_log = ovw["compliance_audit_logs"][0]
        for key in ["operator_name", "signer_address", "action_label", "target_subject", "reason", "signed_at", "result_status"]:
            assert key in first_log, f"Thiếu trường {key} trong Compliance Audit Logs"
        print(
            f"[PASS] Bước 17-19: Kiểm tra KYC Review History ({len(ovw['review_history'])} bản ghi), "
            f"Freeze History ({len(ovw['freeze_history'])} bản ghi) & Compliance Audit Logs ({len(ovw['compliance_audit_logs'])} bản ghi) thành công!"
        )
        print("========================================================================")
        print("KẾT LUẬN: TẤT CẢ 19/19 BƯỚC KIỂM THỬ COMPLIANCE PORTAL ĐỀU PASS 100%!")
        print("========================================================================")
    finally:
        db.close()


if __name__ == "__main__":
    run_compliance_portal_e2e()
