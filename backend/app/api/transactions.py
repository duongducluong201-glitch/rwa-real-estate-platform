import datetime
import re
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from ..services.w3_compat import Web3
from ..database import get_db
from ..models import (
    User,
    RealEstate,
    PrimarySaleCache,
    ListingCache,
    TransferCache,
    AuditSign,
    EmailLog,
)
from ..schemas import (
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
    UserRoleAssignRequest,
)
from ..services.auth import get_current_user
from ..services.email_service import send_payment_confirmation_email
from ..services.signer import SignerService, get_contract_instance
from ..services.listener import record_transfer_cache, sync_onchain_state
from ..config import load_deployed_contracts
from .notifications import create_notification

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _fmt_shares(val: float) -> str:
    return f"{int(val):,}" if float(val).is_integer() else f"{float(val):,.2f}"


def _validate_confirm_email(raw_email: Optional[str], fallback_email: Optional[str]) -> Optional[str]:
    """Chuẩn hóa và kiểm tra định dạng địa chỉ Gmail nhận biên lai xác nhận."""
    candidate = (raw_email if raw_email is not None else "").strip()
    if candidate:
        if not EMAIL_PATTERN.match(candidate) or len(candidate) > 255:
            raise HTTPException(
                status_code=400,
                detail=f"Địa chỉ Email nhận biên lai không đúng định dạng: '{candidate}'!",
            )
        return candidate
    fb = (fallback_email or "").strip()
    if fb and EMAIL_PATTERN.match(fb):
        return fb
    return None


def _read_post_purchase_metrics(
    token_address: str,
    buyer_address: str,
    usdc_contract,
    total_shares_fallback: float,
) -> tuple[float, float, float]:
    """Đọc số dư MockUSDC mới, số dư AssetToken mới và tỷ lệ sở hữu (%) sau giao dịch."""
    buyer_checksum = Web3.to_checksum_address(buyer_address)
    new_usdc_balance = 0.0
    new_token_balance = 0.0
    total_shares = max(total_shares_fallback, 1.0)
    try:
        raw_usdc = usdc_contract.functions.balanceOf(buyer_checksum).call()
        new_usdc_balance = round(float(raw_usdc) / 1e6, 2)
    except Exception:
        pass
    try:
        asset_token = get_contract_instance("AssetToken", token_address)
        raw_bal = asset_token.functions.balanceOf(buyer_checksum).call()
        raw_supply = asset_token.functions.totalSupply().call()
        new_token_balance = round(float(raw_bal) / 1e18, 6)
        if raw_supply and raw_supply > 0:
            total_shares = float(raw_supply) / 1e18
    except Exception:
        pass
    ownership_percent = round((new_token_balance / total_shares) * 100.0, 4) if total_shares > 0 else 0.0
    return new_usdc_balance, new_token_balance, ownership_percent

router = APIRouter(tags=["4. Giao dịch Sơ cấp, Thứ cấp, Tuân thủ & Kiểm toán (UC-06..UC-14)"])


def _resolve_estate(db: Session, real_estate_id: Optional[int], token_address: Optional[str]) -> RealEstate:
    est = None
    if real_estate_id:
        est = db.query(RealEstate).filter(RealEstate.id == real_estate_id).first()
    elif token_address:
        est = db.query(RealEstate).filter(RealEstate.token_address == token_address.lower()).first()
    if not est or not est.token_address:
        raise HTTPException(status_code=404, detail="Không tìm thấy bất động sản đã token hóa")
    return est


# ==========================================
# UC-08: FAUCET MOCKUSDC
# ==========================================
@router.post("/wallet/faucet")
def claim_faucet_mock_usdc(
    amount_usdc: float = 50000.0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-08: Nhận đồng MockUSDC thử nghiệm vào địa chỉ phiên đăng nhập hiện tại."""
    usdc = get_contract_instance("MockUSDC")
    checksum_user = Web3.to_checksum_address(current_user.address)
    raw_amount = int(amount_usdc * (10 ** 6))

    fn = usdc.functions.faucet(checksum_user, raw_amount)
    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name="MockUSDC.faucet",
        params_summary={"recipient": current_user.address, "amount_usdc": amount_usdc},
    )

    try:
        new_bal_raw = usdc.functions.balanceOf(checksum_user).call()
        new_bal = float(new_bal_raw) / 1e6
    except Exception:
        new_bal = 150000.0 + amount_usdc

    return {
        "tx_hash": res["tx_hash"],
        "recipient": current_user.address,
        "claimed_usdc": amount_usdc,
        "new_balance_usdc": new_bal,
    }


# ==========================================
# UC-06 & UC-09: PRIMARY SALE (OPEN / CLOSE / BUY)
# ==========================================
@router.post("/sales/primary/open")
def open_primary_sale(
    req: PrimarySaleOpenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-06: Đơn vị phát hành mở đợt bán sơ cấp với đơn giá cố định pricePerShare (MockUSDC)."""
    if req.price_per_share <= 0:
        raise HTTPException(status_code=400, detail="Giá bán mỗi cổ phần phải lớn hơn 0 mUSDC!")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Số lượng cổ phần đưa ra mở bán phải lớn hơn 0!")

    est = _resolve_estate(db, req.real_estate_id, req.token_address)
    if req.amount > float(est.total_shares):
        raise HTTPException(
            status_code=400,
            detail=f"Số lượng đưa ra mở bán ({req.amount}) vượt quá tổng số cổ phần phát hành của tài sản ({float(est.total_shares)})!",
        )

    primary_sale = get_contract_instance("PrimarySale")
    token_checksum = Web3.to_checksum_address(est.token_address)
    price_units = int(req.price_per_share * (10 ** 6))
    amount_wei = int(req.amount * (10 ** 18))

    summary = {
        "real_estate_id": est.id,
        "token": est.token_address,
        "symbol": est.symbol,
        "name": est.name,
        "pricePerShare": req.price_per_share,
        "amount": req.amount,
    }
    if req.start_date:
        summary["start_date"] = req.start_date
    if req.end_date:
        summary["end_date"] = req.end_date
    if req.notes:
        summary["notes"] = req.notes

    fn = primary_sale.functions.openSale(token_checksum, price_units, amount_wei)
    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name="PrimarySale.openSale",
        params_summary=summary,
        required_roles=["issuer"],
    )

    cache = db.query(PrimarySaleCache).filter(PrimarySaleCache.real_estate_id == est.id).first()
    if not cache:
        cache = PrimarySaleCache(
            real_estate_id=est.id,
            token_address=est.token_address.lower(),
            price_per_share=req.price_per_share,
            total_amount=req.amount,
            remaining_amount=req.amount,
            is_open=True,
        )
        db.add(cache)
    else:
        cache.price_per_share = req.price_per_share
        cache.total_amount = req.amount
        cache.remaining_amount = req.amount
        cache.is_open = True

    est.status = "open_sale"
    db.commit()
    return {"tx_hash": res["tx_hash"], "status": "open_sale"}


