"""
ExamExpert AI — Reports & Analytics API Router
SJB Institute of Technology | Office of Controller of Examinations

Implements Module 14 (Slice B):
1. Comprehensive institutional and departmental reporting endpoints:
   - Summary statistics & status breakdowns
   - Faculty workload & active paper-setting commitments
   - Department allocation distributions
   - Subject-wise allocation order archive
   - External institution distribution (Admin only)
   - Pending verification faculty roster
   - Dataset import batches history
2. Multi-Format Export:
   - Excel export (.xlsx) with OWASP formula injection neutralization
   - PDF export with official SJBIT COE letterhead
   - Printable HTML view for browser direct printing
3. Server-Enforced Role Scoping:
   - Admin: Full institutional access
   - HOD: Department internal faculty & subjects; external faculty restricted (HTTP 403)
   - Faculty: Own personal assignments, profile, and workload only (HTTP 403 for others)
4. Real Data Integrity:
   - Zero mock data; all metrics computed from live database rows
   - Missing data displayed as 'Not provided'
"""
import os
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Allocation, AllocationSetter, Faculty, NotificationLog, AuditLog, User
from ..services.pdf_generator import generate_allocation_pdf
from ..services.migration import resolve_department_names
from ..services.importer import export_faculty_to_excel, export_allocations_to_excel
from ..services.reports_service import (
    get_summary_report,
    get_faculty_workload_report,
    get_department_allocations_report,
    get_subject_allocations_report,
    get_institution_distribution_report,
    get_pending_verification_report,
    get_import_batches_report,
    export_report_to_excel,
    export_report_to_pdf,
    get_printable_html_report
)
from .auth import require_roles, get_current_user

router = APIRouter(prefix="/api/reports", tags=["Reports & Analytics"])

PDF_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "generated_reports"
)
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)


# ─── Summary & Metrics ───────────────────────────────────────────────────────

@router.get("/summary")
def get_reports_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns high-level summary metrics scoped by user role."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return get_summary_report(db, current_user)


# ─── Dimension Reports ───────────────────────────────────────────────────────

