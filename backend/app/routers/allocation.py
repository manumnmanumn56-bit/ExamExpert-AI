"""
ExamExpert AI — Faculty Allocation & Workflow Management API Router
SJB Institute of Technology | Office of Controller of Examinations

Implements Modules 11 & 12 (Slices 3 & 4):
1. Admin Allocation Workflow:
   - Parameters: academic_year, department, scheme, semester, subject, exam_type, mode, total_required
   - Server-side validation including the MCA 4-semester rule
   - Balanced mode 50:50 parity with automated shortage reallocation from eligible candidates
2. Multi-Stage Lifecycle & Server-Enforced Statuses:
   - Draft -> Recommended -> Pending HOD Approval -> Approved | Rejected | Cancelled
   - Submit creates RESERVED workload_ledger entries in ONE atomic transaction
   - Capacity constraint: Two requests (or current load + new request) cannot exceed faculty capacity
   - Relational AllocationSetters (not plain JSON ID strings)
3. HOD Approval Workflow:
   - Scoped strictly to HOD's own department (cross-department attempts return HTTP 403)
   - Decisions: Approve commits workload (COMMITTED), Reject (reason required) releases reservation (RELEASED)
   - Double-decision prevention (only Pending HOD Approval can be decided, exactly once)
   - Full audit trail logging with old and new values
"""
import json, random, string, os
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..database import get_db
from ..models import (
    Faculty, Subject, Allocation, AllocationConflict,
    EligibilityRules, NotificationLog, AuditLog, User,
    AllocationSetter, WorkloadLedger, ExternalInstitution
)
from ..services.matcher import rank_candidates, match_and_rank_faculty
from ..services.migration import resolve_department_names
from ..services.eligibility import get_faculty_workload, get_confirmed_policy
from ..services.pdf_generator import generate_allocation_pdf
from ..services.notification_service import (
    notify_request_submitted,
    notify_request_approved,
    notify_request_rejected,
    create_in_app_notification
)
from .auth import require_roles, get_current_user

router = APIRouter(prefix="/api/allocation", tags=["Allocation Workflow"])

PDF_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "generated_reports"
)
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)


# ─── Helper Functions & Validation ───────────────────────────────────────────

def _get_rules(db: Session) -> EligibilityRules:
    policy = get_confirmed_policy(db)
    if policy:
        return policy
    r = db.query(EligibilityRules).first()
    return r or EligibilityRules(
        min_experience=10.0,
        min_experience_phd=5.0,
        internal_capacity=2,
        external_capacity=2,
        status="CONFIRMED",
        min_experience_years=10.0,
        phd_fasttrack_min_exp=5.0,
        max_papers_per_faculty=2,
        require_parity=True,
        active_academic_year="2025-26",
        upcoming_academic_year="2026-27"
    )


def _generate_ref_number() -> str:
    date_str = datetime.now().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.digits, k=5))
    return f"SJBIT-COE-{date_str}-{suffix}"


def validate_mca_semester(department: str, semester: str):
    """
    Validates MCA 4-Semester Rule:
    The MCA degree curriculum spans strictly 4 semesters (Semesters I to IV).
    Semesters V, VI, VII, VIII are strictly invalid and rejected with HTTP 422.
    """
    dept_clean = (department or "").strip().upper()
    if dept_clean in ("MCA", "MASTER OF COMPUTER APPLICATIONS"):
        sem_clean = str(semester).strip().upper().replace("SEM", "").replace("SEMESTER", "").strip()
        if sem_clean not in ("I", "II", "III", "IV", "1", "2", "3", "4"):
            raise HTTPException(
                status_code=422,
                detail=f"MCA degree curriculum spans strictly 4 semesters (Semesters I to IV). Semester '{semester}' is invalid for MCA."
            )


# ─── Pydantic Schemas ────────────────────────────────────────────────────────

class AutoSelectRequest(BaseModel):
    subject_id: int
    min_handled: int = Field(default=1, ge=1, le=7)
    total_required: int = Field(default=2, ge=1, le=10)
    mode: str = Field(default="Balanced")  # "Balanced" | "Internal Only" | "External Only"
    academic_year: Optional[str] = None


class ConflictCheckRequest(BaseModel):
    subject_id: int
    internal_faculty_ids: list[int]
    external_faculty_ids: list[int]
    total_required: int = 2


class CreateAllocationRequest(BaseModel):
    subject_id: int
    academic_year: str
    department: str
    scheme: str = "2025"
    semester: str
    exam_type: str = "Autonomous End-Semester Examination"
    mode: str = "Balanced"  # "Balanced" | "Internal Only" | "External Only"
    total_required: int = 2
    internal_faculty_ids: list[int] = []
    external_faculty_ids: list[int] = []
    manual_exceptions: Optional[list[dict]] = []
    submission_deadline: Optional[str] = None
    exception_reason: Optional[str] = None
    min_handled: int = 1
    status: str = "Draft"  # 'Draft' | 'Recommended'


