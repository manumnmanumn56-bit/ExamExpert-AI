"""
ExamExpert AI — Eligibility Policy & Candidate Evaluation Engine
SJB Institute of Technology | Office of Controller of Examinations

Implements Module 9 Minimal Slice 1:
1. Dynamic policy retrieval (only CONFIRMED policies are active)
2. Append-only Workload Ledger calculation (committed = approved, reserved = pending HOD approval)
3. Faculty-subject eligibility evaluation returning ELIGIBLE, NOT ELIGIBLE, PENDING VERIFICATION
4. Granular per-rule evaluation with transparent audit reasons:
   - Experience & PhD completion (pursuing Ph.D is NOT completed)
   - Permitted designations (Assistant Professor and above)
   - Confirmed expertise mapping (status == 'CONFIRMED')
   - Faculty availability
   - Workload within capacity (internal vs external limits)
   - External institution whitelist verification
"""
import json
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..models import (
    Faculty, Subject, EligibilityRules, WorkloadLedger,
    FacultySubjectMapping, ExternalInstitution
)

DEFAULT_ALLOWED_DESIGNATIONS = [
    "Assistant Professor",
    "Senior Assistant Professor",
    "Associate Professor",
    "Professor",
    "Professor & HOD",
    "Dean",
    "Director"
]


def get_confirmed_policy(db: Session) -> Optional[EligibilityRules]:
    """
    Retrieves the active institutional eligibility policy.
    Strict Rule: Only policies with status == 'CONFIRMED' are active.
    DRAFT policies are never used for candidate evaluation.
    """
    return db.query(EligibilityRules).filter(
        EligibilityRules.status == "CONFIRMED"
    ).order_by(EligibilityRules.id.desc()).first()


def get_faculty_workload(
    db: Session,
    faculty_id: int,
    academic_year: Optional[str] = None
) -> Dict[str, Any]:
    """
    Computes faculty workload strictly from the append-only WorkloadLedger:
    - committed: confirmed/approved allocations
    - reserved: pending HOD approval allocations
    - total: committed + reserved
    """
    query = db.query(WorkloadLedger).filter(WorkloadLedger.faculty_id == faculty_id)
    if academic_year:
        query = query.filter(WorkloadLedger.academic_year == academic_year)

    rows = query.all()
    committed = 0
    reserved = 0

    for r in rows:
        d = r.delta or 1
        etype = (r.entry_type or "").upper()
        if etype == "COMMITTED":
            committed += d
        elif etype == "RESERVED":
            reserved += d
        elif etype == "RELEASED":
            committed -= d

    committed = max(0, committed)
    reserved = max(0, reserved)

    return {
        "faculty_id": faculty_id,
        "academic_year": academic_year,
        "committed": committed,
        "reserved": reserved,
        "total_active": committed + reserved,
        "entries_count": len(rows)
    }


def is_phd_completed(qualification: Optional[str]) -> bool:
    """
    Checks if a faculty member has completed a Doctoral degree.
    Strict Rule: 'Pursuing', 'registered', 'ongoing' Ph.D is NOT completed.
    """
    if not qualification:
        return False
    q = qualification.upper()
    # Check if pursuing / registered
    is_pursuing = any(term in q for term in ["PURSUING", "PERSUING", "REGISTERED", "ONGOING", "ENROLLED", "CANDIDATE"])
    if is_pursuing:
        return False
    # Check for doctoral keywords
    return any(term in q for term in ["PH.D", "PHD", "DOCTORATE", "D.PHIL"])