@router.get("/faculty-workload")
def get_faculty_workload_data(
    academic_year: Optional[str] = Query("2025-26"),
    department: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Faculty-wise allocations and active workload commitments."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if current_user.role == "HOD" and department and department != current_user.department:
        raise HTTPException(status_code=403, detail="Access Denied: HOD can only query own department.")

    if academic_year is not None and not isinstance(academic_year, str):
        academic_year = "2025-26"
    if department is not None and not isinstance(department, str):
        department = None

    rows = get_faculty_workload_report(db, current_user, academic_year, department)
    return {"total": len(rows), "records": rows}


@router.get("/department-allocations")
def get_department_allocations_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Department-wise allocations breakdown and setter distributions."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if current_user.role == "Faculty":
        raise HTTPException(status_code=403, detail="Access Denied: Faculty cannot view departmental summaries.")

    try:
        rows = get_department_allocations_report(db, current_user)
        return {"total": len(rows), "records": rows}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/subject-allocations")
def get_subject_allocations_data(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Subject-wise allocation order archive with status and nominated setters."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if status is not None and not isinstance(status, str):
        status = None

    rows = get_subject_allocations_report(db, current_user, status)
    return {"total": len(rows), "records": rows}


@router.get("/institution-distribution")
def get_institution_distribution_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """External institution distribution and whitelist status (Admin Only)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access Denied: External faculty reports are restricted to Administrators.")

    try:
        rows = get_institution_distribution_report(db, current_user)
        return {"total": len(rows), "records": rows}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/pending-verification")
def get_pending_verification_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Faculty members pending credential verification."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if current_user.role == "Faculty":
        raise HTTPException(status_code=403, detail="Access Denied: Faculty cannot view verification rosters.")

    try:
        rows = get_pending_verification_report(db, current_user)
        return {"total": len(rows), "records": rows}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/import-batches")
def get_import_batches_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Dataset ETL import history and file hashes (Admin Only)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access Denied: Import batch history is restricted to Administrators.")

    try:
        rows = get_import_batches_report(db, current_user)
        return {"total": len(rows), "records": rows}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ─── Multi-Format Exports ───────────────────────────────────────────────────

@router.get("/export-excel")
def export_excel(
    report_type: str = Query("faculty_workload"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Exports report dataset to Excel (.xlsx) with OWASP formula injection neutralization.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if report_type in ("institution_distribution", "import_batches") and current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access Denied: Report restricted to Administrators.")

    if report_type == "department_allocations" and current_user.role == "Faculty":
        raise HTTPException(status_code=403, detail="Access Denied: Faculty cannot export department summaries.")

    try:
        excel_bytes = export_report_to_excel(db, report_type, current_user)
        filename = f"SJBIT_Report_{report_type}.xlsx"
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/export-pdf")
def export_pdf(
    report_type: str = Query("faculty_workload"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generates official executive report PDF."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if report_type in ("institution_distribution", "import_batches") and current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access Denied: Report restricted to Administrators.")

    if report_type == "department_allocations" and current_user.role == "Faculty":
        raise HTTPException(status_code=403, detail="Access Denied: Faculty cannot export department summaries.")

    try:
        pdf_bytes = export_report_to_pdf(db, report_type, current_user)
        filename = f"SJBIT_Executive_Report_{report_type}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/print-summary", response_class=HTMLResponse)
def get_printable_summary_view(
    report_type: str = Query("faculty_workload"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generates printer-friendly HTML view for browser print / save-as-PDF."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if report_type in ("institution_distribution", "import_batches") and current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Access Denied: Report restricted to Administrators.")

    if report_type == "department_allocations" and current_user.role == "Faculty":
        raise HTTPException(status_code=403, detail="Access Denied: Faculty cannot export department summaries.")

    try:
        html = get_printable_html_report(db, report_type, current_user)
        return HTMLResponse(content=html)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ─── Legacy Document & Order Downloads ───────────────────────────────────────

@router.get("/download-pdf/{allocation_id}")
def download_pdf(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Downloads official PDF appointment order for a specific allocation."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    alloc = db.query(Allocation).filter_by(id=allocation_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation record not found.")

    # Slice 1: PDF is strictly blocked until HOD approval (status == "Approved")
    if alloc.status != "Approved":
        raise HTTPException(
            status_code=400,
            detail=f"Access Denied: Appointment order PDF is only available after HOD approval. Current status is '{alloc.status}'."
        )

    # Server-side role checks: Admin, HOD of the department, or assigned Faculty
    if current_user.role == "Admin":
        pass  # Admin can download any approved order
    elif current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        if dept_variants and alloc.department not in dept_variants:
            raise HTTPException(status_code=403, detail="Access Denied: You can only download orders for your department.")
    elif current_user.role == "Faculty":
        setter = db.query(AllocationSetter).filter_by(allocation_id=alloc.id, faculty_id=current_user.faculty_id).first()
        if not setter:
            raise HTTPException(status_code=403, detail="Access Denied: You are not assigned to this allocation order.")
    else:
        raise HTTPException(status_code=403, detail="Access Denied: Role not authorized to download appointment orders.")

    subj = alloc.subject
    int_ids = json.loads(alloc.internal_faculty_ids or "[]")
    ext_ids = json.loads(alloc.external_faculty_ids or "[]")

    setters_map = {s.faculty_id: s for s in alloc.setters}
    int_faculty = [
        {
            "name": f.name,
            "designation": f.designation,
            "institution": f.institution,
            "is_manual_override": getattr(setters_map.get(f.id), "is_manual_override", False),
            "manual_reason": getattr(setters_map.get(f.id), "manual_reason", None)
        }
        for f in db.query(Faculty).filter(Faculty.id.in_(int_ids)).all()
    ]
    ext_faculty = [
        {
            "name": f.name,
            "designation": f.designation,
            "institution": f.institution,
            "is_manual_override": getattr(setters_map.get(f.id), "is_manual_override", False),
            "manual_reason": getattr(setters_map.get(f.id), "manual_reason", None)
        }
        for f in db.query(Faculty).filter(Faculty.id.in_(ext_ids)).all()
    ]

    alloc_data = {
        "reference_number": alloc.reference_number,
        "academic_year": alloc.academic_year,
        "department": alloc.department,
        "semester": alloc.semester,
        "allocation_ratio": alloc.allocation_ratio,
        "has_manual_override": getattr(alloc, "has_manual_override", False),
        "exception_reason": alloc.exception_reason,
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
    current_user: User = Depends(require_roles(["Admin"]))
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
    current_user: User = Depends(require_roles(["Admin", "HOD"]))
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
    channel: Optional[str] = None,
    allocation_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin", "HOD"]))
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
    current_user: User = Depends(require_roles(["Admin"]))
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
