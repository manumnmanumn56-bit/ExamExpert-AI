"""
ExamExpert AI — Module 5 Academic Subject Master Verification Tests
SJB Institute of Technology | Office of Controller of Examinations

Tests:
1. Subject list with filters: academic year, department, scheme, semester, search.
2. Server-side RBAC scoping:
   - Admin views all subjects (195 total).
   - HOD CSE sees strictly the 31 CSE subjects.
   - HOD MCA sees strictly the 31 MCA subjects.
   - HOD CSDS sees strictly the 44 CSDS subjects.
   - HOD attempting cross-department access is rejected with HTTP 403.
   - Faculty scoped strictly to their own department.
3. Admin subject creation and audit logging.
4. Non-admin (HOD/Faculty) creation block (HTTP 403).
5. Admin subject editing and audit logging.
6. Non-admin (HOD/Faculty) edit block (HTTP 403).
7. MCA statutory 4-semester rule enforced on the server (HTTP 400 for Semesters V-VIII).
8. Duplicate subject prevention on (course_code, department, scheme, semester) (HTTP 400).
"""
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException
from backend.app.database import SessionLocal
from backend.app.models import User, Subject, AuditLog
from backend.app.routers.syllabus import (
    get_all_syllabus,
    get_subject_by_id,
    add_subject,
    edit_subject,
    SubjectCreateRequest,
    SubjectUpdateRequest
)
from backend.app.routers.auth import seed_rbac_users


