"""
ExamExpert AI — Syllabus & Academic Subject Master API Router
SJB Institute of Technology | Office of Controller of Examinations

Retrieves official syllabus courses with dynamic filtering across:
Academic Year → Department → Semester → Subject.

Enforces:
1. Strict 4-semester limit for Master of Computer Applications (MCA) on the server.
2. Server-side RBAC scoping: Admin can view all, add, and edit subjects.
   HOD and Faculty can only view subjects belonging to their own department.
3. Duplicate subject prevention (course_code, department, scheme, semester).
4. Detailed audit logging for every subject addition and modification.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import distinct, or_, func

from ..database import get_db
from ..models import Subject, EligibilityRules, AuditLog, User
from .auth import get_current_user, require_roles

router = APIRouter(prefix="/api/syllabus", tags=["Syllabus"])

MCA_ALLOWED_SEMESTERS = {
    "I", "II", "III", "IV", "1", "2", "3", "4",
    "Semester I", "Semester II", "Semester III", "Semester IV",
    "I/II", "1/2"
}


# ─── Pydantic Request Models ──────────────────────────────────────────────────
class SubjectCreateRequest(BaseModel):
    course_code: str = Field(min_length=2, max_length=50)
    title: str = Field(min_length=3, max_length=300)
    department: str = Field(min_length=2, max_length=200)
    scheme: str = Field(min_length=2, max_length=50)
    semester: str = Field(min_length=1, max_length=20)
    academic_year: str = Field(default="2025-26", min_length=4, max_length=20)
    course_type: str | None = Field(default="Theory")
    credits: int | None = Field(default=4, ge=1, le=10)
    verification_status: str | None = Field(default="Verified from official SJBIT syllabus")
    source_notes: str | None = None


class SubjectUpdateRequest(BaseModel):
    course_code: str | None = Field(default=None, min_length=2, max_length=50)
    title: str | None = Field(default=None, min_length=3, max_length=300)
    department: str | None = Field(default=None, min_length=2, max_length=200)
    scheme: str | None = Field(default=None, min_length=2, max_length=50)
    semester: str | None = Field(default=None, min_length=1, max_length=20)
    academic_year: str | None = Field(default=None, min_length=4, max_length=20)
    course_type: str | None = None
    credits: int | None = Field(default=None, ge=1, le=10)
    verification_status: str | None = None
    source_notes: str | None = None


# ─── Helper Functions ─────────────────────────────────────────────────────────
def _is_verified(status: str | None) -> bool:
    if not status:
        return False
    s = status.lower()
    return "verified" in s and "not" not in s and "pending" not in s and "user" not in s


def _format_verification_badge(status: str | None) -> tuple[str, str]:
    if not status:
        return ("unverified", "Unverified")
    v_low = status.lower()
    if "verified" in v_low and "not" not in v_low and "pending" not in v_low and "user" not in v_low:
        return ("verified", "Officially Verified")
    elif "pending" in v_low or "awaiting" in v_low:
        return ("pending", "Pending Verification")
    elif "user" in v_low or "not yet verified" in v_low:
        return ("unverified", "User-Provided (Unverified)")
    else:
        return ("partially", "Partially Verified")


def resolve_subject_departments(dept_query: str | None) -> list[str]:
    """
    Maps a user's department code (e.g. 'CSE', 'MCA', 'ISE', 'CSDS', 'AIML')
    or full name to the exact department string(s) used in the Subject table.
    """
    if not dept_query:
        return []
    clean = dept_query.strip().upper()
    if clean in ("MCA", "MASTER OF COMPUTER APPLICATIONS"):
        return ["MCA", "Master of Computer Applications"]
    elif clean in ("CSE", "COMPUTER SCIENCE & ENGINEERING", "COMPUTER SCIENCE AND ENGINEERING"):
        return ["CSE", "Computer Science & Engineering"]
    elif clean in ("ISE", "INFORMATION SCIENCE & ENGINEERING", "INFORMATION SCIENCE AND ENGINEERING"):
        return ["ISE", "Information Science & Engineering"]
    elif clean in ("CSDS", "CSE (DATA SCIENCE)", "CSE-DS", "DATA SCIENCE"):
        return ["CSE (Data Science)", "CSDS"]
    elif clean in ("AIML", "AI & ML", "AI AND ML", "ARTIFICIAL INTELLIGENCE & MACHINE LEARNING", "ARTIFICIAL INTELLIGENCE AND MACHINE LEARNING"):
        return ["AI & ML", "AIML", "Artificial Intelligence & Machine Learning"]
    return [dept_query.strip()]


def _validate_mca_semester(dept: str, sem: str):
    """Enforces strict statutory 4-semester limit for Master of Computer Applications (MCA)."""
    is_mca = any(m in dept.lower() for m in ["mca", "master of computer applications"])
    if is_mca:
        clean_sem = sem.replace("Semester", "").strip()
        if clean_sem not in ("I", "II", "III", "IV", "1", "2", "3", "4", "I/II", "1/2"):
            raise HTTPException(
                status_code=400,
                detail=f"Statutory Rule Violation: Master of Computer Applications (MCA) is strictly limited to 4 semesters (Semesters I to IV). Semester '{sem}' is invalid."
            )


def _check_duplicate_subject(
    db: Session,
    course_code: str,
    department: str,
    scheme: str,
    semester: str,
    title: str | None = None,
    exclude_id: int | None = None
):
    """
    Enforces uniqueness constraint on syllabus subjects.
    For standard courses, (course_code, department, scheme, semester) must be unique.
    For shared elective/specialization group codes (e.g. 25MCAE3XY or containing 'XY'/'ELECTIVE'),
    courses are differentiated by title. If the title is also identical, it is rejected as a duplicate.
    """
    query = db.query(Subject).filter(
        Subject.course_code == course_code,
        Subject.department == department,
        Subject.scheme == scheme,
        Subject.semester == semester
    )
    if exclude_id is not None:
        query = query.filter(Subject.id != exclude_id)

    if title:
        t_clean = title.strip().lower()
        if "XY" in course_code.upper() or "ELECTIVE" in course_code.upper():
            existing = query.filter(func.lower(Subject.title) == t_clean).first()
        else:
            existing = query.first()
    else:
        existing = query.first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Duplicate Course Violation: Subject with code '{course_code}', department '{department}', scheme '{scheme}', and semester '{semester}' already exists in syllabus master."
        )


# ─── Cascading Dropdown Endpoints (Used by Allocation Cascade) ───────────────
@router.get("/academic-years")
def get_academic_years(db: Session = Depends(get_db)):
    """
    Returns available academic years from the syllabus dataset.
    Labels the active cycle (default: 2025-26) and upcoming cycle (2026-27).
    """
    rules = db.query(EligibilityRules).first()
    active_year = rules.active_academic_year if (rules and rules.active_academic_year) else "2025-26"
    upcoming_year = rules.upcoming_academic_year if (rules and rules.upcoming_academic_year) else "2026-27"

    rows = db.query(distinct(Subject.academic_year)).filter(
        Subject.academic_year.isnot(None),
        Subject.academic_year != ""
    ).all()

    years = sorted([r[0] for r in rows if r[0]], reverse=True)

    result = []
    for y in years:
        if y == active_year:
            label = f"{y} (Active Cycle)"
            is_active = True
            is_upcoming = False
        elif y == upcoming_year:
            label = f"{y} (Upcoming Cycle)"
            is_active = False
            is_upcoming = True
        else:
            label = y
            is_active = False
            is_upcoming = False

        result.append({
            "year": y,
            "label": label,
            "is_active": is_active,
            "is_upcoming": is_upcoming
        })

    return {"academic_years": result, "default_active_year": active_year}


@router.get("/departments")
def get_departments(academic_year: str, db: Session = Depends(get_db)):
    """Returns departments containing syllabus subjects for the selected academic year."""
    rows = db.query(distinct(Subject.department)).filter(
        Subject.academic_year == academic_year,
        Subject.department.isnot(None),
        Subject.department != ""
    ).all()

    depts = sorted([r[0] for r in rows if r[0]])
    return {"departments": depts}


@router.get("/semesters")
def get_semesters(academic_year: str, department: str, db: Session = Depends(get_db)):
    """
    Returns available semesters for the selected academic year & department.
    Enforces strict MCA restriction: Semester I, II, III, IV ONLY!
    """
    rows = db.query(distinct(Subject.semester)).filter(
        Subject.academic_year == academic_year,
        Subject.department == department,
        Subject.semester.isnot(None),
        Subject.semester != ""
    ).all()

    raw_sems = [r[0] for r in rows if r[0]]

    # Expand any composite semesters like 'I/II'
    expanded = set()
    for s in raw_sems:
        if "/" in s:
            parts = s.split("/")
            for p in parts:
                p_clean = p.strip()
                if p_clean:
                    expanded.add(p_clean)
        else:
            expanded.add(s.strip())

    # Strict MCA limitation: maximum 4 semesters
    is_mca = "mca" in department.lower()
    if is_mca:
        expanded = {s for s in expanded if s in MCA_ALLOWED_SEMESTERS}

    # Sorting
    def sem_sort_order(val: str) -> int:
        clean = val.replace("Semester", "").strip()
        roman_map = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}
        if clean in roman_map:
            return roman_map[clean]
        try:
            return int(clean)
        except ValueError:
            return 99

    sorted_sems = sorted(list(expanded), key=sem_sort_order)

    formatted = []
    for s in sorted_sems:
        label = s if s.startswith("Semester") else f"Semester {s}"
        formatted.append({
            "value": s,
            "label": label
        })

    return {"semesters": formatted}


@router.get("/subjects")
def get_subjects(
    academic_year: str,
    department: str,
    semester: str,
    db: Session = Depends(get_db)
):
    """
    Retrieves matching theory syllabus courses for the selected tuple:
    (Academic Year, Department, Semester).
    Preserves exact verification status and source notes.
    """
    clean_sem = semester.replace("Semester", "").strip()
    target_sems = [clean_sem, semester]
    if clean_sem in ("I", "II"):
        target_sems.extend(["I/II", "1/2"])

    subjects = db.query(Subject).filter(
        Subject.academic_year == academic_year,
        Subject.department == department,
        Subject.semester.in_(target_sems)
    ).order_by(Subject.course_code).all()

    items = []
    for s in subjects:
        badge_class, badge_label = _format_verification_badge(s.verification_status)
        items.append({
            "id": s.id,
            "course_code": s.course_code or "TBD",
            "title": s.title,
            "course_type": s.course_type or "Theory",
            "scheme": s.scheme or "Autonomous",
            "semester": s.semester,
            "verification_status": s.verification_status,
            "badge_class": badge_class,
            "badge_label": badge_label,
            "is_verified": _is_verified(s.verification_status),
            "source_notes": s.source_notes
        })

    return {
        "academic_year": academic_year,
        "department": department,
        "semester": semester,
        "total_found": len(items),
        "subjects": items
    }


# ─── Subject Master Catalog & Management Endpoints ───────────────────────────
@router.get("/all")
def get_all_syllabus(
    department: str | None = None,
    academic_year: str | None = None,
    scheme: str | None = None,
    semester: str | None = None,
    verification_status: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns syllabus entries with filtering across academic year, department, scheme, and semester.
    Strict Server-Side RBAC Scoping:
    - Admin: Full system-wide catalog access across all departments.
    - HOD & Faculty: Scoped strictly to courses belonging to their own department.
    """
    query = db.query(Subject)

    # 1. RBAC Department Scoping
    if current_user.role in ("HOD", "Faculty"):
        allowed_depts = resolve_subject_departments(current_user.department)
        if department:
            req_depts = resolve_subject_departments(department)
            if not any(d in allowed_depts for d in req_depts):
                raise HTTPException(
                    status_code=403,
                    detail=f"Access Denied: As {current_user.role} for '{current_user.department}', you are only authorized to view subjects within your department."
                )
        query = query.filter(Subject.department.in_(allowed_depts))
    elif department:
        target_depts = resolve_subject_departments(department)
        query = query.filter(Subject.department.in_(target_depts))

    # 2. Additional Filters
    if academic_year:
        query = query.filter(Subject.academic_year == academic_year.strip())
    if scheme:
        query = query.filter(Subject.scheme == scheme.strip())
    if semester:
        clean_sem = semester.replace("Semester", "").strip()
        query = query.filter(Subject.semester.in_([clean_sem, semester.strip()]))
    if verification_status:
        query = query.filter(Subject.verification_status.ilike(f"%{verification_status.strip()}%"))
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (Subject.course_code.ilike(s)) |
            (Subject.title.ilike(s)) |
            (Subject.source_notes.ilike(s))
        )

    subjects = query.order_by(
        Subject.academic_year.desc(),
        Subject.department,
        Subject.scheme,
        Subject.semester,
        Subject.course_code
    ).all()

    items = []
    for s in subjects:
        b_class, b_label = _format_verification_badge(s.verification_status)
        items.append({
            "id": s.id,
            "course_code": s.course_code or "TBD",
            "title": s.title,
            "department": s.department,
            "academic_year": s.academic_year,
            "semester": s.semester,
            "scheme": s.scheme,
            "course_type": s.course_type or "Theory",
            "credits": s.credits or 4,
            "verification_status": s.verification_status,
            "badge_class": b_class,
            "badge_label": b_label,
            "source_notes": s.source_notes
        })

    return {
        "total": len(items),
        "user_role": current_user.role,
        "scoped_department": current_user.department if current_user.role in ("HOD", "Faculty") else None,
        "subjects": items
    }