class ConfirmAllocationRequest(BaseModel):
    subject_id: int
    academic_year: str
    department: str
    semester: str
    scheme: Optional[str] = "2025"
    min_handled: int = 1
    total_required: int = 2
    internal_faculty_ids: list[int]
    external_faculty_ids: list[int]
    manual_exceptions: Optional[list[dict]] = []
    exception_reason: Optional[str] = None
    exception_approved_by: Optional[str] = "Controller of Examinations"
    submission_deadline: Optional[str] = None
    mode: Optional[str] = "Balanced"


class SendFacultyOTPRequest(BaseModel):
    subject_id: int
    faculty_ids: list[int]
    channel: str = "all"


class DecisionRequest(BaseModel):
    reason: Optional[str] = None


# ─── Auto-Select & Shortage Reallocation ─────────────────────────────────────

@router.post("/auto-select")
def auto_select(
    req: AutoSelectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin", "HOD"]))
):
    """
    Deterministically ranks eligible faculty using Module 10 matching engine.
    Balanced mode splits 50:50, detects shortages, and fills from the other eligible pool
    without lowering eligibility, logging deviations transparently.
    """
    subject = db.query(Subject).filter_by(id=req.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found in syllabus database.")

    # Explicit server-side role check
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

    # Run deterministic Module 10 matching engine
    int_match = match_and_rank_faculty(db, subject, "internal", ay, rules)
    ext_match = match_and_rank_faculty(db, subject, "external", ay, rules)

    int_recommended = int_match["recommended"]
    ext_recommended = ext_match["recommended"]

    warnings = []
    requires_exception = False

    # Mode Quota Calculation & Shortage Filling
    if mode == "Internal Only":
        internal_quota = total_req
        external_quota = 0
        sel_int = int_recommended[:internal_quota]
        sel_ext = []
        if len(sel_int) < internal_quota:
            warnings.append(
                f"Internal Faculty Shortage: Only {len(sel_int)} of {internal_quota} required internal positions could be filled."
            )
    elif mode == "External Only":
        internal_quota = 0
        external_quota = total_req
        sel_int = []
        sel_ext = ext_recommended[:external_quota]
        if len(sel_ext) < external_quota:
            warnings.append(
                f"External Faculty Shortage: Only {len(sel_ext)} of {external_quota} required external positions could be filled."
            )
    else:  # Balanced 50:50 mode
        internal_quota = (total_req + 1) // 2
        external_quota = total_req - internal_quota

        sel_int = int_recommended[:internal_quota]
        sel_ext = ext_recommended[:external_quota]

        # Detect internal shortage and reallocate to available eligible external candidates
        if len(sel_int) < internal_quota:
            int_deficit = internal_quota - len(sel_int)
            available_ext = ext_recommended[len(sel_ext): len(sel_ext) + int_deficit]
            if available_ext:
                sel_ext.extend(available_ext)
                requires_exception = True
                warnings.append(
                    f"Internal Faculty Shortage: {len(available_ext)} position(s) reallocated to eligible External faculty."
                )

        # Detect external shortage and reallocate to available eligible internal candidates
        if len(sel_ext) < external_quota:
            ext_deficit = external_quota - len(sel_ext)
            available_int = int_recommended[len(sel_int): len(sel_int) + ext_deficit]
            if available_int:
                sel_int.extend(available_int)
                requires_exception = True
                warnings.append(
                    f"External Faculty Shortage: {len(available_int)} position(s) reallocated to eligible Internal faculty."
                )

    unfilled_internal = max(0, internal_quota - len(sel_int))
    unfilled_external = max(0, external_quota - len(sel_ext))

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
        "all_internal_candidates": int_recommended,
        "all_external_candidates": ext_recommended
    }


# ─── Module 11: Create Allocation Request & Save Draft ───────────────────────

