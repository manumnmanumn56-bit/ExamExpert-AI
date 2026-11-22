"""
ExamExpert AI — Deterministic Faculty-Subject Matching & Ranking Engine
SJB Institute of Technology | Office of Controller of Examinations

Implements Module 10 (Slice 2):
1. Strict Deterministic Multi-Level Ranking (No arbitrary 0-100 scores)
   Hierarchy:
   1. Exact subject experience (EXACT_EXPERIENCE confirmed mapping)
   2. Specialization (SPECIALIZATION confirmed mapping)
   3. Related expertise (RELATED confirmed mapping)
   4. Lower combined workload (committed + reserved from workload_ledger)
   5. Avoid repeating the same subject (fresh appointment ranks ahead of repeat setter)
   6. Higher relevant-subject experience (times handled)
   7. Higher total teaching experience (experience_years)
   8. Previous paper-setting experience if recorded (assumed_times_handled)
   9. Faculty ID as final deterministic tie-breaker (ascending)
2. Only ELIGIBLE faculty (from Module 9 policy engine) are ranked.
3. PENDING VERIFICATION and NOT ELIGIBLE faculty are segregated with reasons, never recommended.
4. Excludes faculty from disabled external institutions.
5. Separate internal and external candidate pools with shortage reporting.
"""
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..models import (
    Faculty, Subject, EligibilityRules, Allocation, AllocationSetter,
    FacultySubjectMapping, ExternalInstitution, WorkloadLedger
)
from .eligibility import (
    get_confirmed_policy,
    evaluate_faculty_eligibility,
    get_faculty_workload,
    is_phd_completed
)


def get_mapping_tier(mapping_type: Optional[str]) -> int:
    """
    Returns numeric priority tier for confirmed mappings:
    1: EXACT_EXPERIENCE
    2: SPECIALIZATION
    3: RELATED
    4: Unspecified / None
    """
    if not mapping_type:
        return 4
    mt = mapping_type.upper()
    if mt == "EXACT_EXPERIENCE":
        return 1
    elif mt == "SPECIALIZATION":
        return 2
    elif mt == "RELATED":
        return 3
    return 4


def has_set_subject_before(db: Session, faculty_id: int, subject_id: int) -> bool:
    """
    Checks if a faculty member was previously confirmed as a question paper setter for this subject.
    """
    # 1. Check relational AllocationSetter table
    count = db.query(AllocationSetter).join(Allocation).filter(
        AllocationSetter.faculty_id == faculty_id,
        Allocation.subject_id == subject_id,
        Allocation.status.in_(["Approved", "Confirmed"])
    ).count()
    if count > 0:
        return True

    # 2. Check legacy confirmed allocations
    confirmed_allocs = db.query(Allocation).filter(
        Allocation.subject_id == subject_id,
        Allocation.status.in_(["Approved", "Confirmed"])
    ).all()
    import json
    for a in confirmed_allocs:
        try:
            int_ids = json.loads(a.internal_faculty_ids or "[]")
            ext_ids = json.loads(a.external_faculty_ids or "[]")
            if faculty_id in int_ids or faculty_id in ext_ids:
                return True
        except Exception:
            pass

    return False