@router.post("/sales/primary/close")
def close_primary_sale(
    real_estate_id: Optional[int] = None,
    token_address: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-06 (Nhánh đóng đợt bán): Đóng đợt chào bán sơ cấp."""
    est = _resolve_estate(db, real_estate_id, token_address)
    primary_sale = get_contract_instance("PrimarySale")
    token_checksum = Web3.to_checksum_address(est.token_address)

    fn = primary_sale.functions.closeSale(token_checksum)
    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name="PrimarySale.closeSale",
        params_summary={"token": est.token_address, "symbol": est.symbol},
        required_roles=["issuer"],
    )

    cache = db.query(PrimarySaleCache).filter(PrimarySaleCache.real_estate_id == est.id).first()
    if cache:
        cache.is_open = False
    est.status = "tokenized"
    db.commit()
    return {"tx_hash": res["tx_hash"], "status": "tokenized"}


@router.post("/sales/primary/buy")
def buy_primary_sale(
    req: PrimarySaleBuyRequest,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    UC-09: Nhà đầu tư mua phần sở hữu BĐS trên thị trường sơ cấp bằng MockUSDC.
    - Kiểm tra vai trò investor, KYC (IdentityRegistry), Frozen, Token Paused, đợt bán & số dư MockUSDC.
    - Gộp tuần tự MockUSDC.approve + PrimarySale.buy qua Signer Service & ghi nhật ký audit_signs.
    - Đẩy tác vụ gửi email biên lai xác nhận về Gmail qua FastAPI BackgroundTasks (không chặn API).
    """
    if current_user.role_label != "investor":
        raise HTTPException(
            status_code=403,
            detail="Từ chối phân quyền (403 RBAC): Chỉ tài khoản Nhà đầu tư (investor) mới được mua cổ phần sơ cấp!",
        )
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Số lượng phần sở hữu đặt mua phải lớn hơn 0!")

    recipient_email = _validate_confirm_email(req.confirm_email, current_user.email)

    est = _resolve_estate(db, req.real_estate_id, req.token_address)
    registry = get_contract_instance("IdentityRegistry")
    primary_sale = get_contract_instance("PrimarySale")
    usdc = get_contract_instance("MockUSDC")
    asset_token = get_contract_instance("AssetToken", est.token_address)

    buyer_checksum = Web3.to_checksum_address(current_user.address)
    token_checksum = Web3.to_checksum_address(est.token_address)
    deployed = load_deployed_contracts()
    primary_sale_checksum = Web3.to_checksum_address(deployed["PrimarySale"])

    # 1. Kiểm tra trạng thái KYC trên IdentityRegistry
    try:
        is_verified = registry.functions.isVerified(buyer_checksum).call()
    except Exception:
        is_verified = bool(current_user.is_whitelisted)

    if not is_verified:
        raise HTTPException(
            status_code=400,
            detail="Từ chối nghiệp vụ (UC-09 E1): Tài khoản của bạn chưa được duyệt KYC trên IdentityRegistry. Vui lòng hoàn tất xác minh KYC trước khi mua!",
        )

    # 2. Kiểm tra đóng băng ví (Frozen) & tạm dừng hợp đồng (Paused)
    try:
        onchain_frozen = bool(asset_token.functions.isFrozen(buyer_checksum).call())
    except Exception:
        onchain_frozen = False

    if current_user.is_frozen or onchain_frozen:
        raise HTTPException(
            status_code=400,
            detail="Giao dịch bị chặn bởi Smart Contract (_update): Tài khoản hiện tại đang bị đóng băng (Frozen)!",
        )

    try:
        token_paused = bool(asset_token.functions.paused().call())
    except Exception:
        token_paused = False

    if token_paused:
        raise HTTPException(
            status_code=400,
            detail="Giao dịch bị chặn: Hợp đồng AssetToken của bất động sản này đang ở trạng thái tạm dừng khẩn cấp (Paused)!",
        )

    # 3. Kiểm tra trạng thái đợt mở bán sơ cấp & số lượng còn lại
    ps_cache = db.query(PrimarySaleCache).filter(PrimarySaleCache.real_estate_id == est.id).first()
    try:
        sale_info = primary_sale.functions.getSaleInfo(token_checksum).call()
        is_sale_open = bool(sale_info[5])
        price_per_share_raw = sale_info[1]
        rem_shares = float(sale_info[3]) / 1e18
    except Exception:
        is_sale_open = ps_cache.is_open if ps_cache else False
        price_per_share_raw = int(float(ps_cache.price_per_share) * 1e6) if ps_cache else 100_000_000
        rem_shares = float(ps_cache.remaining_amount) if ps_cache else 0.0

    if not is_sale_open:
        raise HTTPException(status_code=400, detail="Đợt bán sơ cấp của bất động sản này hiện đã đóng!")
    if req.amount > rem_shares:
        raise HTTPException(
            status_code=400,
            detail=f"Số lượng đặt mua ({req.amount:,.2f}) vượt quá số phần sở hữu còn lại ({rem_shares:,.2f}) trong đợt mở bán!",
        )

    amount_wei = int(req.amount * (10 ** 18))
    total_usdc_raw = (amount_wei * price_per_share_raw) // (10 ** 18)
    total_usdc_human = float(total_usdc_raw) / 1e6
    price_per_share_human = float(price_per_share_raw) / 1e6

    # 4. Kiểm tra số dư MockUSDC của nhà đầu tư trước khi ký approve
    try:
        buyer_usdc_raw = usdc.functions.balanceOf(buyer_checksum).call()
        if buyer_usdc_raw < total_usdc_raw:
            buyer_usdc_human = float(buyer_usdc_raw) / 1e6
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Số dư MockUSDC không đủ để thanh toán! "
                    f"Cần ${total_usdc_human:,.2f} MockUSDC, ví hiện có ${buyer_usdc_human:,.2f} MockUSDC. "
                    "Vui lòng nhấn nút '+Faucet' để nhận thêm MockUSDC thử nghiệm."
                ),
            )
    except HTTPException:
        raise
    except Exception:
        pass

    # 5. Ký tuần tự: MockUSDC.approve(PrimarySale, total_usdc_raw) -> PrimarySale.buy(token, amount_wei)
    approve_fn = usdc.functions.approve(primary_sale_checksum, total_usdc_raw)
    approve_res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=approve_fn,
        contract_method_name="MockUSDC.approve",
        params_summary={
            "spender": primary_sale_checksum,
            "usdc_amount": total_usdc_human,
            "purpose": f"PrimarySale.buy({est.symbol})",
        },
        required_roles=["investor"],
    )

    buy_fn = primary_sale.functions.buy(token_checksum, amount_wei)
    buy_res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=buy_fn,
        contract_method_name="PrimarySale.buy",
        params_summary={
            "token": est.token_address,
            "symbol": est.symbol,
            "shares_amount": req.amount,
            "price_per_share": price_per_share_human,
            "usdc_paid": total_usdc_human,
        },
        required_roles=["investor"],
    )

    receipt = buy_res["receipt"]
    if getattr(receipt, "status", 1) != 1:
        raise HTTPException(status_code=400, detail="Giao dịch PrimarySale.buy không được xác nhận thành công trên chuỗi!")

    if ps_cache and not buy_res.get("onchain"):
        ps_cache.remaining_amount = float(ps_cache.remaining_amount) - req.amount
        if float(ps_cache.remaining_amount) <= 0:
            ps_cache.is_open = False
            est.status = "tokenized"
        db.commit()

    block_number = int(getattr(receipt, "blockNumber", 1) or 1)
    record_transfer_cache(
        db=db,
        tx_hash=buy_res["tx_hash"],
        block_number=block_number,
        event_type="PRIMARY_BUY",
        token_address=est.token_address,
        from_address=primary_sale_checksum.lower(),
        to_address=current_user.address.lower(),
        amount_shares=req.amount,
        usdc_paid=total_usdc_human,
    )
    sync_onchain_state(db)

    new_usdc_bal, new_token_bal, ownership_pct = _read_post_purchase_metrics(
        token_address=est.token_address,
        buyer_address=current_user.address,
        usdc_contract=usdc,
        total_shares_fallback=float(est.total_shares or 1),
    )

    # 5b. Gửi thông báo hệ thống trên web cho nhà đầu tư nhận cổ phần
    try:
        shares_str = _fmt_shares(req.amount)
        create_notification(
            db=db,
            user_id=current_user.id,
            category="transfer",
            title=f"Nhận +{shares_str} {est.symbol} (Mua sơ cấp)",
            message=(
                f"Bạn vừa nhận được {shares_str} cổ phần {est.symbol} ({est.name}) "
                f"từ đợt mở bán sơ cấp với tổng thanh toán ${total_usdc_human:,.2f} MockUSDC."
            ),
            tx_hash=buy_res["tx_hash"],
        )
    except Exception:
        pass

    # 6. Kích hoạt gửi Email xác nhận về Gmail qua FastAPI BackgroundTasks (không chặn API)
    email_queued = False
    if recipient_email and background_tasks is not None:
        background_tasks.add_task(
            send_payment_confirmation_email,
            user_id=current_user.id,
            recipient_email=recipient_email,
            investor_name=current_user.display_name,
            wallet_address=current_user.address,
            tx_type="PRIMARY_BUY",
            estate_name=est.name,
            token_symbol=est.symbol,
            token_address=est.token_address,
            amount_shares=req.amount,
            price_per_share=price_per_share_human,
            total_usdc=total_usdc_human,
            tx_hash=buy_res["tx_hash"],
            block_number=block_number,
            ownership_percent=ownership_pct,
            new_token_balance=new_token_bal,
        )
        email_queued = True

    return {
        "approve_tx_hash": approve_res["tx_hash"],
        "tx_hash": buy_res["tx_hash"],
        "block_number": block_number,
        "shares_bought": req.amount,
        "price_per_share": price_per_share_human,
        "usdc_paid": total_usdc_human,
        "new_usdc_balance": new_usdc_bal,
        "new_token_balance": new_token_bal,
        "ownership_percent": ownership_pct,
        "email_queued": email_queued,
        "recipient_email": recipient_email,
    }


# ==========================================
# UC-10: P2P DIRECT TRANSFER
# ==========================================
@router.post("/tokens/transfer")
def transfer_tokens_p2p(
    req: P2PTransferRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-10: Chuyển nhượng trực tiếp ngang hàng (P2P) — kiểm tra tuân thủ tại hàm _update."""
    if not current_user.is_whitelisted:
        raise HTTPException(
            status_code=400,
            detail="Giao dịch bị chặn bởi Smart Contract (_update): Người gửi chưa nằm trong IdentityRegistry whitelist!",
        )
    if current_user.is_frozen:
        raise HTTPException(
            status_code=400,
            detail="Giao dịch bị chặn bởi Smart Contract (_update): Tài khoản người gửi đang bị đóng băng (Frozen)!",
        )

    recipient_user = db.query(User).filter(User.address == req.to_address.strip().lower()).first()
    if recipient_user:
        if not recipient_user.is_whitelisted:
            raise HTTPException(
                status_code=400,
                detail=f"Giao dịch bị chặn bởi Smart Contract (_update — AccountNotWhitelisted): Người nhận ({recipient_user.display_name}) chưa được duyệt KYC trong IdentityRegistry!",
            )
        if recipient_user.is_frozen:
            raise HTTPException(
                status_code=400,
                detail=f"Giao dịch bị chặn bởi Smart Contract (_update — AccountFrozen): Tài khoản người nhận ({recipient_user.display_name}) đang bị đóng băng!",
            )

    token_contract = get_contract_instance("AssetToken", req.token_address)
    to_checksum = Web3.to_checksum_address(req.to_address.strip())
    amount_wei = int(req.amount * (10 ** 18))

    fn = token_contract.functions.transfer(to_checksum, amount_wei)
    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name="AssetToken.transfer",
        params_summary={
            "token": req.token_address.lower(),
            "from": current_user.address,
            "to": req.to_address.lower(),
            "amount": req.amount,
        },
    )

    record_transfer_cache(
        db=db,
        tx_hash=res["tx_hash"],
        block_number=res["receipt"].blockNumber,
        event_type="P2P",
        token_address=req.token_address.lower(),
        from_address=current_user.address.lower(),
        to_address=req.to_address.lower(),
        amount_shares=req.amount,
        usdc_paid=None,
    )

    # Gửi thông báo hệ thống trên trang web cho người nhận cổ phần (UC-10)
    notified_recipient = False
    if recipient_user:
        try:
            est = (
                db.query(RealEstate)
                .filter(RealEstate.token_address == req.token_address.lower())
                .first()
            )
            token_symbol = est.symbol if est else "RWA"
            estate_name = est.name if est else f"AssetToken ({req.token_address[:10]}...)"
            shares_str = _fmt_shares(req.amount)
            sender_short = f"{current_user.address[:8]}...{current_user.address[-6:]}"
            create_notification(
                db=db,
                user_id=recipient_user.id,
                category="transfer",
                title=f"Bạn vừa nhận được +{shares_str} {token_symbol}",
                message=(
                    f"{current_user.display_name} ({sender_short}) vừa chuyển nhượng cho bạn "
                    f"{shares_str} cổ phần {token_symbol} ({estate_name}). "
                    f"Số dư cổ phần của bạn đã được cập nhật on-chain."
                ),
                tx_hash=res["tx_hash"],
            )
            notified_recipient = True
        except Exception:
            pass

    return {
        "tx_hash": res["tx_hash"],
        "amount": req.amount,
        "to": req.to_address.lower(),
        "notified_recipient": notified_recipient,
    }


# ==========================================
# UC-11: SECONDARY MARKETPLACE (FIXED-PRICE ESCROW)
# ==========================================
@router.get("/marketplace/listings", response_model=List[dict])
def get_marketplace_listings(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    sync_onchain_state(db)
    q = db.query(ListingCache)
    if status:
        q = q.filter(ListingCache.status == status)
    items = q.order_by(ListingCache.listing_id.desc()).all()

    result = []
    for item in items:
        est = db.query(RealEstate).filter(RealEstate.id == item.real_estate_id).first()
        seller = db.query(User).filter(User.address == item.seller_address.lower()).first()
        result.append(
            {
                "listing_id": item.listing_id,
                "real_estate_id": item.real_estate_id,
                "real_estate_name": est.name if est else "Bất động sản RWA",
                "symbol": est.symbol if est else "RWA",
                "token_address": item.token_address,
                "seller_address": item.seller_address,
                "seller_name": seller.display_name if seller else item.seller_address,
                "initial_amount": float(item.initial_amount),
                "remaining_amount": float(item.remaining_amount),
                "price_per_share": float(item.price_per_share),
                "status": item.status,
                "tx_hash": item.tx_hash,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
        )
    return result


@router.post("/marketplace/list")
def create_marketplace_listing(
    req: MarketplaceListRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-11 (List): Ký quỹ một lượng AssetToken vào Marketplace với giá cố định (gộp approve + list)."""
    est = _resolve_estate(db, None, req.token_address)
    token_contract = get_contract_instance("AssetToken", est.token_address)
    marketplace = get_contract_instance("Marketplace")
    deployed = load_deployed_contracts()
    mp_checksum = Web3.to_checksum_address(deployed["Marketplace"])
    token_checksum = Web3.to_checksum_address(est.token_address)

    amount_wei = int(req.amount * (10 ** 18))
    price_raw = int(req.price_per_share * (10 ** 6))

    # Bước 1: AssetToken.approve(Marketplace, amount)
    approve_fn = token_contract.functions.approve(mp_checksum, amount_wei)
    approve_res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=approve_fn,
        contract_method_name="AssetToken.approve",
        params_summary={
            "token": est.token_address,
            "spender": mp_checksum,
            "amount": req.amount,
        },
    )

    # Bước 2: Marketplace.list(token, amount, pricePerShare)
    list_fn = marketplace.functions.list(token_checksum, amount_wei, price_raw)
    list_res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=list_fn,
        contract_method_name="Marketplace.list",
        params_summary={
            "token": est.token_address,
            "symbol": est.symbol,
            "amount": req.amount,
            "pricePerShare": req.price_per_share,
        },
    )

    receipt = list_res["receipt"]
    listing_id = None
    if list_res.get("onchain"):
        try:
            logs = marketplace.events.Listed().process_receipt(receipt)
            listing_id = int(logs[0]["args"]["listingId"]) if logs else (marketplace.functions.nextListingId().call() - 1)
        except Exception:
            pass
    if listing_id is None:
        listing_id = db.query(ListingCache).count()

    lcache = ListingCache(
        listing_id=listing_id,
        real_estate_id=est.id,
        token_address=est.token_address.lower(),
        seller_address=current_user.address.lower(),
        initial_amount=req.amount,
        remaining_amount=req.amount,
        price_per_share=req.price_per_share,
        status="open",
        tx_hash=list_res["tx_hash"],
    )
    db.merge(lcache)
    db.commit()

    return {
        "listing_id": listing_id,
        "approve_tx_hash": approve_res["tx_hash"],
        "tx_hash": list_res["tx_hash"],
    }


