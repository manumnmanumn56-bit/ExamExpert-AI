"""
ExamExpert AI — In-App & Email Notification Dispatch Service
SJB Institute of Technology | Office of Controller of Examinations

Implements Module 13 (Slice A):
1. In-App Notifications:
   - HOD when an allocation request is submitted for their department
   - Admin when HOD approves or rejects a request
   - Faculty when approved and officially appointed as question paper setter
2. Real-Time Scoping:
   - Each user can only view their own notifications
   - Unread count calculation and read/unread status management
3. SMTP Email Dispatch:
   - Dispatches email ONLY if SMTP credentials are fully configured in environment
   - Otherwise records IN_APP delivery with a transparent note
   - Strict security: Never exposes OTPs, passwords, or SMTP secrets in logs or messages
"""
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..models import InAppNotification, User, Faculty, Subject, Allocation, AllocationSetter
from .migration import resolve_department_names


def is_smtp_configured() -> bool:
    """Checks whether SMTP configuration is present in environment variables."""
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASSWORD")
    return bool(host and user and pwd)


def try_send_email(recipient_email: str, subject_line: str, body_text: str) -> str:
    """
    Attempts to send email if SMTP is configured.
    Returns status: 'SENT', 'NOT_CONFIGURED', or 'FAILED'.
    Safely catches exceptions so missing network/SMTP never interrupts workflow.
    """
    if not is_smtp_configured():
        return "NOT_CONFIGURED"

    if not recipient_email or "@" not in recipient_email:
        return "FAILED"

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASSWORD")

    try:
        msg = MIMEText(body_text, "plain", "utf-8")
        msg["Subject"] = f"[ExamExpert AI] {subject_line}"
        msg["From"] = user
        msg["To"] = recipient_email

        with smtplib.SMTP(host, port, timeout=5) as server:
            server.starttls()
            server.login(user, pwd)
            server.send_message(msg)
        return "SENT"
    except Exception as e:
        # Never log raw credentials or sensitive trace
        return "FAILED"


def create_in_app_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    event_type: str,
    entity_type: str = "Allocation",
    entity_id: Optional[int] = None,
    recipient_email: Optional[str] = None
) -> InAppNotification:
    """
    Creates an InAppNotification record for a specific user and attempts email dispatch if configured.
    """
    email_status = "NOT_CONFIGURED"
    if recipient_email:
        email_status = try_send_email(recipient_email, title, message)

    notif = InAppNotification(
        user_id=user_id,
        recipient_email=recipient_email,
        title=title,
        message=message,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        is_read=False,
        created_at=datetime.utcnow(),
        email_status=email_status
    )
    db.add(notif)
    db.flush()
    return notif


def notify_request_submitted(
    db: Session,
    alloc: Allocation,
    subject: Optional[Subject],
    submitter_username: str
) -> List[InAppNotification]:
    """
    Notifies HOD user(s) of the department that a new allocation request has been submitted.
    """
    dept_variants = resolve_department_names(db, alloc.department or "")
    hod_users = db.query(User).filter(
        User.role == "HOD",
        User.department.in_(dept_variants) if dept_variants else User.department == alloc.department
    ).all()

    subj_label = f"{subject.course_code} - {subject.title}" if subject else alloc.department
    created = []

    for hod in hod_users:
        title = f"New Allocation Request: {alloc.reference_number}"
        message = (
            f"An allocation request for course '{subj_label}' ({alloc.academic_year}, Semester {alloc.semester}) "
            f"has been submitted by {submitter_username}. Please review the nominated question paper setters and submit your approval."
        )
        notif = create_in_app_notification(
            db=db,
            user_id=hod.id,
            title=title,
            message=message,
            event_type="REQUEST_SUBMITTED",
            entity_type="Allocation",
            entity_id=alloc.id,
            recipient_email=hod.email
        )
        created.append(notif)

    return created


def notify_request_approved(
    db: Session,
    alloc: Allocation,
    subject: Optional[Subject],
    approver_username: str
) -> List[InAppNotification]:
    """
    Notifies Admin user(s) and assigned Faculty members upon HOD approval.
    """
    subj_label = f"{subject.course_code} - {subject.title}" if subject else alloc.department
    created = []

    # 1. Notify Admin User(s)
    admin_users = db.query(User).filter(User.role == "Admin").all()
    for adm in admin_users:
        title = f"Allocation Approved: {alloc.reference_number}"
        message = (
            f"Department HOD '{approver_username}' has formally approved the allocation order for "
            f"'{subj_label}' ({alloc.academic_year}). Candidate workload commitments have been locked."
        )
        notif = create_in_app_notification(
            db=db,
            user_id=adm.id,
            title=title,
            message=message,
            event_type="REQUEST_APPROVED",
            entity_type="Allocation",
            entity_id=alloc.id,
            recipient_email=adm.email
        )
        created.append(notif)

    # 2. Notify Appointed Faculty Setters
    setters = db.query(AllocationSetter).filter_by(allocation_id=alloc.id).all()
    for s in setters:
        fac = s.faculty or db.query(Faculty).filter_by(id=s.faculty_id).first()
        if not fac:
            continue

        # Look up linked User account
        fac_user = db.query(User).filter(
            or_(User.faculty_id == fac.id, User.email == fac.email)
        ).first()

        if fac_user:
            title = f"Appointed as Question Paper Setter: {subject.course_code if subject else ''}"
            message = (
                f"Dear {fac.name}, you have been officially approved and appointed as Question Paper Setter "
                f"for course '{subj_label}' in academic cycle {alloc.academic_year}."
            )
            notif = create_in_app_notification(
                db=db,
                user_id=fac_user.id,
                title=title,
                message=message,
                event_type="FACULTY_ASSIGNED",
                entity_type="Allocation",
                entity_id=alloc.id,
                recipient_email=fac.email
            )
            created.append(notif)

    return created


def notify_request_rejected(
    db: Session,
    alloc: Allocation,
    subject: Optional[Subject],
    rejecter_username: str,
    reason: str
) -> List[InAppNotification]:
    """
    Notifies Admin user(s) upon HOD rejection of an allocation request.
    """
    subj_label = f"{subject.course_code} - {subject.title}" if subject else alloc.department
    created = []

    admin_users = db.query(User).filter(User.role == "Admin").all()
    for adm in admin_users:
        title = f"Allocation Rejected: {alloc.reference_number}"
        message = (
            f"Department HOD '{rejecter_username}' has rejected the allocation request for '{subj_label}'. "
            f"Reason: {reason}. Workload reservations have been released."
        )
        notif = create_in_app_notification(
            db=db,
            user_id=adm.id,
            title=title,
            message=message,
            event_type="REQUEST_REJECTED",
            entity_type="Allocation",
            entity_id=alloc.id,
            recipient_email=adm.email
        )
        created.append(notif)

    return created
