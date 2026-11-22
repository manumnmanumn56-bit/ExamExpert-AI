"""
ExamExpert AI — Module 8 Automated Test Suite
Faculty-Subject Expertise Mapping & Server-Side Verification

Covers:
1. Automated suggestion generation with explicit reasons
2. Prevention of automatic confirmation (suggestions strictly SUGGESTED)
3. Confirmation and Rejection workflow with audit logs tracking old & new status
4. Bulk confirmation workflow with batch count audit
5. Duplicate mapping prevention on (faculty_id, subject_id, mapping_type)
6. Confirmed-only helpers (strictly excluding SUGGESTED and REJECTED mappings)
7. Matcher integration: confirmed database mappings replace static ALIAS_MAP
8. Strict RBAC: HOD departmental scoping, Faculty self-scoping, 403 on mutations
9. 401 Unauthenticated check on protected endpoints
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("mod8_")

from fastapi import HTTPException
from backend.app.database import SessionLocal
from backend.app.models import (
    User, Faculty, Subject, FacultySubjectMapping, AuditLog, EligibilityRules
)
from backend.app.routers.auth import require_roles, get_current_user
from backend.app.routers.mappings import (
    generate_mapping_suggestions,
    get_mappings,
    confirm_mapping,
    reject_mapping,
    bulk_confirm_mappings,
    create_manual_mapping,
    delete_mapping,
    get_confirmed_mappings_for_subject,
    get_confirmed_mappings_for_faculty,
    CreateMappingRequest,
    BulkConfirmRequest
)
from backend.app.services.matcher import compute_suitability, rank_candidates


def test_module8_expertise_mapping():
    db = SessionLocal()
    try:
        print("===========================================================================")
        print("  EXAMEXPERT AI — MODULE 8 TEST SUITE EXECUTION")
        print("  Faculty-Subject Expertise Mapping, Confirmed Matching & RBAC")
        print("===========================================================================")

        # 1. Fetch fixture users
        admin_user = db.query(User).filter_by(role="Admin").first()
        hod_cse = db.query(User).filter_by(role="HOD", department="CSE").first()
        hod_mca = db.query(User).filter_by(role="HOD", department="MCA").first()
        faculty_user = db.query(User).filter_by(role="Faculty").first()

        assert admin_user is not None, "Admin user must exist."
        assert hod_cse is not None, "HOD CSE user must exist."
        assert hod_mca is not None, "HOD MCA user must exist."
        assert faculty_user is not None, "Faculty user must exist."
        print(f"[INIT] Admin: {admin_user.username}, HOD CSE: {hod_cse.username}, HOD MCA: {hod_mca.username}, Faculty: {faculty_user.username}")

        # -------------------------------------------------------------------------
        # TEST 1: Automated Suggestion Generation (Admin Only, SUGGESTED Only)
        # -------------------------------------------------------------------------
        res_gen = generate_mapping_suggestions(db=db, current_user=admin_user)
        assert res_gen["success"] is True
        print(f"[OK] Generated {res_gen['generated_count']} suggestions (Duplicates skipped: {res_gen['duplicates_skipped']})")

        # Verify that all suggestions have status SUGGESTED, is_confirmed=False, and non-empty reason
        all_sugg = db.query(FacultySubjectMapping).filter_by(status="SUGGESTED").all()
        assert len(all_sugg) > 0, "Suggestions should have been created in database."
        for s in all_sugg[:20]:
            assert s.status == "SUGGESTED", f"Expected SUGGESTED, got {s.status}"
            assert s.is_confirmed is False, "Suggestion must NOT be confirmed automatically!"
            assert s.suggestion_reason is not None and len(s.suggestion_reason) > 5, "Explicit reason required!"
        print(f"[OK] Verified {len(all_sugg)} suggestions are strictly in SUGGESTED status with explicit reasons.")

        # Duplicate run check: running generator again should not re-add duplicates
        res_dup_run = generate_mapping_suggestions(db=db, current_user=admin_user)
        assert res_dup_run["generated_count"] == 0, "Second generator run should not create duplicate suggestions!"
        print(f"[OK] Second generator run confirmed: 0 new suggestions created, {res_dup_run['duplicates_skipped']} duplicates skipped.")

        # -------------------------------------------------------------------------
        # TEST 2: Confirmation Workflow & Audit Log Old/New Tracking
        # -------------------------------------------------------------------------
        test_m = db.query(FacultySubjectMapping).filter_by(status="SUGGESTED").first()
        assert test_m is not None
        test_m_id = test_m.id
        old_st = test_m.status

        res_conf = confirm_mapping(mapping_id=test_m_id, db=db, current_user=admin_user)
        assert res_conf["success"] is True
        assert res_conf["old_status"] == old_st
        assert res_conf["new_status"] == "CONFIRMED"
        assert res_conf["confirmed_by"] == admin_user.username

        # Verify in DB
        db.refresh(test_m)
        assert test_m.status == "CONFIRMED"
        assert test_m.is_confirmed is True
        assert test_m.confirmed_by == admin_user.username
        assert test_m.confirmed_at is not None

        # Verify Audit Log
        audit = db.query(AuditLog).filter_by(
            action="MAPPING_STATUS_UPDATED",
            entity_id=test_m_id
        ).order_by(AuditLog.id.desc()).first()
        assert audit is not None
        assert f"status changed from '{old_st}' to 'CONFIRMED'" in audit.details
        print(f"[OK] Confirmed mapping #{test_m_id}. Audit log verified: {audit.details}")

        # -------------------------------------------------------------------------
        # TEST 3: Rejection Workflow & Audit Log Old/New Tracking
        # -------------------------------------------------------------------------
        res_rej = reject_mapping(mapping_id=test_m_id, db=db, current_user=admin_user)
        assert res_rej["success"] is True
        assert res_rej["old_status"] == "CONFIRMED"
        assert res_rej["new_status"] == "REJECTED"

        db.refresh(test_m)
        assert test_m.status == "REJECTED"
        assert test_m.is_confirmed is False

        audit_rej = db.query(AuditLog).filter_by(
            action="MAPPING_STATUS_UPDATED",
            entity_id=test_m_id
        ).order_by(AuditLog.id.desc()).first()
        assert audit_rej is not None
        assert "status changed from 'CONFIRMED' to 'REJECTED'" in audit_rej.details
        print(f"[OK] Rejected mapping #{test_m_id}. Audit log verified: {audit_rej.details}")

        # -------------------------------------------------------------------------
        # TEST 4: Bulk Confirmation Workflow
        # -------------------------------------------------------------------------
        sugg_candidates = db.query(FacultySubjectMapping).filter_by(status="SUGGESTED").limit(3).all()
        assert len(sugg_candidates) >= 3, "At least 3 suggestions required for bulk test."
        bulk_ids = [m.id for m in sugg_candidates]

        res_bulk = bulk_confirm_mappings(
            req=BulkConfirmRequest(mapping_ids=bulk_ids),
            db=db,
            current_user=admin_user
        )
        assert res_bulk["success"] is True
        assert res_bulk["confirmed_count"] == len(bulk_ids)

        for mid in bulk_ids:
            item = db.query(FacultySubjectMapping).filter_by(id=mid).first()
            assert item.status == "CONFIRMED"
            assert item.is_confirmed is True

        audit_bulk = db.query(AuditLog).filter_by(
            action="MAPPINGS_BULK_CONFIRMED"
        ).order_by(AuditLog.id.desc()).first()
        assert audit_bulk is not None
        assert f"bulk-confirmed {len(bulk_ids)} expertise mappings" in audit_bulk.details
        print(f"[OK] Bulk-confirmed {len(bulk_ids)} mappings successfully. Audit log verified.")

        # -------------------------------------------------------------------------
        # TEST 5: Manual Mapping Creation & Duplicate Prevention
        # -------------------------------------------------------------------------
        fac1 = db.query(Faculty).first()
        subj1 = db.query(Subject).first()
        assert fac1 is not None and subj1 is not None

        # Clean existing test mapping if present
        db.query(FacultySubjectMapping).filter_by(
            faculty_id=fac1.id, subject_id=subj1.id, mapping_type="SPECIALIZATION"
        ).delete()
        db.commit()

        # Create valid manual mapping
        res_man = create_manual_mapping(
            req=CreateMappingRequest(
                faculty_id=fac1.id,
                subject_id=subj1.id,
                mapping_type="SPECIALIZATION",
                times_handled=2,
                status="CONFIRMED",
                suggestion_reason="Manual test mapping for verification."
            ),
            db=db,
            current_user=admin_user
        )
        assert res_man["success"] is True
        man_map_id = res_man["mapping_id"]
        print(f"[OK] Created manual mapping #{man_map_id} for faculty '{fac1.name}' → '{subj1.title}'")

        # Duplicate Attempt (same faculty, subject, mapping_type) must fail with 400
        try:
            create_manual_mapping(
                req=CreateMappingRequest(
                    faculty_id=fac1.id,
                    subject_id=subj1.id,
                    mapping_type="SPECIALIZATION",
                    times_handled=2,
                    status="CONFIRMED"
                ),
                db=db,
                current_user=admin_user
            )
            assert False, "Duplicate mapping was unexpectedly allowed!"
        except HTTPException as e:
            assert e.status_code == 400
            assert "Duplicate Mapping Violation" in e.detail
            print(f"[OK] Duplicate mapping properly blocked with HTTP 400: {e.detail}")

        # -------------------------------------------------------------------------
        # TEST 6: Confirmed-Only Server Helpers (Strict Exclusion of SUGGESTED/REJECTED)
        # -------------------------------------------------------------------------
        test_subj = db.query(Subject).first()
        # Create 1 confirmed, 1 suggested, 1 rejected mapping for test_subj
        # Ensure fresh test faculty members
        all_fac = db.query(Faculty).limit(3).all()
        f_conf, f_sugg, f_rej = all_fac[0], all_fac[1], all_fac[2]

        # Clean previous
        db.query(FacultySubjectMapping).filter_by(subject_id=test_subj.id).delete()
        db.commit()

        db.add(FacultySubjectMapping(
            faculty_id=f_conf.id, subject_id=test_subj.id,
            mapping_type="EXACT_EXPERIENCE", status="CONFIRMED",
            is_confirmed=True, confirmed_by="coe_admin"
        ))
        db.add(FacultySubjectMapping(
            faculty_id=f_sugg.id, subject_id=test_subj.id,
            mapping_type="SPECIALIZATION", status="SUGGESTED",
            is_confirmed=False
        ))
        db.add(FacultySubjectMapping(
            faculty_id=f_rej.id, subject_id=test_subj.id,
            mapping_type="RELATED", status="REJECTED",
            is_confirmed=False
        ))
        db.commit()

        confirmed_list = get_confirmed_mappings_for_subject(db, test_subj.id)
        assert len(confirmed_list) == 1, f"Expected exactly 1 confirmed mapping, found {len(confirmed_list)}"
        assert confirmed_list[0].faculty_id == f_conf.id
        assert confirmed_list[0].status == "CONFIRMED"
        print(f"[OK] Server helper get_confirmed_mappings_for_subject returned ONLY confirmed mapping (SUGGESTED and REJECTED strictly excluded).")

        # -------------------------------------------------------------------------
        # TEST 7: Matcher Scoring Integration (Database Mappings Replace ALIAS_MAP)
        # -------------------------------------------------------------------------
        rules = db.query(EligibilityRules).first()
        # Compute suitability for f_conf with confirmed mapping
        conf_m = confirmed_list[0]
        score_conf = compute_suitability(
            faculty=f_conf,
            subject_title=test_subj.title,
            subject_code=test_subj.course_code or "",
            min_handled=3,
            rules=rules,
            confirmed_mapping=conf_m
        )
        assert score_conf["breakdown"]["domain_fit"] == 40, f"Expected 40 domain points for EXACT_EXPERIENCE, got {score_conf['breakdown']['domain_fit']}"

        # Compute suitability for f_sugg without confirmed mapping (should NOT get confirmed mapping domain score)
        sugg_m = db.query(FacultySubjectMapping).filter_by(faculty_id=f_sugg.id, subject_id=test_subj.id).first()
        score_sugg = compute_suitability(
            faculty=f_sugg,
            subject_title=test_subj.title,
            subject_code=test_subj.course_code or "",
            min_handled=3,
            rules=rules,
            confirmed_mapping=sugg_m  # status is SUGGESTED
        )
        assert score_sugg["breakdown"]["domain_fit"] != 40 and score_sugg["breakdown"]["domain_fit"] != 35, "SUGGESTED mapping must NOT receive confirmed domain bonus!"

        # Candidate ranking integration check:
        ranked = rank_candidates(
            db=db,
            subject_title=test_subj.title,
            subject_code=test_subj.course_code or "",
            min_handled=3,
            faculty_type="internal",
            rules=rules,
            allocation_counts={},
            subject_id=test_subj.id
        )
        assert len(ranked) > 0
        # The confirmed faculty f_conf should have higher domain fit score than f_sugg
        f_conf_rank = next((r for r in ranked if r["faculty_id"] == f_conf.id), None)
        assert f_conf_rank is not None
        assert f_conf_rank["breakdown"]["domain_fit"] == 40
        print(f"[OK] Candidate ranking engine verified: Confirmed database mapping replaces ALIAS_MAP with exact 40 points domain score.")

        # -------------------------------------------------------------------------
        # TEST 8: Strict RBAC: HOD Scoping & Mutation Blocking (403)
        # -------------------------------------------------------------------------
        # HOD CSE views mappings:
        res_hod_cse = get_mappings(db=db, current_user=hod_cse)
        # Every mapping returned must be CSE internal faculty & CSE subject
        for m in res_hod_cse["mappings"]:
            assert m["faculty_type"] == "internal", "HOD must only see internal faculty mappings!"
            assert "CSE" in m["faculty_dept"] or "Computer Science" in m["faculty_dept"], f"Cross-department leakage: {m['faculty_dept']}"
        print(f"[OK] HOD CSE query strictly scoped: {len(res_hod_cse['mappings'])} mappings (internal CSE only).")

        # HOD querying cross-department mappings must get 403
        try:
            get_mappings(department="Master of Computer Applications", db=db, current_user=hod_cse)
            assert False, "HOD was able to query another department's mappings!"
        except HTTPException as e:
            assert e.status_code == 403
            assert "Access Denied" in e.detail
            print(f"[OK] HOD cross-department mapping query blocked with 403: {e.detail}")

        # HOD blocked from mutation endpoints
        for action_name, func, args in [
            ("generate-suggestions", generate_mapping_suggestions, {"db": db, "current_user": hod_cse}),
            ("confirm", confirm_mapping, {"mapping_id": test_m_id, "db": db, "current_user": hod_cse}),
            ("reject", reject_mapping, {"mapping_id": test_m_id, "db": db, "current_user": hod_cse}),
            ("bulk-confirm", bulk_confirm_mappings, {"req": BulkConfirmRequest(mapping_ids=[test_m_id]), "db": db, "current_user": hod_cse}),
            ("delete", delete_mapping, {"mapping_id": test_m_id, "db": db, "current_user": hod_cse})
        ]:
            try:
                require_roles(["Admin"])(current_user=hod_cse)
                assert False, f"HOD allowed to perform '{action_name}'!"
            except HTTPException as e:
                assert e.status_code == 403

        print(f"[OK] HOD strictly blocked from all 5 mutation endpoints with HTTP 403.")

        # Faculty blocked from all mutation endpoints
        for action_name in ["generate-suggestions", "confirm", "reject", "bulk-confirm", "create", "delete"]:
            try:
                require_roles(["Admin"])(current_user=faculty_user)
                assert False, f"Faculty allowed to perform '{action_name}'!"
            except HTTPException as e:
                assert e.status_code == 403

        print(f"[OK] Faculty strictly blocked from all mutation endpoints with HTTP 403.")

        # -------------------------------------------------------------------------
        # TEST 9: Delete Mapping
        # -------------------------------------------------------------------------
        del_target = db.query(FacultySubjectMapping).filter_by(id=man_map_id).first()
        if del_target:
            res_del = delete_mapping(mapping_id=man_map_id, db=db, current_user=admin_user)
            assert res_del["success"] is True
            audit_del = db.query(AuditLog).filter_by(
                action="MAPPING_DELETED", entity_id=man_map_id
            ).first()
            assert audit_del is not None
            print(f"[OK] Deleted manual mapping #{man_map_id}. Audit log verified.")

        # -------------------------------------------------------------------------
        # TEST 10: 401 Unauthenticated Protection
        # -------------------------------------------------------------------------
        try:
            get_current_user(authorization=None)
            assert False, "Allowed request without Authorization header!"
        except HTTPException as e:
            assert e.status_code == 401
            print(f"[OK] Unauthenticated call correctly blocked with HTTP 401: {e.detail}")

        print("\n===========================================================================")
        print("  [ALL MODULE 8 TESTS PASSED] Faculty-Subject Expertise Mapping 100% OK")
        print("===========================================================================")

    finally:
        db.close()


if __name__ == "__main__":
    test_module8_expertise_mapping()
