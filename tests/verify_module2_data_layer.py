"""
ExamExpert AI — Module 2 Data Layer & Relational Schema Verification Suite
SJB Institute of Technology | Office of Controller of Examinations

Verifies:
1. Database backup integrity (examexpert_backup_module2.db)
2. All 18 relational tables in SQLite
3. Department mapping resolution (fixing HOD scoping)
4. AllocationSetter junction table functionality
5. WorkloadLedger append-only transaction ledger with semester cycle
6. External institutions whitelist (11 institutions default allowed)
7. Dataset record preservation (47 internal, 77 external, 195 syllabus)
"""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("mod2_")

from backend.app.database import SessionLocal, DB_PATH
from backend.app.models import (
    User, Faculty, Subject, Allocation, AllocationSetter,
    WorkloadLedger, DepartmentMapping, ExternalInstitution,
    FacultyCourseHistory, FacultyExpertise, EligibilityRules
)
from backend.app.services.migration import (
    run_database_migrations,
    resolve_department_names,
    get_faculty_workload_summary,
    record_workload_entry,
    is_external_institution_allowed,
    get_allowed_external_institutions
)
from backend.app.routers.faculty import get_all_faculty

def run_module2_verification():
    print("=" * 75)
    print("  EXAMEXPERT AI — MODULE 2 DATA LAYER & DATABASE DESIGN VERIFICATION")
    print("  SJB Institute of Technology • Office of Controller of Examinations")
    print("=" * 75)

    passed = 0
    failed = 0

    def record(name: str, success: bool, note: str = ""):
        nonlocal passed, failed
        status = "[PASS]" if success else "[FAIL]"
        print(f"{status} {name} {note}")
        if success:
            passed += 1
        else:
            failed += 1

    # 1. Database backup check
    backup_path = os.path.join(os.path.dirname(DB_PATH), "examexpert_backup_module2.db")
    backup_exists = os.path.exists(backup_path) and os.path.getsize(backup_path) > 200000
    record("Database Backup Created & Verified", backup_exists, f"({backup_path})")

    with SessionLocal() as db:
        # Run migrations
        run_database_migrations(db)

        # 2. Table count check
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = set(t[0] for t in c.fetchall())
        conn.close()

        expected_tables = {
            "users", "otp_tokens", "faculty", "subjects", "eligibility_rules",
            "import_history", "audit_logs", "faculty_course_history", "faculty_expertise",
            "allocations", "allocation_conflicts", "notification_logs", "active_sessions",
            "allocation_setters", "workload_ledger", "department_mappings",
            "faculty_subject_mappings", "external_institutions"
        }
        all_tables_present = expected_tables.issubset(tables)
        record("Relational Tables Created in SQLite", all_tables_present, f"(Found {len(tables)} tables, including setters & ledger)")

        # 3. Department mapping resolution
        mca_resolved = resolve_department_names(db, "MCA")
        cse_resolved = resolve_department_names(db, "CSE")
        mca_ok = "Master of Computer Applications" in mca_resolved and "MCA" in mca_resolved
        cse_ok = "Computer Science & Engineering" in cse_resolved and "CSE" in cse_resolved
        record("Department Alias Resolution (MCA & CSE)", mca_ok and cse_ok, f"(MCA -> {mca_resolved})")

        # 4. HOD department scoping with new mapping
        hod_mca = db.query(User).filter_by(email="hod.mca@sjbit.edu.in").first()
        hod_cse = db.query(User).filter_by(email="hod.cse@sjbit.edu.in").first()
        res_mca = get_all_faculty(faculty_type="internal", db=db, current_user=hod_mca)
        res_cse = get_all_faculty(faculty_type="internal", db=db, current_user=hod_cse)
        record("HOD MCA Department Scoping Fix", res_mca["total"] == 3, f"(Found {res_mca['total']} MCA internal faculty)")
        record("HOD CSE Department Scoping Fix", res_cse["total"] == 21, f"(Found {res_cse['total']} CSE internal faculty)")

        # 5. External institutions whitelist
        allowed_insts = get_allowed_external_institutions(db)
        is_rvce_allowed = is_external_institution_allowed(db, "RV College of Engineering (RVCE)")
        is_unknown_allowed = is_external_institution_allowed(db, "Unknown Fictional College 123")
        record("External Institutions Whitelist (11 Institutions Default)", len(allowed_insts) == 11 and is_rvce_allowed and not is_unknown_allowed, f"(Whitelisted: {len(allowed_insts)})")

        # 6. Workload ledger append-only transactions & semester cycle
        test_fac = db.query(Faculty).filter_by(faculty_type="internal").first()
        initial_wl = get_faculty_workload_summary(db, test_fac.id, "2025-26", "I")

        # Record reservation
        r_entry = record_workload_entry(db, test_fac.id, "2025-26", "I", None, "RESERVED", 1, "Test reservation Sem I")
        wl_after_res = get_faculty_workload_summary(db, test_fac.id, "2025-26", "I")
        res_ok = wl_after_res["reserved"] == initial_wl["reserved"] + 1

        # Record commit
        c_entry = record_workload_entry(db, test_fac.id, "2025-26", "I", None, "COMMITTED", 1, "Test commit Sem I")
        wl_after_com = get_faculty_workload_summary(db, test_fac.id, "2025-26", "I")
        com_ok = wl_after_com["committed"] == initial_wl["committed"] + 1

        # Record release of reservation
        rel_entry = record_workload_entry(db, test_fac.id, "2025-26", "I", None, "RESERVED", -1, "Test release reservation")
        wl_after_rel = get_faculty_workload_summary(db, test_fac.id, "2025-26", "I")
        rel_ok = wl_after_rel["reserved"] == initial_wl["reserved"]

        # Clean up test entries
        db.delete(r_entry)
        db.delete(c_entry)
        db.delete(rel_entry)
        db.commit()

        record("Append-Only Workload Ledger (Reserved/Committed/Released)", res_ok and com_ok and rel_ok, "(Semester cycle verified)")

        # 7. Record Preservation Checks
        n_int = db.query(Faculty).filter_by(faculty_type="internal").count()
        n_ext = db.query(Faculty).filter_by(faculty_type="external").count()
        n_sub = db.query(Subject).count()
        n_ch = db.query(FacultyCourseHistory).count()
        n_tags = db.query(FacultyExpertise).count()

        record("Internal Faculty Record Count Preserved", n_int == 47, f"(Count: {n_int}/47)")
        record("External Faculty Record Count Preserved", n_ext == 77, f"(Count: {n_ext}/77)")
        record("Syllabus Courses Record Count Preserved", n_sub == 195, f"(Count: {n_sub}/195)")
        record("Course History Relational Rows Preserved", n_ch == 117, f"(Count: {n_ch})")
        record("Expertise Tags Relational Rows Preserved", n_tags == 161, f"(Count: {n_tags})")

    print("=" * 75)
    print(f"  MODULE 2 VERIFICATION RESULT: {passed} PASSED / {failed} FAILED")
    print("=" * 75)
    return passed, failed

if __name__ == "__main__":
    p, f = run_module2_verification()
    sys.exit(0 if f == 0 else 1)
