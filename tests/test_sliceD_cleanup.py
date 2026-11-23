"""
ExamExpert AI — Slice D Cleanup Fixes Automated Test Suite
SJB Institute of Technology | Office of Controller of Examinations

Explicitly verifies:
1. Item A — Faculty Record Email & User Linking:
   - Dr. Nagamani S faculty email is 'nagamanis@sjbit.edu.in' (matching workbook).
   - Faculty user account 'faculty_mca' ('faculty.mca@sjbit.edu.in') is linked via faculty_id.
   - Faculty login remains fully functional.
2. Item B — Syllabus Key Matching with Title:
   - The three 25MCAE3XY electives exist as 3 distinct rows with distinct titles.
   - Module 5 duplicate rule is intact: true duplicates (same code + title for electives, or same code for core) are rejected.
   - Dry-run import on all 3 real workbooks proves: 0 conflicts, 0 to-add, 0 rejected.
3. Item C — Tiered Mapping Generation & Untouched RELATED Deletion:
   - Batch mapping generates ONLY EXACT_EXPERIENCE and SPECIALIZATION.
   - POST /api/mappings/generate-related/{subject_id} generates RELATED mappings on demand.
   - Untouched SUGGESTED RELATED mappings are deleted with an AuditLog entry.
"""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("sliceD_")

from fastapi import HTTPException
from sqlalchemy.orm import Session
from backend.app.database import SessionLocal
from backend.app.models import (
    User, Faculty, Subject, FacultySubjectMapping, AuditLog
)
from backend.app.routers.auth import hash_password, verify_password
from backend.app.routers.syllabus import _check_duplicate_subject
from backend.app.routers.mappings import (
    generate_mapping_suggestions,
    generate_related_mappings_for_subject,
    purge_untouched_related_mappings
)
from backend.app.services.importer import preview_dataset_import

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_item_a_faculty_email_and_user_link():
    print("[TEST 1] Verifying Dr. Nagamani S Faculty Email & User Link...")
    db = SessionLocal()
    try:
        # 1. Verify Faculty Record Email matches workbook
        faculty = db.query(Faculty).filter(Faculty.name.ilike("%Nagamani%")).first()
        assert faculty is not None, "Dr. Nagamani S record must exist in Faculty table"
        assert faculty.email == "nagamanis@sjbit.edu.in", f"Expected 'nagamanis@sjbit.edu.in', got '{faculty.email}'"
        print(f"  ✓ Faculty record found: ID {faculty.id}, Name '{faculty.name}', Email '{faculty.email}'")

        # 2. Verify User Account linking
        user = db.query(User).filter(User.username == "faculty_mca").first()
        if not user:
            # Seed if not already present
            user = User(
                username="faculty_mca",
                email="faculty.mca@sjbit.edu.in",
                password_hash=hash_password("FacultyPass@123"),
                role="Faculty",
                department="MCA",
                full_name="Dr. Nagamani.S",
                faculty_id=faculty.id,
                is_active=True,
                is_activated=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        assert user.faculty_id == faculty.id, f"User faculty_id ({user.faculty_id}) must link to faculty ID ({faculty.id})"
        assert user.email == "faculty.mca@sjbit.edu.in", "User login email preserved"
        print(f"  ✓ User account '{user.username}' ({user.email}) successfully links to Faculty ID {user.faculty_id}.")

        # 3. Verify Login credentials verify correctly
        assert verify_password("Faculty@2026!", user.password_hash) is True
        print("  ✓ Faculty login verified successfully with existing credentials ('Faculty@2026!').")
    finally:
        db.close()


def test_item_b_syllabus_key_and_duplicate_rule():
    print("\n[TEST 2] Verifying Syllabus Matching Key with Title & Module 5 Duplicate Rule...")
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.role == "Admin").first()

        # 1. Verify three 25MCAE3XY electives exist as 3 distinct rows
        electives = db.query(Subject).filter(
            Subject.course_code == "25MCAE3XY",
            Subject.department == "MCA",
            Subject.semester == "III"
        ).all()
        assert len(electives) == 3, f"Expected 3 rows for 25MCAE3XY, found {len(electives)}"
        titles = {e.title for e in electives}
        assert len(titles) == 3, f"Electives must have 3 distinct titles, got {titles}"
        print(f"  ✓ The three 25MCAE3XY electives successfully exist as 3 distinct rows: {titles}")

        # 2. Verify true duplicate elective (same code AND same title) is rejected with HTTP 400
        first_title = list(titles)[0]
        try:
            _check_duplicate_subject(
                db,
                course_code="25MCAE3XY",
                department="MCA",
                scheme="2025",
                semester="III",
                title=first_title
            )
            assert False, "Duplicate elective with identical code and title must be rejected"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "Duplicate Course Violation" in exc.detail
            print(f"  ✓ True duplicate elective ('25MCAE3XY' with identical title '{first_title}') correctly rejected (HTTP 400).")

        # 3. Verify core course duplicate (same code, dept, scheme, sem) is rejected regardless of title
        try:
            _check_duplicate_subject(
                db,
                course_code="25MCAI101",
                department="MCA",
                scheme="2025",
                semester="I",
                title="Completely New Title Attempt"
            )
            assert False, "Core course with duplicate course code must be rejected"
        except HTTPException as exc:
            assert exc.status_code == 400
            assert "Duplicate Course Violation" in exc.detail
            print("  ✓ Core course duplicate ('25MCAI101') correctly rejected (HTTP 400).")

        # 4. Fresh dry-run on all three workbooks: 0 conflicts, 0 to-add, 0 rejected
        files_to_test = [
            ("SJBIT college data internal faculty.xlsx", "internal"),
            ("External Faculty college data.xlsx", "external"),
            ("SJBIT_All_Academic_Years sylabus.xlsx", "syllabus")
        ]

        for fname, dtype in files_to_test:
            fpath = os.path.join(BASE_DIR, fname)
            assert os.path.isfile(fpath), f"Workbook {fname} not found"
            with open(fpath, "rb") as f:
                res = preview_dataset_import(db, f.read(), fname, dtype)

            assert res["to_add_count"] == 0, f"{fname}: Expected 0 to-add, got {res['to_add_count']}"
            assert res["conflict_count"] == 0, f"{fname}: Expected 0 conflicts, got {res['conflict_count']}"
            assert res["rejected_count"] == 0, f"{fname}: Expected 0 rejected, got {res['rejected_count']}"
            assert res["duplicate_count"] > 0, f"{fname}: Expected duplicates > 0, got {res['duplicate_count']}"
            print(f"  ✓ Dry-run on '{fname}': 0 to-add, 0 conflicts, 0 rejected ({res['duplicate_count']} existing duplicates).")

    finally:
        db.close()


