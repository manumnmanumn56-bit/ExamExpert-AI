"""
ExamExpert AI — Faculty-Subject Expertise Mapping Router
SJB Institute of Technology | Office of Controller of Examinations

Handles database-backed faculty-subject expertise mappings:
- Types: EXACT_EXPERIENCE, SPECIALIZATION, RELATED
- Status: SUGGESTED, CONFIRMED, REJECTED
- Automatic suggestion generation from course history & expertise
- Admin review, confirmation, rejection, bulk confirmation & manual creation
- Strict RBAC: Admin (full CRUD), HOD (department view-only), Faculty (own view-only)
- Server-side helpers for eligibility & matching (confirmed mappings only)
"""
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Faculty, Subject, FacultyCourseHistory, FacultyExpertise,
    FacultySubjectMapping, AuditLog, User
)
from .auth import require_roles, get_current_user
from ..services.migration import resolve_department_names

router = APIRouter(prefix="/api/mappings", tags=["Expertise Mappings"])


# ─── Pydantic Request Models ──────────────────────────────────────────────────

class CreateMappingRequest(BaseModel):
    faculty_id: int
    subject_id: int
    mapping_type: str = Field(..., pattern="^(EXACT_EXPERIENCE|SPECIALIZATION|RELATED)$")
    times_handled: int = 0
    status: str = Field("CONFIRMED", pattern="^(SUGGESTED|CONFIRMED|REJECTED)$")
    suggestion_reason: str | None = None


class BulkConfirmRequest(BaseModel):
    mapping_ids: list[int] = Field(..., min_length=1)


# ─── Server-Side Helpers (Only Confirmed Count for Matching) ──────────────────

def get_confirmed_mappings_for_subject(db: Session, subject_id: int) -> list[FacultySubjectMapping]:
    """
    Returns only CONFIRMED faculty-subject expertise mappings for the given subject.
    SUGGESTED and REJECTED mappings are strictly excluded.
    """
    return db.query(FacultySubjectMapping).filter(
        FacultySubjectMapping.subject_id == subject_id,
        FacultySubjectMapping.status == "CONFIRMED"
    ).all()


def get_confirmed_mappings_for_faculty(db: Session, faculty_id: int) -> list[FacultySubjectMapping]:
    """
    Returns only CONFIRMED subject expertise mappings for the given faculty.
    SUGGESTED and REJECTED mappings are strictly excluded.
    """
    return db.query(FacultySubjectMapping).filter(
        FacultySubjectMapping.faculty_id == faculty_id,
        FacultySubjectMapping.status == "CONFIRMED"
    ).all()


# ─── Suggestion Generator ─────────────────────────────────────────────────────

