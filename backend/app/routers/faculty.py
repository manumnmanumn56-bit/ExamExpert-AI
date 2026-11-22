"""
ExamExpert AI — Faculty & Dataset Management API Router
SJB Institute of Technology | Office of Controller of Examinations

Handles eligible faculty retrieval, statutory verification checks,
Excel imports, profile management, availability toggles, and external
institution whitelist governance.
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import (
    Faculty, Subject, EligibilityRules, Allocation,
    ImportHistory, AuditLog, User, ExternalInstitution
)
from ..services.matcher import rank_candidates
from ..services.importer import (
    import_internal_faculty,
    import_external_faculty,
    import_syllabus,
    preview_dataset_import,
    confirm_dataset_import,
    generate_rejected_report_excel,
    recalculate_eligibility_status,
    get_pending_verification_reason,
    PREVIEW_CACHE
)
from ..services.migration import resolve_department_names
from .auth import require_roles, get_current_user

router = APIRouter(prefix="/api/faculty", tags=["Faculty"])


# ─── Pydantic Request Models ──────────────────────────────────────────────────
class FacultyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    designation: str | None = None
    department: str | None = None
    institution: str | None = None
    qualification: str | None = None
    experience_years: float | None = None
    expertise_text: str | None = None
    course_history_text: str | None = None
    email: str | None = None
    mobile: str | None = None
    is_available: bool | None = None


class ImportConfirmRequest(BaseModel):
    preview_id: str
    conflict_resolution: str = "preserve_existing"  # 'preserve_existing' | 'overwrite'


# ─── Helper Functions ─────────────────────────────────────────────────────────
def _get_rules(db: Session) -> EligibilityRules:
    rules = db.query(EligibilityRules).first()
    if not rules:
        rules = EligibilityRules(
            min_experience_years=10.0,
            phd_fasttrack_min_exp=5.0,
            max_papers_per_faculty=2,
            require_parity=True,
            active_academic_year="2025-26",
            upcoming_academic_year="2026-27"
        )
    return rules


def _get_allocation_counts(db: Session) -> dict[int, int]:
    """Returns number of currently confirmed question paper assignments for each faculty."""
    allocs = db.query(Allocation).filter_by(status="Confirmed").all()
    counts: dict[int, int] = {}
    for a in allocs:
        for fid in json.loads(a.internal_faculty_ids or "[]"):
            counts[fid] = counts.get(fid, 0) + 1
        for fid in json.loads(a.external_faculty_ids or "[]"):
            counts[fid] = counts.get(fid, 0) + 1
    return counts


def recalculate_eligibility_status(qualification: str | None, exp: float | None, faculty_type: str = "internal") -> str:
    """
    Deterministically computes faculty eligibility status:
    1. If experience is None -> 'Cannot Verify'
    2. If completed PhD and experience >= 5.0 -> 'Qualified (Ph.D + Exp >= 5 Yrs)' (or 'Qualified' for external)
    3. If experience >= 10.0 -> 'Qualified (Exp >= 10 Yrs)' (or 'Qualified' for external)
    4. Otherwise -> 'Not Qualified'
    Never assumes 'Ph.D (pursuing)' is completed.
    """
    if exp is None:
        return "Cannot Verify"

    q_low = (qualification or "").lower()
    is_phd = "ph.d" in q_low or "phd" in q_low
    is_pursuing = any(p in q_low for p in ["pursuing", "ongoing", "registered", "enrolled", "candidate"])
    has_completed_phd = is_phd and not is_pursuing

    if has_completed_phd and exp >= 5.0:
        return "Qualified (Ph.D + Exp >= 5 Yrs)" if faculty_type == "internal" else "Qualified"
    elif exp >= 10.0:
        return "Qualified (Exp >= 10 Yrs)" if faculty_type == "internal" else "Qualified"
    else:
        return "Not Qualified"


def get_pending_verification_reason(f: Faculty) -> str | None:
    """Returns detailed explanation of why an external faculty is pending or unverified."""
    if f.eligibility_status == "Cannot Verify" or f.experience_years is None:
        return "Teaching experience duration not specified in source workbook; statutory physical service verification required."
    elif f.eligibility_status == "Not Qualified":
        return "Teaching experience below institutional statutory threshold (minimum 10 years, or completed Ph.D with 5 years)."
    return None


# ─── External Institution Whitelist Endpoints ─────────────────────────────────
@router.get("/institutions/whitelist")
def get_institution_whitelist(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Lists external institutions with their whitelist authorization status
    and the count of associated faculty members.
    Admin only.
    """
    insts = db.query(ExternalInstitution).order_by(ExternalInstitution.name).all()
    results = []
    for inst in insts:
        fac_count = db.query(Faculty).filter(
            Faculty.faculty_type == "external",
            Faculty.institution == inst.name
        ).count()
        results.append({
            "id": inst.id,
            "name": inst.name,
            "is_allowed": inst.is_allowed,
            "faculty_count": fac_count,
            "created_at": inst.created_at.isoformat() if inst.created_at else None
        })

    return {
        "total": len(results),
        "institutions": results
    }