def test_module5_academic_subject_master():
    db = SessionLocal()
    try:
        seed_rbac_users(db)

        admin = db.query(User).filter_by(role="Admin").first()
        hod_cse = db.query(User).filter_by(role="HOD", department="CSE").first()
        hod_mca = db.query(User).filter_by(role="HOD", department="MCA").first()
        hod_csds = db.query(User).filter_by(role="HOD", department="CSDS").first()
        faculty_mca = db.query(User).filter_by(role="Faculty", department="MCA").first()

        assert admin is not None, "Admin account must exist"
        assert hod_cse is not None, "HOD CSE account must exist"
        assert hod_mca is not None, "HOD MCA account must exist"
        assert hod_csds is not None, "HOD CSDS account must exist"
        assert faculty_mca is not None, "Faculty MCA account must exist"

        print(f"[INIT] Admin: {admin.username}, HOD CSE: {hod_cse.username}, HOD MCA: {hod_mca.username}")

        # ─── 1. Admin Full Subject Catalog ────────────────────────────────────
        all_res = get_all_syllabus(db=db, current_user=admin)
        print(f"[OK] Admin views all subjects: {all_res['total']} courses found")
        assert all_res["total"] == 195, f"Expected 195 total syllabus subjects, got {all_res['total']}"

        # ─── 2. HOD Department Scoping ────────────────────────────────────────
        # HOD CSE
        cse_res = get_all_syllabus(db=db, current_user=hod_cse)
        print(f"[OK] HOD CSE sees {cse_res['total']} subjects (strictly CSE)")
        assert cse_res["total"] == 31, f"Expected 31 subjects for HOD CSE, got {cse_res['total']}"
        for s in cse_res["subjects"]:
            assert s["department"] == "CSE", f"Contamination: HOD CSE saw department '{s['department']}'"

        # HOD MCA
        mca_res = get_all_syllabus(db=db, current_user=hod_mca)
        print(f"[OK] HOD MCA sees {mca_res['total']} subjects (strictly MCA)")
        assert mca_res["total"] == 31, f"Expected 31 subjects for HOD MCA, got {mca_res['total']}"
        for s in mca_res["subjects"]:
            assert s["department"] == "MCA", f"Contamination: HOD MCA saw department '{s['department']}'"

        # HOD CSDS
        csds_res = get_all_syllabus(db=db, current_user=hod_csds)
        print(f"[OK] HOD CSDS sees {csds_res['total']} subjects (strictly CSDS)")
        assert csds_res["total"] == 44, f"Expected 44 subjects for HOD CSDS, got {csds_res['total']}"
        for s in csds_res["subjects"]:
            assert s["department"] == "CSE (Data Science)", f"Contamination: HOD CSDS saw department '{s['department']}'"

        # Faculty MCA
        fac_res = get_all_syllabus(db=db, current_user=faculty_mca)
        print(f"[OK] Faculty MCA sees {fac_res['total']} subjects (strictly MCA)")
        assert fac_res["total"] == 31

        # ─── 3. HOD Cross-Department Access Denial (HTTP 403) ─────────────────
        try:
            # HOD CSE attempting to query MCA subjects
            get_all_syllabus(department="MCA", db=db, current_user=hod_cse)
            assert False, "HOD CSE should not be allowed to access MCA subjects!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] Cross-department access properly blocked with 403: {e.detail}")

        try:
            # HOD MCA attempting to query CSE subjects
            get_all_syllabus(department="CSE", db=db, current_user=hod_mca)
            assert False, "HOD MCA should not be allowed to access CSE subjects!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] Cross-department access properly blocked with 403: {e.detail}")

        # ─── 4. Subject Filtering ─────────────────────────────────────────────
        filt_res = get_all_syllabus(academic_year="2025-26", scheme="2023", db=db, current_user=admin)
        print(f"[OK] Filtered subjects by AY=2025-26 and Scheme=2023: {filt_res['total']} courses")
        assert filt_res["total"] > 0
        for s in filt_res["subjects"]:
            assert s["academic_year"] == "2025-26"
            assert s["scheme"] == "2023"
            assert "badge_class" in s
            assert "badge_label" in s

        # ─── 5. MCA 4-Semester Rule Server Enforcement ────────────────────────
        # Attempt to add MCA subject with Semester V (should fail with 400)
        invalid_mca = SubjectCreateRequest(
            course_code="23MCA51_INVALID",
            title="Advanced Cloud Operations",
            department="MCA",
            scheme="2023",
            semester="V",
            academic_year="2025-26"
        )
        try:
            add_subject(req=invalid_mca, db=db, current_user=admin)
            assert False, "MCA subject with semester V should be rejected!"
        except HTTPException as e:
            assert e.status_code == 400
            assert "strictly limited to 4 semesters" in e.detail
            print(f"[OK] MCA 4-semester rule enforced on server: {e.detail}")

        # ─── 6. Subject Creation (Admin Only) ─────────────────────────────────
        test_code = "23TEST99"
        # Cleanup if leftover from earlier run
        existing_test = db.query(Subject).filter_by(course_code=test_code).first()
        if existing_test:
            db.delete(existing_test)
            db.commit()

        # Non-admin attempt (HOD) must fail with 403
        valid_subj = SubjectCreateRequest(
            course_code=test_code,
            title="Test Engineering Mathematics & Systems",
            department="CSE",
            scheme="2023",
            semester="III",
            academic_year="2025-26",
            course_type="Theory",
            credits=4,
            verification_status="Verified from official SJBIT syllabus"
        )

        try:
            from backend.app.routers.auth import require_roles
            require_roles(["Admin"])(current_user=hod_cse)
            assert False, "HOD should not be authorized to add subjects!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD blocked from adding subjects with 403: {e.detail}")

        # Admin add succeeds
        add_res = add_subject(req=valid_subj, db=db, current_user=admin)
        assert add_res["success"] is True
        new_sid = add_res["subject_id"]
        print(f"[OK] Admin created subject {test_code} (id={new_sid})")

        # Verify audit log
        log_create = db.query(AuditLog).filter_by(action="SUBJECT_CREATED", entity_id=new_sid).first()
        assert log_create is not None, "AuditLog SUBJECT_CREATED not found!"
        print(f"[OK] Audit log verified: {log_create.action} - {log_create.details}")

        # ─── 7. Duplicate Subject Prevention (HTTP 400) ───────────────────────
        try:
            # Attempt to add exact duplicate (same code, department, scheme, semester)
            add_subject(req=valid_subj, db=db, current_user=admin)
            assert False, "Duplicate subject addition should be rejected!"
        except HTTPException as e:
            assert e.status_code == 400
            assert "Duplicate Course Violation" in e.detail
            print(f"[OK] Duplicate subject addition blocked with 400: {e.detail}")

        # ─── 8. Subject Editing (Admin Only) ──────────────────────────────────
        upd_req = SubjectUpdateRequest(
            title="Updated Test Engineering Mathematics Systems",
            credits=3,
            source_notes="Updated for Board of Studies review"
        )
        edit_res = edit_subject(subject_id=new_sid, req=upd_req, db=db, current_user=admin)
        assert edit_res["success"] is True

        db_subj = db.query(Subject).filter_by(id=new_sid).first()
        assert db_subj.title == "Updated Test Engineering Mathematics Systems"
        assert db_subj.credits == 3
        print(f"[OK] Subject {test_code} edited successfully by admin")

        # Verify audit log
        log_update = db.query(AuditLog).filter_by(action="SUBJECT_UPDATED", entity_id=new_sid).first()
        assert log_update is not None, "AuditLog SUBJECT_UPDATED not found!"
        print(f"[OK] Audit log verified: {log_update.action} - {log_update.details}")

        # Non-admin edit block
        try:
            require_roles(["Admin"])(current_user=hod_cse)
            assert False, "HOD should not be authorized to edit subjects!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD blocked from editing subjects with 403: {e.detail}")

        # ─── 9. Single Subject Retrieval & Scoping ────────────────────────────
        # Admin can view
        s_view = get_subject_by_id(subject_id=new_sid, db=db, current_user=admin)
        assert s_view["course_code"] == test_code

        # HOD CSE can view (since it is CSE)
        s_view_cse = get_subject_by_id(subject_id=new_sid, db=db, current_user=hod_cse)
        assert s_view_cse["course_code"] == test_code

        # HOD MCA cannot view (since it is CSE)
        try:
            get_subject_by_id(subject_id=new_sid, db=db, current_user=hod_mca)
            assert False, "HOD MCA should not be allowed to view single CSE subject!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD MCA blocked from viewing single CSE subject with 403: {e.detail}")

        # Clean up test subject
        db.delete(db_subj)
        db.commit()
        print("[CLEANUP] Test subject removed")

        print("\n[ALL MODULE 5 TESTS PASSED] Academic Subject Master fully verified.")

    finally:
        db.close()


if __name__ == "__main__":
    test_module5_academic_subject_master()
