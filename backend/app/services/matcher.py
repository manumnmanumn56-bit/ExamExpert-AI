"""
ExamExpert AI — Intelligent Faculty Eligibility & Explainable Matching Engine
SJB Institute of Technology | Office of Controller of Examinations

Deterministic, rule-based matching between curriculum subjects and faculty members.
Evaluates statutory eligibility, subject expertise, verified course-handling history,
designation seniority, and teaching experience.
"""
import re
from sqlalchemy.orm import Session
from ..models import (
    Faculty, FacultyCourseHistory, FacultyExpertise, EligibilityRules,
    FacultySubjectMapping, Subject
)

def _normalize(text: str) -> str:
    """Lowercase, strip non-alphanumeric characters, collapse whitespace."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _word_overlap(a: str, b: str) -> float:
    """Calculates Jaccard overlap fraction between word sets."""
    words_a = set(_normalize(a).split())
    words_b = set(_normalize(b).split())
    # Remove insignificant stopwords
    stopwords = {"and", "in", "for", "with", "the", "of", "to", "an", "a", "lab", "laboratory"}
    words_a -= stopwords
    words_b -= stopwords
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a)


def match_course_title(subject_title: str, candidate_title: str) -> float:
    """
    Returns similarity score (0.0 to 1.0) between a syllabus subject and a candidate course title.
    Employs exact phrase matching, normalized substring, and word overlap.
    """
    norm_subj = _normalize(subject_title)
    norm_cand = _normalize(candidate_title)

    if not norm_subj or not norm_cand:
        return 0.0

    # 1. Exact match
    if norm_subj == norm_cand:
        return 1.0

    # 2. Substring match
    if norm_subj in norm_cand or norm_cand in norm_subj:
        return 0.95

    # 3. Word overlap
    overlap = _word_overlap(norm_subj, norm_cand)
    if overlap >= 0.6:
        return overlap

    return 0.0


# ─── Course Handling History Lookup ────────────────────────────────────────────

def get_verified_course_handling(
    faculty: Faculty,
    subject_title: str,
    confirmed_mapping: FacultySubjectMapping | None = None
) -> tuple[int | None, str]:
    """
    Extracts the subject-specific verified times handled for this exact subject.
    For internal faculty: queries parsed FacultyCourseHistory records or confirmed database mapping.
    For external faculty: returns (None, 'unverified') per Section 2.2 and Section 10 guidelines,
    as external dataset only contains assumed overall question paper setting counts.
    """
    if faculty.faculty_type == "external":
        # External dataset does not contain verified subject-specific course teaching history
        return None, "unverified"

    # Confirmed mapping can supply verified teaching history if EXACT_EXPERIENCE
    if confirmed_mapping and confirmed_mapping.status == "CONFIRMED" and confirmed_mapping.mapping_type == "EXACT_EXPERIENCE":
        if confirmed_mapping.times_handled and confirmed_mapping.times_handled > 0:
            return confirmed_mapping.times_handled, "exact"

    best_count = None
    best_score = 0.0

    for ch in faculty.course_history:
        score = match_course_title(subject_title, ch.course_title or "")
        if score >= 0.70 and score > best_score:
            best_score = score
            best_count = ch.times_handled

    if best_count is not None:
        source = "exact" if best_score >= 0.90 else "overlap"
        return best_count, source

    return None, "none"


# ─── Statutory Eligibility Check ───────────────────────────────────────────────

def check_eligibility(faculty: Faculty, rules: EligibilityRules) -> dict:
    """
    Determines statutory eligibility based on institutional VTU/Autonomous rules:
    - Minimum 10 years of total teaching experience, OR
    - Ph.D holder with minimum 5 years teaching experience.
    Preserves original dataset status provenance.
    """
    raw_status = (faculty.eligibility_status or "").strip()
    qual = (faculty.qualification or "").lower()
    has_phd = ("ph.d" in qual) or ("phd" in qual)
    exp = faculty.experience_years

    # Explicitly Not Qualified in source dataset
    if "not qualified" in raw_status.lower() or "below threshold" in raw_status.lower():
        return {
            "is_eligible": False,
            "status": "Not Qualified",
            "reason": f"Marked 'Not Qualified' in official roster (Experience: {exp} yrs < threshold)."
        }

    # External faculty with undisclosed experience
    if exp is None or "cannot verify" in raw_status.lower() or "not disclosed" in raw_status.lower():
        return {
            "is_eligible": False,
            "status": "Cannot Verify",
            "reason": "Teaching experience not publicly disclosed in university roster. Physical service-certificate verification required before appointment."
        }

    # Statutory Threshold Check
    min_exp = rules.min_experience_years if rules else 10.0
    phd_min = rules.phd_fasttrack_min_exp if rules else 5.0

    if exp >= min_exp:
        return {
            "is_eligible": True,
            "status": "Qualified",
            "reason": f"Meets statutory threshold: {exp:.1f} yrs teaching experience (>= {min_exp:.0f} yrs required)."
        }

    if has_phd and exp >= phd_min:
        return {
            "is_eligible": True,
            "status": "Qualified",
            "reason": f"Doctoral fast-track approved: Ph.D + {exp:.1f} yrs teaching experience (>= {phd_min:.0f} yrs required)."
        }

    return {
        "is_eligible": False,
        "status": "Not Qualified",
        "reason": f"Experience of {exp:.1f} yrs is below statutory threshold of {min_exp:.0f} yrs."
    }


# ─── Transparent Suitability Scoring (0 to 100) ──────────────────────────────

def _score_designation(desig: str | None) -> int:
    d = (desig or "").upper()
    if any(k in d for k in ["HOD", "HEAD", "DIRECTOR", "DEAN"]):
        return 15
    if "PROFESSOR" in d and "ASSOCIATE" not in d and "ASST" not in d and "ASSISTANT" not in d:
        return 13
    if "ASSOCIATE PROFESSOR" in d or "ASSOC. PROFESSOR" in d or "ASSOCIATE" in d:
        return 11
    if "ASST" in d or "ASSISTANT" in d:
        return 8
    return 5


def _score_experience(exp: float | None) -> int:
    if exp is None:
        return 0
    if exp >= 25:
        return 10
    if exp >= 20:
        return 8
    if exp >= 15:
        return 6
    if exp >= 10:
        return 4
    return 2


def _score_handling_count(count: int | None, faculty_type: str) -> int:
    """
    Score verified subject handling experience (0 to 25 points).
    Internal faculty get points based on actual verified times taught.
    External faculty receive a standard baseline for general domain fit.
    """
    if count is None:
        return 5 if faculty_type == "external" else 0
    if count >= 15:
        return 25
    if count >= 10:
        return 22
    if count >= 6:
        return 18
    if count >= 3:
        return 14
    if count >= 1:
        return 10
    return 0


def compute_suitability(
    faculty: Faculty,
    subject_title: str,
    subject_code: str,
    min_handled: int,
    rules: EligibilityRules,
    existing_allocation_count: int = 0,
    confirmed_mapping: FacultySubjectMapping | None = None
) -> dict:
    """
    Computes a transparent, explainable 100-point suitability score:
    - Subject Expertise & Domain Fit: 40 points (database-backed confirmed mapping)
    - Verified Course Handling: 25 points
    - Designation & Academic Seniority: 15 points
    - Overall Teaching Experience: 10 points
    - Statutory Eligibility Gate: 10 points
    """
    elig = check_eligibility(faculty, rules)

    # 1. Domain Fit (0 to 40)
    # Database-backed confirmed expertise mapping replaces static ALIAS_MAP
    norm_subj = _normalize(subject_title)
    norm_code = _normalize(subject_code)
    expertise_corpus = (faculty.expertise_text or "") + " " + " ".join([t.tag for t in faculty.expertise_tags])
    norm_corpus = _normalize(expertise_corpus)

    domain_score = 0
    if confirmed_mapping and confirmed_mapping.status == "CONFIRMED":
        if confirmed_mapping.mapping_type == "EXACT_EXPERIENCE":
            domain_score = 40
        elif confirmed_mapping.mapping_type == "SPECIALIZATION":
            domain_score = 35
        elif confirmed_mapping.mapping_type == "RELATED":
            domain_score = 30
        else:
            domain_score = 30
    elif norm_subj in norm_corpus or (norm_code and norm_code in norm_corpus):
        domain_score = 35
    else:
        overlap = _word_overlap(norm_subj, norm_corpus)
        domain_score = round(min(25, overlap * 35))

    # 2. Course Handling History (0 to 25)
    verified_count, source = get_verified_course_handling(faculty, subject_title, confirmed_mapping)
    handling_score = _score_handling_count(verified_count, faculty.faculty_type)

    # 3. Designation Seniority (0 to 15)
    seniority_score = _score_designation(faculty.designation)

    # 4. Teaching Experience (0 to 10)
    exp_score = _score_experience(faculty.experience_years)

    # 5. Statutory Gate (0 or 10)
    elig_gate_score = 10 if elig["is_eligible"] else 0

    total_score = domain_score + handling_score + seniority_score + exp_score + elig_gate_score

    # Handling threshold verification
    if faculty.faculty_type == "internal":
        meets_handled = (verified_count is not None and verified_count >= min_handled)
        course_handled_display = f"{verified_count} times" if verified_count is not None else "Not Recorded"
    else:
        # External faculty: preserve provenance; do not invent count
        meets_handled = True if elig["is_eligible"] else False
        course_handled_display = "Course History Verification Required"

    # Over-allocation check
    max_papers = rules.max_papers_per_faculty if rules else 2
    over_allocated = (existing_allocation_count >= max_papers)

    return {
        "faculty_id": faculty.id,
        "db_serial_no": faculty.db_serial_no,
        "employee_id": faculty.employee_id,
        "faculty_name": faculty.name,
        "designation": faculty.designation,
        "department": faculty.department,
        "institution": faculty.institution,
        "faculty_type": faculty.faculty_type,
        "qualification": faculty.qualification,
        "experience_years": faculty.experience_years,
        "eligibility_status": elig["status"],
        "is_eligible": elig["is_eligible"],
        "eligibility_reason": elig["reason"],
        "email": faculty.email,
        "mobile": faculty.mobile,
        "expertise_text": faculty.expertise_text,
        "course_handled_count": verified_count,
        "course_handled_source": source,
        "course_handled_display": course_handled_display,
        "assumed_paper_setting_count": faculty.assumed_times_handled,
        "meets_min_handled": meets_handled,
        "is_available": faculty.is_available and not over_allocated,
        "over_allocated": over_allocated,
        "existing_allocation_count": existing_allocation_count,
        "total_score": total_score,
        "breakdown": {
            "domain_fit": domain_score,
            "course_handling": handling_score,
            "seniority": seniority_score,
            "experience": exp_score,
            "eligibility_gate": elig_gate_score
        }
    }


# ─── Candidate Ranking Function ───────────────────────────────────────────────

def rank_candidates(
    db: Session,
    subject_title: str,
    subject_code: str,
    min_handled: int,
    faculty_type: str,
    rules: EligibilityRules,
    allocation_counts: dict,
    subject_id: int | None = None
) -> list[dict]:
    """
    Ranks faculty candidates for a given subject and minimum course-handling count.
    Uses database-backed CONFIRMED expertise mappings for domain fit scoring.
    SUGGESTED and REJECTED mappings are strictly ignored.
    Sort priority:
    1. Eligible, available, and meets minimum course handling criteria
    2. Highest suitability score descending
    """
    roster_query = db.query(Faculty).filter_by(faculty_type=faculty_type)
    if faculty_type == "external":
        from ..models import ExternalInstitution
        allowed_institutions = [i.name for i in db.query(ExternalInstitution).filter_by(is_allowed=True).all()]
        roster_query = roster_query.filter(Faculty.institution.in_(allowed_institutions))
    roster = roster_query.all()
    results = []

    # Resolve confirmed mappings for this subject from database (replaces ALIAS_MAP)
    confirmed_map_by_faculty = {}
    if subject_id is None:
        subj = db.query(Subject).filter(
            (Subject.title == subject_title) | (Subject.course_code == subject_code)
        ).first()
        if subj:
            subject_id = subj.id

    if subject_id:
        confirmed = db.query(FacultySubjectMapping).filter(
            FacultySubjectMapping.subject_id == subject_id,
            FacultySubjectMapping.status == "CONFIRMED"
        ).all()
        for m in confirmed:
            confirmed_map_by_faculty[m.faculty_id] = m

    for f in roster:
        existing = allocation_counts.get(f.id, 0)
        conf_m = confirmed_map_by_faculty.get(f.id)
        rec = compute_suitability(
            f, subject_title, subject_code, min_handled, rules, existing, confirmed_mapping=conf_m
        )
        results.append(rec)

    # Sort order
    def sort_key(r):
        is_top = 0 if (r["is_eligible"] and r["meets_min_handled"] and r["is_available"]) else 1
        return (is_top, -r["total_score"], -(r["course_handled_count"] or 0))

    results.sort(key=sort_key)
    return results
