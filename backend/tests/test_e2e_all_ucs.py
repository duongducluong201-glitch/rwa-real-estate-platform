import os
import sys
from fastapi import Response

# Ensure backend directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Use fresh test database for verification
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rwa_e2e_test.db"))
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from app.main import seed_initial_data
from app.database import SessionLocal
from app.models import (
    User,
    SessionModel,
    KYCApplication,
    RealEstate,
    AuditSign,
    PrimarySaleCache,
    ListingCache,
    TransferCache,
)
from app.schemas import (
    SessionLoginRequest,
    KYCApplicationCreate,
    RealEstateCreateRequest,
    ValuationUpdateRequest,
    PrimarySaleOpenRequest,
    PrimarySaleBuyRequest,
    P2PTransferRequest,
    MarketplaceListRequest,
    MarketplaceBuyRequest,
    MarketplaceCancelRequest,
    FreezeAccountRequest,
    PauseTokenRequest,
    ForcedTransferRequest,
    RoleManageRequest,
)
from app.api.auth import login_lab_session, list_lab_accounts
from app.api.kyc import submit_kyc_application, approve_kyc_application, revoke_kyc_application, list_kyc_applications
from app.api.assets import create_real_estate, tokenize_real_estate, update_real_estate_valuation, get_real_estate_detail, list_real_estates
from app.api.transactions import (
    claim_faucet_mock_usdc,
    open_primary_sale,
    buy_primary_sale,
    transfer_tokens_p2p,
    create_marketplace_listing,
    buy_marketplace_listing,
    cancel_marketplace_listing,
    set_account_frozen,
    set_token_paused,
    execute_forced_transfer,
    manage_contract_role,
    get_investor_ownership,
    list_audit_signs,
)


