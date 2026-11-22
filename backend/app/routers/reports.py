"""
ExamExpert AI — Reports & Notifications API Router
SJB Institute of Technology | Office of Controller of Examinations

Generates printable official PDF appointment orders, exports Excel workbooks,
and provides delivery logs for Email and SMS dispatch.
"""
import os, json
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Allocation, Faculty, NotificationLog, AuditLog, User
from ..services.pdf_generator import generate_allocation_pdf
from ..services.importer import export_faculty_to_excel, export_allocations_to_excel
from .auth import require_roles, get_current_user

router = APIRouter(prefix="/api/reports", tags=["Reports & Notifications"])

PDF_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "generated_reports"
)
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)


@router.get("/download-pdf/{allocation_id}")
def download_pdf(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Downloads or generates the official PDF appointment order with HOD department check."""
    alloc = db.query(Allocation).filter_by(id=allocation_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation record not found.")

    if current_user.role == "HOD" and current_user.department and current_user.department not in alloc.department:
        raise HTTPException(status_code=403, detail="Access Denied: You can only download orders for your department.")

    subj = alloc.subject
    int_ids = json.loads(alloc.internal_faculty_ids or "[]")
    ext_ids = json.loads(alloc.external_faculty_ids or "[]")

    int_faculty = [
        {"name": f.name, "designation": f.designation, "institution": f.institution}
        for f in db.query(Faculty).filter(Faculty.id.in_(int_ids)).all()
    ]
    ext_faculty = [
        {"name": f.name, "designation": f.designation, "institution": f.institution}
        for f in db.query(Faculty).filter(Faculty.id.in_(ext_ids)).all()
    ]

    alloc_data = {
        "reference_number": alloc.reference_number,
        "academic_year": alloc.academic_year,
        "department": alloc.department,
        "semester": alloc.semester,
        "allocation_ratio": alloc.allocation_ratio,
        "subject": {
            "code": subj.course_code if subj else "TBD",
            "title": subj.title if subj else "Theory Course",
            "scheme": subj.scheme if subj else "Autonomous",
            "course_type": subj.course_type if subj else "Core"
        },
        "internal_faculty": int_faculty,
        "external_faculty": ext_faculty
    }

    pdf_filename = f"Allocation_Order_{alloc.reference_number}.pdf"
    pdf_path = os.path.join(PDF_STORAGE_DIR, pdf_filename)

    # Generate PDF if not cached on disk
    if not os.path.exists(pdf_path):
        generate_allocation_pdf(alloc_data, pdf_path)

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=pdf_filename
    )


@router.get("/export-faculty-excel")
def download_faculty_excel(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin"]))
):
    """Exports both Internal and External faculty datasets into a formatted Excel file."""
    excel_bytes = export_faculty_to_excel(db)
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=SJBIT_Faculty_Roster.xlsx"}
    )


@router.get("/export-allocations-excel")
def download_allocations_excel(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin", "HOD"]))
):
    """Exports all allocation orders to Excel."""
    excel_bytes = export_allocations_to_excel(db)
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=SJBIT_Examination_Allocations.xlsx"}
    )


@router.get("/notifications")
def get_notifications(
    channel: str | None = None,
    allocation_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin", "HOD"]))
):
    """Returns dispatch logs for Email and SMS notifications."""
    query = db.query(NotificationLog)
    if channel:
        query = query.filter(NotificationLog.channel == channel)
    if allocation_id:
        query = query.filter(NotificationLog.allocation_id == allocation_id)

    logs = query.order_by(NotificationLog.sent_at.desc()).limit(limit).all()

    return {
        "total": len(logs),
        "notifications": [{
            "id": l.id,
            "allocation_id": l.allocation_id,
            "faculty_name": l.faculty_name,
            "channel": l.channel,
            "recipient": l.recipient,
            "message_preview": l.message_preview,
            "status": l.status,
            "is_simulated": l.is_simulated,
            "sent_at": l.sent_at.isoformat() if l.sent_at else ""
        } for l in logs]
    }


@router.get("/audit-logs")
def get_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin"]))
):
    """Returns immutable system activity and security audit trail."""
    logs = db.query(AuditLog).order_by(AuditLog.performed_at.desc()).limit(limit).all()
    return {
        "total": len(logs),
        "logs": [{
            "id": l.id,
            "action": l.action,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "details": l.details,
            "performed_at": l.performed_at.isoformat() if l.performed_at else ""
        } for l in logs]
    }
