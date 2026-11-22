"""
ExamExpert AI — Administrative Governance & User Management API Router
SJB Institute of Technology | Office of Controller of Examinations

Provides secure endpoints for:
1. Live institutional dashboard analytics (strictly from the database, no hardcoding).
2. Institutional user management (create, edit, unlock, deactivate, server-side password reset).
3. Statutory eligibility rules and allocation policy configuration.
Strict server-side RBAC enforcement: Admin role required for administrative actions.
Comprehensive audit logging on every administrative modification.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import (
    User, Faculty, Subject, Allocation, EligibilityRules,
    AuditLog, ActiveSession, DepartmentMapping
)
from .auth import require_roles, hash_password

router = APIRouter(prefix="/api/admin", tags=["Admin Governance"])


# ─── Pydantic Request Models ──────────────────────────────────────────────────
class RulesUpdateRequest(BaseModel):
    min_experience_years: float = Field(default=10.0, ge=1.0, le=40.0)
    phd_fasttrack_min_exp: float = Field(default=5.0, ge=0.0, le=20.0)
    max_papers_per_faculty: int = Field(default=2, ge=1, le=10)
    require_parity: bool = True
    active_academic_year: str = "2025-26"
    upcoming_academic_year: str = "2026-27"


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=150)
    password: str = Field(min_length=8)
    role: str = Field(pattern="^(Admin|HOD|Faculty)$")
    department: str | None = None
    full_name: str | None = None
    phone: str | None = None


class UpdateUserRequest(BaseModel):
    role: str | None = Field(default=None, pattern="^(Admin|HOD|Faculty)$")
    department: str | None = None
    full_name: str | None = None
    phone: str | None = None
    is_active: bool | None = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8)


# ─── Live Admin Dashboard Analytics ───────────────────────────────────────────
@router.get("/dashboard-stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Computes live system-wide operational statistics directly from the database.
    Zero hardcoded numbers or static placeholders.
    """
    # 1. Faculty statistics
    internal_count = db.query(Faculty).filter(Faculty.faculty_type == "internal").count()
    external_count = db.query(Faculty).filter(Faculty.faculty_type == "external").count()
    pending_verification_count = db.query(Faculty).filter(
        Faculty.faculty_type == "external",
        Faculty.eligibility_status.in_(["Cannot Verify", "Pending Verification"])
    ).count()

    # 2. Syllabus / Course statistics
    subjects_count = db.query(Subject).count()

    # 3. Allocations by status
    total_allocations = db.query(Allocation).count()
    allocations_by_status = {
        "Draft": db.query(Allocation).filter(Allocation.status == "Draft").count(),
        "Pending HOD Approval": db.query(Allocation).filter(Allocation.status == "Pending HOD Approval").count(),
        "Confirmed": db.query(Allocation).filter(Allocation.status == "Confirmed").count(),
        "Cancelled": db.query(Allocation).filter(Allocation.status == "Cancelled").count(),
        "Rejected": db.query(Allocation).filter(Allocation.status == "Rejected").count(),
    }

    # 4. User accounts statistics
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    locked_users = db.query(User).filter(User.is_locked == True).count()
    users_by_role = {
        "Admin": db.query(User).filter(User.role == "Admin").count(),
        "HOD": db.query(User).filter(User.role == "HOD").count(),
        "Faculty": db.query(User).filter(User.role == "Faculty").count(),
    }

    return {
        "faculty": {
            "internal_count": internal_count,
            "external_count": external_count,
            "total_faculty": internal_count + external_count,
            "pending_verification_count": pending_verification_count
        },
        "syllabus": {
            "total_subjects_count": subjects_count
        },
        "allocations": {
            "total_allocations": total_allocations,
            "by_status": allocations_by_status
        },
        "users": {
            "total_users": total_users,
            "active_users": active_users,
            "locked_users": locked_users,
            "by_role": users_by_role
        },
        "generated_at": datetime.utcnow().isoformat()
    }