@router.post("/create-request")
def create_allocation_request(
    req: CreateAllocationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Creates an allocation request in 'Draft' or 'Recommended' status.
    Enforces server-side validations:
    - MCA 4-Semester rule
    - Faculty workload capacity constraint (cannot allocate faculty who have reached capacity)
    - Relational AllocationSetters persistence
    """
    if current_user.role not in ["Admin"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Only Admin can create allocation requests. Current role is '{current_user.role}'."
        )

    subject = db.query(Subject).filter_by(id=req.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found.")

    # 1. MCA 4-Semester Rule Validation
    validate_mca_semester(req.department, req.semester)

    # 2. Duplicate active allocation check
    existing = db.query(Allocation).filter(
        Allocation.subject_id == req.subject_id,
        Allocation.status.in_(["Pending HOD Approval", "Approved", "Confirmed"])
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"An active allocation order already exists for this subject ({existing.reference_number})."
        )

    manual_map = {}
    if req.manual_exceptions:
        for m in req.manual_exceptions:
            if isinstance(m, dict):
                fid = m.get("faculty_id")
                if fid:
                    manual_map[fid] = m
    has_manual = len(manual_map) > 0

    all_ids = req.internal_faculty_ids + req.external_faculty_ids
    if not all_ids:
        raise HTTPException(status_code=400, detail="At least one faculty member must be nominated.")

    # 3. Workload Capacity Pre-Check & Manual Exception Validation
    rules = _get_rules(db)
    for fid in all_ids:
        fac = db.query(Faculty).filter_by(id=fid).first()
        if not fac:
            raise HTTPException(status_code=404, detail=f"Faculty record #{fid} not found.")

        # Check: Faculty not already assigned to the same subject in active allocation
        existing_assignment = db.query(AllocationSetter).join(Allocation).filter(
            Allocation.subject_id == req.subject_id,
            AllocationSetter.faculty_id == fid,
            Allocation.status.in_(["Pending HOD Approval", "Approved", "Confirmed"]),
            AllocationSetter.status.in_(["Nominated", "Approved"])
        ).first()
        if existing_assignment:
            raise HTTPException(
                status_code=400,
                detail=f"Faculty '{fac.name}' is already assigned to this subject in active allocation {existing_assignment.allocation.reference_number}."
            )

        # External institution whitelist check if manual exception
        if fid in manual_map and fac.faculty_type == "external":
            inst = db.query(ExternalInstitution).filter_by(name=fac.institution).first()
            if not inst or not inst.is_allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot select external faculty '{fac.name}': Institution '{fac.institution}' is not on the approved whitelist."
                )

        workload = get_faculty_workload(db, fid, req.academic_year)
        cap = int(rules.internal_capacity if fac.faculty_type == "internal" else rules.external_capacity)
        if workload["total_active"] + 1 > cap:
            man_item = manual_map.get(fid)
            if man_item and man_item.get("override_capacity"):
                db.add(AuditLog(
                    action="ALLOCATION_CAPACITY_OVERRIDE",
                    entity_type="Faculty",
                    entity_id=fid,
                    details=f"Admin '{current_user.username}' confirmed capacity override for '{fac.name}' ({workload['total_active'] + 1} > {cap}). Reason: {man_item.get('reason')}"
                ))
            else:
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot allocate {fac.name}: workload limit of {cap} papers would be exceeded (current active: {workload['total_active']})."
                )

        if fid in manual_map:
            m_reason = str(manual_map[fid].get("reason") or "").strip()
            if not m_reason:
                raise HTTPException(status_code=400, detail=f"A justification reason is mandatory for manual exception faculty '{fac.name}'.")
            db.add(AuditLog(
                action="ALLOCATION_MANUAL_OVERRIDE_ADDED",
                entity_type="Faculty",
                entity_id=fid,
                details=f"Admin '{current_user.username}' added manual exception for '{fac.name}' ({fac.faculty_type}). Reason: {m_reason}"
            ))

    ref_number = _generate_ref_number()
    total_actual = len(all_ids)
    int_pct = round(len(req.internal_faculty_ids) / total_actual * 100, 1) if total_actual else 0
    ext_pct = round(100.0 - int_pct, 1)
    ratio_str = f"{int_pct}% Internal / {ext_pct}% External"
    deadline = req.submission_deadline or datetime.now().strftime("%d %B %Y")

    status = "Recommended" if req.status == "Recommended" else "Draft"

    combined_reason = req.exception_reason
    if has_manual:
        manual_reasons_str = "; ".join([f"{manual_map[fid].get('reason')}" for fid in manual_map if manual_map[fid].get("reason")])
        combined_reason = f"Manual exception: {manual_reasons_str}" if not combined_reason else f"{combined_reason} | Manual exception: {manual_reasons_str}"

    alloc = Allocation(
        reference_number=ref_number,
        academic_year=req.academic_year,
        department=req.department,
        semester=req.semester,
        subject_id=req.subject_id,
        exam_type=req.exam_type,
        total_required=req.total_required,
        internal_required=len(req.internal_faculty_ids),
        external_required=len(req.external_faculty_ids),
        allocation_mode=req.mode,
        internal_faculty_ids=json.dumps(req.internal_faculty_ids),
        external_faculty_ids=json.dumps(req.external_faculty_ids),
        min_handled=req.min_handled,
        allocation_ratio=ratio_str,
        status=status,
        has_manual_override=has_manual,
        submission_deadline=deadline,
        submitted_by=current_user.username,
        exception_reason=combined_reason,
        created_at=datetime.utcnow()
    )
    db.add(alloc)
    db.flush()

    # Create Relational AllocationSetters
    order = 1
    for fid in req.internal_faculty_ids:
        m_item = manual_map.get(fid)
        db.add(AllocationSetter(
            allocation_id=alloc.id,
            faculty_id=fid,
            faculty_type="internal",
            status="Nominated",
            assigned_order=order,
            is_manual_override=(fid in manual_map),
            manual_reason=m_item.get("reason") if m_item else None
        ))
        order += 1

    for fid in req.external_faculty_ids:
        m_item = manual_map.get(fid)
        db.add(AllocationSetter(
            allocation_id=alloc.id,
            faculty_id=fid,
            faculty_type="external",
            status="Nominated",
            assigned_order=order,
            is_manual_override=(fid in manual_map),
            manual_reason=m_item.get("reason") if m_item else None
        ))
        order += 1

    # Record Audit Log
    db.add(AuditLog(
        action="ALLOCATION_REQUEST_CREATED",
        entity_type="Allocation",
        entity_id=alloc.id,
        details=json.dumps({
            "reference_number": alloc.reference_number,
            "status": alloc.status,
            "created_by": current_user.username,
            "nominated_faculty_count": len(all_ids),
            "has_manual_override": has_manual
        })
    ))
    db.commit()
    db.refresh(alloc)

    return {
        "success": True,
        "message": f"Allocation request {alloc.reference_number} created in '{alloc.status}' status.",
        "allocation_id": alloc.id,
        "reference_number": alloc.reference_number,
        "status": alloc.status
    }


# ─── Module 11: Submit Allocation Request to HOD ─────────────────────────────

@router.post("/{allocation_id}/submit")
def submit_allocation_to_hod(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Submits an allocation request to HOD for formal approval.
    Transitions status to 'Pending HOD Approval'.
    Creates RESERVED workload_ledger entries in ONE atomic transaction.
    Enforces that two requests (or existing workload + this request) never exceed faculty capacity.
    """
    if current_user.role not in ["Admin"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Only Admin can submit allocation requests to HOD. Current role is '{current_user.role}'."
        )

    alloc = db.query(Allocation).filter_by(id=allocation_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation request not found.")

    if alloc.status not in ("Draft", "Recommended"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit allocation in '{alloc.status}' status. Only Draft or Recommended requests can be submitted to HOD."
        )

    rules = _get_rules(db)
    setters = db.query(AllocationSetter).filter_by(allocation_id=alloc.id).all()
    if not setters:
        raise HTTPException(status_code=400, detail="No nominated setters found for this allocation.")

    # 1. Capacity Limit Verification Across All Nominated Setters
    for s in setters:
        fac = db.query(Faculty).filter_by(id=s.faculty_id).first()
        if not fac:
            continue
        workload = get_faculty_workload(db, s.faculty_id, alloc.academic_year)
        cap = int(rules.internal_capacity if fac.faculty_type == "internal" else rules.external_capacity)
        if workload["total_active"] + 1 > cap:
            raise HTTPException(
                status_code=422,
                detail=f"Capacity Exceeded: Cannot submit allocation. Faculty member '{fac.name}' would exceed workload capacity ({workload['total_active'] + 1} > {cap})."
            )

    # 2. Atomic Transition & Ledger Reservation in One Transaction
    old_status = alloc.status
    alloc.status = "Pending HOD Approval"
    alloc.submitted_by = current_user.username

    for s in setters:
        db.add(WorkloadLedger(
            faculty_id=s.faculty_id,
            academic_year=alloc.academic_year or "2025-26",
            semester=alloc.semester,
            allocation_id=alloc.id,
            entry_type="RESERVED",
            delta=1,
            remarks=f"Workload reserved for HOD approval: {alloc.reference_number}"
        ))

    # Record Audit Log
    db.add(AuditLog(
        action="ALLOCATION_SUBMITTED_TO_HOD",
        entity_type="Allocation",
        entity_id=alloc.id,
        details=json.dumps({
            "reference_number": alloc.reference_number,
            "old_status": old_status,
            "new_status": "Pending HOD Approval",
            "submitted_by": current_user.username,
            "reserved_setters_count": len(setters)
        })
    ))

    # Module 13: Dispatch In-App / Email Notification to Department HOD
    notify_request_submitted(db, alloc, alloc.subject, current_user.username)

    db.commit()
    db.refresh(alloc)

    return {
        "success": True,
        "message": f"Allocation {alloc.reference_number} successfully submitted to HOD. Workload reserved.",
        "allocation_id": alloc.id,
        "reference_number": alloc.reference_number,
        "status": alloc.status
    }


# ─── Module 12: HOD Approval, Rejection & Decision Endpoints ─────────────────

@router.get("/pending-approvals")
def get_pending_approvals(
    department: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin", "HOD"]))
):
    """
    Retrieves allocation requests awaiting HOD approval.
    HOD sees only their own department's requests.
    Admin sees all pending requests.
    """
    if current_user.role not in ["Admin", "HOD"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Action requires Admin or HOD role permissions. Current role is '{current_user.role}'."
        )

    if department is not None and not isinstance(department, str):
        department = None

    query = db.query(Allocation).filter(Allocation.status == "Pending HOD Approval")

    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        if dept_variants:
            query = query.filter(Allocation.department.in_(dept_variants))
    elif department:
        dept_variants = resolve_department_names(db, department)
        if dept_variants:
            query = query.filter(Allocation.department.in_(dept_variants))

    allocs = query.order_by(Allocation.created_at.desc()).all()
    results = []

    for a in allocs:
        setters = db.query(AllocationSetter).filter_by(allocation_id=a.id).order_by(AllocationSetter.assigned_order).all()
        setter_details = []
        for s in setters:
            fac = s.faculty
            workload = get_faculty_workload(db, s.faculty_id, a.academic_year)
            setter_details.append({
                "setter_id": s.id,
                "faculty_id": s.faculty_id,
                "name": fac.name if fac else f"ID #{s.faculty_id}",
                "faculty_type": s.faculty_type,
                "designation": fac.designation if fac else None,
                "department": fac.department if fac else None,
                "institution": fac.institution if fac else None,
                "qualification": fac.qualification if fac else None,
                "experience_years": fac.experience_years if fac else None,
                "status": s.status,
                "is_manual_override": getattr(s, "is_manual_override", False),
                "manual_reason": getattr(s, "manual_reason", None),
                "workload": workload
            })

        subj = a.subject
        results.append({
            "id": a.id,
            "reference_number": a.reference_number,
            "academic_year": a.academic_year,
            "department": a.department,
            "semester": a.semester,
            "exam_type": a.exam_type,
            "allocation_mode": a.allocation_mode,
            "status": a.status,
            "has_manual_override": getattr(a, "has_manual_override", False),
            "exception_reason": a.exception_reason,
            "submitted_by": a.submitted_by,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "subject": {
                "id": subj.id if subj else None,
                "course_code": subj.course_code if subj else "",
                "title": subj.title if subj else "",
                "department": subj.department if subj else ""
            },
            "setters": setter_details
        })

    return results


@router.post("/{allocation_id}/approve")
def approve_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["HOD"]))
):
    """
    HOD approves the allocation request.
    - Department-scoped: HOD can only approve requests for their own department.
    - Only 'Pending HOD Approval' can be decided, exactly once (double decision blocked).
    - Commits workload (COMMITTED +1) and releases reservation (RELEASED -1) in one atomic transaction.
    """
    if current_user.role not in ["HOD"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Only HOD can approve allocation requests. Current role is '{current_user.role}'."
        )

    alloc = db.query(Allocation).filter_by(id=allocation_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation request not found.")

    # 1. Department Scoping Check
    dept_variants = resolve_department_names(db, current_user.department or "")
    if not dept_variants or alloc.department not in dept_variants:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: HOD of '{current_user.department}' is not authorized to approve requests for '{alloc.department}' department."
        )

    # 2. State & Double Decision Check
    if alloc.status != "Pending HOD Approval":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve allocation: Request is in '{alloc.status}' status. Only requests in 'Pending HOD Approval' can be decided."
        )

    setters = db.query(AllocationSetter).filter_by(allocation_id=alloc.id).all()
    old_status = alloc.status

    # 3. Commit Workload & Update Setters in One Atomic Transaction
    alloc.status = "Approved"
    alloc.approved_by = current_user.username
    alloc.approved_at = datetime.utcnow()

    for s in setters:
        s.status = "Approved"
        # Commit workload
        db.add(WorkloadLedger(
            faculty_id=s.faculty_id,
            academic_year=alloc.academic_year or "2025-26",
            semester=alloc.semester,
            allocation_id=alloc.id,
            entry_type="COMMITTED",
            delta=1,
            remarks=f"Workload committed upon HOD approval: {alloc.reference_number}"
        ))
        # Release reservation
        db.add(WorkloadLedger(
            faculty_id=s.faculty_id,
            academic_year=alloc.academic_year or "2025-26",
            semester=alloc.semester,
            allocation_id=alloc.id,
            entry_type="RELEASED",
            delta=-1,
            remarks=f"Reservation released upon HOD approval: {alloc.reference_number}"
        ))

    # Record Audit Log
    db.add(AuditLog(
        action="ALLOCATION_APPROVED_BY_HOD",
        entity_type="Allocation",
        entity_id=alloc.id,
        details=json.dumps({
            "reference_number": alloc.reference_number,
            "old_status": old_status,
            "new_status": "Approved",
            "approved_by": current_user.username,
            "approved_at": alloc.approved_at.isoformat()
        })
    ))

    # Module 13: Dispatch In-App / Email Notification to Admin & Appointed Faculty
    notify_request_approved(db, alloc, alloc.subject, current_user.username)

    db.commit()
    db.refresh(alloc)

    return {
        "success": True,
        "message": f"Allocation {alloc.reference_number} successfully approved by HOD. Workload committed.",
        "allocation_id": alloc.id,
        "reference_number": alloc.reference_number,
        "status": alloc.status
    }


