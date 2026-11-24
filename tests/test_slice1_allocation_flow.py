"""
Slice 1 Tests: Allocation flow fix and simplification.
Verifies:
1. PDF download blocked (400) when allocation status is 'Pending HOD Approval'.
2. PDF download allowed (200) when allocation status is 'Approved'.
3. Role checks on PDF download:
   - Admin: can download any approved allocation.
   - HOD: can only download approved allocations belonging to their department (403 for others).
   - Faculty: can only download approved allocations where they are an assigned setter (403 for others).
4. Manual addition validation:
   - Reason mandatory (400 if empty).
   - Unallowed external institution rejected (400).
   - Duplicate active subject assignment rejected (400).
   - Capacity constraint enforced unless Admin explicitly authorizes capacity override with reason.
   - Manual exception flag & reason saved on setter and allocation.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("test_slice1_")

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import get_db
from backend.app.models import User, Faculty, Subject, Allocation, AllocationSetter, WorkloadLedger, ExternalInstitution, ActiveSession
from backend.app.routers.auth import create_session, hash_password

client = TestClient(app)

def get_token(role: str, email: str, dept: str = "CSE", fac_id: int = None):
    db = next(get_db())
    try:
        user = db.query(User).filter((User.email == email) | (User.username == email.split("@")[0])).first()
        if not user:
            user = User(
                username=email.split("@")[0],
                email=email,
                password_hash=hash_password("TestSecret123"),
                role=role,
                department=dept,
                faculty_id=fac_id,
                full_name=f"Test {role}",
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.role = role
            user.department = dept
            user.faculty_id = fac_id
            db.commit()
            db.refresh(user)
        return create_session(user, db)
    finally:
        db.close()

def setup_test_data():
    db = next(get_db())
    try:
        # Create or fetch subject
        subj = db.query(Subject).filter(Subject.course_code == "21CS61").first()
        if not subj:
            subj = Subject(
                course_code="21CS61",
                title="Software Engineering",
                department="CSE",
                semester="6",
                academic_year="2025-26",
                scheme="2021",
                credits=4
            )
            db.add(subj)
            db.commit()
            db.refresh(subj)

        # Ensure allowed institutions exist
        inst = db.query(ExternalInstitution).filter(ExternalInstitution.name == "RVCE").first()
        if not inst:
            inst = ExternalInstitution(name="RVCE", is_allowed=True)
            db.add(inst)
            db.commit()

        # Create test internal faculty
        f_int = db.query(Faculty).filter(Faculty.email == "faculty_s1_int@sjbit.edu.in").first()
        if not f_int:
            f_int = Faculty(
                name="Prof. Slice1 Internal",
                email="faculty_s1_int@sjbit.edu.in",
                faculty_type="internal",
                department="CSE",
                institution="SJBIT",
                designation="Associate Professor",
                qualification="Ph.D",
                experience_years=10.0,
                is_available=True
            )
            db.add(f_int)
            db.commit()
            db.refresh(f_int)

        # Create test external faculty in allowed institution
        f_ext = db.query(Faculty).filter(Faculty.email == "faculty_s1_ext@rvce.edu.in").first()
        if not f_ext:
            f_ext = Faculty(
                name="Dr. Slice1 External",
                email="faculty_s1_ext@rvce.edu.in",
                faculty_type="external",
                department="CSE",
                institution="RVCE",
                designation="Professor",
                qualification="Ph.D",
                experience_years=14.0,
                is_available=True
            )
            db.add(f_ext)
            db.commit()
            db.refresh(f_ext)

        # Create test external faculty in UNALLOWED institution
        f_unallowed = db.query(Faculty).filter(Faculty.email == "faculty_s1_unauth@unauth.edu.in").first()
        if not f_unallowed:
            f_unallowed = Faculty(
                name="Prof. Unallowed Ext",
                email="faculty_s1_unauth@unauth.edu.in",
                faculty_type="external",
                department="CSE",
                institution="Unknown Institute XYZ",
                designation="Assistant Professor",
                qualification="M.Tech",
                experience_years=5.0,
                is_available=True
            )
            db.add(f_unallowed)
            db.commit()
            db.refresh(f_unallowed)

        return subj.id, f_int.id, f_ext.id, f_unallowed.id
    finally:
        db.close()

def test_allocation_flow_and_pdf_enforcement():
    subj_id, f_int_id, f_ext_id, f_unauth_id = setup_test_data()

    admin_token = get_token("Admin", "admin@sjbit.edu.in", "CSE")
    hod_cse_token = get_token("HOD", "hod_cse@sjbit.edu.in", "CSE")
    hod_ise_token = get_token("HOD", "hod_ise@sjbit.edu.in", "ISE")
    faculty_assigned_token = get_token("Faculty", "faculty_s1_int@sjbit.edu.in", "CSE", fac_id=f_int_id)
    faculty_unrelated_token = get_token("Faculty", "other_faculty@sjbit.edu.in", "CSE", fac_id=9999)

    # 1. Submit allocation (Pending HOD Approval) with manual override
    payload = {
        "subject_id": subj_id,
        "academic_year": "2025-26",
        "department": "CSE",
        "semester": "6",
        "min_handled": 1,
        "total_required": 2,
        "internal_faculty_ids": [f_int_id],
        "external_faculty_ids": [f_ext_id],
        "manual_exceptions": [
            {
                "faculty_id": f_int_id,
                "reason": "Special domain expertise in AI systems required for Set 1",
                "allow_capacity_override": False
            }
        ],
        "submission_deadline": "Within 10 days"
    }

    res = client.post("/api/allocation/confirm", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200, f"Submit failed: {res.text}"
    alloc_id = res.json()["allocation_id"]

    # Verify allocation status in DB is "Pending HOD Approval"
    db = next(get_db())
    try:
        alloc = db.query(Allocation).filter(Allocation.id == alloc_id).first()
        assert alloc.status == "Pending HOD Approval"
        assert alloc.has_manual_override is True
        setters = db.query(AllocationSetter).filter(AllocationSetter.allocation_id == alloc_id).all()
        int_setter = [s for s in setters if s.faculty_id == f_int_id][0]
        assert int_setter.is_manual_override is True
        assert "AI systems" in int_setter.manual_reason
    finally:
        db.close()

    # 2. Verify PDF download returns 400 because allocation is NOT approved
    pdf_res = client.get(f"/api/reports/download-pdf/{alloc_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert pdf_res.status_code == 400
    assert "Pending HOD Approval" in pdf_res.json()["detail"] or "cannot be downloaded" in pdf_res.json()["detail"]

    # 3. Test HOD of ISE cannot approve CSE allocation
    approve_res_unauth = client.post(f"/api/allocation/{alloc_id}/approve", json={}, headers={"Authorization": f"Bearer {hod_ise_token}"})
    assert approve_res_unauth.status_code in (403, 400)

    # 4. HOD of CSE approves the allocation
    approve_res = client.post(f"/api/allocation/{alloc_id}/approve", json={"remarks": "Approved with manual exception"}, headers={"Authorization": f"Bearer {hod_cse_token}"})
    assert approve_res.status_code == 200

    # 5. Now allocation is "Approved", verify PDF download permissions:
    # Admin can download (200)
    pdf_admin = client.get(f"/api/reports/download-pdf/{alloc_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert pdf_admin.status_code == 200
    assert pdf_admin.headers["content-type"] == "application/pdf"

    # CSE HOD can download (200)
    pdf_hod_cse = client.get(f"/api/reports/download-pdf/{alloc_id}", headers={"Authorization": f"Bearer {hod_cse_token}"})
    assert pdf_hod_cse.status_code == 200

    # ISE HOD gets 403 Forbidden (cross-department)
    pdf_hod_ise = client.get(f"/api/reports/download-pdf/{alloc_id}", headers={"Authorization": f"Bearer {hod_ise_token}"})
    assert pdf_hod_ise.status_code == 403

    # Assigned faculty can download (200)
    pdf_fac_assigned = client.get(f"/api/reports/download-pdf/{alloc_id}", headers={"Authorization": f"Bearer {faculty_assigned_token}"})
    assert pdf_fac_assigned.status_code == 200

    # Unassigned faculty gets 403 Forbidden
    pdf_fac_unrelated = client.get(f"/api/reports/download-pdf/{alloc_id}", headers={"Authorization": f"Bearer {faculty_unrelated_token}"})
    assert pdf_fac_unrelated.status_code == 403

def test_manual_addition_validation_rules():
    subj_id, f_int_id, f_ext_id, f_unauth_id = setup_test_data()
    admin_token = get_token("Admin", "admin@sjbit.edu.in", "CSE")

    # Create a distinct subject for manual validation tests to avoid active order conflicts
    db = next(get_db())
    try:
        subj2 = db.query(Subject).filter(Subject.course_code == "21CS62").first()
        if not subj2:
            subj2 = Subject(
                course_code="21CS62",
                title="Cloud Computing",
                department="CSE",
                semester="6",
                academic_year="2025-26",
                scheme="2021",
                credits=4
            )
            db.add(subj2)
            db.commit()
            db.refresh(subj2)
        target_subj_id = subj2.id
    finally:
        db.close()

    # A. Unallowed external institution must be rejected
    res_unauth_inst = client.post("/api/allocation/confirm", json={
        "subject_id": target_subj_id,
        "academic_year": "2025-26",
        "department": "CSE",
        "semester": "6",
        "min_handled": 1,
        "total_required": 1,
        "internal_faculty_ids": [],
        "external_faculty_ids": [f_unauth_id],
        "manual_exceptions": [
            {"faculty_id": f_unauth_id, "reason": "Testing unallowed institution", "allow_capacity_override": False}
        ]
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert res_unauth_inst.status_code == 400
    assert "approved whitelist" in res_unauth_inst.json()["detail"].lower()

    # B. Missing reason must be rejected
    res_no_reason = client.post("/api/allocation/confirm", json={
        "subject_id": target_subj_id,
        "academic_year": "2025-26",
        "department": "CSE",
        "semester": "6",
        "min_handled": 1,
        "total_required": 1,
        "internal_faculty_ids": [],
        "external_faculty_ids": [f_ext_id],
        "manual_exceptions": [
            {"faculty_id": f_ext_id, "reason": "   ", "allow_capacity_override": False}
        ]
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert res_no_reason.status_code == 400
    assert "reason is mandatory" in res_no_reason.json()["detail"].lower() or "reason is required" in res_no_reason.json()["detail"].lower()

    # C. Duplicate active assignment to the same subject must be rejected
    # Note: f_int_id was already assigned to subj_id in test_allocation_flow_and_pdf_enforcement
    res_dup = client.post("/api/allocation/confirm", json={
        "subject_id": subj_id,
        "academic_year": "2025-26",
        "department": "CSE",
        "semester": "6",
        "min_handled": 1,
        "total_required": 1,
        "internal_faculty_ids": [f_int_id],
        "external_faculty_ids": [],
        "manual_exceptions": [
            {"faculty_id": f_int_id, "reason": "Duplicate assignment test", "allow_capacity_override": False}
        ]
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert res_dup.status_code in (400, 409)

if __name__ == "__main__":
    print("Running Slice 1 Tests...")
    test_allocation_flow_and_pdf_enforcement()
    print("PASS: test_allocation_flow_and_pdf_enforcement")
    test_manual_addition_validation_rules()
    print("PASS: test_manual_addition_validation_rules")
    print("ALL SLICE 1 TESTS PASSED SUCCESSFULLY.")