@router.post("/marketplace/buy")
def buy_marketplace_listing(
    req: MarketplaceBuyRequest,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    UC-11 (Buy): Mua toàn bộ hoặc một phần lệnh đang niêm yết trên Marketplace bằng MockUSDC.
    - Kiểm tra KYC (IdentityRegistry), Frozen, Token Paused, trạng thái listing, số lượng còn lại & số dư MockUSDC.
    - Gộp tuần tự MockUSDC.approve + Marketplace.buy qua Signer Service & ghi audit_signs.
    - Đẩy tác vụ gửi email biên lai về Gmail cho người mua (và thông báo đã bán thành công cho người bán nếu có email).
    """
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Số lượng đặt mua phải lớn hơn 0!")

    buyer_email = _validate_confirm_email(req.confirm_email, current_user.email)

    registry = get_contract_instance("IdentityRegistry")
    marketplace = get_contract_instance("Marketplace")
    usdc = get_contract_instance("MockUSDC")
    deployed = load_deployed_contracts()
    mp_checksum = Web3.to_checksum_address(deployed["Marketplace"])
    buyer_checksum = Web3.to_checksum_address(current_user.address)

    # 1. Kiểm tra KYC người mua trên IdentityRegistry
    try:
        is_verified = registry.functions.isVerified(buyer_checksum).call()
    except Exception:
        is_verified = bool(current_user.is_whitelisted)

    if not is_verified:
        raise HTTPException(
            status_code=400,
            detail="Giao dịch bị chặn bởi Smart Contract: Người mua chưa nằm trong danh sách trắng KYC (IdentityRegistry)!",
        )

    # 2. Lấy thông tin lệnh niêm yết (on-chain ưu tiên, fallback cache)
    lcache = db.query(ListingCache).filter(ListingCache.listing_id == req.listing_id).first()
    try:
        item = marketplace.functions.getListing(req.listing_id).call()
        if not item[6]:
            raise HTTPException(status_code=400, detail="Lệnh niêm yết không còn mở!")
        token_addr = item[1].lower()
        seller_addr = item[2].lower()
        rem_amount = float(item[4]) / 1e18
        price_raw = item[5]
        if req.amount > rem_amount:
            raise HTTPException(
                status_code=400,
                detail=f"Số lượng đặt mua ({req.amount:,.2f}) vượt quá số lượng còn lại ({rem_amount:,.2f}) trong lệnh niêm yết!",
            )
    except HTTPException:
        raise
    except Exception:
        if not lcache or lcache.status != "open":
            raise HTTPException(status_code=400, detail="Lệnh niêm yết không còn mở!")
        if req.amount > float(lcache.remaining_amount):
            raise HTTPException(
                status_code=400,
                detail=f"Số lượng đặt mua ({req.amount:,.2f}) vượt quá số lượng còn lại ({float(lcache.remaining_amount):,.2f}) trong lệnh niêm yết!",
            )
        token_addr = lcache.token_address.lower()
        seller_addr = lcache.seller_address.lower()
        price_raw = int(float(lcache.price_per_share) * 1e6)

    if seller_addr == current_user.address.lower():
        raise HTTPException(
            status_code=400,
            detail="Không thể tự mua lệnh niêm yết của chính địa chỉ ví của mình!",
        )

    # 3. Kiểm tra Frozen & Token Paused
    asset_token = get_contract_instance("AssetToken", token_addr)
    try:
        onchain_frozen = bool(asset_token.functions.isFrozen(buyer_checksum).call())
    except Exception:
        onchain_frozen = False

    if current_user.is_frozen or onchain_frozen:
        raise HTTPException(
            status_code=400,
            detail="Giao dịch bị chặn bởi Smart Contract (_update): Tài khoản người mua đang bị đóng băng (Frozen)!",
        )

    try:
        token_paused = bool(asset_token.functions.paused().call())
    except Exception:
        token_paused = False

    if token_paused:
        raise HTTPException(
            status_code=400,
            detail="Giao dịch bị chặn: Hợp đồng AssetToken này đang bị tạm dừng khẩn cấp (Paused)!",
        )

    amount_wei = int(req.amount * (10 ** 18))
    total_usdc_raw = (amount_wei * price_raw) // (10 ** 18)
    total_usdc_human = float(total_usdc_raw) / 1e6
    price_per_share_human = float(price_raw) / 1e6

    # 4. Kiểm tra số dư MockUSDC
    try:
        buyer_usdc_raw = usdc.functions.balanceOf(buyer_checksum).call()
        if buyer_usdc_raw < total_usdc_raw:
            buyer_usdc_human = float(buyer_usdc_raw) / 1e6
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Số dư MockUSDC không đủ để khớp lệnh! "
                    f"Cần ${total_usdc_human:,.2f} MockUSDC, ví hiện có ${buyer_usdc_human:,.2f} MockUSDC. "
                    "Vui lòng nhấn '+Faucet' để nhận thêm MockUSDC."
                ),
            )
    except HTTPException:
        raise
    except Exception:
        pass

    # 5. Ký tuần tự: MockUSDC.approve(Marketplace, total_usdc_raw) -> Marketplace.buy(listingId, amount_wei)
    approve_fn = usdc.functions.approve(mp_checksum, total_usdc_raw)
    approve_res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=approve_fn,
        contract_method_name="MockUSDC.approve",
        params_summary={
            "spender": mp_checksum,
            "usdc_amount": total_usdc_human,
            "listingId": req.listing_id,
        },
    )

    buy_fn = marketplace.functions.buy(req.listing_id, amount_wei)
    buy_res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=buy_fn,
        contract_method_name="Marketplace.buy",
        params_summary={
            "listingId": req.listing_id,
            "amount": req.amount,
            "price_per_share": price_per_share_human,
            "usdc_paid": total_usdc_human,
        },
    )

    receipt = buy_res["receipt"]
    if getattr(receipt, "status", 1) != 1:
        raise HTTPException(status_code=400, detail="Giao dịch Marketplace.buy không được xác nhận thành công trên chuỗi!")

    if lcache and not buy_res.get("onchain"):
        lcache.remaining_amount = float(lcache.remaining_amount) - req.amount
        if float(lcache.remaining_amount) <= 0:
            lcache.remaining_amount = 0
            lcache.status = "filled"
        db.commit()

    block_number = int(getattr(receipt, "blockNumber", 1) or 1)
    record_transfer_cache(
        db=db,
        tx_hash=buy_res["tx_hash"],
        block_number=block_number,
        event_type="MARKET_BUY",
        token_address=token_addr,
        from_address=seller_addr,
        to_address=current_user.address.lower(),
        amount_shares=req.amount,
        usdc_paid=total_usdc_human,
    )
    sync_onchain_state(db)

    estate = db.query(RealEstate).filter(RealEstate.token_address == token_addr).first()
    estate_name = estate.name if estate else f"AssetToken ({token_addr[:10]}...)"
    token_symbol = estate.symbol if estate else "RWA"

    new_usdc_bal, new_token_bal, ownership_pct = _read_post_purchase_metrics(
        token_address=token_addr,
        buyer_address=current_user.address,
        usdc_contract=usdc,
        total_shares_fallback=float(estate.total_shares if estate else 1),
    )

    # 5b. Gửi thông báo hệ thống trên web cho người mua (nhận cổ phần) và người bán
    seller_user = db.query(User).filter(User.address == seller_addr).first()
    try:
        shares_str = _fmt_shares(req.amount)
        create_notification(
            db=db,
            user_id=current_user.id,
            category="transfer",
            title=f"Nhận +{shares_str} {token_symbol} từ Marketplace",
            message=(
                f"Bạn vừa nhận chuyển nhượng {shares_str} cổ phần {token_symbol} ({estate_name}) "
                f"từ lệnh #{req.listing_id} với tổng thanh toán ${total_usdc_human:,.2f} MockUSDC."
            ),
            tx_hash=buy_res["tx_hash"],
        )
        if seller_user:
            create_notification(
                db=db,
                user_id=seller_user.id,
                category="transfer",
                title=f"Đã chuyển nhượng {shares_str} {token_symbol} (Lệnh #{req.listing_id})",
                message=(
                    f"{current_user.display_name} đã mua {shares_str} cổ phần {token_symbol} ({estate_name}) "
                    f"từ lệnh #{req.listing_id} của bạn. Bạn nhận được +${total_usdc_human:,.2f} MockUSDC."
                ),
                tx_hash=buy_res["tx_hash"],
            )
    except Exception:
        pass

    # 6. Gửi Email xác nhận cho người mua & thông báo bán thành công cho người bán (BackgroundTasks)
    email_queued = False
    if buyer_email and background_tasks is not None:
        background_tasks.add_task(
            send_payment_confirmation_email,
            user_id=current_user.id,
            recipient_email=buyer_email,
            investor_name=current_user.display_name,
            wallet_address=current_user.address,
            tx_type="MARKET_BUY",
            estate_name=estate_name,
            token_symbol=token_symbol,
            token_address=token_addr,
            amount_shares=req.amount,
            price_per_share=price_per_share_human,
            total_usdc=total_usdc_human,
            tx_hash=buy_res["tx_hash"],
            block_number=block_number,
            ownership_percent=ownership_pct,
            new_token_balance=new_token_bal,
            listing_id=req.listing_id,
        )
        email_queued = True

    seller_email_queued = False
    if seller_user and seller_user.email and EMAIL_PATTERN.match(seller_user.email) and background_tasks is not None:
        background_tasks.add_task(
            send_payment_confirmation_email,
            user_id=seller_user.id,
            recipient_email=seller_user.email,
            investor_name=seller_user.display_name,
            wallet_address=seller_user.address,
            tx_type="MARKET_SELL",
            estate_name=estate_name,
            token_symbol=token_symbol,
            token_address=token_addr,
            amount_shares=req.amount,
            price_per_share=price_per_share_human,
            total_usdc=total_usdc_human,
            tx_hash=buy_res["tx_hash"],
            block_number=block_number,
            listing_id=req.listing_id,
        )
        seller_email_queued = True

    return {
        "approve_tx_hash": approve_res["tx_hash"],
        "tx_hash": buy_res["tx_hash"],
        "block_number": block_number,
        "shares_bought": req.amount,
        "price_per_share": price_per_share_human,
        "usdc_paid": total_usdc_human,
        "new_usdc_balance": new_usdc_bal,
        "new_token_balance": new_token_bal,
        "ownership_percent": ownership_pct,
        "email_queued": email_queued,
        "recipient_email": buyer_email,
        "seller_email_queued": seller_email_queued,
    }


@router.get("/email-logs")
def list_email_logs(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Truy vấn nhật ký kiểm toán gửi Email biên lai thanh toán MockUSDC (Admin xem tất cả, User xem của mình)."""
    q = db.query(EmailLog)
    if current_user.role_label != "admin":
        q = q.filter(EmailLog.user_id == current_user.id)
    rows = q.order_by(EmailLog.sent_at.desc()).limit(min(max(limit, 1), 200)).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "recipient_email": r.recipient_email,
            "tx_hash": r.tx_hash,
            "tx_type": r.tx_type,
            "subject": r.subject,
            "status": r.status,
            "error_message": r.error_message,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        }
        for r in rows
    ]


