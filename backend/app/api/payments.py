import datetime
import hashlib
import hmac
import re
import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import load_deployed_contracts
from ..database import get_db
from ..models import ListingCache, PaymentOTP, PrimarySaleCache, RealEstate, User
from ..schemas import PaymentOtpConfirmRequest, PaymentOtpRequest
from ..services.auth import get_current_user
from ..services.email_service import (
    send_payment_confirmation_email,
    send_payment_otp_email,
)
from ..services.listener import record_transfer_cache, sync_onchain_state
from ..services.signer import SignerService, get_contract_instance
from ..services.w3_compat import Web3
from .notifications import create_notification

router = APIRouter(prefix="/payments", tags=["6. Xác thực Thanh toán Gmail OTP (2FA On-chain)"])

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OTP_CODE_REGEX = re.compile(r"^\d{6}$")
OTP_EXPIRY_MINUTES = 5
OTP_MAX_ATTEMPTS = 5


def _sha256_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _precheck_and_resolve_payment(
    db: Session,
    current_user: User,
    tx_type: str,
    target_id: int,
    amount: float,
) -> Dict[str, Any]:
    """
    Kiểm tra toàn diện điều kiện trước khi phát hành OTP hoặc ký giao dịch on-chain:
    - KYC (IdentityRegistry.isVerified)
    - Tài khoản không bị đóng băng (isFrozen)
    - Token không bị tạm dừng (paused)
    - Đợt bán sơ cấp / lệnh Marketplace đang mở & đủ số lượng còn lại
    - Số dư MockUSDC của nhà đầu tư đủ thanh toán
    """
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Số lượng phần sở hữu đặt mua phải lớn hơn 0!")

    tx_type_norm = (tx_type or "").strip().upper()
    if tx_type_norm not in ("PRIMARY_BUY", "MARKET_BUY"):
        raise HTTPException(
            status_code=400,
            detail="Loại giao dịch không hợp lệ! Chỉ chấp nhận PRIMARY_BUY hoặc MARKET_BUY.",
        )

    registry = get_contract_instance("IdentityRegistry")
    usdc = get_contract_instance("MockUSDC")
    buyer_checksum = Web3.to_checksum_address(current_user.address)

    # 1. Kiểm tra KYC
    try:
        is_verified = bool(registry.functions.isVerified(buyer_checksum).call())
    except Exception:
        is_verified = bool(current_user.is_whitelisted)

    if not is_verified:
        raise HTTPException(
            status_code=400,
            detail="Từ chối nghiệp vụ: Tài khoản của bạn chưa được duyệt KYC trên IdentityRegistry. Vui lòng hoàn tất KYC trước khi thanh toán!",
        )

    seller_address: Optional[str] = None
    if tx_type_norm == "PRIMARY_BUY":
        est = db.query(RealEstate).filter(RealEstate.id == target_id).first()
        if not est or not est.token_address:
            raise HTTPException(status_code=404, detail="Không tìm thấy bất động sản đã được token hóa!")

        token_addr = est.token_address.lower()
        estate_name = est.name
        token_symbol = est.symbol
        total_shares_fallback = float(est.total_shares or 1)

        primary_sale = get_contract_instance("PrimarySale")
        token_checksum = Web3.to_checksum_address(token_addr)
        ps_cache = db.query(PrimarySaleCache).filter(PrimarySaleCache.real_estate_id == est.id).first()

        try:
            sale_info = primary_sale.functions.getSaleInfo(token_checksum).call()
            is_open = bool(sale_info[5])
            price_raw = int(sale_info[1])
            remaining_shares = float(sale_info[3]) / 1e18
        except Exception:
            is_open = bool(ps_cache.is_open) if ps_cache else False
            price_raw = int(float(ps_cache.price_per_share) * 1e6) if ps_cache else 100_000_000
            remaining_shares = float(ps_cache.remaining_amount) if ps_cache else 0.0

        if not is_open:
            raise HTTPException(status_code=400, detail="Đợt bán sơ cấp của bất động sản này hiện đã đóng!")
        if amount > remaining_shares:
            raise HTTPException(
                status_code=400,
                detail=f"Số lượng đặt mua ({amount:,.2f}) vượt quá số cổ phần còn lại ({remaining_shares:,.2f})!",
            )
    else:
        marketplace = get_contract_instance("Marketplace")
        lcache = db.query(ListingCache).filter(ListingCache.listing_id == target_id).first()
        try:
            item = marketplace.functions.getListing(target_id).call()
            is_open = bool(item[6])
            if not is_open:
                raise HTTPException(status_code=400, detail="Lệnh niêm yết trên Marketplace không còn mở!")
            token_addr = item[1].lower()
            seller_address = item[2].lower()
            remaining_shares = float(item[4]) / 1e18
            price_raw = int(item[5])
        except HTTPException:
            raise
        except Exception:
            if not lcache or lcache.status != "open":
                raise HTTPException(status_code=400, detail="Lệnh niêm yết trên Marketplace không còn mở!")
            token_addr = lcache.token_address.lower()
            seller_address = lcache.seller_address.lower()
            remaining_shares = float(lcache.remaining_amount)
            price_raw = int(float(lcache.price_per_share) * 1e6)

        if seller_address == current_user.address.lower():
            raise HTTPException(
                status_code=400,
                detail="Không thể tự mua lệnh niêm yết của chính địa chỉ ví của mình!",
            )
        if amount > remaining_shares:
            raise HTTPException(
                status_code=400,
                detail=f"Số lượng đặt mua ({amount:,.2f}) vượt quá số lượng còn lại ({remaining_shares:,.2f}) trong lệnh niêm yết!",
            )

        est = db.query(RealEstate).filter(RealEstate.token_address == token_addr).first()
        estate_name = est.name if est else f"AssetToken ({token_addr[:10]}...)"
        token_symbol = est.symbol if est else "RWA"
        total_shares_fallback = float(est.total_shares if est else 1)

    # 2. Kiểm tra Frozen & Paused trên AssetToken
    asset_token = get_contract_instance("AssetToken", token_addr)
    try:
        onchain_frozen = bool(asset_token.functions.isFrozen(buyer_checksum).call())
    except Exception:
        onchain_frozen = False

    if current_user.is_frozen or onchain_frozen:
        raise HTTPException(
            status_code=400,
            detail="Giao dịch bị chặn bởi Smart Contract: Tài khoản của bạn hiện đang bị đóng băng (Frozen)!",
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

    # 3. Tính toán tổng tiền & kiểm tra số dư MockUSDC
    amount_wei = int(amount * (10 ** 18))
    total_usdc_raw = (amount_wei * price_raw) // (10 ** 18)
    total_usdc_human = round(float(total_usdc_raw) / 1e6, 6)
    price_per_share_human = round(float(price_raw) / 1e6, 6)

    try:
        buyer_usdc_raw = int(usdc.functions.balanceOf(buyer_checksum).call())
        if buyer_usdc_raw < total_usdc_raw:
            buyer_usdc_human = float(buyer_usdc_raw) / 1e6
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Số dư MockUSDC không đủ để thanh toán! "
                    f"Cần ${total_usdc_human:,.2f} MockUSDC, ví hiện có ${buyer_usdc_human:,.2f} MockUSDC. "
                    "Vui lòng nhấn '+Faucet' để nhận thêm MockUSDC thử nghiệm."
                ),
            )
    except HTTPException:
        raise
    except Exception:
        pass

    return {
        "tx_type": tx_type_norm,
        "target_id": target_id,
        "token_address": token_addr,
        "estate_name": estate_name,
        "token_symbol": token_symbol,
        "total_shares_fallback": total_shares_fallback,
        "amount": amount,
        "amount_wei": amount_wei,
        "price_raw": price_raw,
        "price_per_share": price_per_share_human,
        "total_usdc_raw": total_usdc_raw,
        "expected_total_usdc": total_usdc_human,
        "seller_address": seller_address,
    }