@router.post("/institutions/{institution_id}/toggle")
def toggle_institution_whitelist(
    institution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Toggles whitelist status for an external institution.
    Disabling an institution automatically excludes its faculty from paper-setter recommendation.
    Admin only.
    """
    inst = db.query(ExternalInstitution).filter_by(id=institution_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="External institution record not found.")

    inst.is_allowed = not inst.is_allowed
    status_str = "ENABLED" if inst.is_allowed else "DISABLED"

    db.add(AuditLog(
        action="INSTITUTION_WHITELIST_TOGGLED",
        entity_type="ExternalInstitution",
        entity_id=inst.id,
        details=f"Institution '{inst.name}' whitelist status set to {status_str} by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "institution_id": inst.id,
        "name": inst.name,
        "is_allowed": inst.is_allowed,
        "message": f"Institution '{inst.name}' is now {'whitelisted' if inst.is_allowed else 'disabled'}."
    }


# ─── Eligible Faculty Candidate Matcher ───────────────────────────────────────
@router.get("/eligible")
def get_eligible_faculty(
    subject_id: int,
    min_handled: int = Query(1, ge=1, le=7),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin", "HOD"]))
):
    """
    Retrieves and ranks Internal and External faculty for the selected subject
    and minimum course handling threshold (1–7).
    """
    subject = db.query(Subject).filter_by(id=subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found in syllabus database.")

    rules = _get_rules(db)
    alloc_counts = _get_allocation_counts(db)

    # Rank candidates deterministically
    internal = rank_candidates(db, subject.title, subject.course_code or "",
                               min_handled, "internal", rules, alloc_counts)
    external = rank_candidates(db, subject.title, subject.course_code or "",
                               min_handled, "external", rules, alloc_counts)

    return {
        "subject": {
            "id": subject.id,
            "code": subject.course_code or "TBD",
            "title": subject.title,
            "department": subject.department,
            "semester": subject.semester,
            "academic_year": subject.academic_year,
            "scheme": subject.scheme,
            "course_type": subject.course_type,
            "verification_status": subject.verification_status
        },
        "min_handled_requested": min_handled,
        "internal_faculty": internal,
        "external_faculty": external,
        "summary": {
            "internal_total": len(internal),
            "internal_eligible": sum(1 for f in internal if f["is_eligible"]),
            "internal_meets_handled": sum(1 for f in internal if f["is_eligible"] and f["meets_min_handled"]),
            "external_total": len(external),
            "external_qualified": sum(1 for f in external if f["eligibility_status"] == "Qualified"),
            "external_cannot_verify": sum(1 for f in external if f["eligibility_status"] == "Cannot Verify"),
            "external_not_qualified": sum(1 for f in external if f["eligibility_status"] == "Not Qualified")
        }
    }


@router.get("/stats")
def get_faculty_stats(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["Admin", "HOD"]))
):
    """Returns high-level summary metrics of faculty roster."""
    total = db.query(Faculty).count()
    internal = db.query(Faculty).filter_by(faculty_type="internal").count()
    external = db.query(Faculty).filter_by(faculty_type="external").count()
    qualified = db.query(Faculty).filter(Faculty.eligibility_status.like("%Qualified%")).count()
    cannot_verify = db.query(Faculty).filter(Faculty.eligibility_status.like("%Cannot Verify%")).count()
    not_qualified = db.query(Faculty).filter(Faculty.eligibility_status.like("%Not Qualified%")).count()

    return {
        "total": total,
        "internal": internal,
        "external": external,
        "qualified": qualified,
        "cannot_verify": cannot_verify,
        "not_qualified": not_qualified,
        "total_syllabus_subjects": db.query(Subject).count(),
        "total_allocations": db.query(Allocation).count()
    }


# ─── Complete Faculty Roster & Management Endpoints ───────────────────────────
@router.get("/all")
def get_all_faculty(
    faculty_type: str | None = None,
    department: str | None = None,
    institution: str | None = None,
    eligibility_status: str | None = None,
    is_available: bool | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Search and browse complete faculty database with multi-dimensional filtering.
    Enforces Role-Based Access Scoping:
    - Admin: Full system-wide access across internal and external faculty.
    - HOD: Scoped strictly to internal faculty within their own department.
           External faculty are visible to Admin only in roster queries.
    - Faculty: Scoped strictly to their own personal record.
    """
    query = db.query(Faculty)

    # 1. RBAC Department & Faculty Type Scoping
    if current_user.role == "HOD":
        dept_names = resolve_department_names(db, current_user.department)
        if department:
            req_depts = resolve_department_names(db, department)
            if not any(d in dept_names for d in req_depts):
                raise HTTPException(
                    status_code=403,
                    detail=f"Access Denied: As HOD for '{current_user.department}', you are not authorized to view faculty in '{department}'."
                )
        if faculty_type == "external":
            raise HTTPException(
                status_code=403,
                detail="Access Denied: External faculty roster is accessible to Administrators only. Nominated external candidates are presented during allocation review."
            )
        # HOD sees strictly internal faculty of their department
        query = query.filter(
            Faculty.faculty_type == "internal",
            Faculty.department.in_(dept_names)
        )
    elif current_user.role == "Faculty":
        # Faculty can only view their own personal profile
        query = query.filter(
            (Faculty.email == current_user.email) |
            (Faculty.name.ilike(f"%{current_user.full_name or current_user.username}%"))
        )
    else:
        # Admin: Apply optional faculty_type and department filters
        if faculty_type:
            query = query.filter(Faculty.faculty_type == faculty_type.strip())
        if department:
            dept_names = resolve_department_names(db, department)
            query = query.filter(Faculty.department.in_(dept_names))

    # 2. General Filters
    if institution:
        query = query.filter(Faculty.institution.ilike(f"%{institution.strip()}%"))
    if eligibility_status:
        query = query.filter(Faculty.eligibility_status.ilike(f"%{eligibility_status.strip()}%"))
    if is_available is not None:
        query = query.filter(Faculty.is_available == is_available)
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (Faculty.name.ilike(s)) |
            (Faculty.employee_id.ilike(s)) |
            (Faculty.institution.ilike(s)) |
            (Faculty.designation.ilike(s)) |
            (Faculty.expertise_text.ilike(s))
        )

    roster = query.order_by(Faculty.faculty_type, Faculty.name).all()

    return {
        "total": len(roster),
        "user_role": current_user.role,
        "faculty": [{
            "id": f.id,
            "db_serial_no": f.db_serial_no,
            "employee_id": f.employee_id,
            "name": f.name,
            "designation": f.designation,
            "department": f.department,
            "institution": f.institution,
            "faculty_type": f.faculty_type,
            "qualification": f.qualification,
            "experience_years": f.experience_years,  # Stays None if not provided
            "eligibility_status": f.eligibility_status,
            "pending_reason": get_pending_verification_reason(f),
            "expertise_text": f.expertise_text,
            "course_history_text": f.course_history_text,
            "assumed_times_handled": f.assumed_times_handled,
            "email": f.email if (f.email and f.email.strip()) else None,  # Stays None if not provided
            "mobile": f.mobile if (f.mobile and f.mobile.strip()) else None,  # Stays None if not provided
            "is_available": f.is_available if f.is_available is not None else True
        } for f in roster]
    }