@router.post("/{allocation_id}/reject")
def reject_allocation(
    allocation_id: int,
    req: DecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["HOD"]))
):
    """
    HOD rejects the allocation request.
    - Department-scoped: HOD can only reject requests for their own department.
    - Mandatory rejection reason.
    - Only 'Pending HOD Approval' can be decided, exactly once.
    - Releases reservation (RELEASED -1) in one atomic transaction.
    """
    if current_user.role not in ["HOD"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Only HOD can reject allocation requests. Current role is '{current_user.role}'."
        )

    if not req.reason or len(req.reason.strip()) < 3:
        raise HTTPException(status_code=422, detail="A valid rejection reason (minimum 3 characters) is required.")

    alloc = db.query(Allocation).filter_by(id=allocation_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation request not found.")

    # 1. Department Scoping Check
    dept_variants = resolve_department_names(db, current_user.department or "")
    if not dept_variants or alloc.department not in dept_variants:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: HOD of '{current_user.department}' is not authorized to reject requests for '{alloc.department}' department."
        )

    # 2. State & Double Decision Check
    if alloc.status != "Pending HOD Approval":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject allocation: Request is in '{alloc.status}' status. Only requests in 'Pending HOD Approval' can be decided."
        )

    setters = db.query(AllocationSetter).filter_by(allocation_id=alloc.id).all()
    old_status = alloc.status

    # 3. Release Reservations & Update Setters in One Atomic Transaction
    alloc.status = "Rejected"
    alloc.rejection_reason = req.reason.strip()

    for s in setters:
        s.status = "Rejected"
        db.add(WorkloadLedger(
            faculty_id=s.faculty_id,
            academic_year=alloc.academic_year or "2025-26",
            semester=alloc.semester,
            allocation_id=alloc.id,
            entry_type="RELEASED",
            delta=-1,
            remarks=f"Reservation released upon rejection: {alloc.reference_number}"
        ))

    # Record Audit Log
    db.add(AuditLog(
        action="ALLOCATION_REJECTED_BY_HOD",
        entity_type="Allocation",
        entity_id=alloc.id,
        details=json.dumps({
            "reference_number": alloc.reference_number,
            "old_status": old_status,
            "new_status": "Rejected",
            "reason": alloc.rejection_reason,
            "rejected_by": current_user.username
        })
    ))

    # Module 13: Dispatch In-App / Email Notification to Admin on Rejection
    notify_request_rejected(db, alloc, alloc.subject, current_user.username, alloc.rejection_reason)

    db.commit()
    db.refresh(alloc)

    return {
        "success": True,
        "message": f"Allocation {alloc.reference_number} rejected by HOD. Workload reservation released.",
        "allocation_id": alloc.id,
        "reference_number": alloc.reference_number,
        "status": alloc.status,
        "reason": alloc.rejection_reason
    }