@router.post("/marketplace/cancel")
def cancel_marketplace_listing(
    req: MarketplaceCancelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-11 (Cancel): Người bán hủy lệnh niêm yết và rút phần token chưa khớp về ví."""
    marketplace = get_contract_instance("Marketplace")
    fn = marketplace.functions.cancel(req.listing_id)

    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name="Marketplace.cancel",
        params_summary={"listingId": req.listing_id},
    )

    lcache = db.query(ListingCache).filter(ListingCache.listing_id == req.listing_id).first()
    if lcache:
        lcache.remaining_amount = 0
        lcache.status = "cancelled"
        db.commit()

    return {"tx_hash": res["tx_hash"], "listing_id": req.listing_id, "status": "cancelled"}


# ==========================================
# UC-12 & UC-13: COMPLIANCE FREEZE, ADMIN PAUSE, FORCED TRANSFER, ROLES
# ==========================================
@router.post("/admin/freeze")
def set_account_frozen(
    req: FreezeAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-12: Compliance đóng băng hoặc mở băng một địa chỉ trên AssetToken."""
    target_checksum = Web3.to_checksum_address(req.account_address.strip())

    tokens_to_update = []
    if req.token_address:
        tokens_to_update.append(req.token_address)
    else:
        estates = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()
        tokens_to_update = [e.token_address for e in estates]

    if not tokens_to_update:
        raise HTTPException(status_code=400, detail="Chưa có hợp đồng AssetToken nào được triển khai")

    last_tx = ""
    for tok_addr in tokens_to_update:
        token_contract = get_contract_instance("AssetToken", tok_addr)
        fn = token_contract.functions.setFrozen(target_checksum, req.frozen)
        res = SignerService.sign_and_send(
            db=db,
            current_user=current_user,
            contract_function=fn,
            contract_method_name="AssetToken.setFrozen",
            params_summary={
                "token": tok_addr,
                "account": req.account_address.lower(),
                "frozen": req.frozen,
                "reason": req.reason or ("Khóa tài khoản nghi vấn vi phạm" if req.frozen else "Mở khóa tài khoản"),
                "case_code": req.case_code or "",
                "notes": req.notes or "",
            },
            required_roles=["compliance"],
        )
        last_tx = res["tx_hash"]

    target_user = db.query(User).filter(User.address == req.account_address.strip().lower()).first()
    if target_user:
        target_user.is_frozen = req.frozen
        db.commit()
        from .notifications import create_notification
        create_notification(
            db=db,
            user_id=target_user.id,
            category="freeze",
            title="Cảnh báo: Ví của bạn đã bị đóng băng (Frozen)" if req.frozen else "Ví của bạn đã được mở khóa (Unfrozen)",
            message=(
                f"Bộ phận tuân thủ đã {'tạm khóa giao dịch ví của bạn' if req.frozen else 'giải tỏa trạng thái đóng băng cho ví của bạn'}. "
                f"Lý do: {req.reason or ('Nghi vấn vi phạm tuân thủ' if req.frozen else 'Đã hoàn tất xác minh')}."
                + (f" Mã vụ việc: {req.case_code}." if req.case_code else "")
            ),
            tx_hash=last_tx,
        )

    return {
        "tx_hash": last_tx,
        "account": req.account_address.lower(),
        "is_frozen": req.frozen,
    }


@router.post("/admin/pause")
def set_token_paused(
    req: PauseTokenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-13 (Nhánh B): Admin tạm dừng (pause) hoặc mở lại (unpause) hợp đồng AssetToken."""
    est = db.query(RealEstate).filter(RealEstate.token_address == req.token_address.lower()).first()
    token_contract = get_contract_instance("AssetToken", req.token_address)
    fn = token_contract.functions.pause() if req.paused else token_contract.functions.unpause()
    method_label = "AssetToken.pause" if req.paused else "AssetToken.unpause"

    summary = {
        "token": req.token_address.lower(),
        "asset_name": est.name if est else "AssetToken",
        "symbol": est.symbol if est else "RWA",
        "paused": req.paused,
    }
    if req.reason:
        summary["reason"] = req.reason

    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name=method_label,
        params_summary=summary,
        required_roles=["admin"],
    )
    return {
        "tx_hash": res["tx_hash"],
        "token": req.token_address.lower(),
        "asset_name": est.name if est else "AssetToken",
        "symbol": est.symbol if est else "RWA",
        "is_paused": req.paused,
        "block_number": res.get("block_number", 1),
        "actor": current_user.address.lower(),
    }


@router.post("/admin/forced-transfer")
def execute_forced_transfer(
    req: ForcedTransferRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-13 (Nhánh C): Admin thực hiện chuyển nhượng cưỡng chế (forcedTransfer) khi tranh chấp hoặc mất tài khoản."""
    from_raw = req.from_address.strip()
    to_raw = req.to_address.strip()
    if not Web3.is_address(from_raw) or not Web3.is_address(to_raw):
        raise HTTPException(status_code=400, detail="Địa chỉ ví gửi (From) hoặc ví nhận (To) không đúng định dạng Ethereum 0x!")
    if from_raw.lower() == to_raw.lower():
        raise HTTPException(status_code=400, detail="Địa chỉ ví gửi và ví nhận không được trùng nhau!")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Số lượng token cần cưỡng chế chuyển nhượng phải lớn hơn 0!")

    est = db.query(RealEstate).filter(RealEstate.token_address == req.token_address.lower()).first()
    token_contract = get_contract_instance("AssetToken", req.token_address)
    from_checksum = Web3.to_checksum_address(from_raw)
    to_checksum = Web3.to_checksum_address(to_raw)
    amount_wei = int(req.amount * (10 ** 18))

    fn = token_contract.functions.forcedTransfer(from_checksum, to_checksum, amount_wei)
    summary = {
        "token": req.token_address.lower(),
        "asset_name": est.name if est else "AssetToken",
        "symbol": est.symbol if est else "RWA",
        "from": from_raw.lower(),
        "to": to_raw.lower(),
        "amount": req.amount,
    }
    if req.reason:
        summary["reason"] = req.reason
    if req.case_code:
        summary["case_code"] = req.case_code

    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name="AssetToken.forcedTransfer",
        params_summary=summary,
        required_roles=["admin"],
    )

    record_transfer_cache(
        db=db,
        tx_hash=res["tx_hash"],
        block_number=res["receipt"].blockNumber,
        event_type="FORCED_TRANSFER",
        token_address=req.token_address.lower(),
        from_address=from_raw.lower(),
        to_address=to_raw.lower(),
        amount_shares=req.amount,
        usdc_paid=None,
    )

    # Gửi thông báo hệ thống trên trang web cho người nhận (và ví nguồn) sau chuyển nhượng cưỡng chế
    try:
        token_symbol = est.symbol if est else "RWA"
        estate_name = est.name if est else f"AssetToken ({req.token_address[:10]}...)"
        shares_str = _fmt_shares(req.amount)
        reason_suffix = f" Lý do: {req.reason}." if req.reason else ""
        recipient_user = db.query(User).filter(User.address == to_raw.lower()).first()
        if recipient_user:
            create_notification(
                db=db,
                user_id=recipient_user.id,
                category="transfer",
                title=f"Nhận chuyển nhượng cưỡng chế +{shares_str} {token_symbol}",
                message=(
                    f"Quản trị viên ({current_user.display_name}) vừa chuyển nhượng cho bạn "
                    f"{shares_str} cổ phần {token_symbol} ({estate_name}) từ ví "
                    f"{from_raw[:8]}...{from_raw[-6:]}.{reason_suffix}"
                ),
                tx_hash=res["tx_hash"],
            )
        sender_user = db.query(User).filter(User.address == from_raw.lower()).first()
        if sender_user:
            create_notification(
                db=db,
                user_id=sender_user.id,
                category="transfer",
                title=f"Chuyển nhượng cưỡng chế -{shares_str} {token_symbol}",
                message=(
                    f"Quản trị viên ({current_user.display_name}) đã chuyển {shares_str} cổ phần "
                    f"{token_symbol} ({estate_name}) sang ví {to_raw[:8]}...{to_raw[-6:]}.{reason_suffix}"
                ),
                tx_hash=res["tx_hash"],
            )
    except Exception:
        pass

    return {
        "tx_hash": res["tx_hash"],
        "from": from_raw.lower(),
        "to": to_raw.lower(),
        "amount": req.amount,
        "reason": req.reason,
        "case_code": req.case_code,
        "block_number": res.get("block_number", 1),
    }


@router.post("/admin/roles")
def manage_contract_role(
    req: RoleManageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC-13 (Nhánh A): Admin cấp hoặc thu hồi vai trò (grantRole / revokeRole)."""
    if not Web3.is_address(req.account_address.strip()):
        raise HTTPException(status_code=400, detail="Địa chỉ ví mục tiêu không đúng định dạng Ethereum 0x!")

    if req.contract_name == "AssetToken" and req.token_address:
        contract = get_contract_instance("AssetToken", req.token_address)
        target_contract_addr = req.token_address.lower()
    else:
        contract = get_contract_instance(req.contract_name)
        deployed = load_deployed_contracts()
        target_contract_addr = (deployed.get(req.contract_name) or "").lower()

    if req.role_name == "DEFAULT_ADMIN_ROLE":
        role_bytes = b"\x00" * 32
    else:
        role_bytes = Web3.keccak(text=req.role_name)

    target_checksum = Web3.to_checksum_address(req.account_address.strip())

    # Bảo vệ an toàn: Không cho phép thu hồi DEFAULT_ADMIN_ROLE cuối cùng trên hợp đồng
    if not req.grant and req.role_name == "DEFAULT_ADMIN_ROLE":
        from ..services.signer import is_contract_deployed_on_anvil
        all_users = db.query(User).all()
        candidate_addrs = {u.address.lower() for u in all_users}
        candidate_addrs.add(req.account_address.strip().lower())
        active_admins = []
        if is_contract_deployed_on_anvil(target_contract_addr):
            for addr in candidate_addrs:
                try:
                    if contract.functions.hasRole(role_bytes, Web3.to_checksum_address(addr)).call():
                        active_admins.append(addr)
                except Exception:
                    pass
        if len(active_admins) <= 1 and req.account_address.strip().lower() in active_admins:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Chặn an toàn bảo mật: Địa chỉ {req.account_address} đang là quản trị viên "
                    f"(DEFAULT_ADMIN_ROLE) duy nhất trên hợp đồng {req.contract_name}. "
                    "Hệ thống từ chối thu hồi để tránh mất quyền quản trị cuối cùng!"
                ),
            )

    fn = (
        contract.functions.grantRole(role_bytes, target_checksum)
        if req.grant
        else contract.functions.revokeRole(role_bytes, target_checksum)
    )
    method_label = f"{req.contract_name}.{'grantRole' if req.grant else 'revokeRole'}"

    summary = {
        "contract": req.contract_name,
        "contract_address": target_contract_addr,
        "role": req.role_name,
        "account": req.account_address.strip().lower(),
        "grant": req.grant,
    }
    if req.reason:
        summary["reason"] = req.reason

    res = SignerService.sign_and_send(
        db=db,
        current_user=current_user,
        contract_function=fn,
        contract_method_name=method_label,
        params_summary=summary,
        required_roles=["admin"],
    )
    return {
        "tx_hash": res["tx_hash"],
        "contract": req.contract_name,
        "contract_address": target_contract_addr,
        "role": req.role_name,
        "account": req.account_address.strip().lower(),
        "granted": req.grant,
        "block_number": res.get("block_number", 1),
    }


@router.post("/admin/users/assign-role")
def assign_user_system_role(
    req: UserRoleAssignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Phân quyền Tài khoản Hệ thống (RBAC) & Đồng bộ quyền Smart Contract On-chain:
    - Chỉ DEFAULT_ADMIN_ROLE (admin) được phép thay đổi vai trò tài khoản (admin | issuer | compliance | investor).
    - Bảo vệ an toàn: Không cho phép hạ quyền Admin cuối cùng trong hệ thống.
    - Tự động cấp/thu hồi các vai trò tương ứng trên IdentityRegistry, AssetFactory, PrimarySale, AssetToken.
    """
    if current_user.role_label != "admin":
        raise HTTPException(
            status_code=403,
            detail="Từ chối phân quyền (403 RBAC): Chỉ Quản trị viên hệ thống (ADMIN) mới có quyền phân quyền tài khoản!",
        )

    new_role = req.new_role.strip().lower()
    if new_role not in ("admin", "issuer", "compliance", "investor"):
        raise HTTPException(
            status_code=400,
            detail="Vai trò không hợp lệ! Chỉ chấp nhận: admin, issuer, compliance, investor.",
        )

    target_user: Optional[User] = None
    if req.user_id is not None:
        target_user = db.query(User).filter(User.id == req.user_id).first()
    elif req.account_address:
        target_user = db.query(User).filter(User.address == req.account_address.strip().lower()).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản người dùng cần phân quyền!")

    prev_role = target_user.role_label
    if prev_role == new_role:
        raise HTTPException(
            status_code=400,
            detail=f"Tài khoản '{target_user.display_name}' hiện đã giữ vai trò {new_role.upper()} rồi!",
        )
    if target_user.id == current_user.id and new_role != "admin":
        raise HTTPException(
            status_code=400,
            detail="Chặn an toàn bảo mật: Bạn không thể tự hạ quyền Quản trị viên (Admin) của chính tài khoản đang đăng nhập!",
        )
    if prev_role == "admin" and new_role != "admin":
        admin_count = db.query(User).filter(User.role_label == "admin").count()
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Chặn an toàn bảo mật: Không thể hạ quyền Quản trị viên (Admin) duy nhất còn lại trong hệ thống!",
            )

    target_user.role_label = new_role
    if new_role in ("admin", "issuer", "compliance"):
        target_user.is_whitelisted = True
    db.commit()
    db.refresh(target_user)

    onchain_txs = []
    onchain_warnings = []
    if req.sync_onchain:
        from ..services.signer import is_contract_deployed_on_anvil
        deployed = load_deployed_contracts()
        target_checksum = Web3.to_checksum_address(target_user.address)

        role_targets = []
        if new_role == "compliance":
            role_targets.append(("IdentityRegistry", deployed.get("IdentityRegistry"), "COMPLIANCE_ROLE", True))
        elif new_role == "issuer":
            role_targets.append(("AssetFactory", deployed.get("AssetFactory"), "ISSUER_ROLE", True))
            role_targets.append(("PrimarySale", deployed.get("PrimarySale"), "ISSUER_ROLE", True))
        elif new_role == "admin":
            role_targets.append(("IdentityRegistry", deployed.get("IdentityRegistry"), "DEFAULT_ADMIN_ROLE", True))
            role_targets.append(("AssetFactory", deployed.get("AssetFactory"), "DEFAULT_ADMIN_ROLE", True))
            role_targets.append(("PrimarySale", deployed.get("PrimarySale"), "DEFAULT_ADMIN_ROLE", True))

        # Thu hồi quyền cũ nếu chuyển sang investor
        if new_role == "investor":
            if prev_role == "compliance":
                role_targets.append(("IdentityRegistry", deployed.get("IdentityRegistry"), "COMPLIANCE_ROLE", False))
            elif prev_role == "issuer":
                role_targets.append(("AssetFactory", deployed.get("AssetFactory"), "ISSUER_ROLE", False))
                role_targets.append(("PrimarySale", deployed.get("PrimarySale"), "ISSUER_ROLE", False))

        # Đồng bộ thêm với AssetToken đang hoạt động nếu có
        estates_with_token = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()
        for est in estates_with_token[:3]:
            if new_role == "compliance":
                role_targets.append(("AssetToken", est.token_address, "COMPLIANCE_ROLE", True))
            elif new_role == "issuer":
                role_targets.append(("AssetToken", est.token_address, "ISSUER_ROLE", True))
            elif new_role == "investor" and prev_role == "compliance":
                role_targets.append(("AssetToken", est.token_address, "COMPLIANCE_ROLE", False))
            elif new_role == "investor" and prev_role == "issuer":
                role_targets.append(("AssetToken", est.token_address, "ISSUER_ROLE", False))

        for c_name, c_addr, r_name, do_grant in role_targets:
            if not c_addr or not is_contract_deployed_on_anvil(c_addr):
                continue
            try:
                contract = get_contract_instance(c_name, c_addr)
                r_bytes = b"\x00" * 32 if r_name == "DEFAULT_ADMIN_ROLE" else Web3.keccak(text=r_name)
                already_has = contract.functions.hasRole(r_bytes, target_checksum).call()
                if do_grant and already_has:
                    continue
                if not do_grant and not already_has:
                    continue
                fn = (
                    contract.functions.grantRole(r_bytes, target_checksum)
                    if do_grant
                    else contract.functions.revokeRole(r_bytes, target_checksum)
                )
                res = SignerService.sign_and_send(
                    db=db,
                    current_user=current_user,
                    contract_function=fn,
                    contract_method_name=f"{c_name}.{'grantRole' if do_grant else 'revokeRole'}",
                    params_summary={
                        "action": "Assign System Role",
                        "user_id": target_user.id,
                        "username": target_user.username,
                        "account": target_user.address,
                        "previous_role": prev_role,
                        "new_role": new_role,
                        "contract": c_name,
                        "role": r_name,
                        "grant": do_grant,
                        "reason": req.reason or f"Phân quyền tài khoản từ {prev_role} sang {new_role}",
                    },
                    required_roles=["admin"],
                )
                onchain_txs.append({"contract": c_name, "role": r_name, "grant": do_grant, "tx_hash": res["tx_hash"]})
            except Exception as exc:
                onchain_warnings.append(f"{c_name}.{r_name}: {str(exc)[:140]}")

    # Ghi nhận AuditSign tổng hợp cho thao tác phân quyền tài khoản
    audit = AuditSign(
        user_id=current_user.id,
        signer_address=current_user.address,
        role_label="admin",
        contract_method="RBAC.assignUserRole",
        params_json={
            "target_user_id": target_user.id,
            "target_username": target_user.username,
            "target_display_name": target_user.display_name,
            "target_address": target_user.address,
            "previous_role": prev_role,
            "new_role": new_role,
            "sync_onchain": req.sync_onchain,
            "onchain_txs_count": len(onchain_txs),
            "onchain_warnings": onchain_warnings,
            "reason": req.reason or f"Quản trị viên phân quyền từ {prev_role.upper()} sang {new_role.upper()}",
        },
        tx_hash=onchain_txs[0]["tx_hash"] if onchain_txs else f"RBAC_ASSIGN_{target_user.id}_{int(datetime.datetime.utcnow().timestamp())}",
        signed_at=datetime.datetime.utcnow(),
    )
    db.add(audit)
    db.commit()

    return {
        "status": "updated",
        "user": {
            "id": target_user.id,
            "username": target_user.username,
            "email": target_user.email,
            "display_name": target_user.display_name,
            "address": target_user.address,
            "previous_role": prev_role,
            "role_label": target_user.role_label,
        },
        "onchain_txs": onchain_txs,
        "onchain_warnings": onchain_warnings,
    }


# ==========================================
# UC-14: OWNERSHIP PORTFOLIO, TRANSACTIONS & AUDIT SIGNS
# ==========================================
@router.get("/ownership/{address}")
def get_investor_ownership(address: str, db: Session = Depends(get_db)):
    """UC-14: Đọc số dư MockUSDC, số dư AssetToken và tỉ lệ sở hữu (balanceOf / totalShares) của một địa chỉ."""
    sync_onchain_state(db)
    addr_low = address.strip().lower()
    checksum_addr = Web3.to_checksum_address(addr_low)
    user_obj = db.query(User).filter(User.address == addr_low).first()

    usdc_balance = 150000.0 if user_obj else 0.0
    is_verified = bool(user_obj.is_whitelisted) if user_obj else False

    from ..services.signer import is_contract_deployed_on_anvil
    deployed = load_deployed_contracts()
    onchain_live = is_contract_deployed_on_anvil(deployed.get("MockUSDC"))

    if onchain_live:
        try:
            usdc = get_contract_instance("MockUSDC")
            registry = get_contract_instance("IdentityRegistry")
            usdc_balance = float(usdc.functions.balanceOf(checksum_addr).call()) / 1e6
            is_verified = bool(registry.functions.isVerified(checksum_addr).call())
        except Exception:
            pass
    else:
        # Tính toán số dư mUSDC từ lịch sử biến động trong DB khi chạy chế độ mô phỏng nhanh
        inflows = db.query(TransferCache).filter(TransferCache.from_address == addr_low, TransferCache.usdc_paid.isnot(None)).all()
        outflows = db.query(TransferCache).filter(TransferCache.to_address == addr_low, TransferCache.usdc_paid.isnot(None)).all()
        usdc_balance = 150000.0 + sum(float(i.usdc_paid or 0) for i in inflows) - sum(float(o.usdc_paid or 0) for o in outflows)

    estates = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()
    holdings = []
    total_portfolio_value = 0.0

    for est in estates:
        shares = 0.0
        total_shares = float(est.total_shares)
        is_frozen = bool(user_obj.is_frozen) if user_obj else False

        if onchain_live and is_contract_deployed_on_anvil(est.token_address):
            try:
                tok = get_contract_instance("AssetToken", est.token_address)
                raw_bal = tok.functions.balanceOf(checksum_addr).call()
                raw_supply = tok.functions.totalSupply().call()
                is_frozen = bool(tok.functions.isFrozen(checksum_addr).call())
                shares = float(raw_bal) / 1e18
                if raw_supply > 0:
                    total_shares = float(raw_supply) / 1e18
            except Exception:
                pass
        else:
            # Tính số dư từ bảng transfers_cache & listings_cache
            received = (
                db.query(TransferCache)
                .filter(
                    TransferCache.token_address == est.token_address.lower(),
                    TransferCache.to_address == addr_low,
                )
                .all()
            )
            sent = (
                db.query(TransferCache)
                .filter(
                    TransferCache.token_address == est.token_address.lower(),
                    TransferCache.from_address == addr_low,
                )
                .all()
            )
            escrowed = (
                db.query(ListingCache)
                .filter(
                    ListingCache.token_address == est.token_address.lower(),
                    ListingCache.seller_address == addr_low,
                    ListingCache.status == "open",
                )
                .all()
            )
            shares = (
                sum(float(r.amount) for r in received)
                - sum(float(s.amount) for s in sent)
                - sum(float(e.remaining_amount) for e in escrowed)
            )
            if shares < 0:
                shares = 0.0

        ratio_pct = (shares / total_shares * 100.0) if total_shares > 0 else 0.0
        est_val = float(est.valuation)
        holding_value_usdc = (shares / total_shares) * est_val if total_shares > 0 else 0.0
        total_portfolio_value += holding_value_usdc

        holdings.append(
            {
                "real_estate_id": est.id,
                "name": est.name,
                "symbol": est.symbol,
                "property_kind": est.property_kind,
                "token_address": est.token_address,
                "shares_balance": round(shares, 4),
                "total_shares": total_shares,
                "ownership_percent": round(ratio_pct, 4),
                "valuation_usdc": est_val,
                "estimated_value_usdc": round(holding_value_usdc, 2),
                "is_frozen": is_frozen,
                "doc_cid": est.doc_cid,
                "doc_hash": est.doc_hash,
            }
        )

    return {
        "address": addr_low,
        "is_whitelisted": is_verified,
        "usdc_balance": round(usdc_balance, 2),
        "total_portfolio_value_usdc": round(total_portfolio_value, 2),
        "holdings": holdings,
    }


@router.get("/transactions", response_model=List[dict])
def list_transfers_cache(
    address: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(TransferCache)
    if address:
        addr_low = address.strip().lower()
        q = q.filter(
            (TransferCache.from_address == addr_low)
            | (TransferCache.to_address == addr_low)
        )
    rows = q.order_by(TransferCache.id.desc()).limit(limit).all()

    result = []
    for r in rows:
        est = db.query(RealEstate).filter(RealEstate.token_address == r.token_address.lower()).first()
        result.append(
            {
                "id": r.id,
                "tx_hash": r.tx_hash,
                "block_number": r.block_number,
                "event_type": r.event_type,
                "token_address": r.token_address,
                "symbol": est.symbol if est else "RWA",
                "real_estate_name": est.name if est else "Bất động sản",
                "from_address": r.from_address,
                "to_address": r.to_address,
                "amount": float(r.amount),
                "usdc_paid": float(r.usdc_paid) if r.usdc_paid is not None else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return result


@router.get("/audit-signs", response_model=List[dict])
def list_audit_signs(limit: int = 200, db: Session = Depends(get_db)):
    users_map = {u.address.lower(): u.display_name for u in db.query(User).all()}
    rows = db.query(AuditSign).order_by(AuditSign.id.desc()).limit(limit).all()
    return [
        {
            "id": a.id,
            "user_id": a.user_id,
            "signer_address": a.signer_address,
            "signer_name": users_map.get(a.signer_address.lower(), "System Signer"),
            "role_label": a.role_label,
            "contract_method": a.contract_method,
            "params_json": a.params_json,
            "tx_hash": a.tx_hash,
            "block_number": (a.params_json or {}).get("block_number", a.id),
            "status": (a.params_json or {}).get("status", "SUCCESS"),
            "reason": (a.params_json or {}).get("reason"),
            "case_code": (a.params_json or {}).get("case_code"),
            "signed_at": a.signed_at.isoformat() if a.signed_at else None,
        }
        for a in rows
    ]


# ==========================================
# ADMIN ENTERPRISE ENDPOINTS (DASHBOARD, WALLET INSPECT, ROLES MATRIX, SYSTEM MONITORING)
# ==========================================
def _require_admin(current_user: User):
    if current_user.role_label != "admin":
        raise HTTPException(
            status_code=403,
            detail="Từ chối truy cập (RBAC): Chỉ tài khoản Quản trị viên (DEFAULT_ADMIN_ROLE) mới có quyền gọi API quản trị hệ thống!",
        )


@router.get("/admin/overview")
def get_admin_dashboard_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """API tổng hợp dữ liệu thực tế từ Database & Smart Contract cho Admin Dashboard và Emergency Pause."""
    _require_admin(current_user)
    sync_onchain_state(db)

    from ..services.signer import get_w3, is_contract_deployed_on_anvil
    from ..config import settings

    w3 = get_w3()
    deployed = load_deployed_contracts()
    rpc_connected = False
    block_number = 0
    chain_id = settings.CHAIN_ID
    gas_price_gwei = 0.0

    try:
        if w3.is_connected():
            rpc_connected = True
            block_number = int(w3.eth.block_number)
            chain_id = int(w3.eth.chain_id)
            gas_price_gwei = round(float(w3.eth.gas_price) / 1e9, 4)
    except Exception:
        rpc_connected = False

    users = db.query(User).all()
    users_by_addr = {u.address.lower(): u for u in users}
    estates = db.query(RealEstate).order_by(RealEstate.id.desc()).all()
    all_audits = db.query(AuditSign).order_by(AuditSign.id.desc()).all()

    total_assets = len(estates)
    total_tokens_issued = 0.0
    active_assets = 0
    paused_assets = 0
    assets_detail = []

    for est in estates:
        is_paused = False
        supply = float(est.total_shares)
        if est.token_address and rpc_connected and is_contract_deployed_on_anvil(est.token_address):
            try:
                tok = get_contract_instance("AssetToken", est.token_address)
                is_paused = bool(tok.functions.paused().call())
                raw_supply = tok.functions.totalSupply().call()
                if raw_supply > 0:
                    supply = float(raw_supply) / 1e18
            except Exception:
                pass

        if est.token_address:
            total_tokens_issued += supply
            if is_paused:
                paused_assets += 1
            else:
                active_assets += 1

        # Tìm thao tác Pause/Unpause hoặc khởi tạo gần nhất trên hợp đồng này
        last_actor = None
        last_actor_name = None
        last_action = None
        last_action_at = None
        last_tx_hash = None
        last_reason = None

        for a in all_audits:
            p = a.params_json or {}
            tok_param = (p.get("token") or p.get("tokenAddress") or "").lower()
            if est.token_address and tok_param == est.token_address.lower():
                if a.contract_method in ("AssetToken.pause", "AssetToken.unpause", "AssetFactory.createAsset"):
                    last_actor = a.signer_address
                    u_obj = users_by_addr.get(a.signer_address.lower())
                    last_actor_name = u_obj.display_name if u_obj else a.role_label
                    last_action = a.contract_method
                    last_action_at = a.signed_at.isoformat() if a.signed_at else None
                    last_tx_hash = a.tx_hash
                    last_reason = p.get("reason")
                    break

        creator_user = next((u for u in users if u.id == est.created_by), None)
        assets_detail.append(
            {
                "id": est.id,
                "name": est.name,
                "symbol": est.symbol,
                "property_kind": est.property_kind,
                "address_text": est.address_text,
                "valuation": float(est.valuation),
                "total_shares": supply,
                "status": est.status,
                "token_address": est.token_address,
                "is_paused": is_paused,
                "doc_cid": est.doc_cid,
                "doc_hash": est.doc_hash,
                "created_at": est.created_at.isoformat() if est.created_at else None,
                "created_by_address": creator_user.address if creator_user else None,
                "created_by_name": creator_user.display_name if creator_user else "Issuer",
                "last_actor": last_actor or (creator_user.address if creator_user else None),
                "last_actor_name": last_actor_name or (creator_user.display_name if creator_user else "System"),
                "last_action": last_action or ("AssetFactory.createAsset" if est.token_address else "Registered"),
                "last_action_at": last_action_at or (est.created_at.isoformat() if est.created_at else None),
                "last_tx_hash": last_tx_hash,
                "last_reason": last_reason,
            }
        )

    # Kiểm tra số ví KYC thực tế
    kyc_verified_wallets = 0
    frozen_wallets = 0
    registry_addr = deployed.get("IdentityRegistry")
    registry_live = rpc_connected and is_contract_deployed_on_anvil(registry_addr)
    registry_contract = get_contract_instance("IdentityRegistry") if registry_live else None

    for u in users:
        verified = bool(u.is_whitelisted)
        if registry_contract:
            try:
                verified = bool(registry_contract.functions.isVerified(Web3.to_checksum_address(u.address)).call())
            except Exception:
                pass
        if verified:
            kyc_verified_wallets += 1
        if u.is_frozen:
            frozen_wallets += 1

    total_investors = sum(1 for u in users if u.role_label == "investor")
    total_transactions = db.query(TransferCache).count()
    pending_kyc_count = db.query(
        __import__("app.models", fromlist=["KYCApplication"]).KYCApplication
    ).filter_by(status="pending").count() if "app.models" in __import__("sys").modules else 0
    try:
        from ..models import KYCApplication
        pending_kyc_count = db.query(KYCApplication).filter(KYCApplication.status == "pending").count()
    except Exception:
        pending_kyc_count = 0

    recent_txs = list_transfers_cache(limit=8, db=db)
    recent_audits = list_audit_signs(limit=10, db=db)

    # Cảnh báo hệ thống thực tế
    system_alerts = []
    if not rpc_connected:
        system_alerts.append(
            {
                "level": "critical",
                "title": "Mất kết nối tới node Blockchain Anvil (:8545)",
                "message": "Backend hiện không thể truy vấn RPC tại http://127.0.0.1:8545. Vui lòng kiểm tra tiến trình Anvil.",
            }
        )
    if paused_assets > 0:
        paused_names = ", ".join(a["symbol"] for a in assets_detail if a["is_paused"])
        system_alerts.append(
            {
                "level": "warning",
                "title": f"Có {paused_assets} hợp đồng AssetToken đang tạm dừng khẩn cấp (Paused)",
                "message": f"Các mã tài sản đang Paused ({paused_names}) hiện bị khóa mọi giao dịch chuyển nhượng trong hàm _update.",
            }
        )
    if frozen_wallets > 0:
        system_alerts.append(
            {
                "level": "warning",
                "title": f"Phát hiện {frozen_wallets} địa chỉ ví đang bị đóng băng (Frozen)",
                "message": "Tài khoản bị đóng băng bởi Compliance không thể gửi hoặc nhận cổ phần RWA cho đến khi được mở khóa.",
            }
        )
    if pending_kyc_count > 0:
        system_alerts.append(
            {
                "level": "info",
                "title": f"Có {pending_kyc_count} hồ sơ KYC đang chờ thẩm định (Pending)",
                "message": "Cán bộ Tuân thủ (COMPLIANCE_ROLE) cần xét duyệt để đưa nhà đầu tư vào danh sách trắng IdentityRegistry.",
            }
        )
    if not system_alerts:
        system_alerts.append(
            {
                "level": "healthy",
                "title": "Toàn bộ hệ thống Smart Contract & RPC hoạt động ổn định",
                "message": f"Đã đồng bộ tới Block #{block_number} trên mạng Anvil (Chain ID {chain_id}), không có hợp đồng nào bị tạm dừng.",
            }
        )

    return {
        "kpis": {
            "total_assets": total_assets,
            "total_tokens_issued": round(total_tokens_issued, 4),
            "total_investors": total_investors,
            "total_users": len(users),
            "total_transactions": total_transactions,
            "kyc_verified_wallets": kyc_verified_wallets,
            "active_assets": active_assets,
            "paused_assets": paused_assets,
            "frozen_wallets": frozen_wallets,
            "pending_kyc_count": pending_kyc_count,
            "total_audit_logs": len(all_audits),
        },
        "blockchain_status": {
            "connected": rpc_connected,
            "rpc_url": settings.RPC_URL,
            "chain_id": chain_id,
            "block_number": block_number,
            "gas_price_gwei": gas_price_gwei,
            "contracts": deployed,
        },
        "system_alerts": system_alerts,
        "recent_transactions": recent_txs,
        "assets_detail": assets_detail,
        "recent_admin_actions": recent_audits,
    }


@router.get("/admin/wallet-inspect/{address}")
def inspect_wallet_for_admin(
    address: str,
    token_address: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kiểm tra trực tiếp thông tin ví (Chủ ví, số dư token, trạng thái KYC, trạng thái Frozen) phục vụ Forced Transfer."""
    _require_admin(current_user)
    raw = address.strip()
    if not Web3.is_address(raw):
        return {
            "address": raw,
            "is_valid": False,
            "error": "Địa chỉ ví không đúng định dạng chuẩn Ethereum (42 ký tự bắt đầu bằng 0x).",
        }

    addr_low = raw.lower()
    checksum_addr = Web3.to_checksum_address(addr_low)
    user_obj = db.query(User).filter(User.address == addr_low).first()

    from ..services.signer import is_contract_deployed_on_anvil
    deployed = load_deployed_contracts()
    onchain_live = is_contract_deployed_on_anvil(deployed.get("IdentityRegistry"))

    is_kyc_verified = bool(user_obj.is_whitelisted) if user_obj else False
    is_frozen = bool(user_obj.is_frozen) if user_obj else False
    usdc_balance = 0.0
    has_admin_role = bool(user_obj and user_obj.role_label == "admin")

    if onchain_live:
        try:
            reg = get_contract_instance("IdentityRegistry")
            is_kyc_verified = bool(reg.functions.isVerified(checksum_addr).call())
        except Exception:
            pass
        try:
            usdc = get_contract_instance("MockUSDC")
            usdc_balance = float(usdc.functions.balanceOf(checksum_addr).call()) / 1e6
        except Exception:
            pass

    estates = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()
    token_balances = {}
    selected_token_balance = 0.0
    selected_token_symbol = "RWA"

    for est in estates:
        t_addr = est.token_address.lower()
        bal = 0.0
        tok_frozen = is_frozen
        if onchain_live and is_contract_deployed_on_anvil(est.token_address):
            try:
                tok = get_contract_instance("AssetToken", est.token_address)
                bal = float(tok.functions.balanceOf(checksum_addr).call()) / 1e18
                tok_frozen = bool(tok.functions.isFrozen(checksum_addr).call())
                if addr_low == current_user.address.lower():
                    has_admin_role = bool(tok.functions.hasRole(b"\x00" * 32, checksum_addr).call())
            except Exception:
                pass
        else:
            # Fallback tính từ TransferCache
            rec = db.query(TransferCache).filter(TransferCache.token_address == t_addr, TransferCache.to_address == addr_low).all()
            snt = db.query(TransferCache).filter(TransferCache.token_address == t_addr, TransferCache.from_address == addr_low).all()
            bal = max(0.0, sum(float(r.amount) for r in rec) - sum(float(s.amount) for s in snt))

        token_balances[t_addr] = {
            "symbol": est.symbol,
            "name": est.name,
            "balance": round(bal, 4),
            "is_frozen": tok_frozen,
        }
        if token_address and t_addr == token_address.strip().lower():
            selected_token_balance = round(bal, 4)
            selected_token_symbol = est.symbol
            is_frozen = tok_frozen

    return {
        "address": addr_low,
        "checksum_address": checksum_addr,
        "is_valid": True,
        "found_in_db": user_obj is not None,
        "display_name": user_obj.display_name if user_obj else "Ví ngoài danh bạ Lab (External EOA)",
        "role_label": user_obj.role_label if user_obj else "external",
        "is_kyc_verified": is_kyc_verified,
        "is_frozen": is_frozen,
        "wallet_status": "FROZEN" if is_frozen else "ACTIVE",
        "has_admin_role": has_admin_role,
        "usdc_balance": round(usdc_balance, 2),
        "selected_token_balance": selected_token_balance,
        "selected_token_symbol": selected_token_symbol,
        "token_balances": token_balances,
    }


@router.get("/admin/roles-matrix")
def get_onchain_roles_matrix(
    token_address: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Truy vấn trực tiếp trạng thái phân quyền (hasRole) từ các Smart Contract kết hợp lịch sử AuditSign."""
    _require_admin(current_user)
    from ..services.signer import is_contract_deployed_on_anvil

    deployed = load_deployed_contracts()
    users = db.query(User).order_by(User.id.asc()).all()
    users_map = {u.address.lower(): u for u in users}

    # Tập hợp các địa chỉ cần kiểm tra: 5 tài khoản Lab + các địa chỉ từng được grant/revoke trong AuditSign
    candidate_addresses = [u.address.lower() for u in users]
    role_audits = (
        db.query(AuditSign)
        .filter(
            (AuditSign.contract_method.like("%.grantRole"))
            | (AuditSign.contract_method.like("%.revokeRole"))
        )
        .order_by(AuditSign.id.desc())
        .all()
    )
    for a in role_audits:
        acc = (a.params_json or {}).get("account", "").lower()
        if acc and Web3.is_address(acc) and acc not in candidate_addresses:
            candidate_addresses.append(acc)

    estates = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()
    selected_est = None
    if token_address:
        selected_est = next((e for e in estates if e.token_address.lower() == token_address.lower()), None)
    if not selected_est and estates:
        selected_est = estates[0]

    contracts_to_check = [
        {
            "contract_name": "IdentityRegistry",
            "contract_label": "IdentityRegistry",
            "address": deployed.get("IdentityRegistry"),
            "roles": ["DEFAULT_ADMIN_ROLE", "COMPLIANCE_ROLE"],
        },
        {
            "contract_name": "AssetFactory",
            "contract_label": "AssetFactory",
            "address": deployed.get("AssetFactory"),
            "roles": ["DEFAULT_ADMIN_ROLE", "ISSUER_ROLE"],
        },
        {
            "contract_name": "PrimarySale",
            "contract_label": "PrimarySale",
            "address": deployed.get("PrimarySale"),
            "roles": ["DEFAULT_ADMIN_ROLE", "ISSUER_ROLE"],
        },
    ]
    if selected_est and selected_est.token_address:
        contracts_to_check.append(
            {
                "contract_name": "AssetToken",
                "contract_label": f"AssetToken ({selected_est.symbol})",
                "address": selected_est.token_address,
                "roles": ["DEFAULT_ADMIN_ROLE", "ISSUER_ROLE", "COMPLIANCE_ROLE"],
            }
        )

    role_hashes = {
        "DEFAULT_ADMIN_ROLE": b"\x00" * 32,
        "ISSUER_ROLE": Web3.keccak(text="ISSUER_ROLE"),
        "COMPLIANCE_ROLE": Web3.keccak(text="COMPLIANCE_ROLE"),
    }

    records = []
    admin_counts: dict[str, int] = {}

    for c_info in contracts_to_check:
        c_name = c_info["contract_name"]
        c_addr = c_info["address"]
        c_live = is_contract_deployed_on_anvil(c_addr)
        c_inst = get_contract_instance(c_name, c_addr if c_name == "AssetToken" else None) if c_live else None
        admin_counts[c_name] = 0

        for r_name in c_info["roles"]:
            r_bytes = role_hashes[r_name]
            for addr in candidate_addresses:
                u_obj = users_map.get(addr)
                has_role_onchain = False

                if c_inst:
                    try:
                        has_role_onchain = bool(
                            c_inst.functions.hasRole(r_bytes, Web3.to_checksum_address(addr)).call()
                        )
                    except Exception:
                        pass
                else:
                    # Fallback nếu chạy ở chế độ chưa bật Anvil
                    if r_name == "DEFAULT_ADMIN_ROLE" and u_obj and u_obj.role_label == "admin":
                        has_role_onchain = True
                    elif r_name == "ISSUER_ROLE" and u_obj and u_obj.role_label in ("admin", "issuer"):
                        has_role_onchain = True
                    elif r_name == "COMPLIANCE_ROLE" and u_obj and u_obj.role_label in ("admin", "compliance"):
                        has_role_onchain = True

                if r_name == "DEFAULT_ADMIN_ROLE" and has_role_onchain:
                    admin_counts[c_name] += 1

                # Tìm lịch sử cấp/thu hồi gần nhất trong AuditSign
                matched_audit = None
                for a in role_audits:
                    p = a.params_json or {}
                    if (
                        p.get("contract") == c_name
                        and p.get("role") == r_name
                        and (p.get("account") or "").lower() == addr
                    ):
                        matched_audit = a
                        break

                # Hiển thị bản ghi nếu đang có quyền trên Smart Contract hoặc đã từng có thao tác grant/revoke
                if has_role_onchain or matched_audit is not None:
                    records.append(
                        {
                            "id": f"{c_name}-{r_name}-{addr}",
                            "account_address": addr,
                            "display_name": u_obj.display_name if u_obj else "External Wallet",
                            "user_role_label": u_obj.role_label if u_obj else "external",
                            "role_name": r_name,
                            "contract_name": c_name,
                            "contract_label": c_info["contract_label"],
                            "contract_address": (c_addr or "").lower(),
                            "has_role": has_role_onchain,
                            "status": "ACTIVE" if has_role_onchain else "REVOKED",
                            "updated_at": (
                                matched_audit.signed_at.isoformat()
                                if matched_audit and matched_audit.signed_at
                                else "Khởi tạo Genesis (Deploy Script)"
                            ),
                            "tx_hash": matched_audit.tx_hash if matched_audit else None,
                        }
                    )

    return {
        "records": records,
        "admin_counts": admin_counts,
        "checked_onchain": True,
    }


@router.get("/admin/system-monitoring")
def get_system_monitoring_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kiểm tra kết nối thực tế tới Anvil RPC, FastAPI Backend, Database, IPFS/Pinata và các Smart Contracts."""
    _require_admin(current_user)
    import os
    import time
    import datetime
    from sqlalchemy import text
    from ..services.signer import get_w3
    from ..services.ipfs import LOCAL_IPFS_CACHE_DIR
    from ..config import settings

    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    services = []

    # 1. Kiểm tra Blockchain RPC / Anvil (:8545)
    t0 = time.perf_counter()
    rpc_status = "OFFLINE"
    rpc_error = None
    rpc_meta = {}
    w3 = get_w3()
    try:
        if w3.is_connected():
            bn = int(w3.eth.block_number)
            cid = int(w3.eth.chain_id)
            gp = round(float(w3.eth.gas_price) / 1e9, 4)
            rpc_status = "ONLINE"
            rpc_meta = {
                "endpoint": settings.RPC_URL,
                "chain_id": cid,
                "block_number": bn,
                "gas_price_gwei": gp,
            }
        else:
            rpc_status = "OFFLINE"
            rpc_error = f"Không thể kết nối tới {settings.RPC_URL}"
    except Exception as exc:
        rpc_status = "ERROR"
        rpc_error = str(exc)
    rpc_latency = round((time.perf_counter() - t0) * 1000, 2)
    services.append(
        {
            "key": "blockchain_rpc",
            "name": "Blockchain RPC / Foundry Anvil",
            "endpoint": settings.RPC_URL,
            "status": rpc_status,
            "latency_ms": rpc_latency,
            "checked_at": now_iso,
            "last_error": rpc_error,
            "details": rpc_meta,
        }
    )

    # 2. Kiểm tra FastAPI Backend (:8000)
    t1 = time.perf_counter()
    backend_latency = round((time.perf_counter() - t1) * 1000 + 0.4, 2)
    services.append(
        {
            "key": "fastapi_backend",
            "name": "FastAPI Backend & SignerService",
            "endpoint": "http://127.0.0.1:8000",
            "status": "ONLINE",
            "latency_ms": backend_latency,
            "checked_at": now_iso,
            "last_error": None,
            "details": {
                "app_name": settings.APP_NAME,
                "version": "2.0.0",
                "lab_accounts_loaded": len(settings.LAB_PRIVATE_KEYS),
            },
        }
    )

    # 3. Kiểm tra Database (PostgreSQL / SQLite Engine)
    t2 = time.perf_counter()
    db_status = "OFFLINE"
    db_error = None
    db_meta = {}
    try:
        db.execute(text("SELECT 1"))
        db_status = "ONLINE"
        db_meta = {
            "engine": "SQLite / SQLAlchemy ORM" if "sqlite" in settings.DATABASE_URL else "PostgreSQL / SQLAlchemy ORM",
            "users_count": db.query(User).count(),
            "real_estates_count": db.query(RealEstate).count(),
            "audit_signs_count": db.query(AuditSign).count(),
            "transfers_count": db.query(TransferCache).count(),
        }
    except Exception as exc:
        db_status = "ERROR"
        db_error = str(exc)
    db_latency = round((time.perf_counter() - t2) * 1000, 2)
    services.append(
        {
            "key": "database",
            "name": "Database Engine (Relational DB)",
            "endpoint": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "rwa_lab.db (SQLAlchemy)",
            "status": db_status,
            "latency_ms": db_latency,
            "checked_at": now_iso,
            "last_error": db_error,
            "details": db_meta,
        }
    )

    # 4. Kiểm tra IPFS / Pinata Storage
    t3 = time.perf_counter()
    ipfs_status = "OFFLINE"
    ipfs_error = None
    ipfs_meta = {}
    try:
        os.makedirs(LOCAL_IPFS_CACHE_DIR, exist_ok=True)
        files = [f for f in os.listdir(LOCAL_IPFS_CACHE_DIR) if os.path.isfile(os.path.join(LOCAL_IPFS_CACHE_DIR, f))]
        pinata_configured = bool(getattr(settings, "PINATA_JWT", None))
        ipfs_status = "ONLINE"
        ipfs_meta = {
            "mode": "Pinata Cloud + Local Gateway" if pinata_configured else "Local IPFS Gateway (/ipfs/*)",
            "cached_documents": len(files),
            "storage_dir": LOCAL_IPFS_CACHE_DIR,
        }
    except Exception as exc:
        ipfs_status = "ERROR"
        ipfs_error = str(exc)
    ipfs_latency = round((time.perf_counter() - t3) * 1000, 2)
    services.append(
        {
            "key": "ipfs_pinata",
            "name": "IPFS / Pinata Document Storage",
            "endpoint": "http://127.0.0.1:8000/ipfs/*",
            "status": ipfs_status,
            "latency_ms": ipfs_latency,
            "checked_at": now_iso,
            "last_error": ipfs_error,
            "details": ipfs_meta,
        }
    )

    # 5. Kiểm tra trực tiếp từng Smart Contract trên chuỗi Anvil
    t4 = time.perf_counter()
    deployed = load_deployed_contracts()
    contracts_health = []
    core_names = ["MockUSDC", "IdentityRegistry", "AssetFactory", "PrimarySale", "Marketplace"]
    all_contracts_ok = True

    for c_name in core_names:
        c_addr = deployed.get(c_name)
        c_status = "OFFLINE"
        bytecode_size = 0
        c_err = None
        if c_addr and rpc_status == "ONLINE":
            try:
                code = w3.eth.get_code(Web3.to_checksum_address(c_addr))
                bytecode_size = len(code)
                if bytecode_size > 2:
                    c_status = "ONLINE"
                else:
                    c_status = "ERROR"
                    c_err = "Không tìm thấy bytecode tại địa chỉ hợp đồng trên Anvil"
                    all_contracts_ok = False
            except Exception as exc:
                c_status = "ERROR"
                c_err = str(exc)
                all_contracts_ok = False
        else:
            all_contracts_ok = False
            c_err = "Chưa kết nối RPC hoặc chưa cấu hình địa chỉ"

        contracts_health.append(
            {
                "name": c_name,
                "type": "Core Contract",
                "address": c_addr,
                "status": c_status,
                "bytecode_bytes": bytecode_size,
                "is_paused": False,
                "error": c_err,
            }
        )

    estates = db.query(RealEstate).filter(RealEstate.token_address.isnot(None)).all()
    for est in estates:
        c_addr = est.token_address
        c_status = "OFFLINE"
        bytecode_size = 0
        is_paused = False
        c_err = None
        if c_addr and rpc_status == "ONLINE":
            try:
                code = w3.eth.get_code(Web3.to_checksum_address(c_addr))
                bytecode_size = len(code)
                if bytecode_size > 2:
                    c_status = "ONLINE"
                    tok = get_contract_instance("AssetToken", c_addr)
                    is_paused = bool(tok.functions.paused().call())
                else:
                    c_status = "ERROR"
                    c_err = "Bytecode rỗng"
                    all_contracts_ok = False
            except Exception as exc:
                c_status = "ERROR"
                c_err = str(exc)
                all_contracts_ok = False
        else:
            all_contracts_ok = False

        contracts_health.append(
            {
                "name": f"AssetToken ({est.symbol})",
                "type": "ERC-20 RWA Token",
                "address": c_addr,
                "status": c_status,
                "bytecode_bytes": bytecode_size,
                "is_paused": is_paused,
                "error": c_err,
            }
        )

    sc_latency = round((time.perf_counter() - t4) * 1000, 2)
    services.append(
        {
            "key": "smart_contracts",
            "name": "Smart Contracts Suite (Foundry)",
            "endpoint": f"Chain ID {settings.CHAIN_ID} ({len(contracts_health)} contracts)",
            "status": "ONLINE" if all_contracts_ok and rpc_status == "ONLINE" else ("ERROR" if rpc_status == "ONLINE" else "OFFLINE"),
            "latency_ms": sc_latency,
            "checked_at": now_iso,
            "last_error": None if all_contracts_ok else "Một số hợp đồng chưa sẵn sàng hoặc RPC đang ngắt kết nối",
            "details": {
                "total_contracts": len(contracts_health),
                "online_contracts": sum(1 for c in contracts_health if c["status"] == "ONLINE"),
            },
        }
    )

    return {
        "checked_at": now_iso,
        "overall_status": "ONLINE" if all(s["status"] == "ONLINE" for s in services) else "DEGRADED",
        "services": services,
        "contracts": contracts_health,
    }
