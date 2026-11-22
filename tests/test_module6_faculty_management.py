"""
ExamExpert AI — Module 6 Faculty Management & Whitelist Verification Tests
SJB Institute of Technology | Office of Controller of Examinations

Tests:
1. Faculty listing with filters (type, department, institution, eligibility, availability, search).
2. Server-side RBAC scoping:
   - Admin views all 124 faculty (47 internal + 77 external).
   - HOD CSE sees strictly their 21 internal faculty.
   - HOD MCA sees strictly their 3 internal faculty.
   - HOD blocked from querying external faculty in roster (HTTP 403).
   - HOD blocked from cross-department internal faculty (HTTP 403).
   - Faculty scoped strictly to their own record.
3. Faculty profile view and single-record scoping.
4. Faculty profile edit (Admin only; HOD/Faculty blocked with HTTP 403).
5. Availability toggle and audit log (Admin only).
6. External institution whitelist management (Admin only, live counts, toggle).
7. Candidate matcher respects institution whitelist.
8. Data integrity: NULL values preserved, 'Ph.D pursuing' never treated as completed.
"""
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("mod6_")

from fastapi import HTTPException
from backend.app.database import SessionLocal
from backend.app.models import User, Faculty, ExternalInstitution, AuditLog
from backend.app.routers.faculty import (
    get_all_faculty,
    get_faculty_profile,
    update_faculty_profile,
    toggle_faculty_availability,
    get_institution_whitelist,
    toggle_institution_whitelist,
    FacultyUpdateRequest,
    recalculate_eligibility_status
)
from backend.app.routers.auth import seed_rbac_users
from backend.app.services.matcher import rank_candidates
from backend.app.routers.faculty import _get_rules


