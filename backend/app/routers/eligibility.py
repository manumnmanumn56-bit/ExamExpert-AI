"""
ExamExpert AI — Eligibility Policy & Candidate Evaluation Router
SJB Institute of Technology | Office of Controller of Examinations

Implements Module 9 Minimal Slice 1:
1. Dynamic policy management (status: DRAFT or CONFIRMED; only CONFIRMED is active)
2. Admin-only policy edit with complete audit log containing old and new values
3. Subject-based faculty candidate evaluation returning ELIGIBLE, NOT ELIGIBLE, PENDING VERIFICATION
4. Granular per-rule reasons and non-recommendable pending status
5. Strict Role-Based Access Control and department scoping (Admin: all, HOD: department, Faculty: self)
"""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Faculty, Subject, EligibilityRules, AuditLog, WorkloadLedger
from .auth import get_current_user, require_roles
from ..services.eligibility import (
    get_confirmed_policy,
    evaluate_faculty_eligibility,
    get_faculty_workload,
    DEFAULT_ALLOWED_DESIGNATIONS
)
from ..services.migration import resolve_department_names

router = APIRouter(prefix="/api/eligibility", tags=["Eligibility & Policy"])


# ─── Pydantic Request Models ──────────────────────────────────────────────────
class PolicyUpdateRequest(BaseModel):
    min_experience: float = Field(default=10.0, ge=1.0, le=40.0)
    min_experience_phd: float = Field(default=5.0, ge=1.0, le=30.0)
    allowed_designations: List[str] = Field(default=DEFAULT_ALLOWED_DESIGNATIONS)
    internal_capacity: int = Field(default=2, ge=1, le=10)
    external_capacity: int = Field(default=2, ge=1, le=10)
    status: str = Field(default="CONFIRMED")  # 'DRAFT' | 'CONFIRMED'
    active_academic_year: Optional[str] = "2025-26"
    otp_policy: Optional[str] = "ALL_ROLES"


# ─── Policy Endpoints ────────────────────────────────────────────────────────
@router.get("/policy")
def get_eligibility_policy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves the institutional eligibility policy.
    Returns both the active policy and any draft policy if present.
    """
    confirmed = get_confirmed_policy(db)
    # Most recent policy (could be draft or confirmed)
    latest = db.query(EligibilityRules).order_by(EligibilityRules.id.desc()).first()

    def serialize_policy(p: Optional[EligibilityRules]) -> Optional[Dict[str, Any]]:
        if not p:
            return None
        desigs = DEFAULT_ALLOWED_DESIGNATIONS
        if p.allowed_designations:
            try:
                desigs = json.loads(p.allowed_designations)
            except Exception:
                pass
        return {
            "id": p.id,
            "min_experience": float(p.min_experience if p.min_experience is not None else (p.min_experience_years or 10.0)),
            "min_experience_phd": float(p.min_experience_phd if p.min_experience_phd is not None else (p.phd_fasttrack_min_exp or 5.0)),
            "allowed_designations": desigs,
            "internal_capacity": int(p.internal_capacity or 2),
            "external_capacity": int(p.external_capacity or 2),
            "status": p.status or "CONFIRMED",
            "active_academic_year": p.active_academic_year or "2025-26",
            "otp_policy": p.otp_policy or "ALL_ROLES",
            "updated_at": p.updated_at.isoformat() if p.updated_at else None
        }

    return {
        "active_policy": serialize_policy(confirmed),
        "latest_policy": serialize_policy(latest),
        "has_active_confirmed_policy": bool(confirmed and confirmed.status == "CONFIRMED")
    }


@router.post("/policy")
def update_eligibility_policy(
    req: PolicyUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Updates or creates an institutional eligibility policy (Admin-only).
    Writes an audit log entry containing both old and new policy values.
    """
    policy = db.query(EligibilityRules).order_by(EligibilityRules.id.desc()).first()
    if not policy:
        policy = EligibilityRules()
        db.add(policy)

    # Capture old values for audit logging
    old_values = {
        "min_experience": float(policy.min_experience if policy.min_experience is not None else (policy.min_experience_years or 10.0)),
        "min_experience_phd": float(policy.min_experience_phd if policy.min_experience_phd is not None else (policy.phd_fasttrack_min_exp or 5.0)),
        "allowed_designations": policy.allowed_designations,
        "internal_capacity": policy.internal_capacity,
        "external_capacity": policy.external_capacity,
        "status": policy.status,
        "active_academic_year": policy.active_academic_year
    }

    # Update policy fields
    policy.min_experience = req.min_experience
    policy.min_experience_phd = req.min_experience_phd
    policy.min_experience_years = req.min_experience  # Keep legacy column in sync
    policy.phd_fasttrack_min_exp = req.min_experience_phd
    policy.allowed_designations = json.dumps(req.allowed_designations)
    policy.internal_capacity = req.internal_capacity
    policy.external_capacity = req.external_capacity
    policy.max_internal_papers = req.internal_capacity
    policy.max_external_papers = req.external_capacity
    policy.max_papers_per_faculty = req.internal_capacity
    policy.status = req.status.upper()
    if req.active_academic_year:
        policy.active_academic_year = req.active_academic_year
    if req.otp_policy:
        policy.otp_policy = req.otp_policy
    policy.updated_at = datetime.utcnow()

    new_values = {
        "min_experience": policy.min_experience,
        "min_experience_phd": policy.min_experience_phd,
        "allowed_designations": policy.allowed_designations,
        "internal_capacity": policy.internal_capacity,
        "external_capacity": policy.external_capacity,
        "status": policy.status,
        "active_academic_year": policy.active_academic_year
    }

    # Record Audit Log with old and new values
    db.add(AuditLog(
        action="ELIGIBILITY_POLICY_UPDATE",
        entity_type="EligibilityRules",
        entity_id=policy.id,
        details=json.dumps({
            "performed_by": current_user.username,
            "old_values": old_values,
            "new_values": new_values
        })
    ))
    db.commit()
    db.refresh(policy)

    return {
        "success": True,
        "message": f"Institutional eligibility policy successfully updated (Status: {policy.status}).",
        "policy": {
            "id": policy.id,
            "min_experience": policy.min_experience,
            "min_experience_phd": policy.min_experience_phd,
            "allowed_designations": req.allowed_designations,
            "internal_capacity": policy.internal_capacity,
            "external_capacity": policy.external_capacity,
            "status": policy.status,
            "active_academic_year": policy.active_academic_year
        }
    }


