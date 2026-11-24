from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User, Notification
from ..services.auth import get_current_user

router = APIRouter(prefix="/notifications", tags=["Thông báo hệ thống (Notifications)"])


def create_notification(
    db: Session,
    user_id: int,
    category: str,
    title: str,
    message: str,
    tx_hash: Optional[str] = None,
) -> Notification:
    """Tạo bản ghi thông báo mới cho tài khoản người dùng."""
    notif = Notification(
        user_id=user_id,
        category=category,
        title=title,
        message=message,
        tx_hash=tx_hash,
        is_read=False,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


@router.get("")
def list_my_notifications(
    limit: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)  # noqa: E712
        .count()
    )
    return {
        "unread_count": unread_count,
        "items": [
            {
                "id": r.id,
                "category": r.category,
                "title": r.title,
                "message": r.message,
                "tx_hash": r.tx_hash,
                "is_read": r.is_read,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/{notif_id}/read")
def mark_notification_read(
    notif_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notif = (
        db.query(Notification)
        .filter(Notification.id == notif_id, Notification.user_id == current_user.id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông báo")
    notif.is_read = True
    db.commit()
    return {"status": "ok", "id": notif_id}


@router.post("/read-all")
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False,  # noqa: E712
    ).update({"is_read": True})
    db.commit()
    return {"status": "ok"}
