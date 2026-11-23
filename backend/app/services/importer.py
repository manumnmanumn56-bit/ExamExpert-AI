"""
ExamExpert AI — Excel ETL & Dataset Management Service
SJB Institute of Technology | Office of Controller of Examinations

Handles importing, sheet detection, column mapping, validation, deduplication,
conflict analysis, dry-run previews, formula injection protection,
provenance preservation, and export for Internal Faculty, External Faculty,
and Academic Syllabus datasets.
"""
import hashlib
import io
import os
import re
import uuid
from datetime import datetime
from fastapi import HTTPException
import openpyxl
import pandas as pd
from sqlalchemy.orm import Session

from ..models import (
    Faculty, FacultyCourseHistory, FacultyExpertise,
    Subject, EligibilityRules, ImportHistory, Allocation, AuditLog
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# In-memory dry-run preview cache
PREVIEW_CACHE: dict[str, dict] = {}


# ─── Utility & Sanitation Helpers ─────────────────────────────────────────────

def _file_hash(path_or_bytes) -> str:
    h = hashlib.sha256()
    if isinstance(path_or_bytes, str):
        with open(path_or_bytes, "rb") as f:
            h.update(f.read())
    else:
        h.update(path_or_bytes)
    return h.hexdigest()


def _safe_str(val) -> str:
    if val is None or (isinstance(val, float) and str(val) == "nan"):
        return ""
    return str(val).strip()


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return None if str(v) == "nan" else v
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int | None:
    try:
        v = float(val)
        return None if str(v) == "nan" else int(v)
    except (TypeError, ValueError):
        return None


def sanitize_for_excel(val) -> str:
    """
    OWASP CSV & Excel Formula Injection Mitigation:
    If a string starts with '=', '+', '-', '@', '\\t', or '\\r',
    escape it with a leading single quote (') so spreadsheet engines
    treat it as pure static text and never evaluate it as an executable formula.
    """
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def _parse_course_history(text: str | None) -> list[tuple[str, int]]:
    """Parse 'Computer Networks: 13, Information & Network Security: 13' -> [('Computer Networks', 13), ...]"""
    results = []
    if not text:
        return results
    parts = re.split(r",\s*(?=[A-Za-z])", text)
    for part in parts:
        part = part.strip()
        m = re.match(r"^(.+?):\s*(\d+)$", part)
        if m:
            course_name = m.group(1).strip()
            count = int(m.group(2))
            results.append((course_name, count))
    return results


def _expertise_tags(text: str | None) -> list[str]:
    """Split comma/semicolon-separated expertise string into distinct tags."""
    if not text:
        return []
    tags = re.split(r"[,;]+", text)
    return [t.strip() for t in tags if t.strip()]


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


def get_pending_verification_reason(f_or_status, exp: float | None = None) -> str | None:
    """Returns detailed explanation of why an external faculty is pending or unverified."""
    if hasattr(f_or_status, "eligibility_status"):
        status = f_or_status.eligibility_status
        exp = f_or_status.experience_years
    else:
        status = str(f_or_status)

    if status == "Cannot Verify" or exp is None:
        return "Teaching experience duration not specified in source workbook; statutory physical service verification required."
    elif status == "Not Qualified":
        return "Teaching experience below institutional statutory threshold (minimum 10 years, or completed Ph.D with 5 years)."
    return None


# ─── File Validation ──────────────────────────────────────────────────────────

def validate_excel_file(content: bytes, filename: str, dataset_type: str) -> tuple[pd.DataFrame, str]:
    """
    Server-side upload validation:
    1. Extension check (.xlsx, .xls only)
    2. Size limit (max 10MB)
    3. Empty content rejection
    4. Corrupt / unreadable Excel workbook rejection
    5. Required columns validation per dataset_type
    """
    fn_lower = filename.lower()
    if not (fn_lower.endswith(".xlsx") or fn_lower.endswith(".xls")):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Only Microsoft Excel (.xlsx, .xls) workbooks are accepted."
        )

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds the statutory limit of 10MB."
        )

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    try:
        xl = pd.ExcelFile(io.BytesIO(content))
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Corrupt or unreadable Excel workbook. Please upload a valid .xlsx file."
        )

    dt = dataset_type.strip().lower()
    if dt not in ("internal", "external", "syllabus"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dataset type '{dataset_type}'. Must be 'internal', 'external', or 'syllabus'."
        )

    # Determine sheet
    sheet_name = None
    if dt in ("internal", "external"):
        if "Faculty Data" in xl.sheet_names:
            sheet_name = "Faculty Data"
        else:
            sheet_name = xl.sheet_names[0]
    elif dt == "syllabus":
        if "Syllabus" in xl.sheet_names:
            sheet_name = "Syllabus"
        else:
            sheet_name = xl.sheet_names[0]

    try:
        df = pd.read_excel(xl, sheet_name=sheet_name)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to read worksheet '{sheet_name}': {str(e)}"
        )

    cols = [str(c).strip() for c in df.columns]

    if dt == "internal":
        req_cols = ["Faculty Name", "Department"]
    elif dt == "external":
        req_cols = ["Faculty Name", "College Name", "Department"]
    elif dt == "syllabus":
        req_cols = ["Subject Title", "Department", "Semester"]
    else:
        req_cols = []

    missing = [c for c in req_cols if c not in cols]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid workbook structure for '{dt}'. Missing required column(s): {', '.join(missing)}."
        )

    return df, sheet_name


