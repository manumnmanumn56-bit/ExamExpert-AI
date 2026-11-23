"""
ExamExpert AI — In-App Notifications API Router
SJB Institute of Technology | Office of Controller of Examinations

Implements Module 13 (Slice A):
- In-app notification inbox scoped strictly to the authenticated user.
- Unread count indicator for real-time header badge.
- Read/unread state transitions with timestamps.
- Transparent SMTP delivery indicator note.
- Strict security: Never exposes credentials, OTPs, or passwords.
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import InAppNotification, User
from ..services.notification_service import is_smtp_configured
from .auth import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["In-App Notifications"])


@router.get("/my")
def get_my_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns in-app notifications strictly scoped to the authenticated user.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    query = db.query(InAppNotification).filter(InAppNotification.user_id == current_user.id)
    if unread_only:
        query = query.filter(InAppNotification.is_read == False)

    notifications = query.order_by(InAppNotification.created_at.desc()).limit(limit).all()
    unread_count = db.query(InAppNotification).filter(
        InAppNotification.user_id == current_user.id,
        InAppNotification.is_read == False
    ).count()

    results = []
    for n in notifications:
        results.append({
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "event_type": n.event_type,
            "entity_type": n.entity_type,
            "entity_id": n.entity_id,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "read_at": n.read_at.isoformat() if n.read_at else None,
            "email_status": n.email_status
        })

    return {
        "success": True,
        "smtp_configured": is_smtp_configured(),
        "unread_count": unread_count,
        "notifications": results
    }


@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns unread notification count for the authenticated user to update the UI badge.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    count = db.query(InAppNotification).filter(
        InAppNotification.user_id == current_user.id,
        InAppNotification.is_read == False
    ).count()

    return {
        "unread_count": count,
        "smtp_configured": is_smtp_configured()
    }


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Marks a specific notification as read.
    User can only update their own notifications.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    notif = db.query(InAppNotification).filter(
        InAppNotification.id == notification_id,
        InAppNotification.user_id == current_user.id
    ).first()

    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")

    notif.is_read = True
    notif.read_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "message": "Notification marked as read.",
        "id": notif.id,
        "is_read": True
    }


@router.post("/mark-all-read")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Marks all notifications for the authenticated user as read.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    now = datetime.utcnow()
    updated = db.query(InAppNotification).filter(
        InAppNotification.user_id == current_user.id,
        InAppNotification.is_read == False
    ).update({"is_read": True, "read_at": now}, synchronize_session=False)

    db.commit()

    return {
        "success": True,
        "message": f"Marked {updated} notification(s) as read.",
        "updated_count": updated
    }
