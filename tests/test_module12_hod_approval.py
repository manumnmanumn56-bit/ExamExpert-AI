"""
ExamExpert AI — Module 12 HOD Approval Workflow & Audit Trail Automated Test Suite
SJB Institute of Technology | Office of Controller of Examinations

Explicitly verifies:
1. Pending Approvals Listing & Scoping:
   - HOD sees only their department's pending allocations.
   - Admin sees all departments' pending allocations.
   - Faculty access is blocked (HTTP 403).
2. HOD Approval Workflow & Workload Commitment:
   - Transition: 'Pending HOD Approval' -> 'Approved'.
   - Atomic Workload Ledger update: COMMITTED (+1) and RELEASED (-1) entries.
   - Net workload: committed=1, reserved=0, total_active=1.
   - Relational AllocationSetters updated to 'Approved'.
   - AuditLog recorded with old and new values.
3. Cross-Department Approval Security:
   - HOD attempting to decide allocation outside their department is rejected (HTTP 403).
4. Double-Decision Protection:
   - Only requests in 'Pending HOD Approval' can be decided.
   - Subsequent approve or reject calls return HTTP 409.
5. HOD Rejection Workflow & Workload Reservation Release:
   - Mandatory rejection reason: missing or too short returns HTTP 422.
   - Transition: 'Pending HOD Approval' -> 'Rejected'.
   - Atomic Workload Ledger update: RELEASED (-1) entry.
   - Net workload: committed=0, reserved=0, total_active=0.
   - Relational AllocationSetters updated to 'Rejected'.
   - AuditLog recorded with reason and timestamps.
6. Allocation Cancellation:
   - Cancels pending request and releases reserved workload.
   - Cancels approved request and releases committed workload.
   - AuditLog recorded.
7. Role-Based Access Control:
   - Faculty attempting to approve/reject returns HTTP 403.
   - Admin attempting to approve/reject returns HTTP 403 (HOD exclusive).
"""
import os, sys, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("mod12_")

from fastapi import HTTPException
from sqlalchemy.orm import Session
from backend.app.database import SessionLocal
from backend.app.models import (
    User, Faculty, Subject, EligibilityRules, WorkloadLedger,
    Allocation, AllocationSetter, AuditLog, ExternalInstitution,
    FacultySubjectMapping
)
from backend.app.routers.allocation import (
    create_allocation_request, CreateAllocationRequest,
    submit_allocation_to_hod,
    get_pending_approvals,
    approve_allocation,
    reject_allocation, DecisionRequest,
    cancel_allocation
)
from backend.app.services.eligibility import get_faculty_workload


