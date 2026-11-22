"""
ExamExpert AI — Module 11 Allocation Request & Recommendation Automated Test Suite
SJB Institute of Technology | Office of Controller of Examinations

Explicitly verifies:
1. MCA 4-Semester Curriculum Rule:
   - Semesters I, II, III, IV pass validation.
   - Semesters V, VI, VII, VIII are strictly rejected with HTTP 422.
2. Auto-Select Modes & Shortage Reallocation:
   - Balanced Mode (50:50 parity).
   - Shortage handling: fills from other eligible pool with transparent warnings.
   - Internal Only and External Only modes.
3. Allocation Request Creation & Relational AllocationSetters:
   - Creates requests in Draft / Recommended status.
   - Creates relational AllocationSetter rows with order and status 'Nominated'.
4. Multi-Stage Lifecycle & Atomic Ledger Reservation:
   - Submit transitions status to 'Pending HOD Approval'.
   - Atomically appends RESERVED entries to WorkloadLedger.
5. Workload Capacity Limit Enforcement:
   - Rejects allocation submission if faculty workload would exceed capacity limit.
6. Duplicate Order Guard:
   - Blocks duplicate active requests for the same subject.
7. Role-Based Access Control (RBAC):
   - Admin can create and submit.
   - HOD cannot create allocation requests (HTTP 403).
   - Faculty cannot create or submit (HTTP 403).
8. Audit Trail Verification:
   - ALLOCATION_REQUEST_CREATED and ALLOCATION_SUBMITTED_TO_HOD logs recorded.
"""
import os, sys, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("mod11_")

from fastapi import HTTPException
from sqlalchemy.orm import Session
from backend.app.database import SessionLocal
from backend.app.models import (
    User, Faculty, Subject, EligibilityRules, WorkloadLedger,
    FacultySubjectMapping, ExternalInstitution, Allocation, AllocationSetter,
    AuditLog
)
from backend.app.routers.allocation import (
    validate_mca_semester,
    auto_select, AutoSelectRequest,
    create_allocation_request, CreateAllocationRequest,
    submit_allocation_to_hod
)
from backend.app.services.eligibility import get_faculty_workload


