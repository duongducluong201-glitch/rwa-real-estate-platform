import re
import time
import threading
from collections import defaultdict
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, Request, Header
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, func
from eth_account import Account
from ..database import get_db
from ..models import User, KYCApplication
from ..config import ANVIL_EXTRA_ACCOUNTS, LAB_SEED_ACCOUNTS
from ..schemas import (
    LabAccountResponse,
    SessionLoginRequest,
    RegisterAccountRequest,
    ChangePasswordRequest,
    SessionLoginResponse,
)
from ..services.auth import (
    create_lab_session,
    delete_lab_session,
    revoke_user_sessions,
    get_current_user,
    hash_password,
    verify_password,
)
from ..services.listener import sync_onchain_state
from ..services.signer import get_w3
from ..services.w3_compat import Web3

router = APIRouter(prefix="/auth", tags=["1. Xác thực Tài khoản & Phân quyền (Auth — UC-01)"])

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_REGEX = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
RESERVED_USERNAMES = {"system", "root", "superuser", "null", "undefined", "anonymous"}

# Chống dò mật khẩu (Brute-force rate limiting: tối đa 5 lần sai trong 60 giây)
_LOGIN_FAIL_LOCK = threading.Lock()
_LOGIN_FAIL_TRACKER: dict[str, list[float]] = defaultdict(list)
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60


def _check_rate_limit(key: str) -> None:
    now = time.time()
    with _LOGIN_FAIL_LOCK:
        timestamps = [t for t in _LOGIN_FAIL_TRACKER[key] if now - t < LOGIN_WINDOW_SECONDS]
        _LOGIN_FAIL_TRACKER[key] = timestamps
        if len(timestamps) >= MAX_LOGIN_ATTEMPTS:
            wait_sec = max(1, int(LOGIN_WINDOW_SECONDS - (now - timestamps[0])))
            raise HTTPException(
                status_code=429,
                detail=f"Bạn đã nhập sai mật khẩu quá {MAX_LOGIN_ATTEMPTS} lần liên tiếp. Vui lòng thử lại sau {wait_sec} giây!",
            )


def _record_login_failure(key: str) -> None:
    with _LOGIN_FAIL_LOCK:
        _LOGIN_FAIL_TRACKER[key].append(time.time())


def _clear_login_failures(key: str) -> None:
    with _LOGIN_FAIL_LOCK:
        _LOGIN_FAIL_TRACKER.pop(key, None)


def _provision_wallet_for_new_user(db: Session) -> tuple[str, str]:
    """
    Cấp phát ví Ethereum (EOA) riêng cho tài khoản mới đăng ký:
    1. Ưu tiên cấp từ các ví Anvil dư có sẵn 10,000 ETH (#5 -> #9).
    2. Nếu đã dùng hết, tạo mới bằng eth_account.Account.create() và tự động nạp 10 ETH gas từ Admin #0.
    """
    used_addrs = {u.address.lower() for u in db.query(User.address).all()}
    for extra in ANVIL_EXTRA_ACCOUNTS:
        if extra["address"].lower() not in used_addrs:
            return extra["address"].lower(), extra["private_key"]

    acct = Account.create()
    new_addr = acct.address.lower()
    new_pk = "0x" + acct.key.hex().removeprefix("0x")

    # Tự động chuyển 10 ETH gas từ Admin #0 trên Anvil để tài khoản mới có thể ký giao dịch on-chain
    try:
        w3 = get_w3()
        if w3.is_connected():
            admin_acc = LAB_SEED_ACCOUNTS[0]
            admin_addr = Web3.to_checksum_address(admin_acc["address"])
            nonce = w3.eth.get_transaction_count(admin_addr, "pending")
            gas_price = w3.eth.gas_price
            tx = {
                "from": admin_addr,
                "to": Web3.to_checksum_address(new_addr),
                "value": 10 * 10**18,
                "gas": 21000,
                "gasPrice": gas_price,
                "nonce": nonce,
                "chainId": w3.eth.chain_id,
            }
            signed = Account.sign_transaction(tx, private_key=admin_acc["private_key"])
            w3.eth.send_raw_transaction(signed.raw_transaction)
    except Exception:
        pass

    return new_addr, new_pk


