"""
ExamExpert AI — Database Schema Migration & Relational Synchronization
SJB Institute of Technology | Office of Controller of Examinations

Ensures all new tables and columns are created without data loss:
1. Adds allocation_setters, workload_ledger, department_mappings, faculty_subject_mappings, external_institutions
2. Adds missing columns to users, eligibility_rules, allocations, workload_ledger via SQLite ALTER TABLE
3. Seeds standard department alias mappings to ensure seamless department scoping
4. Seeds 11 external institutions whitelisted by default
5. Populates relational allocation_setters from existing JSON allocation records
6. Provides helpers for workload ledger calculations and institution validation
"""
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..database import engine, Base
from ..models import (
    User, EligibilityRules, Allocation, AllocationSetter,
    WorkloadLedger, DepartmentMapping, Faculty, Subject, ExternalInstitution
)

DEFAULT_EXTERNAL_INSTITUTIONS = [
    "Bangalore Institute of Technology (BIT)",
    "Dayananda Sagar Academy of Technology & Management (DSATM)",
    "Dayananda Sagar College of Engineering (DSCE)",
    "Dr. Ambedkar Institute of Technology (Dr. AIT)",
    "JSS Academy of Technical Education, Bengaluru",
    "M. S. Ramaiah University of Applied Sciences (MSRUAS)",
    "Presidency College, Bengaluru (Hebbal)",
    "RNS Institute of Technology (RNSIT)",
    "RV College of Engineering (RVCE)",
    "RajaRajeswari College of Engineering (RRCE)",
    "S-VYASA Deemed to be University"
]