# ─── Cancel Allocation Endpoint ──────────────────────────────────────────────

@router.post("/{allocation_id}/cancel")
def cancel_allocation(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin", "HOD"]))
):
    """
    Cancels an allocation order and safely releases reserved or committed workload.
    """
    if current_user.role not in ["Admin", "HOD"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Only Admin or HOD can cancel allocations. Current role is '{current_user.role}'."
        )

    alloc = db.query(Allocation).filter_by(id=allocation_id).first()
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation order not found.")

    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        if not dept_variants or alloc.department not in dept_variants:
            raise HTTPException(status_code=403, detail="Access denied to cancel allocations outside your department.")

    if alloc.status in ("Cancelled", "Rejected"):
        raise HTTPException(status_code=400, detail=f"Allocation is already in '{alloc.status}' status.")

    old_status = alloc.status
    alloc.status = "Cancelled"
    setters = db.query(AllocationSetter).filter_by(allocation_id=alloc.id).all()

    # Release Workload Ledger Rows
    for s in setters:
        if old_status == "Pending HOD Approval":
            db.add(WorkloadLedger(
                faculty_id=s.faculty_id,
                academic_year=alloc.academic_year or "2025-26",
                semester=alloc.semester,
                allocation_id=alloc.id,
                entry_type="RELEASED",
                delta=-1,
                remarks=f"Reservation released upon cancellation: {alloc.reference_number}"
            ))
        elif old_status in ("Approved", "Confirmed"):
            db.add(WorkloadLedger(
                faculty_id=s.faculty_id,
                academic_year=alloc.academic_year or "2025-26",
                semester=alloc.semester,
                allocation_id=alloc.id,
                entry_type="RELEASED",
                delta=-1,
                remarks=f"Committed workload released upon allocation cancellation: {alloc.reference_number}"
            ))

    db.add(AuditLog(
        action="ALLOCATION_CANCELLED",
        entity_type="Allocation",
        entity_id=alloc.id,
        details=json.dumps({
            "reference_number": alloc.reference_number,
            "old_status": old_status,
            "new_status": "Cancelled",
            "cancelled_by": current_user.username
        })
    ))
    db.commit()

    return {
        "success": True,
        "message": f"Allocation {alloc.reference_number} cancelled. Workload obligations released.",
        "status": "Cancelled"
    }