# ─── User Management Endpoints ────────────────────────────────────────────────
@router.get("/users")
def list_users(
    role: str | None = None,
    department: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Lists institutional user accounts with their security and login status.
    Strictly excludes sensitive hashes, activation tokens, and reset secrets.
    """
    query = db.query(User)

    if role:
        query = query.filter(User.role == role)
    if department:
        query = query.filter(User.department == department)
    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            (User.username.ilike(s)) |
            (User.email.ilike(s)) |
            (User.full_name.ilike(s))
        )

    users = query.order_by(User.role, User.username).all()

    return {
        "total": len(users),
        "users": [{
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "department": u.department,
            "full_name": u.full_name,
            "phone": u.phone,
            "is_active": u.is_active,
            "is_locked": u.is_locked,
            "is_activated": u.is_activated,
            "failed_attempts": u.failed_attempts or 0,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None
        } for u in users]
    }


@router.post("/users")
def create_user(
    req: CreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Registers a new administrative, departmental, or faculty user account.
    Enforces uniqueness, validation, and audit logging.
    """
    username = req.username.strip().lower()
    email = req.email.strip().lower()

    if db.query(User).filter_by(username=username).first():
        raise HTTPException(status_code=400, detail=f"Username '{username}' is already in use.")

    if db.query(User).filter_by(email=email).first():
        raise HTTPException(status_code=400, detail=f"Email address '{email}' is already registered.")

    # Department validation
    dept = req.department.strip() if req.department else None
    if req.role in ("HOD", "Faculty") and not dept:
        raise HTTPException(status_code=400, detail=f"Department is mandatory for {req.role} accounts.")

    if dept:
        # Validate department against mappings
        valid_dept = db.query(DepartmentMapping).filter(
            (DepartmentMapping.short_code.ilike(dept)) |
            (DepartmentMapping.full_name.ilike(dept))
        ).first()
        if valid_dept:
            dept = valid_dept.short_code  # Store standard short code

    new_user = User(
        username=username,
        email=email,
        password_hash=hash_password(req.password),
        role=req.role,
        department=dept,
        full_name=req.full_name.strip() if req.full_name else username,
        phone=req.phone.strip() if req.phone else None,
        is_active=True,
        is_activated=True,
        failed_attempts=0,
        is_locked=False
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    db.add(AuditLog(
        action="ADMIN_USER_CREATED",
        entity_type="User",
        entity_id=new_user.id,
        details=f"User '{new_user.username}' ({new_user.role}, Dept: {new_user.department}) created by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"User account '{new_user.username}' successfully created.",
        "user_id": new_user.id
    }


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    req: UpdateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Updates profile, role, department assignment, or active status of a user.
    Prevents self-deactivation or self-demotion if the admin is the sole active admin.
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    # Guardrails: self-deactivation
    if user.id == current_user.id and req.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own active administrator account.")

    # Guardrails: self-demotion from Admin
    if user.id == current_user.id and req.role and req.role != "Admin":
        admin_count = db.query(User).filter(User.role == "Admin", User.is_active == True).count()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot change role: You are the sole active Administrator.")

    changes = []
    if req.role and req.role != user.role:
        changes.append(f"role: {user.role} → {req.role}")
        user.role = req.role

    if req.department is not None:
        dept = req.department.strip() if req.department else None
        if dept:
            valid_dept = db.query(DepartmentMapping).filter(
                (DepartmentMapping.short_code.ilike(dept)) |
                (DepartmentMapping.full_name.ilike(dept))
            ).first()
            if valid_dept:
                dept = valid_dept.short_code
        if dept != user.department:
            changes.append(f"department: {user.department} → {dept}")
            user.department = dept

    if req.full_name is not None and req.full_name.strip() != user.full_name:
        changes.append(f"name: {user.full_name} → {req.full_name.strip()}")
        user.full_name = req.full_name.strip()

    if req.phone is not None and req.phone.strip() != (user.phone or ""):
        changes.append("phone updated")
        user.phone = req.phone.strip()

    if req.is_active is not None and req.is_active != user.is_active:
        changes.append(f"active: {user.is_active} → {req.is_active}")
        user.is_active = req.is_active
        if not user.is_active:
            # Revoke existing sessions immediately
            db.query(ActiveSession).filter_by(user_id=user.id, is_revoked=False).update({"is_revoked": True})

    db.add(AuditLog(
        action="ADMIN_USER_UPDATED",
        entity_type="User",
        entity_id=user.id,
        details=f"User '{user.username}' updated by admin '{current_user.username}'. Changes: {', '.join(changes) if changes else 'None'}."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"User account '{user.username}' successfully updated."
    }


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Unlocks an account that was locked due to excessive failed password attempts.
    Resets failed_attempts counter to 0 and clears is_locked flag.
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    user.is_locked = False
    user.failed_attempts = 0

    db.add(AuditLog(
        action="ADMIN_USER_UNLOCKED",
        entity_type="User",
        entity_id=user.id,
        details=f"User '{user.username}' unlocked by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"Account '{user.username}' has been successfully unlocked."
    }


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    req: AdminResetPasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Directly updates a user's password from the administrative console.
    Bcrypt hashes the password server-side.
    Revokes any active sessions so the user must sign in with the new credential.
    NEVER displays or returns the plain-text password in API responses.
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    user.password_hash = hash_password(req.new_password)
    user.failed_attempts = 0
    user.is_locked = False

    # Revoke all active sessions
    db.query(ActiveSession).filter_by(user_id=user.id, is_revoked=False).update({"is_revoked": True})

    db.add(AuditLog(
        action="ADMIN_USER_PASSWORD_RESET",
        entity_type="User",
        entity_id=user.id,
        details=f"Password for user '{user.username}' was reset by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"Password for account '{user.username}' has been securely reset."
    }


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Deactivates a user account and immediately terminates all active web sessions.
    Prevents self-deactivation of the logged-in administrator.
    """
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own administrator account.")

    user.is_active = False
    # Revoke sessions
    db.query(ActiveSession).filter_by(user_id=user.id, is_revoked=False).update({"is_revoked": True})

    db.add(AuditLog(
        action="ADMIN_USER_DEACTIVATED",
        entity_type="User",
        entity_id=user.id,
        details=f"User '{user.username}' deactivated by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"User '{user.username}' has been deactivated and active sessions revoked."
    }


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """Reactivates a previously deactivated user account."""
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    user.is_active = True

    db.add(AuditLog(
        action="ADMIN_USER_ACTIVATED",
        entity_type="User",
        entity_id=user.id,
        details=f"User '{user.username}' reactivated by admin '{current_user.username}'."
    ))
    db.commit()

    return {
        "success": True,
        "message": f"User '{user.username}' has been reactivated."
    }


# ─── Eligibility Rules & Policy Configuration ────────────────────────────────
@router.get("/rules")
def get_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin", "HOD"]))
):
    """Retrieves current institutional eligibility and allocation policies."""
    r = db.query(EligibilityRules).first()
    if not r:
        r = EligibilityRules(
            min_experience_years=10.0,
            phd_fasttrack_min_exp=5.0,
            max_papers_per_faculty=2,
            require_parity=True,
            active_academic_year="2025-26",
            upcoming_academic_year="2026-27"
        )
        db.add(r)
        db.commit()
        db.refresh(r)

    return {
        "min_experience_years": r.min_experience_years,
        "phd_fasttrack_min_exp": r.phd_fasttrack_min_exp,
        "max_papers_per_faculty": r.max_papers_per_faculty,
        "require_parity": r.require_parity,
        "active_academic_year": r.active_academic_year or "2025-26",
        "upcoming_academic_year": r.upcoming_academic_year or "2026-27",
        "updated_at": r.updated_at.isoformat() if r.updated_at else ""
    }


@router.post("/rules")
def update_rules(
    req: RulesUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """Updates institutional allocation policies and logs change to audit trail."""
    r = db.query(EligibilityRules).first()
    if not r:
        r = EligibilityRules()
        db.add(r)

    r.min_experience_years = req.min_experience_years
    r.phd_fasttrack_min_exp = req.phd_fasttrack_min_exp
    r.max_papers_per_faculty = req.max_papers_per_faculty
    r.require_parity = req.require_parity
    r.active_academic_year = req.active_academic_year
    r.upcoming_academic_year = req.upcoming_academic_year
    r.updated_at = datetime.utcnow()

    db.add(AuditLog(
        action="ADMIN_POLICY_UPDATED",
        entity_type="EligibilityRules",
        entity_id=r.id,
        details=f"Updated: Min Exp={req.min_experience_years}y, PhD Fast-track={req.phd_fasttrack_min_exp}y, Max Papers={req.max_papers_per_faculty}, Active AY={req.active_academic_year}."
    ))
    db.commit()

    return {"success": True, "message": "Institutional policies successfully updated."}