# ─── Dry-Run Import Preview ───────────────────────────────────────────────────

def preview_dataset_import(db: Session, content: bytes, filename: str, dataset_type: str) -> dict:
    """
    Performs complete dry-run validation and classification before any data is written:
    - Rows to add
    - Exact duplicates (matching key & identical attributes)
    - Conflicting rows (matching key but differing attributes — e.g. manual Admin edits)
    - Rejected rows (missing mandatory fields, invalid semester, etc.)
    Stores analysis in PREVIEW_CACHE for subsequent confirmation.
    """
    df, sheet_name = validate_excel_file(content, filename, dataset_type)
    fhash = _file_hash(content)
    dt = dataset_type.strip().lower()

    to_add = []
    duplicates = []
    conflicts = []
    rejected = []

    if dt == "internal":
        existing = db.query(Faculty).filter_by(faculty_type="internal").all()
        by_emp = {f.employee_id.strip(): f for f in existing if f.employee_id}
        by_name_dept = {(f.name.strip().lower(), f.department.strip().lower()): f for f in existing if f.name and f.department}
        by_serial = {f.db_serial_no.strip(): f for f in existing if f.db_serial_no}

        for idx, row in df.iterrows():
            row_num = idx + 2
            name = _safe_str(row.get("Faculty Name"))
            dept = _safe_str(row.get("Department"))
            emp_id = _safe_str(row.get("Employee ID"))
            serial = _safe_str(row.get("DB Serial No"))
            college = _safe_str(row.get("College Name")) or "SJB Institute of Technology"
            desig = _safe_str(row.get("Designation"))
            qual = _safe_str(row.get("Qualification"))
            exp = _safe_float(row.get("Experience (Years)"))
            email = _safe_str(row.get("Official Email ID")) or None
            mobile = _safe_str(row.get("Mobile Number")) or None
            raw_history = _safe_str(row.get("Number of times handled the course"))
            raw_exp = _safe_str(row.get("Courses Taught / Area of Expertise"))
            scheme = _safe_str(row.get("Syllabus Scheme"))
            addr = _safe_str(row.get("College Address & Pincode"))

            if not name:
                rejected.append({
                    "row": row_num,
                    "identifier": f"Row #{row_num}",
                    "reason": "Missing mandatory field 'Faculty Name'",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue
            if not dept:
                rejected.append({
                    "row": row_num,
                    "identifier": name,
                    "reason": "Missing mandatory field 'Department'",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue

            elig_status = recalculate_eligibility_status(qual, exp, "internal")

            # Match on Employee ID > (Name, Dept) > DB Serial No
            matched_f = None
            if emp_id and emp_id in by_emp:
                matched_f = by_emp[emp_id]
            elif (name.lower(), dept.lower()) in by_name_dept:
                matched_f = by_name_dept[(name.lower(), dept.lower())]
            elif serial and serial in by_serial:
                matched_f = by_serial[serial]

            row_data = {
                "row": row_num,
                "db_serial_no": serial or f"INT-{name[:8].replace(' ', '')}",
                "employee_id": emp_id or None,
                "name": name,
                "designation": desig,
                "department": dept,
                "institution": college,
                "faculty_type": "internal",
                "qualification": qual or None,
                "experience_years": exp,
                "eligibility_status": elig_status,
                "email": email,
                "mobile": mobile,
                "expertise_text": raw_exp or None,
                "course_history_text": raw_history or None,
                "scheme": scheme or None,
                "address": addr or None,
                "provenance_file": filename
            }

            if matched_f:
                diffs = []
                if desig and matched_f.designation != desig:
                    diffs.append({"field": "designation", "existing": matched_f.designation, "incoming": desig})
                if exp is not None and matched_f.experience_years != exp:
                    diffs.append({"field": "experience_years", "existing": matched_f.experience_years, "incoming": exp})
                if qual and matched_f.qualification != qual:
                    diffs.append({"field": "qualification", "existing": matched_f.qualification, "incoming": qual})
                if email and matched_f.email != email:
                    diffs.append({"field": "email", "existing": matched_f.email, "incoming": email})
                if mobile and matched_f.mobile != mobile:
                    diffs.append({"field": "mobile", "existing": matched_f.mobile, "incoming": mobile})
                if dept and matched_f.department != dept:
                    diffs.append({"field": "department", "existing": matched_f.department, "incoming": dept})

                if diffs:
                    conflicts.append({
                        "row": row_num,
                        "faculty_id": matched_f.id,
                        "identifier": f"{name} ({dept})",
                        "diffs": diffs,
                        "incoming": row_data
                    })
                else:
                    duplicates.append({
                        "row": row_num,
                        "faculty_id": matched_f.id,
                        "identifier": f"{name} ({dept})"
                    })
            else:
                to_add.append(row_data)

    elif dt == "external":
        existing = db.query(Faculty).filter_by(faculty_type="external").all()
        by_name_inst = {(f.name.strip().lower(), f.institution.strip().lower(), f.department.strip().lower()): f for f in existing if f.name and f.institution and f.department}
        by_serial = {f.db_serial_no.strip(): f for f in existing if f.db_serial_no}

        for idx, row in df.iterrows():
            row_num = idx + 2
            name = _safe_str(row.get("Faculty Name"))
            college = _safe_str(row.get("College Name"))
            dept = _safe_str(row.get("Department"))
            serial = _safe_str(row.get("DB Serial No"))
            emp_id = _safe_str(row.get("Employee ID"))
            desig = _safe_str(row.get("Designation"))
            qual = _safe_str(row.get("Qualification"))
            exp = _safe_float(row.get("Experience (Years)"))
            assumed = _safe_int(row.get("Assumed No. of Times Handled (Question Paper Setting)"))
            raw_exp = _safe_str(row.get("Courses Taught / Area of Expertise"))
            scheme = _safe_str(row.get("Syllabus Scheme"))
            addr = _safe_str(row.get("College Address & Pincode"))
            email = _safe_str(row.get("Official Email ID")) or None
            mobile = _safe_str(row.get("Mobile Number")) or None

            if not name:
                rejected.append({
                    "row": row_num,
                    "identifier": f"Row #{row_num}",
                    "reason": "Missing mandatory field 'Faculty Name'",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue
            if not college:
                rejected.append({
                    "row": row_num,
                    "identifier": name,
                    "reason": "Missing mandatory field 'College Name'",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue
            if not dept:
                rejected.append({
                    "row": row_num,
                    "identifier": name,
                    "reason": "Missing mandatory field 'Department'",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue

            elig_status = recalculate_eligibility_status(qual, exp, "external")

            # Match on (Name, College, Dept) > DB Serial No
            matched_f = None
            if (name.lower(), college.lower(), dept.lower()) in by_name_inst:
                matched_f = by_name_inst[(name.lower(), college.lower(), dept.lower())]
            elif serial and serial in by_serial:
                matched_f = by_serial[serial]

            row_data = {
                "row": row_num,
                "db_serial_no": serial or f"EXT-{name[:8].replace(' ', '')}",
                "employee_id": emp_id or None,
                "name": name,
                "designation": desig,
                "department": dept,
                "institution": college,
                "faculty_type": "external",
                "qualification": qual or None,
                "experience_years": exp,
                "eligibility_status": elig_status,
                "email": email,
                "mobile": mobile,
                "expertise_text": raw_exp or None,
                "course_history_text": None,
                "assumed_times_handled": assumed,
                "scheme": scheme or None,
                "address": addr or None,
                "provenance_file": filename
            }

            if matched_f:
                diffs = []
                if desig and matched_f.designation != desig:
                    diffs.append({"field": "designation", "existing": matched_f.designation, "incoming": desig})
                if exp is not None and matched_f.experience_years != exp:
                    diffs.append({"field": "experience_years", "existing": matched_f.experience_years, "incoming": exp})
                if qual and matched_f.qualification != qual:
                    diffs.append({"field": "qualification", "existing": matched_f.qualification, "incoming": qual})
                if email and matched_f.email != email:
                    diffs.append({"field": "email", "existing": matched_f.email, "incoming": email})
                if mobile and matched_f.mobile != mobile:
                    diffs.append({"field": "mobile", "existing": matched_f.mobile, "incoming": mobile})

                if diffs:
                    conflicts.append({
                        "row": row_num,
                        "faculty_id": matched_f.id,
                        "identifier": f"{name} ({college})",
                        "diffs": diffs,
                        "incoming": row_data
                    })
                else:
                    duplicates.append({
                        "row": row_num,
                        "faculty_id": matched_f.id,
                        "identifier": f"{name} ({college})"
                    })
            else:
                to_add.append(row_data)

    elif dt == "syllabus":
        existing = db.query(Subject).all()
        by_exact = {
            (s.course_code.strip().upper(), s.department.strip().upper(), (s.scheme or "").strip(), s.semester.strip().upper(), s.title.strip().lower()): s
            for s in existing if s.course_code and s.title
        }
        by_code_dept = {
            (s.course_code.strip().upper(), s.department.strip().upper(), (s.scheme or "").strip(), s.semester.strip().upper()): s
            for s in existing if s.course_code and "XY" not in s.course_code.upper() and "ELECTIVE" not in s.course_code.upper()
        }
        by_title_dept = {(s.title.strip().lower(), s.department.strip().upper(), (s.scheme or "").strip(), s.semester.strip().upper()): s for s in existing if s.title}

        for idx, row in df.iterrows():
            row_num = idx + 2
            title = _safe_str(row.get("Subject Title"))
            dept = _safe_str(row.get("Department"))
            sem = _safe_str(row.get("Semester"))
            code = _safe_str(row.get("Course Code")).upper()
            scheme = _safe_str(row.get("Scheme"))
            ay = _safe_str(row.get("Academic Year"))
            ctype = _safe_str(row.get("Course Type")) or "Theory"
            vstatus = _safe_str(row.get("Verification Status")) or "Verified"
            notes = _safe_str(row.get("Source / Notes"))

            if not title:
                rejected.append({
                    "row": row_num,
                    "identifier": f"Row #{row_num}",
                    "reason": "Missing mandatory field 'Subject Title'",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue
            if not dept:
                rejected.append({
                    "row": row_num,
                    "identifier": title,
                    "reason": "Missing mandatory field 'Department'",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue
            if not sem:
                rejected.append({
                    "row": row_num,
                    "identifier": title,
                    "reason": "Missing mandatory field 'Semester'",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue

            # MCA 4-semester rule check
            clean_sem = sem.replace("Semester", "").strip().upper()
            if dept.upper() == "MCA" and clean_sem not in ("I", "II", "III", "IV", "1", "2", "3", "4"):
                rejected.append({
                    "row": row_num,
                    "identifier": f"{title} ({dept} Sem {sem})",
                    "reason": "MCA 4-semester rule: Master of Computer Applications is strictly limited to Semesters I to IV.",
                    "source_values": {str(k): str(v) for k, v in row.items() if pd.notna(v)}
                })
                continue

            # Fallback academic year from notes if missing
            if not ay:
                m = re.search(r"Academic year:\s*(\d{4}-\d{2})", notes)
                ay = m.group(1) if m else "2023-24"

            matched_s = None
            exact_key = (code, dept.upper(), scheme, sem.upper(), title.strip().lower())
            if exact_key in by_exact:
                matched_s = by_exact[exact_key]
            elif code and (code, dept.upper(), scheme, sem.upper()) in by_code_dept:
                matched_s = by_code_dept[(code, dept.upper(), scheme, sem.upper())]
            elif (title.lower(), dept.upper(), scheme, sem.upper()) in by_title_dept:
                matched_s = by_title_dept[(title.lower(), dept.upper(), scheme, sem.upper())]

            row_data = {
                "row": row_num,
                "course_code": code or None,
                "title": title,
                "department": dept,
                "scheme": scheme or None,
                "academic_year": ay,
                "semester": sem,
                "course_type": ctype,
                "verification_status": vstatus,
                "source_notes": notes or None
            }

            if matched_s:
                diffs = []
                if title and matched_s.title != title:
                    diffs.append({"field": "title", "existing": matched_s.title, "incoming": title})
                if ctype and matched_s.course_type != ctype:
                    diffs.append({"field": "course_type", "existing": matched_s.course_type, "incoming": ctype})
                if vstatus and matched_s.verification_status != vstatus:
                    diffs.append({"field": "verification_status", "existing": matched_s.verification_status, "incoming": vstatus})

                if diffs:
                    conflicts.append({
                        "row": row_num,
                        "subject_id": matched_s.id,
                        "identifier": f"{code or title} ({dept} Sem {sem})",
                        "diffs": diffs,
                        "incoming": row_data
                    })
                else:
                    duplicates.append({
                        "row": row_num,
                        "subject_id": matched_s.id,
                        "identifier": f"{code or title} ({dept} Sem {sem})"
                    })
            else:
                to_add.append(row_data)

    preview_id = str(uuid.uuid4())
    preview_payload = {
        "preview_id": preview_id,
        "filename": filename,
        "file_hash": fhash,
        "dataset_type": dt,
        "total_rows": len(df),
        "to_add": to_add,
        "duplicates": duplicates,
        "conflicts": conflicts,
        "rejected": rejected,
        "created_at": datetime.utcnow()
    }

    PREVIEW_CACHE[preview_id] = preview_payload

    return {
        "preview_id": preview_id,
        "filename": filename,
        "dataset_type": dt,
        "total_rows": len(df),
        "to_add_count": len(to_add),
        "duplicate_count": len(duplicates),
        "conflict_count": len(conflicts),
        "rejected_count": len(rejected),
        "to_add_sample": to_add[:10],
        "duplicate_sample": duplicates[:10],
        "conflicts": conflicts,
        "rejected": rejected
    }


# ─── Confirm & Execute Import ─────────────────────────────────────────────────

def confirm_dataset_import(db: Session, preview_id: str, conflict_resolution: str, user_username: str) -> dict:
    """
    Commits the approved import after Admin confirmation:
    - Inserts all approved 'to_add' rows
    - Applies conflict resolution ('preserve_existing' preserves Admin manual edits; 'overwrite' updates them)
    - Records detailed ImportHistory with imported_by username
    - Records comprehensive AuditLog entry
    - Returns finalized counts
    """
    if preview_id not in PREVIEW_CACHE:
        raise HTTPException(
            status_code=400,
            detail="Import preview session expired or not found. Please upload the file again to preview."
        )

    preview = PREVIEW_CACHE[preview_id]
    dt = preview["dataset_type"]
    to_add = preview["to_add"]
    conflicts = preview["conflicts"]
    duplicates = preview["duplicates"]
    rejected = preview["rejected"]

    added_count = 0
    updated_count = 0

    if dt == "internal":
        for r in to_add:
            f = Faculty(
                db_serial_no=r["db_serial_no"],
                employee_id=r["employee_id"],
                name=r["name"],
                designation=r["designation"],
                department=r["department"],
                institution=r["institution"],
                faculty_type="internal",
                qualification=r["qualification"],
                experience_years=r["experience_years"],
                eligibility_status=r["eligibility_status"],
                expertise_text=r["expertise_text"],
                course_history_text=r["course_history_text"],
                assumed_times_handled=None,
                scheme=r["scheme"],
                address=r["address"],
                email=r["email"],
                mobile=r["mobile"],
                is_available=True,
                provenance_file=r["provenance_file"]
            )
            db.add(f)
            db.flush()
            added_count += 1

            if r["course_history_text"]:
                for cname, cnt in _parse_course_history(r["course_history_text"]):
                    db.add(FacultyCourseHistory(faculty_id=f.id, course_title=cname, times_handled=cnt))
            if r["expertise_text"]:
                for tag in _expertise_tags(r["expertise_text"]):
                    db.add(FacultyExpertise(faculty_id=f.id, tag=tag))

        if conflict_resolution == "overwrite":
            for c in conflicts:
                inc = c["incoming"]
                fid = c["faculty_id"]
                f = db.query(Faculty).filter_by(id=fid).first()
                if f:
                    f.designation = inc["designation"]
                    f.qualification = inc["qualification"]
                    f.experience_years = inc["experience_years"]
                    f.email = inc["email"]
                    f.mobile = inc["mobile"]
                    f.eligibility_status = inc["eligibility_status"]
                    f.provenance_file = inc["provenance_file"]
                    updated_count += 1

    elif dt == "external":
        for r in to_add:
            f = Faculty(
                db_serial_no=r["db_serial_no"],
                employee_id=r["employee_id"],
                name=r["name"],
                designation=r["designation"],
                department=r["department"],
                institution=r["institution"],
                faculty_type="external",
                qualification=r["qualification"],
                experience_years=r["experience_years"],
                eligibility_status=r["eligibility_status"],
                expertise_text=r["expertise_text"],
                course_history_text=None,
                assumed_times_handled=r.get("assumed_times_handled"),
                scheme=r["scheme"],
                address=r["address"],
                email=r["email"],
                mobile=r["mobile"],
                is_available=True,
                provenance_file=r["provenance_file"]
            )
            db.add(f)
            db.flush()
            added_count += 1

            if r["expertise_text"]:
                for tag in _expertise_tags(r["expertise_text"]):
                    db.add(FacultyExpertise(faculty_id=f.id, tag=tag))

        if conflict_resolution == "overwrite":
            for c in conflicts:
                inc = c["incoming"]
                fid = c["faculty_id"]
                f = db.query(Faculty).filter_by(id=fid).first()
                if f:
                    f.designation = inc["designation"]
                    f.qualification = inc["qualification"]
                    f.experience_years = inc["experience_years"]
                    f.email = inc["email"]
                    f.mobile = inc["mobile"]
                    f.eligibility_status = inc["eligibility_status"]
                    f.provenance_file = inc["provenance_file"]
                    updated_count += 1

    elif dt == "syllabus":
        for r in to_add:
            s = Subject(
                course_code=r["course_code"],
                title=r["title"],
                department=r["department"],
                scheme=r["scheme"],
                academic_year=r["academic_year"],
                semester=r["semester"],
                course_type=r["course_type"],
                credits=None,
                verification_status=r["verification_status"],
                source_notes=r["source_notes"]
            )
            db.add(s)
            added_count += 1

        if conflict_resolution == "overwrite":
            for c in conflicts:
                inc = c["incoming"]
                sid = c["subject_id"]
                s = db.query(Subject).filter_by(id=sid).first()
                if s:
                    s.title = inc["title"]
                    s.course_type = inc["course_type"]
                    s.verification_status = inc["verification_status"]
                    s.source_notes = inc["source_notes"]
                    updated_count += 1

    # Record ImportHistory
    history = ImportHistory(
        file_name=preview["filename"],
        file_hash=preview["file_hash"],
        file_type=dt,
        total_rows=preview["total_rows"],
        valid_rows=added_count,
        duplicate_rows=len(duplicates),
        conflicts_count=len(conflicts),
        skipped_rows=len(rejected),
        imported_by=user_username,
        imported_at=datetime.utcnow()
    )
    db.add(history)

    # Record AuditLog
    db.add(AuditLog(
        action="DATASET_IMPORTED",
        entity_type="Dataset",
        entity_id=None,
        details=f"Admin '{user_username}' confirmed import of {preview['filename']} ({dt}): {added_count} added, {len(duplicates)} duplicates, {len(conflicts)} conflicts ({conflict_resolution}: {updated_count} updated), {len(rejected)} rejected."
    ))

    db.commit()

    return {
        "success": True,
        "preview_id": preview_id,
        "filename": preview["filename"],
        "dataset_type": dt,
        "total_rows": preview["total_rows"],
        "added_count": added_count,
        "updated_count": updated_count,
        "duplicate_count": len(duplicates),
        "conflict_count": len(conflicts),
        "rejected_count": len(rejected),
        "conflict_resolution": conflict_resolution
    }


# ─── Rejected & Conflict Report Export ────────────────────────────────────────

def generate_rejected_report_excel(preview: dict) -> bytes:
    """
    Generates an Excel report containing:
    1. Sheet 'Rejected Rows': row number, identifier, reason, raw values
    2. Sheet 'Conflicting Rows': row number, identifier, differing fields, incoming vs existing
    3. Sheet 'Import Summary': overall breakdown
    Strictly escapes any value starting with '=', '+', '-', '@', '\\t', '\\r' using sanitize_for_excel
    to protect against CSV/Excel Formula Injection attacks.
    """
    wb = openpyxl.Workbook()

    # Sheet 1: Rejected Rows
    ws_rej = wb.active
    ws_rej.title = "Rejected Rows"
    ws_rej.append(["Row #", "Identifier", "Rejection Reason", "Source Notes / Raw Data"])

    for r in preview.get("rejected", []):
        row_num = str(r.get("row", ""))
        ident = sanitize_for_excel(r.get("identifier", ""))
        reason = sanitize_for_excel(r.get("reason", ""))
        src_vals = str(r.get("source_values", ""))
        ws_rej.append([row_num, ident, reason, sanitize_for_excel(src_vals[:250])])

    # Sheet 2: Conflicting Rows
    ws_conf = wb.create_sheet(title="Conflicting Rows")
    ws_conf.append(["Row #", "Identifier", "Conflicting Field", "Existing DB Value", "Incoming Workbook Value"])

    for c in preview.get("conflicts", []):
        row_num = str(c.get("row", ""))
        ident = sanitize_for_excel(c.get("identifier", ""))
        diffs = c.get("diffs", [])
        for d in diffs:
            field = sanitize_for_excel(d.get("field", ""))
            exist_val = sanitize_for_excel(d.get("existing", ""))
            inc_val = sanitize_for_excel(d.get("incoming", ""))
            ws_conf.append([row_num, ident, field, exist_val, inc_val])

    # Sheet 3: Summary
    ws_sum = wb.create_sheet(title="Import Summary")
    ws_sum.append(["Metric", "Count"])
    ws_sum.append(["Workbook File", sanitize_for_excel(preview.get("filename", ""))])
    ws_sum.append(["Dataset Type", sanitize_for_excel(preview.get("dataset_type", ""))])
    ws_sum.append(["Total Rows Evaluated", preview.get("total_rows", 0)])
    ws_sum.append(["Rows to Add", len(preview.get("to_add", []))])
    ws_sum.append(["Duplicate Rows (Skipped)", len(preview.get("duplicates", []))])
    ws_sum.append(["Conflicting Rows (Preserved)", len(preview.get("conflicts", []))])
    ws_sum.append(["Rejected Rows", len(preview.get("rejected", []))])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ─── Backward-Compatible Direct Import Wrappers ───────────────────────────────

def import_internal_faculty(db: Session, filepath_or_bytes, filename: str = "SJBIT college data internal faculty.xlsx") -> dict:
    if isinstance(filepath_or_bytes, (str, os.PathLike)):
        with open(filepath_or_bytes, "rb") as f:
            content = f.read()
    else:
        content = filepath_or_bytes

    preview = preview_dataset_import(db, content, filename, "internal")
    result = confirm_dataset_import(db, preview["preview_id"], "preserve_existing", "system_init")
    return {
        "file_name": filename,
        "total_rows": result["total_rows"],
        "valid_rows": result["added_count"],
        "duplicate_rows": result["duplicate_count"],
        "conflict_rows": result["conflict_count"],
        "invalid_rows": result["rejected_count"]
    }


def import_external_faculty(db: Session, filepath_or_bytes, filename: str = "External Faculty college data.xlsx") -> dict:
    if isinstance(filepath_or_bytes, (str, os.PathLike)):
        with open(filepath_or_bytes, "rb") as f:
            content = f.read()
    else:
        content = filepath_or_bytes

    preview = preview_dataset_import(db, content, filename, "external")
    result = confirm_dataset_import(db, preview["preview_id"], "preserve_existing", "system_init")
    return {
        "file_name": filename,
        "total_rows": result["total_rows"],
        "valid_rows": result["added_count"],
        "duplicate_rows": result["duplicate_count"],
        "conflict_rows": result["conflict_count"],
        "invalid_rows": result["rejected_count"]
    }


def import_syllabus(db: Session, filepath_or_bytes, filename: str = "SJBIT_All_Academic_Years sylabus.xlsx") -> dict:
    if isinstance(filepath_or_bytes, (str, os.PathLike)):
        with open(filepath_or_bytes, "rb") as f:
            content = f.read()
    else:
        content = filepath_or_bytes

    preview = preview_dataset_import(db, content, filename, "syllabus")
    result = confirm_dataset_import(db, preview["preview_id"], "preserve_existing", "system_init")
    return {
        "file_name": filename,
        "total_rows": result["total_rows"],
        "valid_rows": result["added_count"],
        "duplicate_rows": result["duplicate_count"],
        "conflict_rows": result["conflict_count"],
        "invalid_rows": result["rejected_count"]
    }


# ─── Dataset Export Helpers ───────────────────────────────────────────────────

def export_faculty_to_excel(db: Session) -> bytes:
    """Exports both internal and external faculty rosters into a clean formatted Excel workbook."""
    internal = db.query(Faculty).filter_by(faculty_type="internal").all()
    external = db.query(Faculty).filter_by(faculty_type="external").all()

    int_rows = [{
        "DB Serial No": f.db_serial_no,
        "Employee ID": f.employee_id,
        "Faculty Name": f.name,
        "Designation": f.designation,
        "Department": f.department,
        "College Name": f.institution,
        "Qualification": f.qualification,
        "Experience (Years)": f.experience_years,
        "Eligibility Status": f.eligibility_status,
        "Courses Taught / Area of Expertise": f.expertise_text,
        "Course Handling History": f.course_history_text,
        "Official Email ID": f.email,
        "Mobile Number": f.mobile
    } for f in internal]

    ext_rows = [{
        "DB Serial No": f.db_serial_no,
        "Employee ID": f.employee_id,
        "Faculty Name": f.name,
        "College Name": f.institution,
        "Designation": f.designation,
        "Department": f.department,
        "Qualification": f.qualification,
        "Experience (Years)": f.experience_years,
        "Assumed Times Handled (QP Setting)": f.assumed_times_handled,
        "Eligibility Status": f.eligibility_status,
        "Courses Taught / Area of Expertise": f.expertise_text,
        "Official Email ID": f.email,
        "Mobile Number": f.mobile
    } for f in external]

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        pd.DataFrame(int_rows).to_excel(writer, sheet_name="Internal Faculty", index=False)
        pd.DataFrame(ext_rows).to_excel(writer, sheet_name="External Faculty", index=False)

    return out.getvalue()


def export_allocations_to_excel(db: Session) -> bytes:
    """Exports confirmed allocation records to Excel."""
    allocs = db.query(Allocation).all()
    rows = []
    for a in allocs:
        subj = a.subject
        rows.append({
            "Reference Number": a.reference_number,
            "Academic Year": a.academic_year,
            "Department": a.department,
            "Semester": a.semester,
            "Course Code": subj.course_code if subj else "",
            "Subject Title": subj.title if subj else "",
            "Scheme": subj.scheme if subj else "",
            "Total Required": a.total_required,
            "Internal Required": a.internal_required,
            "External Required": a.external_required,
            "Allocation Ratio": a.allocation_ratio,
            "Status": a.status,
            "Exception Reason": a.exception_reason or "N/A",
            "Confirmed At": a.confirmed_at.isoformat() if a.confirmed_at else "",
            "Created At": a.created_at.isoformat() if a.created_at else ""
        })

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Allocations", index=False)

    return out.getvalue()


def seed_eligibility_rules(db: Session):
    r = db.query(EligibilityRules).first()
    if not r:
        import json
        db.add(EligibilityRules(
            min_experience=10.0,
            min_experience_phd=5.0,
            allowed_designations=json.dumps(["Assistant Professor", "Associate Professor", "Professor"]),
            internal_capacity=2,
            external_capacity=2,
            status="CONFIRMED",
            min_experience_years=10.0,
            phd_fasttrack_min_exp=5.0,
            max_papers_per_faculty=2,
            max_internal_papers=2,
            max_external_papers=2,
            require_parity=True,
            active_academic_year="2025-26",
            upcoming_academic_year="2026-27"
        ))
        db.commit()
