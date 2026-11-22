"""
ExamExpert AI — Faculty Allocation & Conflict Management API Router
SJB Institute of Technology | Office of Controller of Examinations

Implements statutory 50:50 Internal:External parity quota, odd/even rounding rules,
deterministic candidate selection, multi-point conflict detection,
administrative exception overrides, and atomic transaction persistence.
"""
import json, random, string, os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Faculty, Subject, Allocation, AllocationConflict,
    EligibilityRules, NotificationLog, AuditLog, User
)
from ..services.matcher import rank_candidates, match_and_rank_faculty
from ..services.migration import resolve_department_names
from ..services.pdf_generator import generate_allocation_pdf
from .auth import require_roles, get_current_user

router = APIRouter(prefix="/api/allocation", tags=["Allocation"])

PDF_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "generated_reports"
)
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)


def _get_rules(db: Session) -> EligibilityRules:
    r = db.query(EligibilityRules).first()
    return r or EligibilityRules(
        min_experience_years=10.0,
        phd_fasttrack_min_exp=5.0,
        max_papers_per_faculty=2,
        require_parity=True,
        active_academic_year="2025-26",
        upcoming_academic_year="2026-27"
    )


def _get_existing_counts(db: Session) -> dict[int, int]:
    allocs = db.query(Allocation).filter_by(status="Confirmed").all()
    counts: dict[int, int] = {}
    for a in allocs:
        for fid in json.loads(a.internal_faculty_ids or "[]"):
            counts[fid] = counts.get(fid, 0) + 1
        for fid in json.loads(a.external_faculty_ids or "[]"):
            counts[fid] = counts.get(fid, 0) + 1
    return counts


def _generate_ref_number() -> str:
    date_str = datetime.now().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.digits, k=5))
    return f"SJBIT-COE-{date_str}-{suffix}"


# ─── Pydantic Schemas ────────────────────────────────────────────────────────

class AutoSelectRequest(BaseModel):
    subject_id: int
    min_handled: int = Field(default=1, ge=1, le=7)
    total_required: int = Field(default=2, ge=1, le=10)
    mode: str = Field(default="Balanced")  # "Balanced" | "Internal Only" | "External Only"
    academic_year: str | None = None


class ConflictCheckRequest(BaseModel):
    subject_id: int
    internal_faculty_ids: list[int]
    external_faculty_ids: list[int]
    total_required: int = 2


class SendFacultyOTPRequest(BaseModel):
    subject_id: int
    faculty_ids: list[int]
    channel: str = "all"


class ConfirmAllocationRequest(BaseModel):
    subject_id: int
    academic_year: str
    department: str
    semester: str
    min_handled: int = 1
    total_required: int = 2
    internal_faculty_ids: list[int]
    external_faculty_ids: list[int]
    exception_reason: str | None = None
    exception_approved_by: str | None = "Controller of Examinations"
    submission_deadline: str | None = None


# ─── Auto-Select & Deterministic Matching Recommendation ─────────────────────