@router.get("/subjects/{subject_id}")
def get_subject_by_id(
    subject_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieves full details of a single subject with server-side department scoping."""
    subj = db.query(Subject).filter_by(id=subject_id).first()
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found in syllabus master.")

    if current_user.role in ("HOD", "Faculty"):
        allowed_depts = resolve_subject_departments(current_user.department)
        if subj.department not in allowed_depts:
            raise HTTPException(
                status_code=403,
                detail=f"Access Denied: Subject '{subj.course_code}' belongs to department '{subj.department}'."
            )

    b_class, b_label = _format_verification_badge(subj.verification_status)
    return {
        "id": subj.id,
        "course_code": subj.course_code,
        "title": subj.title,
        "department": subj.department,
        "academic_year": subj.academic_year,
        "semester": subj.semester,
        "scheme": subj.scheme,
        "course_type": subj.course_type,
        "credits": subj.credits,
        "verification_status": subj.verification_status,
        "badge_class": b_class,
        "badge_label": b_label,
        "source_notes": subj.source_notes
    }


@router.post("/subjects")
def add_subject(
    req: SubjectCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Registers a new academic subject course in the syllabus master.
    Strict Server-Side Enforcement:
    - Admin only (HOD and Faculty receive 403 Forbidden).
    - Enforces MCA 4-semester statutory cap.
    - Prevents duplicates on (course_code, department, scheme, semester).
    - Records comprehensive audit log.
    """
    code = req.course_code.strip().upper()
    dept = req.department.strip()
    scheme = req.scheme.strip()
    sem = req.semester.strip()

    # 1. MCA 4-semester rule check
    _validate_mca_semester(dept, sem)

    # 2. Duplicate course check
    _check_duplicate_subject(db, code, dept, scheme, sem, title=req.title.strip() if req.title else None)

    new_subj = Subject(
        course_code=code,
        title=req.title.strip(),
        department=dept,
        scheme=scheme,
        semester=sem,
        academic_year=req.academic_year.strip(),
        course_type=req.course_type.strip() if req.course_type else "Theory",
        credits=req.credits or 4,
        verification_status=req.verification_status.strip() if req.verification_status else "Verified from official SJBIT syllabus",
        source_notes=req.source_notes.strip() if req.source_notes else None
    )
    db.add(new_subj)
    db.commit()
    db.refresh(new_subj)

    db.add(AuditLog(
        action="SUBJECT_CREATED",
        entity_type="Subject",
        entity_id=new_subj.id,
        details=f"Subject '{new_subj.course_code}' - '{new_subj.title}' ({new_subj.department}, Sem {new_subj.semester}, Scheme {new_subj.scheme}) added by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"Academic subject '{new_subj.course_code}' successfully added.",
        "subject_id": new_subj.id
    }


@router.put("/subjects/{subject_id}")
def edit_subject(
    subject_id: int,
    req: SubjectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Updates an existing subject in the syllabus master.
    Strict Server-Side Enforcement:
    - Admin only (HOD and Faculty receive 403 Forbidden).
    - Enforces MCA 4-semester statutory cap.
    - Prevents duplicate tuples on update.
    - Records comprehensive audit log.
    """
    subj = db.query(Subject).filter_by(id=subject_id).first()
    if not subj:
        raise HTTPException(status_code=404, detail="Subject not found in syllabus master.")

    target_code = req.course_code.strip().upper() if req.course_code else subj.course_code
    target_dept = req.department.strip() if req.department else subj.department
    target_scheme = req.scheme.strip() if req.scheme else subj.scheme
    target_sem = req.semester.strip() if req.semester else subj.semester

    # 1. MCA 4-semester rule check
    _validate_mca_semester(target_dept, target_sem)

    # 2. Duplicate course check across other records
    target_title = req.title.strip() if req.title else subj.title
    _check_duplicate_subject(db, target_code, target_dept, target_scheme, target_sem, title=target_title, exclude_id=subj.id)

    changes = []
    if req.course_code and req.course_code.strip().upper() != subj.course_code:
        changes.append(f"code: {subj.course_code} → {target_code}")
        subj.course_code = target_code

    if req.title and req.title.strip() != subj.title:
        changes.append(f"title: '{subj.title}' → '{req.title.strip()}'")
        subj.title = req.title.strip()

    if req.department and req.department.strip() != subj.department:
        changes.append(f"dept: {subj.department} → {target_dept}")
        subj.department = target_dept

    if req.scheme and req.scheme.strip() != subj.scheme:
        changes.append(f"scheme: {subj.scheme} → {target_scheme}")
        subj.scheme = target_scheme

    if req.semester and req.semester.strip() != subj.semester:
        changes.append(f"sem: {subj.semester} → {target_sem}")
        subj.semester = target_sem

    if req.academic_year and req.academic_year.strip() != subj.academic_year:
        changes.append(f"AY: {subj.academic_year} → {req.academic_year.strip()}")
        subj.academic_year = req.academic_year.strip()

    if req.course_type is not None and req.course_type.strip() != (subj.course_type or ""):
        changes.append("course_type updated")
        subj.course_type = req.course_type.strip()

    if req.credits is not None and req.credits != subj.credits:
        changes.append(f"credits: {subj.credits} → {req.credits}")
        subj.credits = req.credits

    if req.verification_status is not None and req.verification_status.strip() != (subj.verification_status or ""):
        changes.append("verification_status updated")
        subj.verification_status = req.verification_status.strip()

    if req.source_notes is not None:
        subj.source_notes = req.source_notes.strip()

    db.add(AuditLog(
        action="SUBJECT_UPDATED",
        entity_type="Subject",
        entity_id=subj.id,
        details=f"Subject '{subj.course_code}' updated by admin '{current_user.username}'. Changes: {', '.join(changes) if changes else 'None'}."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"Subject '{subj.course_code}' successfully updated."
    }