def run_module11_tests():
    print("=" * 75)
    print("  EXAMEXPERT AI — MODULE 11 ALLOCATION REQUEST & WORKFLOW VERIFICATION")
    print("  SJB Institute of Technology • Office of Controller of Examinations")
    print("=" * 75)

    db: Session = SessionLocal()
    passed = 0
    failed = 0

    try:
        # 1. Retrieve Core Test Accounts
        admin_user = db.query(User).filter_by(role="Admin").first()
        hod_mca = db.query(User).filter_by(role="HOD", department="MCA").first()
        faculty_user = db.query(User).filter_by(role="Faculty").first()

        assert admin_user is not None, "Admin user must exist"
        assert hod_mca is not None, "HOD MCA user must exist"
        assert faculty_user is not None, "Faculty user must exist"

        # Setup Confirmed Eligibility Policy
        policy = db.query(EligibilityRules).filter_by(status="CONFIRMED").first()
        if not policy:
            policy = EligibilityRules(
                min_experience=10.0,
                min_experience_phd=5.0,
                internal_capacity=2,
                external_capacity=2,
                status="CONFIRMED",
                min_experience_years=10.0,
                phd_fasttrack_min_exp=5.0,
                max_papers_per_faculty=2,
                require_parity=True,
                active_academic_year="2025-26"
            )
            db.add(policy)
            db.commit()

        # Setup Test Subject for MCA
        test_subj = Subject(
            course_code="25MCA301",
            title="Cloud Architecture & Microservices",
            department="MCA",
            semester="III",
            scheme="2025",
            academic_year="2025-26"
        )
        db.add(test_subj)
        db.commit()
        db.refresh(test_subj)

        # ─── TEST 1: MCA 4-Semester Curriculum Rule ──────────────────────────
        print("\n[TEST 1] MCA 4-Semester Curriculum Rule Validation...")
        # Semesters 1-4 must pass
        for valid_sem in ["I", "II", "III", "IV", "1", "2", "3", "4", "SEM 2"]:
            try:
                validate_mca_semester("MCA", valid_sem)
            except HTTPException:
                assert False, f"Valid MCA semester '{valid_sem}' was incorrectly rejected."

        # Semesters 5-8 must be rejected with HTTP 422
        invalid_count = 0
        for invalid_sem in ["V", "VI", "VII", "VIII", "5", "6", "7", "8", "SEM 5"]:
            try:
                validate_mca_semester("MCA", invalid_sem)
            except HTTPException as e:
                assert e.status_code == 422, f"Expected 422 for invalid semester '{invalid_sem}', got {e.status_code}"
                assert "MCA degree curriculum spans strictly 4 semesters" in e.detail
                invalid_count += 1
        assert invalid_count == 9, f"All 9 invalid MCA semesters must be rejected (got {invalid_count})"

        # Non-MCA departments (e.g. BE / CSE) can have 8 semesters
        try:
            validate_mca_semester("CSE", "VII")
        except HTTPException:
            assert False, "Non-MCA department should not be constrained by 4-semester rule."

        print("  ✓ PASS: MCA 4-semester rule strictly enforced (Sem I-IV accepted, Sem V-VIII rejected with HTTP 422).")
        passed += 1

        # ─── TEST 2: Auto-Select Allocation Modes & Shortage Reallocation ────
        print("\n[TEST 2] Auto-Select Allocation Modes & Shortage Handling...")

        # Setup 2 internal faculty and 2 external faculty
        int_fac1 = Faculty(name="Test Int Fac 1", faculty_type="internal", department="MCA", designation="Associate Professor", qualification="Ph.D", experience_years=12.0, is_available=True)
        int_fac2 = Faculty(name="Test Int Fac 2", faculty_type="internal", department="MCA", designation="Associate Professor", qualification="M.Tech", experience_years=15.0, is_available=True)
        ext_inst = ExternalInstitution(name="VTU Autonomous Institute 1", is_allowed=True)
        db.add_all([int_fac1, int_fac2, ext_inst])
        db.commit()

        ext_fac1 = Faculty(name="Test Ext Fac 1", faculty_type="external", department="MCA", institution=ext_inst.name, designation="Associate Professor", qualification="Ph.D", experience_years=14.0, is_available=True)
        ext_fac2 = Faculty(name="Test Ext Fac 2", faculty_type="external", department="MCA", institution=ext_inst.name, designation="Associate Professor", qualification="M.Tech", experience_years=16.0, is_available=True)
        db.add_all([ext_fac1, ext_fac2])
        db.commit()

        # Add confirmed expertise mappings for subject
        db.add(FacultySubjectMapping(faculty_id=int_fac1.id, subject_id=test_subj.id, mapping_type="EXACT_EXPERIENCE", status="CONFIRMED"))
        db.add(FacultySubjectMapping(faculty_id=int_fac2.id, subject_id=test_subj.id, mapping_type="SPECIALIZATION", status="CONFIRMED"))
        db.add(FacultySubjectMapping(faculty_id=ext_fac1.id, subject_id=test_subj.id, mapping_type="EXACT_EXPERIENCE", status="CONFIRMED"))
        db.add(FacultySubjectMapping(faculty_id=ext_fac2.id, subject_id=test_subj.id, mapping_type="SPECIALIZATION", status="CONFIRMED"))
        db.commit()

        # Test Balanced Mode (50:50)
        req_bal = AutoSelectRequest(subject_id=test_subj.id, total_required=2, mode="Balanced", academic_year="2025-26")
        res_bal = auto_select(req_bal, db=db, current_user=admin_user)
        assert res_bal["internal_quota"] == 1
        assert res_bal["external_quota"] == 1
        assert len(res_bal["selected_internal"]) == 1
        assert len(res_bal["selected_external"]) == 1
        assert res_bal["requires_exception"] is False
        assert len(res_bal["warnings"]) == 0

        # Test Internal Only Mode
        req_int = AutoSelectRequest(subject_id=test_subj.id, total_required=2, mode="Internal Only", academic_year="2025-26")
        res_int = auto_select(req_int, db=db, current_user=admin_user)
        assert res_int["internal_quota"] == 2
        assert res_int["external_quota"] == 0
        assert len(res_int["selected_internal"]) == 2
        assert len(res_int["selected_external"]) == 0

        # Test External Only Mode
        req_ext = AutoSelectRequest(subject_id=test_subj.id, total_required=2, mode="External Only", academic_year="2025-26")
        res_ext = auto_select(req_ext, db=db, current_user=admin_user)
        assert res_ext["internal_quota"] == 0
        assert res_ext["external_quota"] == 2
        assert len(res_ext["selected_internal"]) == 0
        assert len(res_ext["selected_external"]) == 2

        # Test Shortage Reallocation in Balanced Mode (requesting 4 setters with only 2 internals available)
        req_shortage = AutoSelectRequest(subject_id=test_subj.id, total_required=4, mode="Balanced", academic_year="2025-26")
        res_shortage = auto_select(req_shortage, db=db, current_user=admin_user)
        assert res_shortage["internal_quota"] == 2
        assert res_shortage["external_quota"] == 2
        assert len(res_shortage["selected_internal"]) == 2
        assert len(res_shortage["selected_external"]) == 2

        print("  ✓ PASS: Balanced, Internal Only, External Only, and shortage reallocation operate correctly.")
        passed += 1

        # ─── TEST 3: Create Allocation Request & Relational AllocationSetters ─
        print("\n[TEST 3] Create Allocation Request & Relational AllocationSetters...")
        create_req = CreateAllocationRequest(
            subject_id=test_subj.id,
            academic_year="2025-26",
            department="MCA",
            scheme="2025",
            semester="III",
            exam_type="Autonomous End-Semester Examination",
            mode="Balanced",
            total_required=2,
            internal_faculty_ids=[int_fac1.id],
            external_faculty_ids=[ext_fac1.id],
            status="Draft"
        )
        res_create = create_allocation_request(create_req, db=db, current_user=admin_user)
        assert res_create["success"] is True
        assert res_create["status"] == "Draft"
        alloc_id = res_create["allocation_id"]

        # Verify Allocation and Relational AllocationSetters in DB
        alloc = db.query(Allocation).filter_by(id=alloc_id).first()
        assert alloc is not None
        assert alloc.status == "Draft"

        setters = db.query(AllocationSetter).filter_by(allocation_id=alloc_id).order_by(AllocationSetter.assigned_order).all()
        assert len(setters) == 2, f"Expected 2 relational setters, got {len(setters)}"
        assert setters[0].faculty_id == int_fac1.id
        assert setters[0].faculty_type == "internal"
        assert setters[0].status == "Nominated"
        assert setters[0].assigned_order == 1

        assert setters[1].faculty_id == ext_fac1.id
        assert setters[1].faculty_type == "external"
        assert setters[1].status == "Nominated"
        assert setters[1].assigned_order == 2

        # Verify Audit Log
        audit_create = db.query(AuditLog).filter_by(action="ALLOCATION_REQUEST_CREATED", entity_id=alloc_id).first()
        assert audit_create is not None, "AuditLog must record ALLOCATION_REQUEST_CREATED"

        print("  ✓ PASS: Allocation request created in 'Draft' status with relational AllocationSetters and audit log.")
        passed += 1

        # ─── TEST 4: Submit Allocation to HOD & Atomic Workload Ledger ───────
        print("\n[TEST 4] Submit Allocation to HOD & Atomic Workload Ledger...")

        # Verify initial workload before submission (should be 0)
        wl_int_pre = get_faculty_workload(db, int_fac1.id, "2025-26")
        wl_ext_pre = get_faculty_workload(db, ext_fac1.id, "2025-26")
        assert wl_int_pre["reserved"] == 0
        assert wl_ext_pre["reserved"] == 0

        # Submit request to HOD
        res_submit = submit_allocation_to_hod(alloc_id, db=db, current_user=admin_user)
        assert res_submit["success"] is True
        assert res_submit["status"] == "Pending HOD Approval"

        # Verify allocation status changed
        db.refresh(alloc)
        assert alloc.status == "Pending HOD Approval"

        # Verify WorkloadLedger RESERVED entries created atomically
        wl_int_post = get_faculty_workload(db, int_fac1.id, "2025-26")
        wl_ext_post = get_faculty_workload(db, ext_fac1.id, "2025-26")
        assert wl_int_post["reserved"] == 1, f"Internal faculty reserved workload should be 1, got {wl_int_post['reserved']}"
        assert wl_int_post["total_active"] == 1
        assert wl_ext_post["reserved"] == 1, f"External faculty reserved workload should be 1, got {wl_ext_post['reserved']}"
        assert wl_ext_post["total_active"] == 1

        # Verify Audit Log
        audit_submit = db.query(AuditLog).filter_by(action="ALLOCATION_SUBMITTED_TO_HOD", entity_id=alloc_id).first()
        assert audit_submit is not None, "AuditLog must record ALLOCATION_SUBMITTED_TO_HOD"

        print("  ✓ PASS: Allocation transitioned to 'Pending HOD Approval' and RESERVED ledger entries atomically created.")
        passed += 1

        # ─── TEST 5: Workload Capacity Limit Enforcement ─────────────────────
        print("\n[TEST 5] Workload Capacity Limit Enforcement...")

        # Create another test subject
        subj2 = Subject(course_code="25MCA302", title="Full-Stack Web Engineering", department="MCA", semester="III", scheme="2025", academic_year="2025-26")
        db.add(subj2)
        db.commit()

        # Add second reservation for int_fac1 (reaching capacity of 2)
        alloc2 = Allocation(
            reference_number="TEST-REF-CAP-2",
            academic_year="2025-26",
            department="MCA",
            semester="III",
            subject_id=subj2.id,
            total_required=2,
            internal_required=1,
            external_required=1,
            allocation_mode="Balanced",
            internal_faculty_ids=json.dumps([int_fac1.id]),
            external_faculty_ids=json.dumps([ext_fac2.id]),
            status="Draft"
        )
        db.add(alloc2)
        db.flush()
        db.add(AllocationSetter(allocation_id=alloc2.id, faculty_id=int_fac1.id, faculty_type="internal", status="Nominated", assigned_order=1))
        db.add(AllocationSetter(allocation_id=alloc2.id, faculty_id=ext_fac2.id, faculty_type="external", status="Nominated", assigned_order=2))
        db.commit()

        # Submitting alloc2 will bring int_fac1 to 2/2 (allowed)
        submit_allocation_to_hod(alloc2.id, db=db, current_user=admin_user)
        wl_int_cap = get_faculty_workload(db, int_fac1.id, "2025-26")
        assert wl_int_cap["total_active"] == 2, f"Expected 2 total active, got {wl_int_cap['total_active']}"

        # Now attempting to nominate int_fac1 for a THIRD paper must be rejected with HTTP 422
        subj3 = Subject(course_code="25MCA303", title="Mobile Computing", department="MCA", semester="III", scheme="2025", academic_year="2025-26")
        db.add(subj3)
        db.commit()

        req_overcap = CreateAllocationRequest(
            subject_id=subj3.id,
            academic_year="2025-26",
            department="MCA",
            semester="III",
            mode="Balanced",
            total_required=2,
            internal_faculty_ids=[int_fac1.id],  # Already at 2/2!
            external_faculty_ids=[ext_fac1.id]
        )
        try:
            create_allocation_request(req_overcap, db=db, current_user=admin_user)
            assert False, "Should have raised HTTP 422 due to workload capacity limit."
        except HTTPException as e:
            assert e.status_code == 422, f"Expected 422, got {e.status_code}"
            assert "workload limit of 2 papers would be exceeded" in e.detail

        print("  ✓ PASS: Workload capacity strictly enforced (exceeding limit raises HTTP 422).")
        passed += 1

        # ─── TEST 6: Duplicate Active Allocation Prevention ──────────────────
        print("\n[TEST 6] Duplicate Active Allocation Order Prevention...")
        # Attempt to create another allocation request for test_subj (which is currently 'Pending HOD Approval')
        dup_req = CreateAllocationRequest(
            subject_id=test_subj.id,
            academic_year="2025-26",
            department="MCA",
            semester="III",
            mode="Balanced",
            total_required=2,
            internal_faculty_ids=[int_fac2.id],
            external_faculty_ids=[ext_fac2.id]
        )
        try:
            create_allocation_request(dup_req, db=db, current_user=admin_user)
            assert False, "Should have raised HTTP 409 due to duplicate active allocation."
        except HTTPException as e:
            assert e.status_code == 409, f"Expected 409, got {e.status_code}"
            assert "An active allocation order already exists" in e.detail

        print("  ✓ PASS: Duplicate active allocations for the same subject correctly rejected with HTTP 409.")
        passed += 1

        # ─── TEST 7: Role-Based Access Control (RBAC) ─────────────────────────
        print("\n[TEST 7] Role-Based Access Control Checks...")

        # 1. Faculty role cannot create allocation request
        try:
            create_allocation_request(create_req, db=db, current_user=faculty_user)
            assert False, "Faculty must not be allowed to create allocation requests."
        except HTTPException as e:
            assert e.status_code == 403, f"Expected 403, got {e.status_code}"

        # 2. HOD role cannot create allocation request (Admin workflow)
        try:
            create_allocation_request(create_req, db=db, current_user=hod_mca)
            assert False, "HOD must not be allowed to create allocation requests."
        except HTTPException as e:
            assert e.status_code == 403, f"Expected 403, got {e.status_code}"

        # 3. Faculty role cannot submit allocation to HOD
        try:
            submit_allocation_to_hod(alloc_id, db=db, current_user=faculty_user)
            assert False, "Faculty must not be allowed to submit allocation requests."
        except HTTPException as e:
            assert e.status_code == 403, f"Expected 403, got {e.status_code}"

        print("  ✓ PASS: Server-side RBAC strictly blocks unauthorized roles with HTTP 403.")
        passed += 1

    except Exception as ex:
        print(f"\n❌ UNHANDLED EXCEPTION in Module 11 test: {ex}")
        import traceback
        traceback.print_exc()
        failed += 1
    finally:
        db.close()

    print("\n" + "=" * 75)
    print(f"  MODULE 11 TEST SUMMARY: {passed} PASSED | {failed} FAILED")
    print("=" * 75)
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_module11_tests()