@router.get("/me")
def get_my_faculty_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves the authenticated faculty member's OWN profile, qualifications,
    eligibility status, and current QP setting workload.
    Strictly server-resolved from the current session (never from a browser-supplied ID).
    """
    # 1. Match Faculty record by email or full name / username
    f = None
    if current_user.email:
        f = db.query(Faculty).filter(Faculty.email.ilike(current_user.email.strip())).first()
    if not f and current_user.full_name:
        f = db.query(Faculty).filter(Faculty.name.ilike(f"%{current_user.full_name.strip()}%")).first()
    if not f and current_user.username:
        clean_user = current_user.username.replace("faculty_", "").replace("hod_", "").strip()
        f = db.query(Faculty).filter(Faculty.name.ilike(f"%{clean_user}%")).first()

    if not f:
        raise HTTPException(
            status_code=404,
            detail="No linked faculty profile found for current user session. Contact the Controller of Examinations."
        )

    # 2. Compute assigned workload in active academic cycle
    alloc_counts = _get_allocation_counts(db)
    assigned_count = alloc_counts.get(f.id, 0)

    # Query detailed allocations where faculty is assigned
    confirmed_allocs = db.query(Allocation).filter_by(status="Confirmed").all()
    assigned_allocations = []
    for a in confirmed_allocs:
        int_ids = json.loads(a.internal_faculty_ids or "[]")
        ext_ids = json.loads(a.external_faculty_ids or "[]")
        if f.id in int_ids or f.id in ext_ids:
            subj = a.subject
            assigned_allocations.append({
                "allocation_id": a.id,
                "reference_number": a.reference_number,
                "academic_year": a.academic_year,
                "department": a.department,
                "semester": a.semester,
                "course_code": subj.course_code if subj else "",
                "subject_title": subj.title if subj else "",
                "confirmed_at": a.confirmed_at.isoformat() if a.confirmed_at else None
            })

    rules = _get_rules(db)
    max_workload = rules.max_papers_per_faculty or 2

    return {
        "id": f.id,
        "employee_id": f.employee_id,
        "name": f.name,
        "designation": f.designation,
        "department": f.department,
        "institution": f.institution,
        "faculty_type": f.faculty_type,
        "qualification": f.qualification,
        "experience_years": f.experience_years,
        "eligibility_status": f.eligibility_status,
        "pending_reason": get_pending_verification_reason(f),
        "expertise_text": f.expertise_text,
        "course_history_text": f.course_history_text,
        "email": f.email if (f.email and f.email.strip()) else None,
        "mobile": f.mobile if (f.mobile and f.mobile.strip()) else None,
        "is_available": f.is_available if f.is_available is not None else True,
        "workload": {
            "assigned_papers": assigned_count,
            "max_allowed_papers": max_workload,
            "remaining_quota": max(0, max_workload - assigned_count),
            "allocations": assigned_allocations
        }
    }


@router.get("/{faculty_id}")
def get_faculty_profile(
    faculty_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves complete profile details for a specific faculty member.
    Enforces server-side scoping:
    - Admin: Can view any faculty profile.
    - HOD: Can only view internal faculty belonging to their own department.
    - Faculty: Can only view their own profile.
    """
    f = db.query(Faculty).filter_by(id=faculty_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Faculty record not found.")

    if current_user.role == "HOD":
        dept_names = resolve_department_names(db, current_user.department)
        if f.faculty_type != "internal":
            raise HTTPException(
                status_code=403,
                detail="Access Denied: External faculty profiles are accessible to Administrators only."
            )
        if f.department not in dept_names:
            raise HTTPException(
                status_code=403,
                detail=f"Access Denied: Faculty '{f.name}' belongs to department '{f.department}', not '{current_user.department}'."
            )
    elif current_user.role == "Faculty":
        is_self = (f.email == current_user.email) or (current_user.full_name and current_user.full_name in f.name)
        if not is_self:
            raise HTTPException(
                status_code=403,
                detail="Access Denied: You are only authorized to view your own profile."
            )

    return {
        "id": f.id,
        "db_serial_no": f.db_serial_no,
        "employee_id": f.employee_id,
        "name": f.name,
        "designation": f.designation,
        "department": f.department,
        "institution": f.institution,
        "faculty_type": f.faculty_type,
        "qualification": f.qualification,
        "experience_years": f.experience_years,
        "eligibility_status": f.eligibility_status,
        "pending_reason": get_pending_verification_reason(f),
        "expertise_text": f.expertise_text,
        "course_history_text": f.course_history_text,
        "assumed_times_handled": f.assumed_times_handled,
        "email": f.email if (f.email and f.email.strip()) else None,
        "mobile": f.mobile if (f.mobile and f.mobile.strip()) else None,
        "is_available": f.is_available if f.is_available is not None else True,
        "scheme": f.scheme,
        "address": f.address,
        "provenance_file": f.provenance_file,
        "created_at": f.created_at.isoformat() if f.created_at else None
    }


@router.put("/{faculty_id}")
def update_faculty_profile(
    faculty_id: int,
    req: FacultyUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Updates faculty profile details and recalculates eligibility status.
    Strict Server-Side Enforcement:
    - Admin only (HOD and Faculty receive 403 Forbidden).
    - Preserves NULLs for missing experience, email, and mobile (never invents values).
    - Never treats 'Ph.D pursuing' as completed Ph.D.
    - Records comprehensive audit trail.
    """
    f = db.query(Faculty).filter_by(id=faculty_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Faculty record not found.")

    if req.experience_years is not None and req.experience_years < 0:
        raise HTTPException(status_code=400, detail="Experience years cannot be negative.")

    changes = []

    if req.name is not None and req.name.strip() != f.name:
        changes.append(f"name: '{f.name}' → '{req.name.strip()}'")
        f.name = req.name.strip()

    if req.designation is not None and req.designation.strip() != f.designation:
        changes.append(f"designation: '{f.designation}' → '{req.designation.strip()}'")
        f.designation = req.designation.strip()

    if req.department is not None and req.department.strip() != f.department:
        changes.append(f"department: '{f.department}' → '{req.department.strip()}'")
        f.department = req.department.strip()

    if req.institution is not None and req.institution.strip() != f.institution:
        changes.append(f"institution: '{f.institution}' → '{req.institution.strip()}'")
        f.institution = req.institution.strip()

    qual_changed = False
    if req.qualification is not None and req.qualification.strip() != (f.qualification or ""):
        changes.append(f"qualification: '{f.qualification}' → '{req.qualification.strip()}'")
        f.qualification = req.qualification.strip()
        qual_changed = True

    exp_changed = False
    if req.experience_years is not None and req.experience_years != f.experience_years:
        changes.append(f"experience: {f.experience_years} → {req.experience_years}")
        f.experience_years = req.experience_years
        exp_changed = True

    if req.expertise_text is not None and req.expertise_text.strip() != (f.expertise_text or ""):
        old_val = (f.expertise_text or "")[:40]
        new_val = req.expertise_text.strip()[:40]
        changes.append(f"expertise_text: '{old_val}' → '{new_val}'")
        f.expertise_text = req.expertise_text.strip()

    if req.course_history_text is not None and req.course_history_text.strip() != (f.course_history_text or ""):
        old_val = (f.course_history_text or "")[:40]
        new_val = req.course_history_text.strip()[:40]
        changes.append(f"course_history_text: '{old_val}' → '{new_val}'")
        f.course_history_text = req.course_history_text.strip()

    if req.email is not None:
        clean_email = req.email.strip() if req.email.strip() else None
        if clean_email != f.email:
            changes.append(f"email: '{f.email}' → '{clean_email}'")
            f.email = clean_email

    if req.mobile is not None:
        clean_mobile = req.mobile.strip() if req.mobile.strip() else None
        if clean_mobile != f.mobile:
            changes.append(f"mobile: '{f.mobile}' → '{clean_mobile}'")
            f.mobile = clean_mobile

    if req.is_available is not None and req.is_available != f.is_available:
        changes.append(f"is_available: {f.is_available} → {req.is_available}")
        f.is_available = req.is_available

    # Recalculate eligibility status if qualification or experience updated
    if qual_changed or exp_changed:
        new_status = recalculate_eligibility_status(f.qualification, f.experience_years, f.faculty_type)
        if new_status != f.eligibility_status:
            changes.append(f"eligibility_status: '{f.eligibility_status}' → '{new_status}'")
            f.eligibility_status = new_status

    db.add(AuditLog(
        action="FACULTY_PROFILE_UPDATED",
        entity_type="Faculty",
        entity_id=f.id,
        details=f"Faculty '{f.name}' updated by admin '{current_user.username}'. Changes: {', '.join(changes) if changes else 'None'}."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"Faculty profile for '{f.name}' updated successfully.",
        "faculty_id": f.id,
        "eligibility_status": f.eligibility_status
    }


@router.post("/{faculty_id}/toggle-availability")
def toggle_faculty_availability(
    faculty_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Toggles availability flag for a faculty member.
    Admin only.
    """
    f = db.query(Faculty).filter_by(id=faculty_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Faculty record not found.")

    current_val = f.is_available if f.is_available is not None else True
    f.is_available = not current_val

    db.add(AuditLog(
        action="FACULTY_AVAILABILITY_TOGGLED",
        entity_type="Faculty",
        entity_id=f.id,
        details=f"Faculty '{f.name}' availability changed from {current_val} to {f.is_available} by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "faculty_id": f.id,
        "name": f.name,
        "is_available": f.is_available,
        "message": f"Faculty '{f.name}' is now {'marked Available' if f.is_available else 'marked Unavailable'}."
    }


# ─── Dataset Excel Import Endpoints (Module 7) ─────────────────────────────────

@router.post("/import-preview")
async def preview_excel_dataset(
    file: UploadFile = File(...),
    dataset_type: str = Form(...),  # 'internal' | 'external' | 'syllabus'
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Dry-run import preview before saving.
    Validates workbook format, column structure, identifies rows to add,
    duplicates, conflicts against existing DB records (e.g. manual Admin edits),
    and rejected rows with detailed reasons.
    Admin only.
    """
    content = await file.read()
    result = preview_dataset_import(db, content, file.filename, dataset_type)
    return result


@router.post("/import-confirm")
def confirm_excel_dataset(
    req: ImportConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Executes approved dataset import into the database.
    Applies conflict resolution ('preserve_existing' protects manual Admin edits;
    'overwrite' updates existing records).
    Preserves NULLs for missing experience, email, and mobile.
    Never treats 'Ph.D pursuing' as completed.
    Records ImportHistory with imported_by and comprehensive AuditLog entry.
    Admin only.
    """
    return confirm_dataset_import(db, req.preview_id, req.conflict_resolution, current_user.username)


@router.get("/import-rejected-report/{preview_id}")
def download_rejected_report(
    preview_id: str,
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Downloads an Excel (.xlsx) report containing all rejected and conflicting rows.
    Strictly escapes any values starting with '=', '+', '-', '@', '\\t', '\\r'
    to prevent CSV / Excel formula injection.
    Admin only.
    """
    if preview_id not in PREVIEW_CACHE:
        raise HTTPException(
            status_code=404,
            detail="Preview session expired or not found. Please upload the workbook again to generate a new report."
        )

    preview = PREVIEW_CACHE[preview_id]
    report_bytes = generate_rejected_report_excel(preview)

    clean_fn = f"rejected_report_{preview['dataset_type']}_{preview_id[:8]}.xlsx"
    return Response(
        content=report_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={clean_fn}"}
    )


@router.post("/import-excel")
async def upload_excel_dataset(
    file: UploadFile = File(...),
    dataset_type: str = Form(...),  # 'internal' | 'external' | 'syllabus'
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Direct import endpoint (backward compatibility).
    Executes preview and commits in one transaction.
    """
    content = await file.read()
    preview = preview_dataset_import(db, content, file.filename, dataset_type)
    result = confirm_dataset_import(db, preview["preview_id"], "preserve_existing", current_user.username)
    return {
        "success": True,
        "metrics": {
            "file_name": file.filename,
            "total_rows": result["total_rows"],
            "valid_rows": result["added_count"],
            "duplicate_rows": result["duplicate_count"],
            "conflict_rows": result["conflict_count"],
            "invalid_rows": result["rejected_count"]
        }
    }


@router.get("/import-history")
def get_import_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Returns audit log of all imported workbooks, including who imported,
    file name, date, rows read, added, duplicates, conflicts, and rejected.
    Admin only.
    """
    history = db.query(ImportHistory).order_by(ImportHistory.imported_at.desc()).all()
    return {
        "total": len(history),
        "history": [{
            "id": h.id,
            "file_name": h.file_name,
            "file_type": h.file_type,
            "total_rows": h.total_rows,
            "valid_rows": h.valid_rows,
            "duplicate_rows": h.duplicate_rows,
            "conflicts_count": h.conflicts_count or 0,
            "skipped_rows": h.skipped_rows,
            "imported_by": h.imported_by or "System Administrator",
            "imported_at": h.imported_at.isoformat() if h.imported_at else ""
        } for h in history]
    }