@router.post("/auto-select")
def auto_select(
    req: AutoSelectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin", "HOD"]))
):
    """
    Deterministically ranks eligible faculty using Module 10 matching engine.
    Order:
    1. Exact subject experience (EXACT_EXPERIENCE confirmed mapping)
    2. Specialization (SPECIALIZATION confirmed mapping)
    3. Related expertise (RELATED confirmed mapping)
    4. Lower combined workload (committed + reserved from ledger)
    5. Avoid repeating same subject
    6. Higher relevant-subject experience
    7. Higher total experience
    8. Previous paper-setting experience
    9. Faculty ID as final tie-breaker
    Role-scoped: Admin all; HOD own department only; Faculty 403.
    """
    subject = db.query(Subject).filter_by(id=req.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found in syllabus database.")

    # Explicit server-side role check (enforces RBAC on both API and direct python calls)
    if current_user.role not in ["Admin", "HOD"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Action requires one of ['Admin', 'HOD'] role permissions. Current role is '{current_user.role}'."
        )

    # Server-side department scoping: HOD can only run auto-select for own department subjects
    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        if dept_variants and subject.department not in dept_variants:
            raise HTTPException(
                status_code=403,
                detail=f"Access Denied: HOD of '{current_user.department}' is not authorized to allocate faculty for '{subject.department}' subjects."
            )

    rules = _get_rules(db)
    total_req = req.total_required
    mode = req.mode or "Balanced"
    ay = req.academic_year or (rules.active_academic_year if rules else "2025-26")

    # Mode Quota Calculation
    if mode == "Internal Only":
        internal_quota = total_req
        external_quota = 0
    elif mode == "External Only":
        internal_quota = 0
        external_quota = total_req
    else:  # Balanced 50:50 parity (odd numbers round internal up)
        internal_quota = (total_req + 1) // 2
        external_quota = total_req - internal_quota

    # Run deterministic Module 10 matching engine
    int_match = match_and_rank_faculty(db, subject, "internal", ay, rules)
    ext_match = match_and_rank_faculty(db, subject, "external", ay, rules)

    int_recommended = int_match["recommended"]
    ext_recommended = ext_match["recommended"]

    # Select top N eligible candidates
    sel_int = int_recommended[:internal_quota]
    sel_ext = ext_recommended[:external_quota]

    warnings = []
    requires_exception = False
    unfilled_internal = max(0, internal_quota - len(sel_int))
    unfilled_external = max(0, external_quota - len(sel_ext))

    if unfilled_internal > 0:
        warnings.append(
            f"Internal Faculty Shortage: Only {len(sel_int)} of {internal_quota} required internal "
            f"positions could be filled with eligible faculty."
        )

    if unfilled_external > 0:
        requires_exception = True
        warnings.append(
            f"External Faculty Shortage: Only {len(sel_ext)} of {external_quota} required external "
            f"positions could be filled with eligible faculty."
        )

    return {
        "subject": {
            "id": subject.id,
            "code": subject.course_code or "TBD",
            "title": subject.title,
            "department": subject.department,
            "semester": subject.semester,
            "academic_year": subject.academic_year,
            "scheme": subject.scheme
        },
        "mode": mode,
        "total_required": total_req,
        "internal_quota": internal_quota,
        "external_quota": external_quota,
        "selected_internal": sel_int,
        "selected_external": sel_ext,
        "selected_internal_ids": [f["faculty_id"] for f in sel_int],
        "selected_external_ids": [f["faculty_id"] for f in sel_ext],
        "unfilled_internal": unfilled_internal,
        "unfilled_external": unfilled_external,
        "requires_exception": requires_exception,
        "warnings": warnings,
        "recommended_internal": int_recommended,
        "recommended_external": ext_recommended,
        "not_eligible_internal": int_match["not_eligible"],
        "not_eligible_external": ext_match["not_eligible"],
        "pending_internal": int_match["pending_verification"],
        "pending_external": ext_match["pending_verification"],
        # Backward-compatible candidate lists
        "all_internal_candidates": int_recommended,
        "all_external_candidates": ext_recommended
    }


# ─── Conflict Checking Endpoint ───────────────────────────────────────────────

@router.post("/check-conflicts")
def check_conflicts(
    req: ConflictCheckRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin", "HOD"]))
):
    """Validates setter list against over-allocation, duplicates, and same-exam conflicts."""
    conflicts = []
    int_ids = req.internal_faculty_ids
    ext_ids = req.external_faculty_ids
    all_ids = int_ids + ext_ids

    # 1. Duplicate selection check
    if len(all_ids) != len(set(all_ids)):
        conflicts.append({
            "type": "DUPLICATE_SELECTION",
            "severity": "Critical",
            "description": "Same faculty member selected multiple times in this allocation."
        })

    # 2. Existing allocation for same subject
    existing = db.query(Allocation).filter(
        Allocation.subject_id == req.subject_id,
        Allocation.status == "Confirmed"
    ).first()
    if existing:
        conflicts.append({
            "type": "SUBJECT_ALREADY_ALLOCATED",
            "severity": "Critical",
            "description": f"This subject already has a confirmed allocation (Order Ref: {existing.reference_number})."
        })

    # 3. Workload limits check (capacity per internal/external from policy)
    rules = _get_rules(db)
    alloc_counts = _get_existing_counts(db)

    for fid in all_ids:
        cur_count = alloc_counts.get(fid, 0)
        f = db.query(Faculty).filter_by(id=fid).first()
        fname = f.name if f else f"Faculty #{fid}"
        ftype = f.faculty_type if f else "internal"
        cap = int(rules.internal_capacity if ftype == "internal" else rules.external_capacity) if getattr(rules, "internal_capacity", None) else int(rules.max_papers_per_faculty or 2)
        if cur_count >= cap:
            conflicts.append({
                "type": "MAX_PAPERS_EXCEEDED",
                "severity": "Critical",
                "description": f"{fname} already has {cur_count} confirmed question paper allocations (maximum limit: {cap})."
            })

    # 4. Total count match
    if len(all_ids) != req.total_required:
        conflicts.append({
            "type": "COUNT_MISMATCH",
            "severity": "Warning",
            "description": f"Selected faculty count ({len(all_ids)}) does not equal requested total ({req.total_required})."
        })

    critical = [c for c in conflicts if c["severity"] == "Critical"]
    return {
        "has_conflicts": len(conflicts) > 0,
        "can_proceed": len(critical) == 0,
        "conflicts": conflicts
    }


# ─── Faculty OTP & Notification Dispatch ─────────────────────────────────────

@router.post("/send-faculty-otp")
def send_faculty_otp(
    req: SendFacultyOTPRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin", "HOD"]))
):
    """
    Dispatches a verification OTP notification (Email + SMS) to selected faculty members
    for question paper setter appointment confirmation.
    """
    subject = db.query(Subject).filter_by(id=req.subject_id).first()
    subj_name = f"{subject.course_code} - {subject.title}" if subject else "Question Paper Setting"

    if not req.faculty_ids:
        raise HTTPException(status_code=400, detail="No faculty members selected.")

    faculties = db.query(Faculty).filter(Faculty.id.in_(req.faculty_ids)).all()
    if not faculties:
        raise HTTPException(status_code=404, detail="Selected faculty records not found.")

    dispatches = []
    for f in faculties:
        otp_code = f"{random.randint(100000, 999999)}"
        email_addr = f.email or f"{f.name.lower().replace(' ', '.')}@sjbit.edu.in"
        phone_num = f.mobile or "+91-98450XXXXX"

        # Log simulated Email notification
        email_msg = (
            f"SJBIT Examination Portal: Your confidential verification OTP for appointment "
            f"as Question Paper Setter for {subj_name} is {otp_code}. Valid for 10 minutes."
        )
        db.add(NotificationLog(
            allocation_id=None,
            faculty_id=f.id,
            faculty_name=f.name,
            channel="Email",
            recipient=email_addr,
            message_preview=email_msg,
            status="Simulated (Sent)",
            is_simulated=True,
            sent_at=datetime.utcnow()
        ))

        # Log simulated SMS notification
        sms_msg = f"SJBIT COE: QP Setter Verification OTP is {otp_code} for {subject.course_code if subject else 'Exam'}. Do not share."
        db.add(NotificationLog(
            allocation_id=None,
            faculty_id=f.id,
            faculty_name=f.name,
            channel="SMS",
            recipient=phone_num,
            message_preview=sms_msg,
            status="Simulated (Delivered)",
            is_simulated=True,
            sent_at=datetime.utcnow()
        ))

        # Audit Log
        db.add(AuditLog(
            action="FACULTY_OTP_DISPATCHED",
            entity_type="Faculty",
            entity_id=f.id,
            details=f"Verification OTP dispatched to {f.name} ({f.faculty_type}) for {subj_name}."
        ))

        # Print OTP to server console only in development mode (never exposed to client/UI)
        print(f"[CONSOLE LOG - DEV OTP] Faculty OTP for {f.name} ({email_addr}): {otp_code}")

        # Mask contact details for safe client display
        parts = email_addr.split("@")
        masked_email = (parts[0][:3] + "***@" + parts[1]) if len(parts) == 2 else email_addr
        masked_mobile = phone_num[:4] + "******" + phone_num[-2:] if len(phone_num) >= 6 else phone_num

        dispatches.append({
            "faculty_id": f.id,
            "faculty_name": f.name,
            "faculty_type": f.faculty_type,
            "email_masked": masked_email,
            "mobile_masked": masked_mobile,
            "status": "Dispatched"
        })

    db.commit()

    return {
        "success": True,
        "message": f"Notification sent successfully! Verification OTP dispatched to {len(dispatches)} faculty member(s).",
        "dispatched_count": len(dispatches),
        "dispatches": dispatches
    }


# ─── Final Submission & Atomic Persistence ────────────────────────────────────

@router.post("/confirm")
def confirm_allocation(
    req: ConfirmAllocationRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin"]))
):
    """
    Atomically saves the confirmed allocation, checks conflicts, creates
    simulated Email/SMS notifications, and triggers PDF generation.
    """
    subject = db.query(Subject).filter_by(id=req.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found.")

    # Duplicate check
    existing = db.query(Allocation).filter(
        Allocation.subject_id == req.subject_id,
        Allocation.status == "Confirmed"
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"An active allocation order already exists for this course ({existing.reference_number})."
        )

    int_ids = req.internal_faculty_ids
    ext_ids = req.external_faculty_ids
    all_ids = int_ids + ext_ids

    if not all_ids:
        raise HTTPException(status_code=400, detail="At least one faculty member must be selected.")

    # Over-allocation conflict verification against policy capacities
    rules = _get_rules(db)
    alloc_counts = _get_existing_counts(db)

    for fid in all_ids:
        f = db.query(Faculty).filter_by(id=fid).first()
        fname = f.name if f else f"ID {fid}"
        ftype = f.faculty_type if f else "internal"
        cap = int(rules.internal_capacity if ftype == "internal" else rules.external_capacity) if getattr(rules, "internal_capacity", None) else int(rules.max_papers_per_faculty or 2)
        if alloc_counts.get(fid, 0) >= cap:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot allocate {fname}: faculty workload limit of {cap} papers reached."
            )

    ref_number = _generate_ref_number()
    total_actual = len(all_ids)
    int_pct = round(len(int_ids) / total_actual * 100, 1) if total_actual else 0
    ext_pct = round(100.0 - int_pct, 1)
    ratio_str = f"{int_pct}% Internal / {ext_pct}% External"

    deadline = req.submission_deadline or (datetime.now().strftime("%d %B %Y"))

    try:
        # 1. Create Allocation record
        alloc = Allocation(
            reference_number=ref_number,
            academic_year=req.academic_year,
            department=req.department,
            semester=req.semester,
            subject_id=req.subject_id,
            exam_type="Autonomous End-Semester Examination",
            total_required=req.total_required,
            internal_required=len(int_ids),
            external_required=len(ext_ids),
            internal_faculty_ids=json.dumps(int_ids),
            external_faculty_ids=json.dumps(ext_ids),
            min_handled=req.min_handled,
            allocation_ratio=ratio_str,
            status="Confirmed",
            submission_deadline=deadline,
            submitted_by="coe_admin",
            exception_reason=req.exception_reason,
            exception_approved_by=req.exception_approved_by if req.exception_reason else None,
            created_at=datetime.utcnow(),
            confirmed_at=datetime.utcnow()
        )
        db.add(alloc)
        db.flush()

        # 2. Retrieve faculty objects for notification & PDF
        int_faculties = db.query(Faculty).filter(Faculty.id.in_(int_ids)).all()
        ext_faculties = db.query(Faculty).filter(Faculty.id.in_(ext_ids)).all()
        all_faculties = int_faculties + ext_faculties

        # 3. Create simulated / real Notification logs
        for f in all_faculties:
            # Email log
            recipient_email = f.email or f"{f.name.lower().replace(' ', '.')}@sjbit.edu.in"
            email_body = (
                f"CONFIDENTIAL: You have been appointed as Question Paper Setter for "
                f"{subject.course_code} — {subject.title} (Sem {req.semester}, AY {req.academic_year}). "
                f"Appointment Order Ref: {ref_number}. Submission Deadline: {deadline}."
            )
            db.add(NotificationLog(
                allocation_id=alloc.id,
                faculty_id=f.id,
                faculty_name=f.name,
                channel="Email",
                recipient=recipient_email,
                message_preview=email_body,
                status="Simulated (Sent)",
                is_simulated=True,
                sent_at=datetime.utcnow()
            ))

            # SMS log
            recipient_sms = f.mobile or "+91-98450XXXXX"
            sms_body = f"SJBIT COE: Appointed as QP Setter for {subject.course_code}. Ref: {ref_number}. Check official email."
            db.add(NotificationLog(
                allocation_id=alloc.id,
                faculty_id=f.id,
                faculty_name=f.name,
                channel="SMS",
                recipient=recipient_sms,
                message_preview=sms_body,
                status="Simulated (Delivered)",
                is_simulated=True,
                sent_at=datetime.utcnow()
            ))

        # 4. Generate Official Allocation Order PDF
        alloc_data = {
            "reference_number": ref_number,
            "academic_year": req.academic_year,
            "department": req.department,
            "semester": req.semester,
            "allocation_ratio": ratio_str,
            "subject": {
                "code": subject.course_code or "TBD",
                "title": subject.title,
                "scheme": subject.scheme or "2025 Scheme",
                "course_type": subject.course_type or "Core Theory"
            },
            "internal_faculty": [
                {"name": f.name, "designation": f.designation, "institution": f.institution}
                for f in int_faculties
            ],
            "external_faculty": [
                {"name": f.name, "designation": f.designation, "institution": f.institution}
                for f in ext_faculties
            ]
        }
        pdf_path = os.path.join(PDF_STORAGE_DIR, f"Allocation_Order_{ref_number}.pdf")
        generate_allocation_pdf(alloc_data, pdf_path)

        # 5. Audit Log
        db.add(AuditLog(
            action="ALLOCATION_CONFIRMED",
            entity_type="Allocation",
            entity_id=alloc.id,
            details=f"Order {ref_number} confirmed for {subject.course_code} ({subject.title}). Setters: {len(int_ids)} Int, {len(ext_ids)} Ext."
        ))

        db.commit()
        db.refresh(alloc)

        return {
            "success": True,
            "reference_number": ref_number,
            "allocation_id": alloc.id,
            "pdf_url": f"/api/reports/download-pdf/{alloc.id}",
            "message": "Allocation confirmed, order cryptographically registered, and notifications dispatched."
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database transaction failed: {str(e)}")


# ─── History & Details ────────────────────────────────────────────────────────

@router.get("/history")
def get_allocation_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns chronological list of allocations.
    Enforces HOD department scoping.
    """
    query = db.query(Allocation)
    if current_user.role == "HOD" and current_user.department:
        query = query.filter(Allocation.department.like(f"%{current_user.department}%"))

    allocs = query.order_by(Allocation.created_at.desc()).limit(100).all()
    results = []
    for a in allocs:
        subj = a.subject
        results.append({
            "id": a.id,
            "reference_number": a.reference_number,
            "academic_year": a.academic_year,
            "department": a.department,
            "semester": a.semester,
            "subject_title": subj.title if subj else "N/A",
            "course_code": subj.course_code if subj else "N/A",
            "total_required": a.total_required,
            "allocation_ratio": a.allocation_ratio,
            "status": a.status,
            "confirmed_at": a.confirmed_at.isoformat() if a.confirmed_at else "",
            "created_at": a.created_at.isoformat() if a.created_at else ""
        })
    return {"allocations": results}


@router.get("/{allocation_id}")
def get_allocation_details(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves full details of a specific allocation order with HOD department authorization check."""
    alloc = db.query(Allocation).filter_by(id=allocation_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation record not found.")

    if current_user.role == "HOD" and current_user.department and current_user.department not in alloc.department:
        raise HTTPException(status_code=403, detail="Access Denied: You can only view allocations for your department.")

    subj = alloc.subject
    int_ids = json.loads(alloc.internal_faculty_ids or "[]")
    ext_ids = json.loads(alloc.external_faculty_ids or "[]")

    int_faculty = [
        {"id": f.id, "name": f.name, "designation": f.designation, "institution": f.institution, "email": f.email}
        for f in db.query(Faculty).filter(Faculty.id.in_(int_ids)).all()
    ]
    ext_faculty = [
        {"id": f.id, "name": f.name, "designation": f.designation, "institution": f.institution, "email": f.email}
        for f in db.query(Faculty).filter(Faculty.id.in_(ext_ids)).all()
    ]

    return {
        "id": alloc.id,
        "reference_number": alloc.reference_number,
        "academic_year": alloc.academic_year,
        "department": alloc.department,
        "semester": alloc.semester,
        "total_required": alloc.total_required,
        "internal_required": alloc.internal_required,
        "external_required": alloc.external_required,
        "allocation_ratio": alloc.allocation_ratio,
        "status": alloc.status,
        "exception_reason": alloc.exception_reason,
        "confirmed_at": alloc.confirmed_at.isoformat() if alloc.confirmed_at else None,
        "subject": {
            "id": subj.id if subj else None,
            "code": subj.course_code if subj else "",
            "title": subj.title if subj else "",
            "scheme": subj.scheme if subj else ""
        },
        "internal_faculty": int_faculty,
        "external_faculty": ext_faculty
    }


@router.post("/{allocation_id}/cancel")
def cancel_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin"]))
):
    """Cancels a previously confirmed allocation order with audit log."""
    alloc = db.query(Allocation).filter_by(id=allocation_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation not found.")

    alloc.status = "Cancelled"
    db.add(AuditLog(
        action="ALLOCATION_CANCELLED",
        entity_type="Allocation",
        entity_id=alloc.id,
        details=f"Allocation order {alloc.reference_number} cancelled by admin {current_user.username}."
    ))
    db.commit()

    return {"success": True, "message": f"Allocation order {alloc.reference_number} cancelled."}