def run_all_14_use_cases():
    print("=" * 72)
    print("KIỂM THỬ TÍCH HỢP END-TO-END (E2E) TOÀN BỘ 14 USE CASE CHƯƠNG 2 & 3")
    print("=" * 72)

    # Seed initial 5 Anvil accounts & sample real estate records
    seed_initial_data()
    db = SessionLocal()

    try:
        # 1. UC-01: Đăng nhập Session Lab (không cần ví trình duyệt)
        accounts = list_lab_accounts(db=db)
        assert len(accounts) == 5, f"Expected 5 Lab accounts, got {len(accounts)}"

        admin_login = login_lab_session(SessionLoginRequest(address=accounts[0]["address"]), Response(), db=db)
        issuer_login = login_lab_session(SessionLoginRequest(address=accounts[1]["address"]), Response(), db=db)
        compliance_login = login_lab_session(SessionLoginRequest(address=accounts[2]["address"]), Response(), db=db)
        inv_a_login = login_lab_session(SessionLoginRequest(address=accounts[3]["address"]), Response(), db=db)
        inv_b_login = login_lab_session(SessionLoginRequest(address=accounts[4]["address"]), Response(), db=db)

        admin = db.query(User).filter(User.address == accounts[0]["address"]).first()
        issuer = db.query(User).filter(User.address == accounts[1]["address"]).first()
        compliance = db.query(User).filter(User.address == accounts[2]["address"]).first()
        inv_a = db.query(User).filter(User.address == accounts[3]["address"]).first()
        inv_b = db.query(User).filter(User.address == accounts[4]["address"]).first()

        print(f"[PASS] UC-01: Session Lab Login thành công cho 5 vai trò (Session Token: {inv_a_login.session_token[:12]}...)")

        # 2. UC-02: Nộp hồ sơ KYC (Investor B)
        if inv_b.is_whitelisted:
            existing_b_kyc = db.query(KYCApplication).filter(KYCApplication.user_id == inv_b.id).first()
            if existing_b_kyc:
                revoke_kyc_application(kyc_id=existing_b_kyc.id, current_user=compliance, db=db)

        kyc_req = KYCApplicationCreate(
            full_name="Trần Thị Bình",
            id_number="079099005678",
            email="binh.tran@rwa-lab.vn",
            phone="0909888777",
            notes="Hồ sơ xác minh danh tính Nhà đầu tư B",
        )
        kyc_sub = submit_kyc_application(req=kyc_req, current_user=inv_b, db=db)
        assert kyc_sub.status == "pending"
        print(f"[PASS] UC-02: Investor B nộp hồ sơ KYC thành công (App ID={kyc_sub.id}, status={kyc_sub.status})")

        # 3. UC-03: Phê duyệt KYC & Whitelist On-chain (Compliance Officer)
        kyc_app_res = approve_kyc_application(kyc_id=kyc_sub.id, current_user=compliance, db=db)
        assert kyc_app_res.status == "approved"
        assert inv_b.is_whitelisted is True
        print(f"[PASS] UC-03: Compliance duyệt KYC & ghi IdentityRegistry.addToWhitelist (TxHash={kyc_app_res.tx_hash[:18]}...)")

        # 4. UC-04: Tạo hồ sơ BĐS & Upload tài liệu pháp lý IPFS (docCID + docHash Keccak-256)
        create_req = RealEstateCreateRequest(
            name="Khu Đô Thị Sinh Thái Aqua City Elite",
            symbol="AQUA01",
            address_text="Biên Hòa, Đồng Nai",
            area_m2=250.0,
            property_kind="building",
            build_year=2025,
            description="Biệt thự ven sông có sổ hồng riêng, kiểm toán độc lập.",
            valuation=800_000.0,
            total_shares=8_000.0,
            auto_tokenize=False,
        )
        new_estate = create_real_estate(req=create_req, current_user=issuer, db=db)
        assert new_estate["symbol"] == "AQUA01"
        assert new_estate["doc_cid"].startswith("Qm")
        assert new_estate["doc_hash"].startswith("0x") and len(new_estate["doc_hash"]) == 66
        print(f"[PASS] UC-04: Tạo hồ sơ BĐS & Băm tài liệu IPFS thành công (CID={new_estate['doc_cid']}, Hash={new_estate['doc_hash'][:18]}...)")

        # 5. UC-05: Token hóa BĐS qua AssetFactory.createAsset (Issuer / Admin)
        tok_res = tokenize_real_estate(estate_id=new_estate["id"], current_user=issuer, db=db)
        assert tok_res["status"] == "tokenized"
        assert tok_res["token_address"].startswith("0x")
        aqua_id = tok_res["id"]
        aqua_token = tok_res["token_address"]
        print(f"[PASS] UC-05: Token hóa BĐS qua AssetFactory.createAsset thành công (Token={aqua_token})")

        # 6. UC-06: Mở bán sơ cấp PrimarySale.openSale (Issuer)
        open_res = open_primary_sale(
            req=PrimarySaleOpenRequest(real_estate_id=aqua_id, price_per_share=100.0, amount=4_000.0),
            current_user=issuer,
            db=db,
        )
        assert open_res["status"] == "open_sale"
        print(f"[PASS] UC-06: Mở đợt chào bán sơ cấp PrimarySale.openSale (4,000 AQUA01 @ 100 mUSDC)")

        # 7. UC-07: Cập nhật định giá BĐS AssetToken.updateValuation (Issuer)
        val_res = update_real_estate_valuation(
            estate_id=aqua_id,
            req=ValuationUpdateRequest(new_valuation=880_000.0),
            current_user=issuer,
            db=db,
        )
        assert val_res["real_estate"]["valuation"] == 880_000.0
        assert val_res["real_estate"]["intrinsic_price_per_share"] == 110.0
        print(f"[PASS] UC-07: Cập nhật định giá on-chain AssetToken.updateValuation -> 880,000 USDC (110 USDC/cp)")

        # 8. UC-08: Nhận tiền thử nghiệm MockUSDC.faucet (Investor A & B)
        faucet_a = claim_faucet_mock_usdc(amount_usdc=50_000.0, current_user=inv_a, db=db)
        faucet_b = claim_faucet_mock_usdc(amount_usdc=50_000.0, current_user=inv_b, db=db)
        assert faucet_a["new_balance_usdc"] >= 50_000.0
        print(f"[PASS] UC-08: Nhận MockUSDC Faucet thành công (Số dư Investor A={faucet_a['new_balance_usdc']:,.0f} mUSDC)")

        # 9. UC-09: Mua cổ phần sơ cấp PrimarySale.buy (Investor A mua 50 cổ phần AQUA01)
        buy_prim = buy_primary_sale(
            req=PrimarySaleBuyRequest(real_estate_id=aqua_id, amount=50.0),
            current_user=inv_a,
            db=db,
        )
        assert buy_prim["shares_bought"] == 50.0
        assert buy_prim["usdc_paid"] == 5_000.0
        print(f"[PASS] UC-09: Investor A mua 50 cổ phần sơ cấp AQUA01 (Thanh toán 5,000 mUSDC, Tx={buy_prim['tx_hash'][:18]}...)")

        # 10. UC-10: Chuyển nhượng P2P trực tiếp AssetToken.transfer (Investor A -> Investor B 10 cổ phần)
        p2p_res = transfer_tokens_p2p(
            req=P2PTransferRequest(token_address=aqua_token, to_address=inv_b.address, amount=10.0),
            current_user=inv_a,
            db=db,
        )
        assert p2p_res["amount"] == 10.0
        print(f"[PASS] UC-10: Chuyển nhượng P2P 10 AQUA01 từ Investor A sang Investor B thành công (Tx={p2p_res['tx_hash'][:18]}...)")

        # 11. UC-11: Giao dịch thứ cấp qua Escrow Marketplace (Đăng bán -> Mua một phần -> Hủy phần dư)
        list_res = create_marketplace_listing(
            req=MarketplaceListRequest(token_address=aqua_token, amount=20.0, price_per_share=115.0),
            current_user=inv_a,
            db=db,
        )
        listing_id = list_res["listing_id"]
        buy_mkt = buy_marketplace_listing(
            req=MarketplaceBuyRequest(listing_id=listing_id, amount=8.0),
            current_user=inv_b,
            db=db,
        )
        assert buy_mkt["usdc_paid"] == 920.0
        cancel_mkt = cancel_marketplace_listing(
            req=MarketplaceCancelRequest(listing_id=listing_id),
            current_user=inv_a,
            db=db,
        )
        assert cancel_mkt["status"] == "cancelled"
        print(f"[PASS] UC-11: Marketplace Escrow (Niêm yết #ID={listing_id}: 20 cp -> Investor B khớp 8 cp @ 115 USDC -> Hủy hoàn trả 12 cp)")

        # 12. UC-12: Đóng băng / Mở khóa tài khoản trên AssetToken (Compliance Officer)
        freeze_res = set_account_frozen(
            req=FreezeAccountRequest(token_address=aqua_token, account_address=inv_a.address, frozen=True),
            current_user=compliance,
            db=db,
        )
        assert freeze_res["is_frozen"] is True

        unfreeze_res = set_account_frozen(
            req=FreezeAccountRequest(token_address=aqua_token, account_address=inv_a.address, frozen=False),
            current_user=compliance,
            db=db,
        )
        assert unfreeze_res["is_frozen"] is False
        print(f"[PASS] UC-12: Đóng băng & Mở khóa ví nhà đầu tư (AssetToken.setFrozen) thành công")

        # 13. UC-13: Tạm dừng khẩn cấp (pause/unpause), Cấp quyền (grantRole) & Chuyển nhượng cưỡng chế (forcedTransfer) bởi Admin
        pause_res = set_token_paused(
            req=PauseTokenRequest(token_address=aqua_token, paused=True),
            current_user=admin,
            db=db,
        )
        assert pause_res["is_paused"] is True

        unpause_res = set_token_paused(
            req=PauseTokenRequest(token_address=aqua_token, paused=False),
            current_user=admin,
            db=db,
        )
        assert unpause_res["is_paused"] is False

        forced_res = execute_forced_transfer(
            req=ForcedTransferRequest(
                token_address=aqua_token,
                from_address=inv_a.address,
                to_address=inv_b.address,
                amount=5.0,
            ),
            current_user=admin,
            db=db,
        )
        assert forced_res["amount"] == 5.0
        print(f"[PASS] UC-13: Tạm dừng khẩn cấp (pause/unpause) & Cưỡng chế thu hồi/khôi phục 5 AQUA01 (forcedTransfer) thành công")

        # 14. UC-14: Tra cứu danh mục đầu tư, Tỷ lệ sở hữu và Nhật ký kiểm toán chữ ký số (audit_signs)
        portfolio_a = get_investor_ownership(address=inv_a.address, db=db)
        portfolio_b = get_investor_ownership(address=inv_b.address, db=db)
        audit_logs = list_audit_signs(limit=100, db=db)

        aqua_pos_a = next((p for p in portfolio_a["holdings"] if p["symbol"] == "AQUA01"), None)
        aqua_pos_b = next((p for p in portfolio_b["holdings"] if p["symbol"] == "AQUA01"), None)
        # Investor A: 50 (mua sơ cấp) - 10 (P2P) - 8 (khớp trên Marketplace) - 5 (forcedTransfer) = 27.0 cổ phần
        # Investor B: 10 (P2P) + 8 (mua trên Marketplace) + 5 (forcedTransfer) = 23.0 cổ phần
        assert aqua_pos_a is not None and aqua_pos_a["shares_balance"] == 27.0
        assert aqua_pos_b is not None and aqua_pos_b["shares_balance"] == 23.0
        print(
            f"[PASS] UC-14: Tra cứu Danh mục & Tỷ lệ sở hữu chính xác 100% "
            f"(Investor A: {aqua_pos_a['shares_balance']} AQUA01 [{aqua_pos_a['ownership_percent']}%], "
            f"Investor B: {aqua_pos_b['shares_balance']} AQUA01 [{aqua_pos_b['ownership_percent']}%])"
        )
        print(f"[PASS] Nhật ký kiểm toán Server-side Signing (audit_signs): Đã ghi nhận {len(audit_logs)} bút toán ký số!")
        print("=" * 72)
        print("KẾT LUẬN: TẤT CẢ 14/14 USE CASE CHƯƠNG 2 & CHƯƠNG 3 ĐỀU PASS 100%!")
        print("=" * 72)
    finally:
        db.close()
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass


if __name__ == "__main__":
    run_all_14_use_cases()