def match_and_rank_faculty(
    db: Session,
    subject: Subject,
    faculty_type: str,
    academic_year: Optional[str] = None,
    policy: Optional[EligibilityRules] = None
) -> Dict[str, Any]:
    """
    Evaluates and deterministically ranks all faculty candidates of a given type for a subject.
    Order:
    1. Exact subject experience (EXACT_EXPERIENCE confirmed mapping)
    2. Specialization (SPECIALIZATION confirmed mapping)
    3. Related expertise (RELATED confirmed mapping)
    4. Lower combined workload (committed + reserved from ledger)
    5. Avoid repeating the same subject
    6. Higher relevant-subject experience
    7. Higher total experience
    8. Previous paper-setting experience
    9. Faculty ID as final tie-breaker
    """
    if policy is None:
        policy = get_confirmed_policy(db)

    active_ay = academic_year or (policy.active_academic_year if policy else "2025-26")

    # Fetch whitelist if external
    disabled_institutions = set()
    if faculty_type == "external":
        disabled_rows = db.query(ExternalInstitution).filter_by(is_allowed=False).all()
        disabled_institutions = {i.name.strip().lower() for i in disabled_rows if i.name}

    roster = db.query(Faculty).filter_by(faculty_type=faculty_type).all()

    eligible_pool: List[Dict[str, Any]] = []
    not_eligible_pool: List[Dict[str, Any]] = []
    pending_pool: List[Dict[str, Any]] = []
    excluded_inst_count = 0

    for fac in roster:
        # Check institution exclusion for external faculty
        if faculty_type == "external" and fac.institution:
            if fac.institution.strip().lower() in disabled_institutions:
                excluded_inst_count += 1
                not_eligible_pool.append({
                    "faculty_id": fac.id,
                    "name": fac.name,
                    "faculty_type": fac.faculty_type,
                    "institution": fac.institution,
                    "overall_status": "NOT ELIGIBLE",
                    "reason": f"External institution '{fac.institution}' is disabled on the institutional whitelist."
                })
                continue

        # Evaluate candidate against Module 9 policy engine
        eval_res = evaluate_faculty_eligibility(
            db=db,
            faculty=fac,
            subject=subject,
            policy=policy,
            academic_year=active_ay
        )

        overall = eval_res["overall_status"]
        if overall == "ELIGIBLE":
            # Retrieve confirmed mapping
            mapping = db.query(FacultySubjectMapping).filter(
                FacultySubjectMapping.faculty_id == fac.id,
                FacultySubjectMapping.subject_id == subject.id,
                or_(
                    FacultySubjectMapping.status == "CONFIRMED",
                    FacultySubjectMapping.is_confirmed == True
                )
            ).first()

            mapping_type = mapping.mapping_type if mapping else "RELATED"
            tier = get_mapping_tier(mapping_type)

            # Combined workload from ledger (committed + reserved)
            workload = get_faculty_workload(db, fac.id, active_ay)
            combined_load = workload["total_active"]
            committed_load = workload["committed"]
            reserved_load = workload["reserved"]

            # Avoid repeating subject
            repeated = 1 if has_set_subject_before(db, fac.id, subject.id) else 0

            # Relevant handling count
            relevant_handling = mapping.times_handled if (mapping and mapping.times_handled is not None) else 0

            # Total experience
            total_exp = float(fac.experience_years or 0.0)

            # Previous QP setting experience
            prev_qp_exp = int(fac.assumed_times_handled or 0)

            # Deterministic sorting tuple:
            # 1. Tier (1=EXACT, 2=SPECIALIZATION, 3=RELATED)
            # 2. Combined workload asc
            # 3. Repeated subject asc (0 before 1)
            # 4. Relevant course handling desc
            # 5. Total experience desc
            # 6. Previous QP assignments desc
            # 7. Faculty ID asc (final tie-breaker)
            sort_tuple = (
                tier,
                combined_load,
                repeated,
                -relevant_handling,
                -total_exp,
                -prev_qp_exp,
                fac.id
            )

            tier_labels = {
                1: f"Tier 1: Exact Course Experience ({mapping_type})",
                2: f"Tier 2: Domain Specialization ({mapping_type})",
                3: f"Tier 3: Related Subject Expertise ({mapping_type})"
            }

            candidate_record = {
                "faculty_id": fac.id,
                "db_serial_no": fac.db_serial_no,
                "employee_id": fac.employee_id,
                "name": fac.name,
                "faculty_name": fac.name,
                "designation": fac.designation,
                "department": fac.department,
                "institution": fac.institution,
                "faculty_type": fac.faculty_type,
                "qualification": fac.qualification,
                "experience_years": fac.experience_years,
                "has_completed_phd": is_phd_completed(fac.qualification),
                "mapping_type": mapping_type,
                "mapping_tier": tier,
                "combined_workload": combined_load,
                "committed_workload": committed_load,
                "reserved_workload": reserved_load,
                "capacity": eval_res["capacity"],
                "repeated_subject": bool(repeated),
                "relevant_handled_count": relevant_handling,
                "course_handled_count": relevant_handling,
                "course_handled_display": f"{relevant_handling} times" if relevant_handling else "0 times",
                "assumed_paper_setting_count": prev_qp_exp,
                "is_eligible": True,
                "is_available": True,
                "meets_min_handled": True,
                "eligibility_status": "Qualified",
                "email": fac.email,
                "mobile": fac.mobile,
                "criteria_reasons": {
                    "tier": tier_labels.get(tier, f"Tier {tier}: {mapping_type}"),
                    "workload": f"{combined_load}/{eval_res['capacity']} active workload ({committed_load} committed, {reserved_load} reserved)",
                    "subject_repetition": "First-time setter for this subject" if not repeated else "Previously appointed for this subject",
                    "relevant_handling": f"{relevant_handling} times handled course",
                    "total_experience": f"{total_exp:.1f}y teaching experience",
                    "qp_setting_history": f"{prev_qp_exp} prior QP setting assignments",
                    "tie_breaker": f"Deterministic Faculty ID #{fac.id}"
                },
                "_sort_tuple": sort_tuple
            }
            eligible_pool.append(candidate_record)

        elif overall == "PENDING VERIFICATION":
            pending_pool.append({
                "faculty_id": fac.id,
                "name": fac.name,
                "faculty_name": fac.name,
                "faculty_type": fac.faculty_type,
                "department": fac.department,
                "institution": fac.institution,
                "designation": fac.designation,
                "qualification": fac.qualification,
                "overall_status": "PENDING VERIFICATION",
                "reason": eval_res["summary_reason"]
            })
        else:
            not_eligible_pool.append({
                "faculty_id": fac.id,
                "name": fac.name,
                "faculty_name": fac.name,
                "faculty_type": fac.faculty_type,
                "department": fac.department,
                "institution": fac.institution,
                "designation": fac.designation,
                "qualification": fac.qualification,
                "overall_status": "NOT ELIGIBLE",
                "reason": eval_res["summary_reason"]
            })

    # Sort eligible pool deterministically
    eligible_pool.sort(key=lambda c: c["_sort_tuple"])

    # Assign deterministic 1-based ranks and clean internal sorting tuple
    for idx, c in enumerate(eligible_pool, start=1):
        c["rank"] = idx
        c.pop("_sort_tuple", None)

    return {
        "faculty_type": faculty_type,
        "recommended": eligible_pool,
        "not_eligible": not_eligible_pool,
        "pending_verification": pending_pool,
        "counts": {
            "eligible": len(eligible_pool),
            "not_eligible": len(not_eligible_pool),
            "pending_verification": len(pending_pool),
            "excluded_institutions": excluded_inst_count,
            "total_evaluated": len(roster)
        }
    }


def rank_candidates(
    db: Session,
    subject_title: str,
    subject_code: str,
    min_handled: int,
    faculty_type: str,
    rules: Optional[EligibilityRules] = None,
    allocation_counts: Optional[dict] = None,
    subject_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Backward-compatible ranking interface returning deterministically ordered eligible faculty.
    Strictly removes arbitrary 0-100 scores.
    """
    subject = None
    if subject_id:
        subject = db.query(Subject).filter_by(id=subject_id).first()
    if not subject:
        subject = db.query(Subject).filter(
            or_(Subject.course_code == subject_code, Subject.title == subject_title)
        ).first()

    if not subject:
        return []

    result = match_and_rank_faculty(
        db=db,
        subject=subject,
        faculty_type=faculty_type,
        policy=rules
    )

    return result["recommended"]