def run_database_migrations(db: Session):
    """Safely upgrades SQLite schema, creates new tables, and adds missing columns."""
    bind = db.get_bind()
    # 1. Create any non-existing tables
    Base.metadata.create_all(bind=bind)

    # 2. Check and add missing columns to existing tables
    with bind.connect() as conn:
        # Users table checks
        user_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
        if "is_activated" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_activated BOOLEAN DEFAULT 1"))
        if "activation_token" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN activation_token VARCHAR(100)"))
        if "reset_token" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN reset_token VARCHAR(100)"))
        if "reset_token_expires" not in user_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN reset_token_expires DATETIME"))

        # Eligibility rules checks
        rules_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(eligibility_rules)")).fetchall()]
        if "otp_policy" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN otp_policy VARCHAR(30) DEFAULT 'ALL_ROLES'"))
        if "max_internal_papers" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN max_internal_papers INTEGER DEFAULT 2"))
        if "max_external_papers" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN max_external_papers INTEGER DEFAULT 2"))
        if "external_allowed_institutions" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN external_allowed_institutions TEXT"))
        if "min_experience" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN min_experience FLOAT DEFAULT 10.0"))
        if "min_experience_phd" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN min_experience_phd FLOAT DEFAULT 5.0"))
        if "allowed_designations" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN allowed_designations TEXT DEFAULT '[\"Assistant Professor\", \"Associate Professor\", \"Professor\"]'"))
        if "internal_capacity" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN internal_capacity INTEGER DEFAULT 2"))
        if "external_capacity" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN external_capacity INTEGER DEFAULT 2"))
        if "status" not in rules_cols:
            conn.execute(text("ALTER TABLE eligibility_rules ADD COLUMN status VARCHAR(20) DEFAULT 'CONFIRMED'"))

        conn.execute(text("""
            UPDATE eligibility_rules
            SET min_experience = coalesce(min_experience, min_experience_years, 10.0),
                min_experience_phd = coalesce(min_experience_phd, phd_fasttrack_min_exp, 5.0),
                internal_capacity = coalesce(internal_capacity, max_internal_papers, max_papers_per_faculty, 2),
                external_capacity = coalesce(external_capacity, max_external_papers, 2),
                allowed_designations = coalesce(allowed_designations, '["Assistant Professor", "Associate Professor", "Professor"]'),
                status = coalesce(status, 'CONFIRMED')
        """))

        # Allocations table checks
        alloc_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(allocations)")).fetchall()]
        if "allocation_mode" not in alloc_cols:
            conn.execute(text("ALTER TABLE allocations ADD COLUMN allocation_mode VARCHAR(30) DEFAULT 'Balanced'"))
        if "has_manual_override" not in alloc_cols:
            conn.execute(text("ALTER TABLE allocations ADD COLUMN has_manual_override BOOLEAN DEFAULT 0"))

        setter_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(allocation_setters)")).fetchall()]
        if "is_manual_override" not in setter_cols:
            conn.execute(text("ALTER TABLE allocation_setters ADD COLUMN is_manual_override BOOLEAN DEFAULT 0"))
        if "manual_reason" not in setter_cols:
            conn.execute(text("ALTER TABLE allocation_setters ADD COLUMN manual_reason TEXT"))

        # Workload ledger checks & triggers
        workload_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(workload_ledger)")).fetchall()]
        if "semester" not in workload_cols:
            conn.execute(text("ALTER TABLE workload_ledger ADD COLUMN semester VARCHAR(20)"))

        # SQLite triggers: enforce append-only immutability (block UPDATE and DELETE)
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_workload_ledger_no_update
            BEFORE UPDATE ON workload_ledger
            BEGIN
                SELECT RAISE(ABORT, 'Workload ledger is append-only: UPDATE operations are strictly prohibited.');
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_workload_ledger_no_delete
            BEFORE DELETE ON workload_ledger
            BEGIN
                SELECT RAISE(ABORT, 'Workload ledger is append-only: DELETE operations are strictly prohibited.');
            END;
        """))

        # Faculty subject mappings checks
        fsm_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(faculty_subject_mappings)")).fetchall()]
        if "mapping_type" not in fsm_cols:
            conn.execute(text("ALTER TABLE faculty_subject_mappings ADD COLUMN mapping_type VARCHAR(50) DEFAULT 'SPECIALIZATION'"))
        if "status" not in fsm_cols:
            conn.execute(text("ALTER TABLE faculty_subject_mappings ADD COLUMN status VARCHAR(30) DEFAULT 'SUGGESTED'"))
        if "suggestion_reason" not in fsm_cols:
            conn.execute(text("ALTER TABLE faculty_subject_mappings ADD COLUMN suggestion_reason VARCHAR(500)"))
        if "times_handled" not in fsm_cols:
            conn.execute(text("ALTER TABLE faculty_subject_mappings ADD COLUMN times_handled INTEGER DEFAULT 0"))
        if "is_confirmed" not in fsm_cols:
            conn.execute(text("ALTER TABLE faculty_subject_mappings ADD COLUMN is_confirmed BOOLEAN DEFAULT 0"))
        if "confirmed_by" not in fsm_cols:
            conn.execute(text("ALTER TABLE faculty_subject_mappings ADD COLUMN confirmed_by VARCHAR(100)"))
        if "confirmed_at" not in fsm_cols:
            conn.execute(text("ALTER TABLE faculty_subject_mappings ADD COLUMN confirmed_at DATETIME"))

        conn.commit()

    # 3. Seed Department Mappings
    default_mappings = [
        {"short_code": "MCA", "full_name": "Master of Computer Applications"},
        {"short_code": "CSE", "full_name": "Computer Science & Engineering"},
        {"short_code": "ISE", "full_name": "Information Science & Engineering"},
        {"short_code": "AIML", "full_name": "Artificial Intelligence & Machine Learning"},
        {"short_code": "CSDS", "full_name": "CSE (Data Science)"}
    ]
    for m in default_mappings:
        existing = db.query(DepartmentMapping).filter_by(short_code=m["short_code"]).first()
        if not existing:
            db.add(DepartmentMapping(short_code=m["short_code"], full_name=m["full_name"]))

    # 4. Seed External Institutions (11 default institutions, enabled by default)
    for inst_name in DEFAULT_EXTERNAL_INSTITUTIONS:
        existing_inst = db.query(ExternalInstitution).filter_by(name=inst_name).first()
        if not existing_inst:
            db.add(ExternalInstitution(name=inst_name, is_allowed=True))

    db.commit()

    # 5. Migrate any existing JSON faculty IDs in allocations into relational AllocationSetter table
    allocations = db.query(Allocation).all()
    for a in allocations:
        existing_setters = db.query(AllocationSetter).filter_by(allocation_id=a.id).count()
        if existing_setters == 0:
            order = 1
            # Internal setters
            try:
                int_ids = json.loads(a.internal_faculty_ids or "[]")
                for fid in int_ids:
                    db.add(AllocationSetter(
                        allocation_id=a.id,
                        faculty_id=fid,
                        faculty_type="internal",
                        status="Approved" if a.status in ("Confirmed", "Approved") else "Nominated",
                        assigned_order=order
                    ))
                    order += 1
            except Exception:
                int_ids = []

            # External setters
            try:
                ext_ids = json.loads(a.external_faculty_ids or "[]")
                for fid in ext_ids:
                    db.add(AllocationSetter(
                        allocation_id=a.id,
                        faculty_id=fid,
                        faculty_type="external",
                        status="Approved" if a.status in ("Confirmed", "Approved") else "Nominated",
                        assigned_order=order
                    ))
                    order += 1
            except Exception:
                ext_ids = []

            # Synchronize workload ledger for confirmed allocations
            if a.status in ("Confirmed", "Approved"):
                for fid in int_ids + ext_ids:
                    db.add(WorkloadLedger(
                        faculty_id=fid,
                        academic_year=a.academic_year or "2025-26",
                        semester=a.semester or "I",
                        allocation_id=a.id,
                        entry_type="COMMITTED",
                        delta=1,
                        remarks=f"Allocation confirmed: {a.reference_number}"
                    ))

    db.commit()


def resolve_department_names(db: Session, dept_query: str) -> list[str]:
    """
    Given a department query like 'MCA' or 'Master of Computer Applications',
    returns all canonical variants (e.g. ['MCA', 'Master of Computer Applications'])
    using the DepartmentMapping table.
    """
    if not dept_query:
        return []
    clean = dept_query.strip()
    mapping = db.query(DepartmentMapping).filter(
        (DepartmentMapping.short_code.ilike(clean)) |
        (DepartmentMapping.full_name.ilike(clean))
    ).first()

    if mapping:
        return [mapping.short_code, mapping.full_name]
    return [clean]


def get_faculty_workload_summary(db: Session, faculty_id: int, academic_year: str, semester: str | None = None) -> dict:
    """
    Returns committed and reserved workload from WorkloadLedger for a given exam cycle.
    Workload limit is evaluated per faculty per semester exam cycle.
    """
    query = db.query(WorkloadLedger).filter(
        WorkloadLedger.faculty_id == faculty_id,
        WorkloadLedger.academic_year == academic_year
    )
    if semester:
        query = query.filter(WorkloadLedger.semester == semester)

    entries = query.all()
    committed = sum(e.delta for e in entries if e.entry_type == "COMMITTED")
    reserved = sum(e.delta for e in entries if e.entry_type == "RESERVED")
    return {
        "committed": max(0, committed),
        "reserved": max(0, reserved),
        "total": max(0, committed + reserved)
    }


def record_workload_entry(
    db: Session,
    faculty_id: int,
    academic_year: str,
    semester: str,
    allocation_id: int | None,
    entry_type: str,
    delta: int = 1,
    remarks: str | None = None
) -> WorkloadLedger:
    """Appends an immutable entry to the workload ledger."""
    entry = WorkloadLedger(
        faculty_id=faculty_id,
        academic_year=academic_year,
        semester=semester,
        allocation_id=allocation_id,
        entry_type=entry_type,
        delta=delta,
        remarks=remarks
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def is_external_institution_allowed(db: Session, institution_name: str) -> bool:
    """Verifies whether an external institution is on the active whitelist."""
    if not institution_name:
        return False
    clean = institution_name.strip()
    inst = db.query(ExternalInstitution).filter(
        (ExternalInstitution.name.ilike(clean)) |
        (ExternalInstitution.name.ilike(f"%{clean}%"))
    ).first()
    if inst:
        return bool(inst.is_allowed)
    return False


def get_allowed_external_institutions(db: Session) -> list[str]:
    """Returns list of all currently whitelisted external institutions."""
    rows = db.query(ExternalInstitution.name).filter_by(is_allowed=True).order_by(ExternalInstitution.name).all()
    return [r[0] for r in rows]