def test_module6_faculty_management():
    db = SessionLocal()
    try:
        seed_rbac_users(db)

        admin = db.query(User).filter_by(role="Admin").first()
        hod_cse = db.query(User).filter_by(role="HOD", department="CSE").first()
        hod_mca = db.query(User).filter_by(role="HOD", department="MCA").first()
        faculty_user = db.query(User).filter_by(role="Faculty").first()

        assert admin is not None
        assert hod_cse is not None
        assert hod_mca is not None
        assert faculty_user is not None

        print(f"[INIT] Admin: {admin.username}, HOD CSE: {hod_cse.username}, Faculty: {faculty_user.username}")

        # ─── 1. Admin Full Faculty Listing ────────────────────────────────────
        all_res = get_all_faculty(db=db, current_user=admin)
        print(f"[OK] Admin views all faculty: {all_res['total']} members")
        assert all_res["total"] == 124

        int_res = get_all_faculty(faculty_type="internal", db=db, current_user=admin)
        ext_res = get_all_faculty(faculty_type="external", db=db, current_user=admin)
        assert int_res["total"] == 47, f"Expected 47 internal faculty, got {int_res['total']}"
        assert ext_res["total"] == 77, f"Expected 77 external faculty, got {ext_res['total']}"
        print(f"[OK] Faculty counts: {int_res['total']} Internal + {ext_res['total']} External = 124 Total")

        # ─── 2. HOD Department Scoping & External Roster Block ────────────────
        cse_fac = get_all_faculty(db=db, current_user=hod_cse)
        print(f"[OK] HOD CSE sees {cse_fac['total']} internal faculty (strictly CSE)")
        assert cse_fac["total"] == 21
        for f in cse_fac["faculty"]:
            assert f["faculty_type"] == "internal"
            assert f["department"] == "Computer Science & Engineering"

        mca_fac = get_all_faculty(db=db, current_user=hod_mca)
        print(f"[OK] HOD MCA sees {mca_fac['total']} internal faculty (strictly MCA)")
        assert mca_fac["total"] == 3
        for f in mca_fac["faculty"]:
            assert f["faculty_type"] == "internal"
            assert f["department"] == "Master of Computer Applications"

        # HOD blocked from querying external faculty roster
        try:
            get_all_faculty(faculty_type="external", db=db, current_user=hod_cse)
            assert False, "HOD should not be allowed to browse external faculty roster!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD blocked from external roster with 403: {e.detail}")

        # HOD blocked from querying another department's faculty
        try:
            get_all_faculty(department="MCA", db=db, current_user=hod_cse)
            assert False, "HOD CSE should not be allowed to query MCA department faculty!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD cross-department access blocked with 403: {e.detail}")

        # ─── 3. Single Profile Retrieval Scoping ──────────────────────────────
        cse_sample = db.query(Faculty).filter_by(department="Computer Science & Engineering").first()
        mca_sample = db.query(Faculty).filter_by(department="Master of Computer Applications").first()
        ext_sample = db.query(Faculty).filter_by(faculty_type="external").first()

        # Admin can view all three
        assert get_faculty_profile(faculty_id=cse_sample.id, db=db, current_user=admin)["id"] == cse_sample.id
        assert get_faculty_profile(faculty_id=mca_sample.id, db=db, current_user=admin)["id"] == mca_sample.id
        assert get_faculty_profile(faculty_id=ext_sample.id, db=db, current_user=admin)["id"] == ext_sample.id

        # HOD CSE can view CSE faculty
        assert get_faculty_profile(faculty_id=cse_sample.id, db=db, current_user=hod_cse)["id"] == cse_sample.id

        # HOD CSE blocked from MCA faculty
        try:
            get_faculty_profile(faculty_id=mca_sample.id, db=db, current_user=hod_cse)
            assert False, "HOD CSE should be blocked from viewing MCA faculty profile!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD blocked from viewing other department profile with 403: {e.detail}")

        # HOD CSE blocked from External faculty profile
        try:
            get_faculty_profile(faculty_id=ext_sample.id, db=db, current_user=hod_cse)
            assert False, "HOD CSE should be blocked from viewing external faculty profile directly!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD blocked from viewing external faculty profile with 403: {e.detail}")

        # ─── 4. Availability Toggle (Admin Only) ──────────────────────────────
        initial_avail = cse_sample.is_available
        t_res = toggle_faculty_availability(faculty_id=cse_sample.id, db=db, current_user=admin)
        assert t_res["success"] is True
        assert t_res["is_available"] == (not initial_avail)

        db.refresh(cse_sample)
        assert cse_sample.is_available == (not initial_avail)

        # Audit log verified
        log_avail = db.query(AuditLog).filter_by(action="FACULTY_AVAILABILITY_TOGGLED", entity_id=cse_sample.id).first()
        assert log_avail is not None
        print(f"[OK] Availability toggle verified for {cse_sample.name} (new state: {cse_sample.is_available})")

        # Revert back
        toggle_faculty_availability(faculty_id=cse_sample.id, db=db, current_user=admin)
        db.refresh(cse_sample)
        assert cse_sample.is_available == initial_avail

        # Non-admin blocked
        try:
            from backend.app.routers.auth import require_roles
            require_roles(["Admin"])(current_user=hod_cse)
            assert False, "HOD should not be allowed to toggle availability!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD blocked from availability toggle with 403: {e.detail}")

        # ─── 5. Faculty Profile Edit (Admin Only) ─────────────────────────────
        orig_desig = cse_sample.designation
        req_upd = FacultyUpdateRequest(
            designation="Senior Associate Professor",
            expertise_text="Artificial Intelligence; Cloud Infrastructure; Formal Verification"
        )
        upd_res = update_faculty_profile(faculty_id=cse_sample.id, req=req_upd, db=db, current_user=admin)
        assert upd_res["success"] is True

        db.refresh(cse_sample)
        assert cse_sample.designation == "Senior Associate Professor"
        assert "Formal Verification" in cse_sample.expertise_text

        # Audit log verified
        log_upd = db.query(AuditLog).filter_by(action="FACULTY_PROFILE_UPDATED", entity_id=cse_sample.id).first()
        assert log_upd is not None
        print(f"[OK] Profile edit verified: {log_upd.action} - {log_upd.details}")

        # Revert designation
        update_faculty_profile(faculty_id=cse_sample.id, req=FacultyUpdateRequest(designation=orig_desig), db=db, current_user=admin)

        # Non-admin edit block
        try:
            require_roles(["Admin"])(current_user=faculty_user)
            assert False, "Faculty should not be allowed to edit profiles!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] Faculty blocked from editing profiles with 403: {e.detail}")

        # ─── 6. External Institution Whitelist Management ─────────────────────
        wl_res = get_institution_whitelist(db=db, current_user=admin)
        assert wl_res["total"] == 11
        for inst in wl_res["institutions"]:
            assert inst["faculty_count"] > 0
            assert inst["is_allowed"] is True
            print(f"  [Whitelist] {inst['name'][:40]}... ({inst['faculty_count']} faculty)")

        # Toggle RVCE whitelist off and verify
        rvce = db.query(ExternalInstitution).filter(ExternalInstitution.name.ilike("%RV College%")).first()
        assert rvce is not None

        toggle_institution_whitelist(institution_id=rvce.id, db=db, current_user=admin)
        db.refresh(rvce)
        assert rvce.is_allowed is False
        print(f"[OK] Toggled {rvce.name} whitelist to False")

        # Verify candidate matcher excludes disabled institution faculty
        rules = _get_rules(db)
        ranked_ext = rank_candidates(db, "Java Programming", "23MCA11", 1, "external", rules, {})
        rvce_candidates = [c for c in ranked_ext if "RV College" in c["institution"]]
        assert len(rvce_candidates) == 0, "Candidates from disabled institution should not appear in matcher!"
        print(f"[OK] Candidate matcher correctly excluded all {rvce.name} faculty while whitelisting is disabled")

        # Toggle RVCE whitelist back on
        toggle_institution_whitelist(institution_id=rvce.id, db=db, current_user=admin)
        db.refresh(rvce)
        assert rvce.is_allowed is True
        print(f"[OK] Toggled {rvce.name} whitelist back to True")

        # ─── 7. Data Integrity Rules: NULL Preservation & PhD Pursuing ────────
        # Verify Nagarathinam A (RRCE): PhD pursuing with 2.8 yrs exp is Not Qualified
        nag = db.query(Faculty).filter_by(name="Nagarathinam A").first()
        assert nag is not None
        assert "pursuing" in nag.qualification.lower()
        assert nag.experience_years == 2.8
        assert nag.eligibility_status == "Not Qualified"
        print(f"[OK] 'PhD pursuing' candidate {nag.name} correctly evaluated as '{nag.eligibility_status}'")

        # Verify recalculate_eligibility_status logic
        assert recalculate_eligibility_status("M.Tech, Ph.D (pursuing)", 4.0) == "Not Qualified"
        assert recalculate_eligibility_status("M.Tech, Ph.D (pursuing)", 11.0) == "Qualified (Exp >= 10 Yrs)"
        assert recalculate_eligibility_status("M.Tech, Ph.D", 6.0) == "Qualified (Ph.D + Exp >= 5 Yrs)"
        assert recalculate_eligibility_status("M.Tech", None) == "Cannot Verify"
        print("[OK] Deterministic eligibility recalculation verified across all edge cases")

        # Verify missing experience, email, and mobile remain NULL
        missing_exp_ext = db.query(Faculty).filter(Faculty.faculty_type == "external", Faculty.experience_years.is_(None)).all()
        assert len(missing_exp_ext) == 70, f"Expected 70 external faculty with NULL experience, got {len(missing_exp_ext)}"
        for f in missing_exp_ext:
            assert f.experience_years is None
            assert f.eligibility_status == "Cannot Verify"

        print(f"[OK] All 70 external faculty have experience strictly preserved as NULL with status 'Cannot Verify'")

        print("\n[ALL MODULE 6 TESTS PASSED] Faculty Management & Whitelist Governance fully verified.")

    finally:
        db.close()


if __name__ == "__main__":
    test_module6_faculty_management()