def _read_post_purchase_metrics(
    token_address: str,
    buyer_address: str,
    total_shares_fallback: float,
) -> tuple[float, float, float]:
    buyer_checksum = Web3.to_checksum_address(buyer_address)
    usdc = get_contract_instance("MockUSDC")
    new_usdc_bal = 0.0
    new_token_bal = 0.0
    total_shares = max(total_shares_fallback, 1.0)
    try:
        new_usdc_bal = round(float(usdc.functions.balanceOf(buyer_checksum).call()) / 1e6, 2)
    except Exception:
        pass
    try:
        asset_token = get_contract_instance("AssetToken", token_address)
        new_token_bal = round(float(asset_token.functions.balanceOf(buyer_checksum).call()) / 1e18, 6)
        raw_supply = asset_token.functions.totalSupply().call()
        if raw_supply and raw_supply > 0:
            total_shares = float(raw_supply) / 1e18
    except Exception:
        pass
    ownership_pct = round((new_token_bal / total_shares) * 100.0, 4) if total_shares > 0 else 0.0
    return new_usdc_bal, new_token_bal, ownership_pct


@router.post("/request-otp")
async def request_payment_otp(
    req: PaymentOtpRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Bước 1: Kiểm tra trước toàn bộ điều kiện on-chain (KYC, Frozen, Paused, Đợt bán/Listing, Số dư MockUSDC),
    khóa tham số giao dịch vào payment_otps, sinh mã OTP 6 chữ số (lưu SHA-256) và gửi về Gmail.
    """
    if current_user.role_label != "investor":
        raise HTTPException(
            status_code=403,
            detail="Từ chối phân quyền (403 RBAC): Chỉ tài khoản Nhà đầu tư (investor) mới được thực hiện mua cổ phần!",
        )

    clean_email = (req.email or "").strip()
    if not clean_email or not EMAIL_REGEX.match(clean_email) or len(clean_email) > 255:
        raise HTTPException(
            status_code=400,
            detail="Vui lòng nhập địa chỉ Gmail hợp lệ để nhận mã xác thực OTP!",
        )

    resolved = _precheck_and_resolve_payment(
        db=db,
        current_user=current_user,
        tx_type=req.tx_type,
        target_id=req.target_id,
        amount=req.amount,
    )

    # Hủy toàn bộ mã OTP pending cũ của user này để đảm bảo chỉ có 1 mã hiệu lực
    db.query(PaymentOTP).filter(
        PaymentOTP.user_id == current_user.id,
        PaymentOTP.status == "pending",
    ).update({"status": "expired"}, synchronize_session=False)

    otp_code = f"{secrets.randbelow(1_000_000):06d}"
    otp_hash = _sha256_otp(otp_code)
    now_utc = datetime.datetime.utcnow()
    expires_at = now_utc + datetime.timedelta(minutes=OTP_EXPIRY_MINUTES)

    locked_payload = {
        "tx_type": resolved["tx_type"],
        "target_id": resolved["target_id"],
        "token_address": resolved["token_address"],
        "estate_name": resolved["estate_name"],
        "token_symbol": resolved["token_symbol"],
        "total_shares_fallback": resolved["total_shares_fallback"],
        "amount": resolved["amount"],
        "price_per_share": resolved["price_per_share"],
        "expected_total_usdc": resolved["expected_total_usdc"],
        "seller_address": resolved["seller_address"],
    }

    otp_row = PaymentOTP(
        user_id=current_user.id,
        email=clean_email,
        otp_hash=otp_hash,
        tx_type=resolved["tx_type"],
        payload_json=locked_payload,
        attempts=0,
        status="pending",
        expires_at=expires_at,
        created_at=now_utc,
    )
    db.add(otp_row)
    db.commit()
    db.refresh(otp_row)

    # Gửi mã OTP 6 chữ số về Gmail (báo lỗi rõ ràng nếu gửi thất bại)
    send_res = await send_payment_otp_email(
        user_id=current_user.id,
        recipient_email=clean_email,
        investor_name=current_user.display_name,
        wallet_address=current_user.address,
        otp_id=otp_row.id,
        otp_code=otp_code,
        tx_type=resolved["tx_type"],
        estate_name=resolved["estate_name"],
        token_symbol=resolved["token_symbol"],
        amount_shares=resolved["amount"],
        price_per_share=resolved["price_per_share"],
        total_usdc=resolved["expected_total_usdc"],
        expires_minutes=OTP_EXPIRY_MINUTES,
        listing_id=resolved["target_id"] if resolved["tx_type"] == "MARKET_BUY" else None,
    )

    if not send_res["sent"]:
        otp_row.status = "failed"
        db.commit()
        raise HTTPException(
            status_code=502,
            detail=f"Không thể gửi mã OTP về Gmail ({clean_email}): {send_res.get('error_message') or 'Lỗi dịch vụ gửi email'}",
        )

    return {
        "otp_id": otp_row.id,
        "message": f"Đã gửi mã OTP 6 chữ số về Gmail {clean_email}",
        "email": clean_email,
        "expires_in_seconds": OTP_EXPIRY_MINUTES * 60,
        "tx_type": resolved["tx_type"],
        "expected_total_usdc": resolved["expected_total_usdc"],
        "channel": send_res["channel"],
    }


@router.post("/confirm")
def confirm_payment_otp(
    req: PaymentOtpConfirmRequest,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Bước 2: Xác thực mã OTP 6 chữ số (SHA-256, hạn 5 phút, tối đa 5 lần sai).
    Khi OTP hợp lệ -> đọc tham số giao dịch đã khóa ở Bước 1 và ký giao dịch on-chain qua Signer Service.
    """
    if current_user.role_label != "investor":
        raise HTTPException(
            status_code=403,
            detail="Từ chối phân quyền (403 RBAC): Chỉ tài khoản Nhà đầu tư (investor) mới được xác nhận thanh toán!",
        )

    clean_code = (req.otp_code or "").strip()
    if not OTP_CODE_REGEX.match(clean_code):
        raise HTTPException(status_code=400, detail="Mã OTP phải gồm đúng 6 chữ số (0–9)!")

    otp_row = db.query(PaymentOTP).filter(PaymentOTP.id == req.otp_id.strip()).first()
    if not otp_row:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên xác thực OTP! Vui lòng gửi lại mã mới.")

    if otp_row.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Mã OTP này không thuộc về tài khoản đang đăng nhập!")

    if otp_row.status == "verified":
        raise HTTPException(status_code=400, detail="Mã OTP này đã được sử dụng để thanh toán trước đó!")
    if otp_row.status == "expired":
        raise HTTPException(status_code=400, detail="Mã OTP đã hết hạn hoặc đã bị thay thế bởi mã mới. Vui lòng gửi lại mã!")
    if otp_row.status == "failed" or otp_row.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=400,
            detail="Phiên OTP đã bị khóa do nhập sai quá 5 lần. Vui lòng tạo yêu cầu OTP mới!",
        )

    now_utc = datetime.datetime.utcnow()
    if now_utc > otp_row.expires_at:
        otp_row.status = "expired"
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Mã OTP đã hết hạn (quá 5 phút hiệu lực). Vui lòng nhấn 'Gửi lại mã' để nhận mã mới!",
        )

    # So sánh băm SHA-256 an toàn thời gian hằng (chống timing attack)
    if not hmac.compare_digest(_sha256_otp(clean_code), otp_row.otp_hash):
        otp_row.attempts += 1
        remaining_attempts = OTP_MAX_ATTEMPTS - otp_row.attempts
        if remaining_attempts <= 0:
            otp_row.status = "failed"
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="Bạn đã nhập sai mã OTP quá 5 lần! Giao dịch đã bị hủy, vui lòng gửi lại mã OTP mới.",
            )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Mã OTP không chính xác! Bạn còn {remaining_attempts} lần thử.",
        )

    # OTP HỢP LỆ -> Đọc tham số giao dịch đã khóa ở Bước 1 & kiểm tra lại điều kiện on-chain
    locked = otp_row.payload_json or {}
    tx_type = locked["tx_type"]
    target_id = int(locked["target_id"])
    amount = float(locked["amount"])

    resolved = _precheck_and_resolve_payment(
        db=db,
        current_user=current_user,
        tx_type=tx_type,
        target_id=target_id,
        amount=amount,
    )

    usdc = get_contract_instance("MockUSDC")
    deployed = load_deployed_contracts()
    amount_wei = resolved["amount_wei"]
    total_usdc_raw = resolved["total_usdc_raw"]
    total_usdc_human = resolved["expected_total_usdc"]
    price_per_share_human = resolved["price_per_share"]
    token_addr = resolved["token_address"]
    token_checksum = Web3.to_checksum_address(token_addr)

    if tx_type == "PRIMARY_BUY":
        primary_sale = get_contract_instance("PrimarySale")
        spender_checksum = Web3.to_checksum_address(deployed["PrimarySale"])

        approve_res = SignerService.sign_and_send(
            db=db,
            current_user=current_user,
            contract_function=usdc.functions.approve(spender_checksum, total_usdc_raw),
            contract_method_name="MockUSDC.approve",
            params_summary={
                "spender": spender_checksum,
                "usdc_amount": total_usdc_human,
                "purpose": f"OTP-Verified PrimarySale.buy({resolved['token_symbol']})",
                "otp_id": otp_row.id,
            },
            required_roles=["investor"],
        )

        buy_res = SignerService.sign_and_send(
            db=db,
            current_user=current_user,
            contract_function=primary_sale.functions.buy(token_checksum, amount_wei),
            contract_method_name="PrimarySale.buy",
            params_summary={
                "token": token_addr,
                "symbol": resolved["token_symbol"],
                "shares_amount": amount,
                "price_per_share": price_per_share_human,
                "usdc_paid": total_usdc_human,
                "otp_id": otp_row.id,
            },
            required_roles=["investor"],
        )

        receipt = buy_res["receipt"]
        if getattr(receipt, "status", 1) != 1:
            raise HTTPException(status_code=400, detail="Giao dịch PrimarySale.buy không thành công trên chuỗi!")

        ps_cache = db.query(PrimarySaleCache).filter(PrimarySaleCache.real_estate_id == target_id).first()
        if ps_cache and not buy_res.get("onchain"):
            ps_cache.remaining_amount = max(0.0, float(ps_cache.remaining_amount) - amount)
            if float(ps_cache.remaining_amount) <= 0:
                ps_cache.is_open = False
            db.commit()

        from_addr_cache = spender_checksum.lower()
        event_type_cache = "PRIMARY_BUY"
    else:
        marketplace = get_contract_instance("Marketplace")
        spender_checksum = Web3.to_checksum_address(deployed["Marketplace"])

        approve_res = SignerService.sign_and_send(
            db=db,
            current_user=current_user,
            contract_function=usdc.functions.approve(spender_checksum, total_usdc_raw),
            contract_method_name="MockUSDC.approve",
            params_summary={
                "spender": spender_checksum,
                "usdc_amount": total_usdc_human,
                "listingId": target_id,
                "otp_id": otp_row.id,
            },
            required_roles=["investor"],
        )

        buy_res = SignerService.sign_and_send(
            db=db,
            current_user=current_user,
            contract_function=marketplace.functions.buy(target_id, amount_wei),
            contract_method_name="Marketplace.buy",
            params_summary={
                "listingId": target_id,
                "amount": amount,
                "price_per_share": price_per_share_human,
                "usdc_paid": total_usdc_human,
                "otp_id": otp_row.id,
            },
            required_roles=["investor"],
        )

        receipt = buy_res["receipt"]
        if getattr(receipt, "status", 1) != 1:
            raise HTTPException(status_code=400, detail="Giao dịch Marketplace.buy không thành công trên chuỗi!")

        lcache = db.query(ListingCache).filter(ListingCache.listing_id == target_id).first()
        if lcache and not buy_res.get("onchain"):
            lcache.remaining_amount = max(0.0, float(lcache.remaining_amount) - amount)
            if float(lcache.remaining_amount) <= 0:
                lcache.status = "filled"
            db.commit()

        from_addr_cache = (resolved["seller_address"] or spender_checksum).lower()
        event_type_cache = "MARKET_BUY"

    block_number = int(getattr(receipt, "blockNumber", 1) or 1)
    record_transfer_cache(
        db=db,
        tx_hash=buy_res["tx_hash"],
        block_number=block_number,
        event_type=event_type_cache,
        token_address=token_addr,
        from_address=from_addr_cache,
        to_address=current_user.address.lower(),
        amount_shares=amount,
        usdc_paid=total_usdc_human,
    )

    # Đánh dấu OTP đã xác thực thành công
    otp_row.status = "verified"
    db.commit()
    sync_onchain_state(db)

    new_usdc_bal, new_token_bal, ownership_pct = _read_post_purchase_metrics(
        token_address=token_addr,
        buyer_address=current_user.address,
        total_shares_fallback=resolved["total_shares_fallback"],
    )

    # Gửi thông báo hệ thống trên trang web cho người nhận cổ phần (và người bán trên Marketplace)
    try:
        shares_str = f"{int(amount):,}" if float(amount).is_integer() else f"{float(amount):,.2f}"
        if tx_type == "PRIMARY_BUY":
            create_notification(
                db=db,
                user_id=current_user.id,
                category="transfer",
                title=f"Nhận +{shares_str} {resolved['token_symbol']} (Mua sơ cấp)",
                message=(
                    f"Bạn vừa nhận được {shares_str} cổ phần {resolved['token_symbol']} ({resolved['estate_name']}) "
                    f"từ đợt mở bán sơ cấp với tổng thanh toán ${total_usdc_human:,.2f} MockUSDC."
                ),
                tx_hash=buy_res["tx_hash"],
            )
        else:
            create_notification(
                db=db,
                user_id=current_user.id,
                category="transfer",
                title=f"Nhận +{shares_str} {resolved['token_symbol']} từ Marketplace",
                message=(
                    f"Bạn vừa nhận chuyển nhượng {shares_str} cổ phần {resolved['token_symbol']} "
                    f"({resolved['estate_name']}) từ lệnh #{target_id} với tổng thanh toán "
                    f"${total_usdc_human:,.2f} MockUSDC."
                ),
                tx_hash=buy_res["tx_hash"],
            )
            seller_addr_l = (resolved.get("seller_address") or "").lower()
            if seller_addr_l:
                seller_user = db.query(User).filter(User.address == seller_addr_l).first()
                if seller_user:
                    create_notification(
                        db=db,
                        user_id=seller_user.id,
                        category="transfer",
                        title=f"Đã chuyển nhượng {shares_str} {resolved['token_symbol']} (Lệnh #{target_id})",
                        message=(
                            f"{current_user.display_name} đã mua {shares_str} cổ phần {resolved['token_symbol']} "
                            f"({resolved['estate_name']}) từ lệnh #{target_id} của bạn. "
                            f"Bạn nhận được +${total_usdc_human:,.2f} MockUSDC."
                        ),
                        tx_hash=buy_res["tx_hash"],
                    )
    except Exception:
        pass

    # Gửi biên lai xác nhận hoàn tất giao dịch về Gmail trong nền (BackgroundTasks)
    receipt_email_queued = False
    if otp_row.email and background_tasks is not None:
        background_tasks.add_task(
            send_payment_confirmation_email,
            user_id=current_user.id,
            recipient_email=otp_row.email,
            investor_name=current_user.display_name,
            wallet_address=current_user.address,
            tx_type=tx_type,
            estate_name=resolved["estate_name"],
            token_symbol=resolved["token_symbol"],
            token_address=token_addr,
            amount_shares=amount,
            price_per_share=price_per_share_human,
            total_usdc=total_usdc_human,
            tx_hash=buy_res["tx_hash"],
            block_number=block_number,
            ownership_percent=ownership_pct,
            new_token_balance=new_token_bal,
            listing_id=target_id if tx_type == "MARKET_BUY" else None,
        )
        receipt_email_queued = True

    return {
        "otp_id": otp_row.id,
        "otp_verified": True,
        "tx_type": tx_type,
        "approve_tx_hash": approve_res["tx_hash"],
        "tx_hash": buy_res["tx_hash"],
        "block_number": block_number,
        "shares_bought": amount,
        "price_per_share": price_per_share_human,
        "usdc_paid": total_usdc_human,
        "new_usdc_balance": new_usdc_bal,
        "new_token_balance": new_token_bal,
        "ownership_percent": ownership_pct,
        "receipt_email_queued": receipt_email_queued,
        "recipient_email": otp_row.email,
    }