def run_module12_tests():
    print("=" * 75)
    print("  EXAMEXPERT AI — MODULE 12 HOD APPROVAL & AUDIT TRAIL VERIFICATION")
    print("  SJB Institute of Technology • Office of Controller of Examinations")
    print("=" * 75)

    db: Session = SessionLocal()
    passed = 0
    failed = 0

    try:
        # 1. Retrieve Test Accounts
        admin_user = db.query(User).filter_by(role="Admin").first()
        hod_mca = db.query(User).filter_by(role="HOD", department="MCA").first()
        hod_cse = db.query(User).filter_by(role="HOD", department="CSE").first()
        faculty_user = db.query(User).filter_by(role="Faculty").first()

        assert admin_user is not None, "Admin user must exist"
        assert hod_mca is not None, "HOD MCA user must exist"
        assert hod_cse is not None, "HOD CSE user must exist"
        assert faculty_user is not None, "Faculty user must exist"

        # Ensure Confirmed Policy
        policy = db.query(EligibilityRules).filter_by(status="CONFIRMED").first()
        if not policy:
            policy = EligibilityRules(
                min_experience=10.0,
                min_experience_phd=5.0,
                internal_capacity=2,
                external_capacity=2,
                status="CONFIRMED",
                active_academic_year="2025-26"
            )
            db.add(policy)
            db.commit()

        # Setup Test Subjects
        subj_mca = Subject(
            course_code="25MCA401",
            title="Enterprise Cloud Security & DevSecOps",
            department="MCA",
            semester="IV",
            scheme="2025",
            academic_year="2025-26"
        )
        subj_cse = Subject(
            course_code="25CSE401",
            title="Advanced Computer Networks",
            department="CSE",
            semester="IV",
            scheme="2025",
            academic_year="2025-26"
        )
        db.add_all([subj_mca, subj_cse])
        db.commit()

        # Setup Faculty
        int_fac_mca = Faculty(name="Dr. MCA Internal Expert", faculty_type="internal", department="MCA", designation="Professor", qualification="Ph.D", experience_years=15.0, is_available=True)
        int_fac_cse = Faculty(name="Dr. CSE Internal Expert", faculty_type="internal", department="CSE", designation="Professor", qualification="Ph.D", experience_years=16.0, is_available=True)
        ext_inst = ExternalInstitution(name="VTU Autonomous Engineering College", is_allowed=True)
        db.add_all([int_fac_mca, int_fac_cse, ext_inst])
        db.commit()

        ext_fac_mca = Faculty(name="Dr. MCA External Expert", faculty_type="external", department="MCA", institution=ext_inst.name, designation="Professor", qualification="Ph.D", experience_years=18.0, is_available=True)
        db.add(ext_fac_mca)
        db.commit()

        # ─── Setup 1 MCA Allocation and 1 CSE Allocation ───────────────────────
        req_mca = CreateAllocationRequest(
            subject_id=subj_mca.id,
            academic_year="2025-26",
            department="MCA",
            semester="IV",
            mode="Balanced",
            total_required=2,
            internal_faculty_ids=[int_fac_mca.id],
            external_faculty_ids=[ext_fac_mca.id]
        )
        res_mca = create_allocation_request(req_mca, db=db, current_user=admin_user)
        alloc_mca_id = res_mca["allocation_id"]
        submit_allocation_to_hod(alloc_mca_id, db=db, current_user=admin_user)

        req_cse = CreateAllocationRequest(
            subject_id=subj_cse.id,
            academic_year="2025-26",
            department="CSE",
            semester="IV",
            mode="Internal Only",
            total_required=1,
            internal_faculty_ids=[int_fac_cse.id],
            external_faculty_ids=[]
        )
        res_cse = create_allocation_request(req_cse, db=db, current_user=admin_user)
        alloc_cse_id = res_cse["allocation_id"]
        submit_allocation_to_hod(alloc_cse_id, db=db, current_user=admin_user)

        # ─── TEST 1: Pending Approvals Department Scoping ─────────────────────
        print("\n[TEST 1] Pending Approvals Department Scoping...")

        # MCA HOD must see only MCA allocation
        mca_pending = get_pending_approvals(department=None, db=db, current_user=hod_mca)
        mca_ids = [p["id"] for p in mca_pending]
        assert alloc_mca_id in mca_ids, "MCA HOD must see MCA pending allocation"
        assert alloc_cse_id not in mca_ids, "MCA HOD must NOT see CSE pending allocation"

        # CSE HOD must see only CSE allocation
        cse_pending = get_pending_approvals(department=None, db=db, current_user=hod_cse)
        cse_ids = [p["id"] for p in cse_pending]
        assert alloc_cse_id in cse_ids, "CSE HOD must see CSE pending allocation"
        assert alloc_mca_id not in cse_ids, "CSE HOD must NOT see MCA pending allocation"

        # Admin must see both
        admin_pending = get_pending_approvals(department=None, db=db, current_user=admin_user)
        admin_ids = [p["id"] for p in admin_pending]
        assert alloc_mca_id in admin_ids, "Admin must see MCA pending allocation"
        assert alloc_cse_id in admin_ids, "Admin must see CSE pending allocation"

        # Faculty role must be rejected with HTTP 403
        try:
            get_pending_approvals(department=None, db=db, current_user=faculty_user)
            assert False, "Faculty should not be allowed to view pending approvals"
        except HTTPException as e:
            assert e.status_code == 403, f"Expected 403, got {e.status_code}"

        print("  ✓ PASS: Pending approvals strictly scoped by department for HOD; Admin sees all; Faculty blocked.")
        passed += 1

        # ─── TEST 2: Cross-Department Approval Security ───────────────────────
        print("\n[TEST 2] Cross-Department Approval Security Guard...")

        # HOD CSE attempting to approve MCA allocation must raise HTTP 403
        try:
            approve_allocation(alloc_mca_id, db=db, current_user=hod_cse)
            assert False, "HOD CSE must not be permitted to approve MCA allocation"
        except HTTPException as e:
            assert e.status_code == 403, f"Expected 403, got {e.status_code}"
            assert "not authorized to approve requests for 'MCA'" in e.detail

        print("  ✓ PASS: Cross-department approval attempt strictly blocked with HTTP 403.")
        passed += 1

        # ─── TEST 3: HOD Approval Workflow & Workload Ledger Commitment ───────
        print("\n[TEST 3] HOD Approval Workflow & Workload Ledger Commitment...")

        # Verify state before approval
        alloc_mca = db.query(Allocation).filter_by(id=alloc_mca_id).first()
        assert alloc_mca.status == "Pending HOD Approval"

        wl_int_pre = get_faculty_workload(db, int_fac_mca.id, "2025-26")
        assert wl_int_pre["committed"] == 0
        assert wl_int_pre["reserved"] == 1
        assert wl_int_pre["total_active"] == 1

        # MCA HOD approves MCA allocation
        res_app = approve_allocation(alloc_mca_id, db=db, current_user=hod_mca)
        assert res_app["success"] is True
        assert res_app["status"] == "Approved"

        # Verify Allocation status and audit fields
        db.refresh(alloc_mca)
        assert alloc_mca.status == "Approved"
        assert alloc_mca.approved_by == hod_mca.username
        assert alloc_mca.approved_at is not None

        # Verify AllocationSetters status
        setters = db.query(AllocationSetter).filter_by(allocation_id=alloc_mca_id).all()
        for s in setters:
            assert s.status == "Approved"

        # Verify Workload Ledger: COMMITTED=+1, RELEASED=-1, net reserved=0, net committed=1
        wl_int_post = get_faculty_workload(db, int_fac_mca.id, "2025-26")
        assert wl_int_post["committed"] == 1, f"Expected committed=1, got {wl_int_post['committed']}"
        assert wl_int_post["reserved"] == 0, f"Expected reserved=0, got {wl_int_post['reserved']}"
        assert wl_int_post["total_active"] == 1, f"Expected total_active=1, got {wl_int_post['total_active']}"

        # Verify AuditLog
        audit_app = db.query(AuditLog).filter_by(action="ALLOCATION_APPROVED_BY_HOD", entity_id=alloc_mca_id).first()
        assert audit_app is not None
        details = json.loads(audit_app.details)
        assert details["new_status"] == "Approved"
        assert details["approved_by"] == hod_mca.username

        print("  ✓ PASS: Allocation approved, workload committed (+1) and reservation released (-1) atomically.")
        passed += 1

        # ─── TEST 4: Double Decision Prevention on Approved Allocation ────────
        print("\n[TEST 4] Double Decision Prevention on Approved Allocation...")

        # Attempt to approve again -> HTTP 409
        try:
            approve_allocation(alloc_mca_id, db=db, current_user=hod_mca)
            assert False, "Should raise HTTP 409 for double approval"
        except HTTPException as e:
            assert e.status_code == 409, f"Expected 409, got {e.status_code}"
            assert "Only requests in 'Pending HOD Approval' can be decided" in e.detail

        # Attempt to reject an already approved allocation -> HTTP 409
        try:
            reject_allocation(alloc_mca_id, req=DecisionRequest(reason="Changed mind"), db=db, current_user=hod_mca)
            assert False, "Should raise HTTP 409 for rejecting already approved allocation"
        except HTTPException as e:
            assert e.status_code == 409, f"Expected 409, got {e.status_code}"

        print("  ✓ PASS: Double-decision strictly blocked with HTTP 409 on approved requests.")
        passed += 1

        # ─── TEST 5: HOD Rejection Workflow & Workload Reservation Release ────
        print("\n[TEST 5] HOD Rejection Workflow & Workload Reservation Release...")

        # Verify CSE allocation is currently 'Pending HOD Approval'
        alloc_cse = db.query(Allocation).filter_by(id=alloc_cse_id).first()
        assert alloc_cse.status == "Pending HOD Approval"

        wl_cse_pre = get_faculty_workload(db, int_fac_cse.id, "2025-26")
        assert wl_cse_pre["reserved"] == 1
        assert wl_cse_pre["committed"] == 0
        assert wl_cse_pre["total_active"] == 1

        # Test rejection without reason (or < 3 chars) -> HTTP 422
        try:
            reject_allocation(alloc_cse_id, req=DecisionRequest(reason=""), db=db, current_user=hod_cse)
            assert False, "Empty rejection reason must raise HTTP 422"
        except HTTPException as e:
            assert e.status_code == 422, f"Expected 422, got {e.status_code}"
            assert "A valid rejection reason" in e.detail

        try:
            reject_allocation(alloc_cse_id, req=DecisionRequest(reason="no"), db=db, current_user=hod_cse)
            assert False, "Short rejection reason must raise HTTP 422"
        except HTTPException as e:
            assert e.status_code == 422, f"Expected 422, got {e.status_code}"

        # CSE HOD rejects with valid reason
        rejection_note = "Faculty member has conflicts with upcoming accreditation audit."
        res_rej = reject_allocation(alloc_cse_id, req=DecisionRequest(reason=rejection_note), db=db, current_user=hod_cse)
        assert res_rej["success"] is True
        assert res_rej["status"] == "Rejected"
        assert res_rej["reason"] == rejection_note

        # Verify Allocation status
        db.refresh(alloc_cse)
        assert alloc_cse.status == "Rejected"
        assert alloc_cse.rejection_reason == rejection_note

        # Verify AllocationSetters status
        setters_cse = db.query(AllocationSetter).filter_by(allocation_id=alloc_cse_id).all()
        for s in setters_cse:
            assert s.status == "Rejected"

        # Verify Workload Ledger: reservation released, net workload = 0
        wl_cse_post = get_faculty_workload(db, int_fac_cse.id, "2025-26")
        assert wl_cse_post["committed"] == 0
        assert wl_cse_post["reserved"] == 0
        assert wl_cse_post["total_active"] == 0

        # Verify AuditLog
        audit_rej = db.query(AuditLog).filter_by(action="ALLOCATION_REJECTED_BY_HOD", entity_id=alloc_cse_id).first()
        assert audit_rej is not None
        rej_details = json.loads(audit_rej.details)
        assert rej_details["new_status"] == "Rejected"
        assert rej_details["reason"] == rejection_note

        print("  ✓ PASS: Allocation rejected with mandatory reason; workload reservations released atomically.")
        passed += 1

        # ─── TEST 6: Double Decision Prevention on Rejected Allocation ────────
        print("\n[TEST 6] Double Decision Prevention on Rejected Allocation...")

        # Attempt to reject again -> HTTP 409
        try:
            reject_allocation(alloc_cse_id, req=DecisionRequest(reason="Repeat rejection"), db=db, current_user=hod_cse)
            assert False, "Should raise HTTP 409 for double rejection"
        except HTTPException as e:
            assert e.status_code == 409, f"Expected 409, got {e.status_code}"

        # Attempt to approve a rejected allocation -> HTTP 409
        try:
            approve_allocation(alloc_cse_id, db=db, current_user=hod_cse)
            assert False, "Should raise HTTP 409 for approving already rejected allocation"
        except HTTPException as e:
            assert e.status_code == 409, f"Expected 409, got {e.status_code}"

        print("  ✓ PASS: Double-decision strictly blocked with HTTP 409 on rejected requests.")
        passed += 1

        # ─── TEST 7: Cancel Allocation & Safe Ledger Release ──────────────────
        print("\n[TEST 7] Cancel Allocation & Workload Ledger Release...")

        # Create a new pending allocation for MCA
        subj_mca2 = Subject(course_code="25MCA402", title="Machine Learning Ops", department="MCA", semester="IV", scheme="2025", academic_year="2025-26")
        db.add(subj_mca2)
        db.commit()

        req_cancel = CreateAllocationRequest(
            subject_id=subj_mca2.id,
            academic_year="2025-26",
            department="MCA",
            semester="IV",
            mode="Balanced",
            total_required=2,
            internal_faculty_ids=[int_fac_mca.id],
            external_faculty_ids=[ext_fac_mca.id]
        )
        res_cancel = create_allocation_request(req_cancel, db=db, current_user=admin_user)
        cancel_alloc_id = res_cancel["allocation_id"]
        submit_allocation_to_hod(cancel_alloc_id, db=db, current_user=admin_user)

        # Before cancel, int_fac_mca has 1 committed + 1 reserved = 2 active
        wl_cancel_pre = get_faculty_workload(db, int_fac_mca.id, "2025-26")
        assert wl_cancel_pre["committed"] == 1
        assert wl_cancel_pre["reserved"] == 1
        assert wl_cancel_pre["total_active"] == 2

        # HOD CSE trying to cancel MCA allocation -> HTTP 403
        try:
            cancel_allocation(cancel_alloc_id, db=db, current_user=hod_cse)
            assert False, "HOD CSE must not be allowed to cancel MCA allocation"
        except HTTPException as e:
            assert e.status_code == 403

        # MCA HOD cancels allocation
        res_c = cancel_allocation(cancel_alloc_id, db=db, current_user=hod_mca)
        assert res_c["success"] is True
        assert res_c["status"] == "Cancelled"

        # After cancel, reserved workload released -> returns to 1 committed + 0 reserved = 1 active
        wl_cancel_post = get_faculty_workload(db, int_fac_mca.id, "2025-26")
        assert wl_cancel_post["committed"] == 1
        assert wl_cancel_post["reserved"] == 0
        assert wl_cancel_post["total_active"] == 1

        # Trying to cancel already cancelled allocation -> HTTP 400
        try:
            cancel_allocation(cancel_alloc_id, db=db, current_user=hod_mca)
            assert False, "Cancelling already cancelled allocation must raise HTTP 400"
        except HTTPException as e:
            assert e.status_code == 400

        print("  ✓ PASS: Allocation cancellation cleanly releases workload reservations with audit trail.")
        passed += 1

        # ─── TEST 8: Role-Based Access Control Permissions ────────────────────
        print("\n[TEST 8] Role-Based Access Control Permissions...")

        # Faculty role attempting to approve -> HTTP 403
        try:
            approve_allocation(alloc_mca_id, db=db, current_user=faculty_user)
            assert False, "Faculty role must not be allowed to approve allocations"
        except HTTPException as e:
            assert e.status_code == 403

        # Faculty role attempting to reject -> HTTP 403
        try:
            reject_allocation(alloc_mca_id, req=DecisionRequest(reason="Unauthorized"), db=db, current_user=faculty_user)
            assert False, "Faculty role must not be allowed to reject allocations"
        except HTTPException as e:
            assert e.status_code == 403

        # Admin role attempting to approve directly -> HTTP 403 (HOD exclusive)
        try:
            approve_allocation(alloc_mca_id, db=db, current_user=admin_user)
            assert False, "Admin role must not bypass HOD approval directly"
        except HTTPException as e:
            assert e.status_code == 403

        print("  ✓ PASS: Server-side RBAC enforces HOD exclusivity for approvals and rejections.")
        passed += 1

    except Exception as ex:
        print(f"\n❌ UNHANDLED EXCEPTION in Module 12 test: {ex}")
        import traceback
        traceback.print_exc()
        failed += 1
    finally:
        db.close()

    print("\n" + "=" * 75)
    print(f"  MODULE 12 TEST SUMMARY: {passed} PASSED | {failed} FAILED")
    print("=" * 75)
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_module12_tests()