# ─── Candidate Evaluation Matrix Endpoint ────────────────────────────────────
@router.get("/evaluate")
def evaluate_candidates(
    subject_id: int = Query(..., description="Subject master ID to evaluate faculty against"),
    academic_year: Optional[str] = Query(None, description="Academic year (defaults to active policy year)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Evaluates candidate faculty eligibility for a specific subject against active CONFIRMED policy.
    Returns:
    - ELIGIBLE, NOT ELIGIBLE, PENDING VERIFICATION with rule-by-rule audit trail.
    - Scoped strictly by role: Admin sees all; HOD sees department; Faculty sees own record.
    """
    subject = db.query(Subject).filter(Subject.id == subject_id).first()
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found.")

    # Guard against direct python calls where academic_year receives FastAPI Query object
    if academic_year is not None and not isinstance(academic_year, str):
        academic_year = None

    policy = get_confirmed_policy(db)
    if not policy:
        raise HTTPException(
            status_code=400,
            detail="No CONFIRMED eligibility policy found in the database. Admin must confirm policy first."
        )

    # Faculty query scoped by role
    query = db.query(Faculty)

    if current_user.role == "Faculty":
        # Resolve faculty linked to this user
        fac_record = None
        if current_user.faculty_id:
            fac_record = db.query(Faculty).filter(Faculty.id == current_user.faculty_id).first()
        if not fac_record and current_user.email:
            fac_record = db.query(Faculty).filter(Faculty.email.ilike(current_user.email.strip())).first()
        if not fac_record and current_user.full_name:
            fac_record = db.query(Faculty).filter(Faculty.name.ilike(f"%{current_user.full_name.strip()}%")).first()

        if not fac_record:
            raise HTTPException(status_code=404, detail="No linked faculty record found for current session.")
        query = query.filter(Faculty.id == fac_record.id)

    elif current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        if dept_variants:
            # HOD sees internal faculty in their department + external faculty if relevant
            query = query.filter(
                (Faculty.department.in_(dept_variants)) |
                (Faculty.faculty_type == "external")
            )

    faculty_list = query.all()

    evaluations = []
    counts = {"total": len(faculty_list), "ELIGIBLE": 0, "NOT ELIGIBLE": 0, "PENDING VERIFICATION": 0}

    for fac in faculty_list:
        res = evaluate_faculty_eligibility(
            db=db,
            faculty=fac,
            subject=subject,
            policy=policy,
            academic_year=academic_year
        )
        evaluations.append(res)
        counts[res["overall_status"]] = counts.get(res["overall_status"], 0) + 1

    return {
        "subject": {
            "id": subject.id,
            "course_code": subject.course_code,
            "title": subject.title,
            "department": subject.department,
            "semester": subject.semester
        },
        "policy": {
            "status": policy.status,
            "min_experience": policy.min_experience,
            "min_experience_phd": policy.min_experience_phd,
            "internal_capacity": policy.internal_capacity,
            "external_capacity": policy.external_capacity,
            "active_academic_year": policy.active_academic_year
        },
        "counts": counts,
        "evaluations": evaluations
    }


# ─── Workload Ledger Faculty Endpoint ────────────────────────────────────────
@router.get("/workload/{faculty_id}")
def get_faculty_ledger_workload(
    faculty_id: int,
    academic_year: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves workload ledger audit trail for a faculty member.
    Enforces role scoping (Admin: all, HOD: department, Faculty: self).
    """
    faculty = db.query(Faculty).filter(Faculty.id == faculty_id).first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty record not found.")

    if academic_year is not None and not isinstance(academic_year, str):
        academic_year = None

    # Role Scoping
    if current_user.role == "Faculty":
        if current_user.faculty_id and current_user.faculty_id != faculty_id:
            raise HTTPException(status_code=403, detail="Access denied: Faculty may only inspect their own workload.")
    elif current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        if faculty.faculty_type == "internal" and dept_variants and faculty.department not in dept_variants:
            raise HTTPException(status_code=403, detail="Access denied: HOD can only inspect faculty within their department.")

    return get_faculty_workload(db, faculty_id, academic_year)