@router.post("/generate-suggestions")
def generate_mapping_suggestions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Automatically generates SUGGESTED faculty-subject expertise mappings
    from historical course handling records and expertise tags.
    Every suggestion includes an explicit reason.
    Never marks anything CONFIRMED automatically.
    Prevents duplicate mappings.
    Admin only.
    """
    all_fac = db.query(Faculty).all()
    all_sub = db.query(Subject).all()

    # Pre-load existing mapping keys to avoid duplicates
    existing_keys = set(
        (m.faculty_id, m.subject_id, m.mapping_type)
        for m in db.query(
            FacultySubjectMapping.faculty_id,
            FacultySubjectMapping.subject_id,
            FacultySubjectMapping.mapping_type
        ).all()
    )

    generated_count = 0
    duplicates_skipped = 0

    # Domain keyword mapping helpers for RELATED category
    related_domains = [
        ({"python", "programming", "c", "c++", "java"}, "Programming Fundamentals"),
        ({"machine learning", "ml", "artificial intelligence", "ai", "deep learning", "neural"}, "AI & Machine Learning"),
        ({"network", "networking", "security", "cryptography", "cyber", "firewall"}, "Networks & Cybersecurity"),
        ({"database", "dbms", "sql", "nosql", "data warehousing", "mining"}, "Data & Database Systems"),
        ({"cloud", "aws", "azure", "devops", "distributed", "virtualization"}, "Cloud & Infrastructure"),
        ({"web", "html", "javascript", "full stack", "react", "frontend"}, "Web Technologies"),
        ({"operating system", "os", "linux", "unix", "kernel", "system software"}, "Systems & Operating Environments")
    ]

    for f in all_fac:
        # 1. EXACT_EXPERIENCE: from FacultyCourseHistory & course_history_text
        for ch in f.course_history:
            cname = (ch.course_title or "").strip().lower()
            if not cname:
                continue
            for s in all_sub:
                stitle = (s.title or "").strip().lower()
                scode = (s.course_code or "").strip().lower()

                is_exact = (cname == stitle) or (cname in stitle and len(cname) >= 6) or (stitle in cname and len(stitle) >= 6) or (scode and scode == cname)
                if is_exact:
                    key = (f.id, s.id, "EXACT_EXPERIENCE")
                    if key in existing_keys:
                        duplicates_skipped += 1
                        continue

                    existing_keys.add(key)
                    db.add(FacultySubjectMapping(
                        faculty_id=f.id,
                        subject_id=s.id,
                        mapping_type="EXACT_EXPERIENCE",
                        times_handled=ch.times_handled or 1,
                        status="SUGGESTED",
                        suggestion_reason=f"Faculty previously handled '{ch.course_title}' {ch.times_handled or 1} time(s) according to institutional teaching records.",
                        is_confirmed=False
                    ))
                    generated_count += 1

        # 2. SPECIALIZATION & RELATED: from expertise_tags & expertise_text
        all_tags = [t.tag.strip() for t in f.expertise_tags if t.tag and len(t.tag.strip()) >= 3]
        if f.expertise_text:
            text_tags = [p.strip() for p in re.split(r"[,;]+", f.expertise_text) if len(p.strip()) >= 3]
            all_tags.extend(text_tags)

        # Unique lowercase tags
        seen_tags = set()
        clean_tags = []
        for t in all_tags:
            t_low = t.lower()
            if t_low not in seen_tags:
                seen_tags.add(t_low)
                clean_tags.append((t, t_low))

        for orig_tag, tag_low in clean_tags:
            for s in all_sub:
                stitle_low = (s.title or "").strip().lower()

                # Direct specialization match: tag is a substring of subject title
                if tag_low in stitle_low:
                    key = (f.id, s.id, "SPECIALIZATION")
                    if key in existing_keys:
                        duplicates_skipped += 1
                        continue

                    existing_keys.add(key)
                    db.add(FacultySubjectMapping(
                        faculty_id=f.id,
                        subject_id=s.id,
                        mapping_type="SPECIALIZATION",
                        times_handled=0,
                        status="SUGGESTED",
                        suggestion_reason=f"Faculty specialization keyword '{orig_tag}' directly aligns with syllabus course '{s.title}'.",
                        is_confirmed=False
                    ))
                    generated_count += 1
                else:
                    # Check RELATED domain topic overlap
                    for kw_set, domain_label in related_domains:
                        tag_in_domain = any(k in tag_low for k in kw_set)
                        subj_in_domain = any(k in stitle_low for k in kw_set)
                        if tag_in_domain and subj_in_domain:
                            key = (f.id, s.id, "RELATED")
                            if key in existing_keys:
                                duplicates_skipped += 1
                                break

                            existing_keys.add(key)
                            db.add(FacultySubjectMapping(
                                faculty_id=f.id,
                                subject_id=s.id,
                                mapping_type="RELATED",
                                times_handled=0,
                                status="SUGGESTED",
                                suggestion_reason=f"Subject '{s.title}' and faculty expertise '{orig_tag}' share common curriculum domain '{domain_label}'.",
                                is_confirmed=False
                            ))
                            generated_count += 1
                            break

    db.add(AuditLog(
        action="MAPPINGS_SUGGESTIONS_GENERATED",
        entity_type="FacultySubjectMapping",
        entity_id=None,
        details=f"Admin '{current_user.username}' ran automated suggestion generator: {generated_count} suggestions created, {duplicates_skipped} duplicates skipped."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"Successfully generated {generated_count} mapping suggestions. All suggestions placed in SUGGESTED status awaiting Admin confirmation.",
        "generated_count": generated_count,
        "duplicates_skipped": duplicates_skipped
    }


# ─── Mapping Query & Filter Endpoint ──────────────────────────────────────────

@router.get("")
def get_mappings(
    department: str | None = None,
    subject_id: int | None = None,
    faculty_id: int | None = None,
    status: str | None = None,
    mapping_type: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Browses expertise mappings with multi-dimensional filtering.
    Enforces server-side RBAC scoping:
    - Admin: Full system-wide access.
    - HOD: Scoped strictly to their own department's internal faculty & subjects.
    - Faculty: Scoped strictly to their own faculty record.
    """
    query = db.query(FacultySubjectMapping).join(Faculty, FacultySubjectMapping.faculty_id == Faculty.id).join(Subject, FacultySubjectMapping.subject_id == Subject.id)

    # 1. RBAC Scoping
    if current_user.role == "HOD":
        dept_names = resolve_department_names(db, current_user.department)
        if department:
            req_depts = resolve_department_names(db, department)
            if not any(d in dept_names for d in req_depts):
                raise HTTPException(
                    status_code=403,
                    detail=f"Access Denied: As HOD for '{current_user.department}', you are only authorized to view mappings for your department."
                )
        # HOD strictly views internal faculty and subjects in their department
        query = query.filter(
            Faculty.faculty_type == "internal",
            Subject.department.in_(dept_names),
            Faculty.department.in_(dept_names)
        )
    elif current_user.role == "Faculty":
        query = query.filter(
            (Faculty.email == current_user.email) |
            (Faculty.name.ilike(f"%{current_user.full_name or current_user.username}%"))
        )
    else:
        # Admin: Apply optional department filter
        if department:
            dept_names = resolve_department_names(db, department)
            query = query.filter(Subject.department.in_(dept_names))

    # 2. General Query Filters
    if subject_id:
        query = query.filter(FacultySubjectMapping.subject_id == subject_id)
    if faculty_id:
        query = query.filter(FacultySubjectMapping.faculty_id == faculty_id)
    if status and status.upper() != "ALL":
        query = query.filter(FacultySubjectMapping.status == status.upper().strip())
    if mapping_type and mapping_type.upper() != "ALL":
        query = query.filter(FacultySubjectMapping.mapping_type == mapping_type.upper().strip())
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (Faculty.name.ilike(s)) |
            (Subject.title.ilike(s)) |
            (Subject.course_code.ilike(s)) |
            (FacultySubjectMapping.suggestion_reason.ilike(s))
        )

    mappings = query.order_by(FacultySubjectMapping.id.desc()).all()

    return {
        "total": len(mappings),
        "user_role": current_user.role,
        "mappings": [{
            "id": m.id,
            "faculty_id": m.faculty_id,
            "faculty_name": m.faculty.name if m.faculty else "Unknown",
            "faculty_dept": m.faculty.department if m.faculty else "",
            "faculty_type": m.faculty.faculty_type if m.faculty else "internal",
            "institution": m.faculty.institution if m.faculty else "SJBIT",
            "subject_id": m.subject_id,
            "course_code": m.subject.course_code if m.subject else "",
            "subject_title": m.subject.title if m.subject else "Unknown",
            "subject_dept": m.subject.department if m.subject else "",
            "semester": m.subject.semester if m.subject else "",
            "mapping_type": m.mapping_type or "SPECIALIZATION",
            "status": m.status or "SUGGESTED",
            "times_handled": m.times_handled or 0,
            "suggestion_reason": m.suggestion_reason,
            "confirmed_by": m.confirmed_by,
            "confirmed_at": m.confirmed_at.isoformat() if m.confirmed_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None
        } for m in mappings]
    }