@router.get("/accounts", response_model=List[dict])
def list_lab_accounts(db: Session = Depends(get_db)):
    """Liệt kê danh sách toàn bộ tài khoản người dùng trong hệ thống kèm vai trò và trạng thái KYC/Frozen."""
    sync_onchain_state(db)
    users = db.query(User).order_by(User.id.asc()).all()
    result = []
    for u in users:
        latest_kyc = (
            db.query(KYCApplication)
            .filter(KYCApplication.user_id == u.id)
            .order_by(KYCApplication.created_at.desc())
            .first()
        )
        result.append(
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "address": u.address,
                "role_label": u.role_label,
                "display_name": u.display_name,
                "is_whitelisted": u.is_whitelisted,
                "is_frozen": u.is_frozen,
                "kyc_status": latest_kyc.status if latest_kyc else ("approved" if u.is_whitelisted else "none"),
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
        )
    return result


@router.post("/register", response_model=SessionLoginResponse)
def register_account(
    req: RegisterAccountRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Đăng ký tài khoản mới (mặc định vai trò Nhà đầu tư - investor, tự động cấp ví EOA trên Anvil)."""
    username = (req.username or "").strip().lower()
    email = (req.email or "").strip().lower()
    display_name = (req.display_name or "").strip()
    password = req.password or ""

    if not USERNAME_REGEX.match(username):
        raise HTTPException(
            status_code=400,
            detail="Tên đăng nhập phải từ 3–40 ký tự, bắt đầu bằng chữ hoặc số, chỉ chứa chữ thường (a-z), số (0-9), dấu chấm, gạch dưới hoặc gạch ngang.",
        )
    if username in RESERVED_USERNAMES:
        raise HTTPException(status_code=400, detail=f"Tên đăng nhập '{username}' là tên hệ thống, vui lòng chọn tên khác.")
    if not EMAIL_REGEX.match(email) or len(email) > 120:
        raise HTTPException(status_code=400, detail="Địa chỉ Email không đúng định dạng (VD: ten@domain.com).")
    if len(password.strip()) < 6 or len(password) > 128:
        raise HTTPException(status_code=400, detail="Mật khẩu phải có từ 6 đến 128 ký tự và không được toàn khoảng trắng.")
    if len(display_name) < 2 or len(display_name) > 100:
        raise HTTPException(status_code=400, detail="Họ và tên hiển thị phải từ 2 đến 100 ký tự.")

    existing = (
        db.query(User)
        .filter(or_(func.lower(User.username) == username, func.lower(User.email) == email))
        .first()
    )
    if existing:
        if (existing.username or "").lower() == username:
            raise HTTPException(status_code=409, detail=f"Tên đăng nhập '{username}' đã tồn tại! Vui lòng chọn tên khác.")
        raise HTTPException(status_code=409, detail=f"Email '{email}' đã được đăng ký cho tài khoản khác!")

    wallet_addr, wallet_pk = _provision_wallet_for_new_user(db)

    new_user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        private_key=wallet_pk,
        address=wallet_addr,
        role_label="investor",
        display_name=display_name,
        is_whitelisted=False,
        is_frozen=False,
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Tên đăng nhập, Email hoặc địa chỉ ví bị trùng lặp trong cơ sở dữ liệu. Vui lòng thử lại!",
        )
    db.refresh(new_user)

    session_obj = create_lab_session(db, new_user)
    response.set_cookie(
        key="rwa_session_token",
        value=session_obj.token,
        httponly=False,
        max_age=60 * 60 * 24,
        samesite="lax",
    )

    return SessionLoginResponse(
        session_token=session_obj.token,
        user=LabAccountResponse.model_validate(new_user),
    )


@router.post("/login", response_model=SessionLoginResponse)
def login_lab_session(
    req: SessionLoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Đăng nhập hệ thống:
    - Chế độ chuẩn: Đăng nhập bằng username / email + mật khẩu (có giới hạn số lần nhập sai chống Brute-force).
    - Chế độ tương thích Lab: Đăng nhập bằng địa chỉ ví address (dành cho kịch bản kiểm thử tự động).
    """
    user: Optional[User] = None

    if req.username or req.password is not None:
        identifier = (req.username or req.address or "").strip().lower()
        if not identifier:
            raise HTTPException(status_code=400, detail="Vui lòng nhập Tên đăng nhập hoặc Email.")
        if not req.password:
            raise HTTPException(status_code=400, detail="Vui lòng nhập mật khẩu.")

        _check_rate_limit(identifier)

        user = (
            db.query(User)
            .filter(
                or_(
                    func.lower(User.username) == identifier,
                    func.lower(User.email) == identifier,
                    func.lower(User.address) == identifier,
                )
            )
            .first()
        )
        if not user or not verify_password(req.password, user.password_hash):
            _record_login_failure(identifier)
            raise HTTPException(
                status_code=401,
                detail="Tên đăng nhập/Email hoặc mật khẩu không chính xác!",
            )
        _clear_login_failures(identifier)
    elif req.address:
        addr = req.address.strip().lower()
        user = db.query(User).filter(func.lower(User.address) == addr).first()
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f"Tài khoản {req.address} không tồn tại trong hệ thống.",
            )
    else:
        raise HTTPException(status_code=400, detail="Thiếu thông tin đăng nhập.")

    session_obj = create_lab_session(db, user)
    response.set_cookie(
        key="rwa_session_token",
        value=session_obj.token,
        httponly=False,
        max_age=60 * 60 * 24,
        samesite="lax",
    )

    return SessionLoginResponse(
        session_token=session_obj.token,
        user=LabAccountResponse.model_validate(user),
    )


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Đổi mật khẩu cho tài khoản đang đăng nhập và thu hồi các phiên cũ khác."""
    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không chính xác!")

    new_pw = req.new_password or ""
    if len(new_pw.strip()) < 6 or len(new_pw) > 128:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải có từ 6 đến 128 ký tự!")
    if req.current_password == new_pw:
        raise HTTPException(status_code=400, detail="Mật khẩu mới không được trùng với mật khẩu hiện tại!")

    current_user.password_hash = hash_password(new_pw)
    db.commit()

    current_token = None
    if authorization and authorization.lower().startswith("bearer "):
        current_token = authorization.split(" ", 1)[1].strip()
    elif "rwa_session_token" in request.cookies:
        current_token = request.cookies.get("rwa_session_token")

    revoke_user_sessions(db, current_user.id, keep_token=current_token)
    return {
        "status": "password_changed",
        "message": "Đổi mật khẩu thành công! Các phiên đăng nhập cũ khác đã được thu hồi.",
    }


@router.post("/logout")
def logout_session(
    request: Request,
    response: Response,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Đăng xuất và hủy phiên làm việc hiện tại."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif "rwa_session_token" in request.cookies:
        token = request.cookies.get("rwa_session_token")

    delete_lab_session(db, token)
    response.delete_cookie("rwa_session_token")
    return {"status": "logged_out", "message": "Đã đăng xuất thành công!"}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    latest_kyc = (
        db.query(KYCApplication)
        .filter(KYCApplication.user_id == current_user.id)
        .order_by(KYCApplication.created_at.desc())
        .first()
    )
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "address": current_user.address,
        "role_label": current_user.role_label,
        "display_name": current_user.display_name,
        "is_whitelisted": current_user.is_whitelisted,
        "is_frozen": current_user.is_frozen,
        "kyc_status": latest_kyc.status if latest_kyc else ("approved" if current_user.is_whitelisted else "none"),
    }