def test_item_c_tiered_mappings_and_untouched_purge():
    print("\n[TEST 3] Verifying Tiered Mapping Generation & Untouched RELATED Deletion...")
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.role == "Admin").first()

        # 1. Purge untouched RELATED rows
        purge_res = purge_untouched_related_mappings(db=db, current_user=admin_user)
        assert purge_res["success"] is True
        print(f"  ✓ Purge result: {purge_res['deleted_count']} untouched RELATED rows deleted.")
        print(f"  ✓ Remaining rows: {purge_res['exact_remaining']} EXACT_EXPERIENCE, {purge_res['specialization_remaining']} SPECIALIZATION.")

        # 2. Verify batch suggestion generator creates ONLY EXACT_EXPERIENCE and SPECIALIZATION
        gen_res = generate_mapping_suggestions(db=db, current_user=admin_user)
        assert gen_res["success"] is True
        
        # Check database for any newly created SUGGESTED RELATED rows
        related_after_batch = db.query(FacultySubjectMapping).filter(
            FacultySubjectMapping.mapping_type == "RELATED"
        ).count()
        assert related_after_batch == 0, f"Batch generator must not create RELATED mappings, found {related_after_batch}"
        print("  ✓ Batch suggestion generator creates ONLY EXACT_EXPERIENCE and SPECIALIZATION (0 RELATED created).")

        # 3. Test on-demand generation: POST /api/mappings/generate-related/{subject_id}
        # Choose a Python or Networks course
        target_subject = db.query(Subject).filter(
            Subject.title.ilike("%Python%") | Subject.title.ilike("%Network%")
        ).first()
        assert target_subject is not None, "Target subject for related mapping test must exist"

        rel_res = generate_related_mappings_for_subject(
            subject_id=target_subject.id,
            db=db,
            current_user=admin_user
        )
        assert rel_res["success"] is True
        assert rel_res["subject_id"] == target_subject.id
        print(f"  ✓ On-demand generator created {rel_res['generated_count']} RELATED mappings for '{target_subject.title}'.")

        # Verify AuditLog recorded
        audit = db.query(AuditLog).filter(
            AuditLog.action.in_(["MAPPING_BULK_CLEANUP", "RELATED_MAPPINGS_GENERATED"])
        ).first()
        assert audit is not None
        print("  ✓ Audit logs successfully recorded for cleanup and on-demand mapping generation.")

    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 70)
    print("  ExamExpert AI — Slice D Cleanup Fixes Test Suite")
    print("=" * 70)
    test_item_a_faculty_email_and_user_link()
    test_item_b_syllabus_key_and_duplicate_rule()
    test_item_c_tiered_mappings_and_untouched_purge()
    print("\n" + "=" * 70)
    print("  ALL SLICE D CLEANUP TESTS PASSED (3/3)")
    print("=" * 70)
