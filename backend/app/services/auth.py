import hashlib
import hmac
import secrets
import datetime
from typing import Optional
from fastapi import Depends, HTTPException, Header, Request
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, SessionModel
from ..config import settings


def hash_password(raw_password: str, salt: Optional[str] = None) -> str:
    """Băm mật khẩu an toàn bằng PBKDF2-HMAC-SHA256 kèm salt ngẫu nhiên."""
    salt_hex = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw_password.encode("utf-8"), salt_hex.encode("utf-8"), 100_000)
    return f"pbkdf2_sha256${salt_hex}${dk.hex()}"


def verify_password(raw_password: str, stored_hash: Optional[str]) -> bool:
    if not stored_hash:
        return False
    try:
        algo, salt_hex, hash_hex = stored_hash.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", raw_password.encode("utf-8"), salt_hex.encode("utf-8"), 100_000)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def create_lab_session(db: Session, user: User) -> SessionModel:
    token = secrets.token_hex(32)
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=settings.SESSION_EXPIRATION_HOURS)
    session_obj = SessionModel(
        token=token,
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)
    return session_obj


def delete_lab_session(db: Session, token: Optional[str]) -> None:
    if not token:
        return
    db.query(SessionModel).filter(SessionModel.token == token).delete()
    db.commit()


def revoke_user_sessions(db: Session, user_id: int, keep_token: Optional[str] = None) -> None:
    """Thu hồi toàn bộ phiên cũ của người dùng (trừ phiên hiện tại nếu chỉ định)."""
    q = db.query(SessionModel).filter(SessionModel.user_id == user_id)
    if keep_token:
        q = q.filter(SessionModel.token != keep_token)
    q.delete(synchronize_session=False)
    db.commit()


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_session_address: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    # 1. Kiểm tra Bearer Session Token từ header hoặc cookie
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif "rwa_session_token" in request.cookies:
        token = request.cookies.get("rwa_session_token")

    if token:
        sess = (
            db.query(SessionModel)
            .filter(
                SessionModel.token == token,
                SessionModel.expires_at > datetime.datetime.utcnow(),
            )
            .first()
        )
        if not sess:
            raise HTTPException(
                status_code=401,
                detail="Phiên đăng nhập đã hết hạn hoặc đã đăng xuất. Vui lòng đăng nhập lại tại /login!",
            )
        user = db.query(User).filter(User.id == sess.user_id).first()
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Tài khoản gắn với phiên làm việc không còn tồn tại.",
            )
        return user

    # 2. Hỗ trợ header X-Session-Address chỉ khi không gửi Bearer Token (tương thích kịch bản kiểm thử Lab)
    if x_session_address:
        user = db.query(User).filter(User.address == x_session_address.lower()).first()
        if user:
            return user

    raise HTTPException(
        status_code=401,
        detail="Bạn chưa đăng nhập phiên làm việc. Vui lòng đăng nhập tài khoản tại /login!",
    )


def get_optional_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_session_address: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    try:
        return get_current_user(request, authorization, x_session_address, db)
    except HTTPException:
        return None