def evaluate_faculty_eligibility(
    db: Session,
    faculty: Faculty,
    subject: Subject,
    policy: Optional[EligibilityRules] = None,
    academic_year: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluates faculty eligibility for a specific subject against the active policy.
    Returns:
    - overall_status: 'ELIGIBLE' | 'NOT ELIGIBLE' | 'PENDING VERIFICATION'
    - is_recommendable: True only if 'ELIGIBLE' (Pending faculty are NEVER recommended)
    - rules: Granular per-rule audit trail with PASS, FAIL, or PENDING_VERIFICATION
    """
    if policy is None:
        policy = get_confirmed_policy(db)

    if not policy or policy.status != "CONFIRMED":
        return {
            "faculty_id": faculty.id,
            "faculty_name": faculty.name,
            "faculty_type": faculty.faculty_type,
            "subject_id": subject.id,
            "course_code": subject.course_code,
            "overall_status": "PENDING VERIFICATION",
            "is_recommendable": False,
            "summary_reason": "No CONFIRMED institutional eligibility policy is active in the database.",
            "rules": {}
        }

    active_ay = academic_year or policy.active_academic_year or "2025-26"
    rules_breakdown: Dict[str, Dict[str, Any]] = {}

    # ─── 1. Designation Rule ──────────────────────────────────────────────────
    allowed_desigs = DEFAULT_ALLOWED_DESIGNATIONS
    if policy.allowed_designations:
        try:
            parsed = json.loads(policy.allowed_designations)
            if isinstance(parsed, list) and parsed:
                allowed_desigs = parsed
        except Exception:
            pass

    desig = (faculty.designation or "").strip()
    if not desig:
        rules_breakdown["designation"] = {
            "status": "PENDING_VERIFICATION",
            "reason": "Faculty designation is missing from institutional profile."
        }
    else:
        desig_lower = desig.lower()
        matched = any(
            d.lower() == desig_lower or d.lower() in desig_lower or desig_lower in d.lower()
            for d in allowed_desigs
        )
        if matched:
            rules_breakdown["designation"] = {
                "status": "PASS",
                "reason": f"Designation '{desig}' is authorized under active policy."
            }
        else:
            rules_breakdown["designation"] = {
                "status": "FAIL",
                "reason": f"Designation '{desig}' is not authorized (requires Assistant Professor or above)."
            }

    # ─── 2. Qualification & Experience Rule ───────────────────────────────────
    phd_done = is_phd_completed(faculty.qualification)
    min_exp_required = float(policy.min_experience_phd if phd_done else policy.min_experience)

    if faculty.experience_years is None:
        rules_breakdown["experience"] = {
            "status": "PENDING_VERIFICATION",
            "reason": "Teaching experience is not recorded in faculty profile; certificate verification required."
        }
    elif faculty.experience_years >= min_exp_required:
        phd_tag = "with completed Ph.D" if phd_done else "standard minimum"
        rules_breakdown["experience"] = {
            "status": "PASS",
            "reason": f"Meets experience requirement: {faculty.experience_years:.1f}y (>= {min_exp_required:.1f}y required {phd_tag})."
        }
    else:
        phd_tag = "with completed Ph.D" if phd_done else "standard minimum"
        rules_breakdown["experience"] = {
            "status": "FAIL",
            "reason": f"Insufficient experience: {faculty.experience_years:.1f}y (< {min_exp_required:.1f}y required {phd_tag})."
        }

    rules_breakdown["phd_completion"] = {
        "status": "INFO",
        "has_completed_phd": phd_done,
        "qualification": faculty.qualification or "Not Recorded",
        "reason": "Completed Doctoral degree verified." if phd_done else "Doctorate not completed or in-progress."
    }

    # ─── 3. Confirmed Expertise Mapping Rule ──────────────────────────────────
    mapping = db.query(FacultySubjectMapping).filter(
        FacultySubjectMapping.faculty_id == faculty.id,
        FacultySubjectMapping.subject_id == subject.id
    ).first()

    if mapping and (mapping.status == "CONFIRMED" or mapping.is_confirmed):
        rules_breakdown["expertise_mapping"] = {
            "status": "PASS",
            "mapping_type": mapping.mapping_type,
            "reason": f"Confirmed {mapping.mapping_type} expertise mapping verified."
        }
    elif mapping and mapping.status == "SUGGESTED":
        rules_breakdown["expertise_mapping"] = {
            "status": "FAIL",
            "mapping_type": mapping.mapping_type,
            "reason": f"Expertise mapping for {subject.course_code} is only SUGGESTED; Admin confirmation required before eligibility."
        }
    else:
        rules_breakdown["expertise_mapping"] = {
            "status": "FAIL",
            "mapping_type": None,
            "reason": f"No confirmed expertise mapping found for subject {subject.course_code} ({subject.title})."
        }

    # ─── 4. Availability Rule ─────────────────────────────────────────────────
    is_avail = getattr(faculty, "is_available", True)
    if is_avail is False or is_avail == 0:
        rules_breakdown["availability"] = {
            "status": "FAIL",
            "reason": "Faculty member is marked unavailable for question paper setting in this cycle."
        }
    else:
        rules_breakdown["availability"] = {
            "status": "PASS",
            "reason": "Faculty member is available."
        }

    # ─── 5. Workload Capacity Rule ────────────────────────────────────────────
    capacity = int(policy.internal_capacity if faculty.faculty_type == "internal" else policy.external_capacity)
    workload = get_faculty_workload(db, faculty.id, active_ay)
    active_load = workload["total_active"]

    if active_load >= capacity:
        rules_breakdown["workload"] = {
            "status": "FAIL",
            "current_workload": active_load,
            "capacity": capacity,
            "reason": f"Workload capacity reached: {active_load}/{capacity} papers allocated/reserved in cycle {active_ay}."
        }
    else:
        rules_breakdown["workload"] = {
            "status": "PASS",
            "current_workload": active_load,
            "capacity": capacity,
            "reason": f"Workload within limit: {active_load}/{capacity} papers allocated/reserved in cycle {active_ay}."
        }

    # ─── 6. External Institution Whitelist Rule ───────────────────────────────
    if faculty.faculty_type == "external":
        inst_name = (faculty.institution or "").strip()
        if not inst_name:
            rules_breakdown["institution_whitelist"] = {
                "status": "PENDING_VERIFICATION",
                "reason": "External institution name not recorded in faculty profile."
            }
        else:
            inst = db.query(ExternalInstitution).filter(
                ExternalInstitution.name.ilike(inst_name)
            ).first()
            if inst and not inst.is_allowed:
                rules_breakdown["institution_whitelist"] = {
                    "status": "FAIL",
                    "reason": f"External institution '{inst_name}' is not approved on the institutional whitelist."
                }
            else:
                rules_breakdown["institution_whitelist"] = {
                    "status": "PASS",
                    "reason": f"External institution '{inst_name}' is whitelisted."
                }
    else:
        rules_breakdown["institution_whitelist"] = {
            "status": "PASS",
            "reason": "Internal SJBIT faculty member."
        }

    # ─── Overall Status Rollup ────────────────────────────────────────────────
    has_pending = any(r.get("status") == "PENDING_VERIFICATION" for r in rules_breakdown.values())
    has_fail = any(r.get("status") == "FAIL" for r in rules_breakdown.values())

    fail_reasons = [r["reason"] for r in rules_breakdown.values() if r.get("status") == "FAIL"]
    pending_reasons = [r["reason"] for r in rules_breakdown.values() if r.get("status") == "PENDING_VERIFICATION"]

    if has_pending:
        overall_status = "PENDING VERIFICATION"
        is_recommendable = False
        summary_reason = "; ".join(pending_reasons + fail_reasons)
    elif has_fail:
        overall_status = "NOT ELIGIBLE"
        is_recommendable = False
        summary_reason = "; ".join(fail_reasons)
    else:
        overall_status = "ELIGIBLE"
        is_recommendable = True
        summary_reason = "Satisfies all institutional eligibility rules and workload limits."

    return {
        "faculty_id": faculty.id,
        "faculty_name": faculty.name,
        "faculty_type": faculty.faculty_type,
        "department": faculty.department,
        "institution": faculty.institution,
        "designation": faculty.designation,
        "qualification": faculty.qualification,
        "experience_years": faculty.experience_years,
        "has_completed_phd": phd_done,
        "subject_id": subject.id,
        "course_code": subject.course_code,
        "subject_title": subject.title,
        "overall_status": overall_status,
        "is_recommendable": is_recommendable,
        "current_workload": active_load,
        "capacity": capacity,
        "rules": rules_breakdown,
        "summary_reason": summary_reason
    }