@router.get("/available-roster")
def get_available_roster(
    subject_id: int,
    faculty_type: str = "internal",  # 'internal' | 'external'
    academic_year: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Returns available faculty from the roster for manual addition during shortages.
    For external faculty, strictly filters to allowed institutions.
    Flags candidates already assigned to the subject in an active order.
    """
    subject = db.query(Subject).filter_by(id=subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found.")

    rules = _get_rules(db)
    ay = academic_year or (rules.active_academic_year if rules else "2025-26")

    assigned_subquery = db.query(AllocationSetter.faculty_id).join(Allocation).filter(
        Allocation.subject_id == subject_id,
        Allocation.status.in_(["Pending HOD Approval", "Approved", "Confirmed"]),
        AllocationSetter.status.in_(["Nominated", "Approved"])
    ).subquery()

    query = db.query(Faculty).filter(Faculty.faculty_type == faculty_type)

    if faculty_type == "external":
        allowed_insts = [inst.name for inst in db.query(ExternalInstitution).filter(ExternalInstitution.is_allowed == True).all()]
        if allowed_insts:
            query = query.filter(Faculty.institution.in_(allowed_insts))

    faculty_list = query.order_by(Faculty.name).all()
    assigned_ids = {row[0] for row in db.query(assigned_subquery).all()}

    cap = int(rules.internal_capacity if faculty_type == "internal" else rules.external_capacity)
    results = []
    for f in faculty_list:
        wl = get_faculty_workload(db, f.id, ay)
        results.append({
            "id": f.id,
            "name": f.name,
            "designation": f.designation or "Not provided",
            "department": f.department or "Not provided",
            "institution": f.institution or ("SJBIT" if faculty_type == "internal" else "Not provided"),
            "experience_years": f.experience_years if f.experience_years is not None else "Not provided",
            "qualification": f.qualification or "Not provided",
            "workload_committed": wl["committed"],
            "workload_reserved": wl["reserved"],
            "workload_active": wl["total_active"],
            "capacity": cap,
            "is_capacity_exceeded": wl["total_active"] >= cap,
            "is_already_assigned": f.id in assigned_ids
        })

    return {
        "success": True,
        "subject_id": subject_id,
        "faculty_type": faculty_type,
        "total": len(results),
        "roster": results
    }


# ─── Legacy / Confirm Backward Compatibility Endpoint ────────────────────────

@router.post("/confirm")
def confirm_allocation(
    req: ConfirmAllocationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Submits an allocation order into the formal approval cycle (Pending HOD Approval).
    Enforces MCA 4-Semester validation, capacity checks, and relational AllocationSetters.
    Direct bypass of HOD approval is strictly removed.
    """
    if current_user.role not in ["Admin"]:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Only Admin can initiate allocation requests. Current role is '{current_user.role}'."
        )

    subject = db.query(Subject).filter_by(id=req.subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found.")

    # MCA 4-Semester Validation
    validate_mca_semester(req.department, req.semester)

    # Convert into standard creation request and submit to HOD
    create_req = CreateAllocationRequest(
        subject_id=req.subject_id,
        academic_year=req.academic_year,
        department=req.department,
        scheme=req.scheme or "2025",
        semester=req.semester,
        exam_type="Autonomous End-Semester Examination",
        mode=req.mode or "Balanced",
        total_required=req.total_required,
        internal_faculty_ids=req.internal_faculty_ids,
        external_faculty_ids=req.external_faculty_ids,
        manual_exceptions=req.manual_exceptions,
        submission_deadline=req.submission_deadline,
        exception_reason=req.exception_reason,
        min_handled=req.min_handled,
        status="Draft"
    )
    res_create = create_allocation_request(create_req, db, current_user)
    alloc_id = res_create["allocation_id"]

    # Immediately submit to HOD approval with ledger reservation
    res_submit = submit_allocation_to_hod(alloc_id, db, current_user)

    return {
        "success": True,
        "message": f"Allocation {res_submit['reference_number']} created and submitted to HOD for approval.",
        "allocation_id": alloc_id,
        "reference_number": res_submit["reference_number"],
        "status": res_submit["status"]
    }


# ─── History & Detail Endpoints ──────────────────────────────────────────────

@router.get("/history")
def get_allocation_history(
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves full allocation archive across all lifecycle statuses.
    Role-scoped: Admin sees all; HOD sees department; Faculty sees own assignments.
    """
    query = db.query(Allocation)

    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        if dept_variants:
            query = query.filter(Allocation.department.in_(dept_variants))
    elif current_user.role == "Faculty":
        # Faculty sees only allocations where they are nominated or approved
        fac_id = current_user.faculty_id
        if fac_id:
            query = query.join(AllocationSetter).filter(AllocationSetter.faculty_id == fac_id)
        else:
            return []
    elif department:
        dept_variants = resolve_department_names(db, department)
        if dept_variants:
            query = query.filter(Allocation.department.in_(dept_variants))

    if status:
        query = query.filter(Allocation.status == status)

    allocs = query.order_by(Allocation.created_at.desc()).all()
    results = []

    for a in allocs:
        subj = a.subject
        setters = db.query(AllocationSetter).filter_by(allocation_id=a.id).order_by(AllocationSetter.assigned_order).all()
        results.append({
            "id": a.id,
            "reference_number": a.reference_number,
            "academic_year": a.academic_year,
            "department": a.department,
            "semester": a.semester,
            "exam_type": a.exam_type,
            "allocation_mode": a.allocation_mode,
            "status": a.status,
            "has_manual_override": getattr(a, "has_manual_override", False),
            "exception_reason": a.exception_reason,
            "allocation_ratio": a.allocation_ratio,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "confirmed_at": a.confirmed_at.isoformat() if a.confirmed_at else None,
            "approved_at": a.approved_at.isoformat() if a.approved_at else None,
            "approved_by": a.approved_by,
            "rejection_reason": a.rejection_reason,
            "subject": {
                "id": subj.id if subj else None,
                "code": subj.course_code if subj else "N/A",
                "title": subj.title if subj else "N/A",
                "department": subj.department if subj else ""
            },
            "setters": [
                {
                    "setter_id": s.id,
                    "faculty_id": s.faculty_id,
                    "name": s.faculty.name if s.faculty else f"ID #{s.faculty_id}",
                    "faculty_type": s.faculty_type,
                    "designation": s.faculty.designation if s.faculty else None,
                    "status": s.status,
                    "is_manual_override": getattr(s, "is_manual_override", False),
                    "manual_reason": getattr(s, "manual_reason", None)
                }
                for s in setters
            ]
        })

    return results


@router.get("/{allocation_id}")
def get_allocation_detail(
    allocation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves single allocation order with complete setter details."""
    a = db.query(Allocation).filter_by(id=allocation_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Allocation order not found.")

    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        if dept_variants and a.department not in dept_variants:
            raise HTTPException(status_code=403, detail="Access denied to allocation orders outside your department.")

    subj = a.subject
    setters = db.query(AllocationSetter).filter_by(allocation_id=a.id).order_by(AllocationSetter.assigned_order).all()

    return {
        "id": a.id,
        "reference_number": a.reference_number,
        "academic_year": a.academic_year,
        "department": a.department,
        "semester": a.semester,
        "exam_type": a.exam_type,
        "allocation_mode": a.allocation_mode,
        "status": a.status,
        "has_manual_override": getattr(a, "has_manual_override", False),
        "exception_reason": a.exception_reason,
        "total_required": a.total_required,
        "allocation_ratio": a.allocation_ratio,
        "submission_deadline": a.submission_deadline,
        "submitted_by": a.submitted_by,
        "approved_by": a.approved_by,
        "approved_at": a.approved_at.isoformat() if a.approved_at else None,
        "rejection_reason": a.rejection_reason,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "subject": {
            "id": subj.id if subj else None,
            "code": subj.course_code if subj else "N/A",
            "title": subj.title if subj else "N/A",
            "department": subj.department if subj else "",
            "semester": subj.semester if subj else ""
        },
        "setters": [
            {
                "setter_id": s.id,
                "faculty_id": s.faculty_id,
                "name": s.faculty.name if s.faculty else f"ID #{s.faculty_id}",
                "faculty_type": s.faculty_type,
                "designation": s.faculty.designation if s.faculty else None,
                "department": s.faculty.department if s.faculty else None,
                "institution": s.faculty.institution if s.faculty else None,
                "status": s.status,
                "is_manual_override": getattr(s, "is_manual_override", False),
                "manual_reason": getattr(s, "manual_reason", None),
                "assigned_order": s.assigned_order
            }
            for s in setters
        ]
    }


# ─── Conflict Checking Endpoint ───────────────────────────────────────────────

@router.post("/check-conflicts")
def check_conflicts(
    req: ConflictCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin", "HOD"]))
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
        Allocation.status.in_(["Pending HOD Approval", "Approved", "Confirmed"])
    ).first()
    if existing:
        conflicts.append({
            "type": "SUBJECT_ALREADY_ALLOCATED",
            "severity": "Critical",
            "description": f"This subject already has an active allocation (Ref: {existing.reference_number}, Status: {existing.status})."
        })

    # 3. Workload limits check (capacity per internal/external from policy)
    rules = _get_rules(db)
    for fid in all_ids:
        f = db.query(Faculty).filter_by(id=fid).first()
        fname = f.name if f else f"Faculty #{fid}"
        ftype = f.faculty_type if f else "internal"
        cap = int(rules.internal_capacity if ftype == "internal" else rules.external_capacity)
        workload = get_faculty_workload(db, fid, rules.active_academic_year or "2025-26")
        if workload["total_active"] >= cap:
            conflicts.append({
                "type": "MAX_PAPERS_EXCEEDED",
                "severity": "Critical",
                "description": f"{fname} already has {workload['total_active']} active question paper allocations (maximum limit: {cap})."
            })

    # 4. Total count match
    if len(all_ids) != req.total_required:
        conflicts.append({
            "type": "COUNT_MISMATCH",
            "severity": "Warning",
            "description": f"Selected {len(all_ids)} faculty, but required quota is {req.total_required}."
        })

    return {
        "has_conflicts": any(c["severity"] == "Critical" for c in conflicts),
        "conflict_count": len(conflicts),
        "conflicts": conflicts
    }


# ─── Dispatch Faculty Notification ───────────────────────────────────────────

@router.post("/send-faculty-otp")
def send_faculty_otp(
    req: SendFacultyOTPRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """Dispatches official appointment notifications to nominated faculty."""
    subject = db.query(Subject).filter_by(id=req.subject_id).first()
    subj_name = f"{subject.course_code} - {subject.title}" if subject else "Course"

    faculties = db.query(Faculty).filter(Faculty.id.in_(req.faculty_ids)).all()
    dispatches = []

    for f in faculties:
        # Find linked user account if exists
        fac_user = db.query(User).filter(
            or_(User.faculty_id == f.id, User.email == f.email)
        ).first()

        title = f"Nomination: Question Paper Setter for {subj_name}"
        message = f"You have been nominated as Question Paper Setter for course '{subj_name}'. Official appointment details are recorded in your faculty portal."

        if fac_user:
            create_in_app_notification(
                db=db,
                user_id=fac_user.id,
                title=title,
                message=message,
                event_type="FACULTY_ASSIGNED",
                entity_type="Subject",
                entity_id=req.subject_id,
                recipient_email=f.email
            )

        db.add(NotificationLog(
            faculty_id=f.id,
            channel="Email",
            recipient=f.email or "internal@sjbit.edu.in",
            subject_line=title,
            message_preview=message,
            status="Delivered",
            is_simulated=False
        ))
        dispatches.append({"faculty_id": f.id, "name": f.name, "status": "Delivered"})

    db.commit()
    return {
        "success": True,
        "message": f"Notifications dispatched to {len(dispatches)} nominated faculty member(s).",
        "dispatches": dispatches
    }