# ─── Individual Status Transitions (Confirm / Reject) ─────────────────────────

@router.post("/{mapping_id}/confirm")
def confirm_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Confirms an expertise mapping.
    Admin only. HOD and Faculty receive 403 Forbidden.
    Logs old and new status to AuditLog.
    """
    m = db.query(FacultySubjectMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Expertise mapping not found.")

    old_status = m.status
    m.status = "CONFIRMED"
    m.is_confirmed = True
    m.confirmed_by = current_user.username
    m.confirmed_at = datetime.utcnow()

    f_name = m.faculty.name if m.faculty else f"Faculty #{m.faculty_id}"
    s_title = m.subject.title if m.subject else f"Subject #{m.subject_id}"

    db.add(AuditLog(
        action="MAPPING_STATUS_UPDATED",
        entity_type="FacultySubjectMapping",
        entity_id=m.id,
        details=f"Expertise mapping #{m.id} ('{f_name}' → '{s_title}', {m.mapping_type}) status changed from '{old_status}' to 'CONFIRMED' by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "mapping_id": m.id,
        "old_status": old_status,
        "new_status": m.status,
        "confirmed_by": m.confirmed_by,
        "confirmed_at": m.confirmed_at.isoformat()
    }


@router.post("/{mapping_id}/reject")
def reject_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Rejects an expertise mapping.
    Admin only. HOD and Faculty receive 403 Forbidden.
    Logs old and new status to AuditLog.
    """
    m = db.query(FacultySubjectMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Expertise mapping not found.")

    old_status = m.status
    m.status = "REJECTED"
    m.is_confirmed = False
    m.confirmed_by = current_user.username
    m.confirmed_at = datetime.utcnow()

    f_name = m.faculty.name if m.faculty else f"Faculty #{m.faculty_id}"
    s_title = m.subject.title if m.subject else f"Subject #{m.subject_id}"

    db.add(AuditLog(
        action="MAPPING_STATUS_UPDATED",
        entity_type="FacultySubjectMapping",
        entity_id=m.id,
        details=f"Expertise mapping #{m.id} ('{f_name}' → '{s_title}', {m.mapping_type}) status changed from '{old_status}' to 'REJECTED' by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "mapping_id": m.id,
        "old_status": old_status,
        "new_status": m.status,
        "confirmed_by": m.confirmed_by,
        "confirmed_at": m.confirmed_at.isoformat()
    }


# ─── Bulk Confirmation Endpoint ───────────────────────────────────────────────

@router.post("/bulk-confirm")
def bulk_confirm_mappings(
    req: BulkConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Bulk confirms multiple expertise mappings after Admin verification.
    Admin only.
    Logs audit trail for the batch operation.
    """
    mappings = db.query(FacultySubjectMapping).filter(FacultySubjectMapping.id.in_(req.mapping_ids)).all()
    if not mappings:
        raise HTTPException(status_code=404, detail="No matching mappings found for the provided IDs.")

    now = datetime.utcnow()
    confirmed_count = 0
    for m in mappings:
        m.status = "CONFIRMED"
        m.is_confirmed = True
        m.confirmed_by = current_user.username
        m.confirmed_at = now
        confirmed_count += 1

    db.add(AuditLog(
        action="MAPPINGS_BULK_CONFIRMED",
        entity_type="FacultySubjectMapping",
        entity_id=None,
        details=f"Admin '{current_user.username}' bulk-confirmed {confirmed_count} expertise mappings."
    ))
    db.commit()

    return {
        "success": True,
        "confirmed_count": confirmed_count,
        "message": f"Successfully confirmed {confirmed_count} expertise mapping(s)."
    }


# ─── Manual Creation Endpoint (Duplicate Prevention) ──────────────────────────

@router.post("")
def create_manual_mapping(
    req: CreateMappingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Manually creates a faculty-subject expertise mapping.
    Prevents duplicate mappings on (faculty_id, subject_id, mapping_type).
    Admin only.
    """
    # 1. Validate faculty and subject exist
    fac = db.query(Faculty).filter_by(id=req.faculty_id).first()
    if not fac:
        raise HTTPException(status_code=404, detail=f"Faculty record #{req.faculty_id} not found.")

    subj = db.query(Subject).filter_by(id=req.subject_id).first()
    if not subj:
        raise HTTPException(status_code=404, detail=f"Subject record #{req.subject_id} not found.")

    # 2. Prevent duplicate mappings (same faculty, subject, type)
    dup = db.query(FacultySubjectMapping).filter_by(
        faculty_id=req.faculty_id,
        subject_id=req.subject_id,
        mapping_type=req.mapping_type
    ).first()
    if dup:
        raise HTTPException(
            status_code=400,
            detail=f"Duplicate Mapping Violation: An expertise mapping of type '{req.mapping_type}' already exists for faculty '{fac.name}' and subject '{subj.title}'."
        )

    is_conf = (req.status == "CONFIRMED")
    now = datetime.utcnow() if is_conf else None
    conf_by = current_user.username if is_conf else None

    mapping = FacultySubjectMapping(
        faculty_id=req.faculty_id,
        subject_id=req.subject_id,
        mapping_type=req.mapping_type,
        times_handled=req.times_handled,
        status=req.status,
        suggestion_reason=req.suggestion_reason or f"Manually registered by admin '{current_user.username}'.",
        is_confirmed=is_conf,
        confirmed_by=conf_by,
        confirmed_at=now
    )
    db.add(mapping)
    db.flush()

    db.add(AuditLog(
        action="MAPPING_CREATED",
        entity_type="FacultySubjectMapping",
        entity_id=mapping.id,
        details=f"Admin '{current_user.username}' created manual mapping #{mapping.id} for '{fac.name}' → '{subj.title}' ({req.mapping_type}, Status: {req.status})."
    ))
    db.commit()

    return {
        "success": True,
        "mapping_id": mapping.id,
        "faculty_name": fac.name,
        "subject_title": subj.title,
        "mapping_type": mapping.mapping_type,
        "status": mapping.status,
        "times_handled": mapping.times_handled
    }


# ─── Delete Mapping Endpoint ──────────────────────────────────────────────────

@router.delete("/{mapping_id}")
def delete_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Deletes an expertise mapping.
    Admin only.
    """
    m = db.query(FacultySubjectMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Expertise mapping not found.")

    f_name = m.faculty.name if m.faculty else f"Faculty #{m.faculty_id}"
    s_title = m.subject.title if m.subject else f"Subject #{m.subject_id}"
    m_type = m.mapping_type

    db.delete(m)
    db.add(AuditLog(
        action="MAPPING_DELETED",
        entity_type="FacultySubjectMapping",
        entity_id=mapping_id,
        details=f"Admin '{current_user.username}' deleted expertise mapping #{mapping_id} ('{f_name}' → '{s_title}', {m_type})."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"Mapping #{mapping_id} deleted successfully."
    }


# ─── Confirmed Mappings Query Endpoint ────────────────────────────────────────

@router.get("/confirmed-for-subject/{subject_id}")
def get_confirmed_mappings_for_subject_endpoint(
    subject_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Returns only CONFIRMED expertise mappings for the specified subject.
    SUGGESTED and REJECTED mappings are strictly excluded.
    Accessible to all authenticated users.
    """
    confirmed = get_confirmed_mappings_for_subject(db, subject_id)
    return {
        "subject_id": subject_id,
        "confirmed_count": len(confirmed),
        "mappings": [{
            "id": m.id,
            "faculty_id": m.faculty_id,
            "faculty_name": m.faculty.name if m.faculty else "",
            "mapping_type": m.mapping_type,
            "times_handled": m.times_handled,
            "status": m.status,
            "confirmed_by": m.confirmed_by,
            "confirmed_at": m.confirmed_at.isoformat() if m.confirmed_at else None
        } for m in confirmed]
    }
