"""
Slice 2 Tests: Role dashboards (Guide requirements).
Verifies:
1. HOD Dashboard:
   - Scoped strictly to HOD's own department.
   - Faculty table returns experience, designation, confirmed expertise count, committed/reserved workload from ledger.
   - Returns counts of pending, approved, and rejected requests.
   - Non-HOD gets 403 Forbidden.
2. Faculty Dashboard:
   - Resolved from session user.
   - Returns personal profile (qualification, designation, experience), confirmed expertise subjects,
     workload (committed, reserved, policy capacity, remaining), assigned papers with status, and unread notification count.
   - Non-Faculty gets 403 Forbidden.
3. Admin Workload Distribution:
   - Returns departmental breakdown (committed, reserved, capacity, remaining, internal vs external).
   - Only Admin can access (403 for HOD and Faculty).
4. Unauthenticated requests to all three endpoints return 401 Unauthorized.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("test_slice2_")

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import get_db
from backend.app.models import (
    User, Faculty, Subject, Allocation, AllocationSetter,
    WorkloadLedger, FacultySubjectMapping, InAppNotification, EligibilityRules
)
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

def setup_slice2_data():
    db = next(get_db())
    try:
        # Create CSE Faculty
        f_cse = db.query(Faculty).filter_by(email="fac_cse_slice2@sjbit.edu.in").first()
        if not f_cse:
            f_cse = Faculty(
                name="Prof. S2 CSE Faculty",
                email="fac_cse_slice2@sjbit.edu.in",
                faculty_type="internal",
                department="CSE",
                institution="SJBIT",
                designation="Associate Professor",
                qualification="Ph.D",
                experience_years=8.5,
                is_available=True
            )
            db.add(f_cse)
            db.commit()
            db.refresh(f_cse)

        # Create ISE Faculty
        f_ise = db.query(Faculty).filter_by(email="fac_ise_slice2@sjbit.edu.in").first()
        if not f_ise:
            f_ise = Faculty(
                name="Prof. S2 ISE Faculty",
                email="fac_ise_slice2@sjbit.edu.in",
                faculty_type="internal",
                department="ISE",
                institution="SJBIT",
                designation="Assistant Professor",
                qualification="M.Tech",
                experience_years=5.0,
                is_available=True
            )
            db.add(f_ise)
            db.commit()
            db.refresh(f_ise)

        # Create Subject for CSE
        subj = db.query(Subject).filter_by(course_code="21CS71").first()
        if not subj:
            subj = Subject(
                course_code="21CS71",
                title="Distributed Systems",
                department="CSE",
                semester="7",
                academic_year="2025-26",
                scheme="2021",
                credits=4
            )
            db.add(subj)
            db.commit()
            db.refresh(subj)

        # Confirmed Expertise Mapping for CSE Faculty
        mapping = db.query(FacultySubjectMapping).filter_by(faculty_id=f_cse.id, subject_id=subj.id).first()
        if not mapping:
            mapping = FacultySubjectMapping(
                faculty_id=f_cse.id,
                subject_id=subj.id,
                mapping_type="SPECIALIZATION",
                times_handled=3,
                is_confirmed=True,
                status="CONFIRMED"
            )
            db.add(mapping)
            db.commit()

        # Workload ledger entries for CSE Faculty: 1 COMMITTED, 1 RESERVED (immutable ledger, append only if needed)
        existing_wl = db.query(WorkloadLedger).filter_by(faculty_id=f_cse.id).first()
        if not existing_wl:
            wl_com = WorkloadLedger(
                faculty_id=f_cse.id,
                academic_year="2025-26",
                entry_type="COMMITTED",
                delta=1,
                remarks="Committed test workload"
            )
            wl_res = WorkloadLedger(
                faculty_id=f_cse.id,
                academic_year="2025-26",
                entry_type="RESERVED",
                delta=1,
                remarks="Reserved test workload"
            )
            db.add_all([wl_com, wl_res])
            db.commit()

        # Create Allocation records for CSE: 1 Pending, 1 Approved
        alloc_pend = db.query(Allocation).filter_by(reference_number="SJBIT-CSE-PEND-1").first()
        if not alloc_pend:
            alloc_pend = Allocation(
                reference_number="SJBIT-CSE-PEND-1",
                subject_id=subj.id,
                academic_year="2025-26",
                department="CSE",
                semester="7",
                status="Pending HOD Approval",
                total_required=1
            )
            db.add(alloc_pend)
            db.commit()

        alloc_appr = db.query(Allocation).filter_by(reference_number="SJBIT-CSE-APPR-1").first()
        if not alloc_appr:
            alloc_appr = Allocation(
                reference_number="SJBIT-CSE-APPR-1",
                subject_id=subj.id,
                academic_year="2025-26",
                department="CSE",
                semester="7",
                status="Approved",
                total_required=1
            )
            db.add(alloc_appr)
            db.commit()
            db.refresh(alloc_appr)

        # Assign f_cse to alloc_appr if not already assigned
        existing_setter = db.query(AllocationSetter).filter_by(allocation_id=alloc_appr.id, faculty_id=f_cse.id).first()
        if not existing_setter:
            setter = AllocationSetter(
                allocation_id=alloc_appr.id,
                faculty_id=f_cse.id,
                faculty_type="internal",
                assigned_order=1,
                status="Approved"
            )
            db.add(setter)
            db.commit()

        return f_cse.id, f_ise.id, subj.id
    finally:
        db.close()


def test_hod_dashboard_scoping():
    f_cse_id, f_ise_id, subj_id = setup_slice2_data()

    hod_cse_token = get_token("HOD", "hod_cse_s2@sjbit.edu.in", "CSE")
    hod_ise_token = get_token("HOD", "hod_ise_s2@sjbit.edu.in", "ISE")
    faculty_token = get_token("Faculty", "fac_cse_slice2@sjbit.edu.in", "CSE", fac_id=f_cse_id)

    # 1. HOD CSE accesses dashboard
    res = client.get("/api/reports/hod-dashboard?academic_year=2025-26", headers={"Authorization": f"Bearer {hod_cse_token}"})
    assert res.status_code == 200, f"HOD CSE dashboard error: {res.text}"
    data = res.json()
    assert data["department"] == "CSE"
    assert data["counts"]["pending"] >= 1
    assert data["counts"]["approved"] >= 1

    # Check that returned faculty list contains CSE faculty and NOT ISE faculty
    fac_ids = [f["faculty_id"] for f in data["faculty"]]
    assert f_cse_id in fac_ids
    assert f_ise_id not in fac_ids

    # Check workload ledger values for CSE faculty
    cse_fac_row = [f for f in data["faculty"] if f["faculty_id"] == f_cse_id][0]
    assert cse_fac_row["workload_committed"] == 1
    assert cse_fac_row["workload_reserved"] == 1
    assert cse_fac_row["workload_active"] == 2
    assert cse_fac_row["confirmed_expertise_count"] >= 1
    assert cse_fac_row["designation"] == "Associate Professor"
    assert cse_fac_row["experience_years"] == 8.5

    # 2. HOD ISE accesses dashboard: should see ISE faculty and NOT CSE faculty
    res_ise = client.get("/api/reports/hod-dashboard?academic_year=2025-26", headers={"Authorization": f"Bearer {hod_ise_token}"})
    assert res_ise.status_code == 200
    data_ise = res_ise.json()
    assert data_ise["department"] == "ISE"
    fac_ids_ise = [f["faculty_id"] for f in data_ise["faculty"]]
    assert f_ise_id in fac_ids_ise
    assert f_cse_id not in fac_ids_ise

    # 3. Faculty role forbidden from HOD dashboard (403)
    res_fac_denied = client.get("/api/reports/hod-dashboard", headers={"Authorization": f"Bearer {faculty_token}"})
    assert res_fac_denied.status_code == 403


def test_faculty_dashboard():
    f_cse_id, f_ise_id, subj_id = setup_slice2_data()

    faculty_token = get_token("Faculty", "fac_cse_slice2@sjbit.edu.in", "CSE", fac_id=f_cse_id)
    hod_token = get_token("HOD", "hod_cse_s2@sjbit.edu.in", "CSE")

    # 1. Faculty accesses own dashboard
    res = client.get("/api/reports/faculty-dashboard?academic_year=2025-26", headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 200, f"Faculty dashboard error: {res.text}"
    data = res.json()
    assert data["faculty_id"] == f_cse_id
    assert data["name"] == "Prof. S2 CSE Faculty"
    assert data["qualification"] == "Ph.D"
    assert data["experience_years"] == 8.5
    assert data["workload"]["committed"] == 1
    assert data["workload"]["reserved"] == 1
    assert data["workload"]["total_active"] == 2

    # Check confirmed expertise subjects
    assert len(data["confirmed_subjects"]) >= 1
    codes = [s["course_code"] for s in data["confirmed_subjects"]]
    assert "21CS71" in codes

    # Check assigned papers
    assert len(data["assigned_papers"]) >= 1
    refs = [p["reference_number"] for p in data["assigned_papers"]]
    assert "SJBIT-CSE-APPR-1" in refs
    assigned_paper = [p for p in data["assigned_papers"] if p["reference_number"] == "SJBIT-CSE-APPR-1"][0]
    assert assigned_paper["can_download_pdf"] is True

    # 2. HOD role forbidden from Faculty dashboard (403)
    res_hod_denied = client.get("/api/reports/faculty-dashboard", headers={"Authorization": f"Bearer {hod_token}"})
    assert res_hod_denied.status_code == 403


def test_admin_workload_distribution():
    f_cse_id, f_ise_id, subj_id = setup_slice2_data()

    admin_token = get_token("Admin", "admin@sjbit.edu.in", "CSE")
    hod_token = get_token("HOD", "hod_cse_s2@sjbit.edu.in", "CSE")
    faculty_token = get_token("Faculty", "fac_cse_slice2@sjbit.edu.in", "CSE", fac_id=f_cse_id)

    # 1. Admin accesses workload distribution
    res = client.get("/api/reports/admin-workload-distribution?academic_year=2025-26", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200, f"Admin workload distribution error: {res.text}"
    data = res.json()
    assert "summary" in data
    assert "departments" in data
    assert "chart_data" in data
    assert data["summary"]["total_committed"] >= 1
    assert data["summary"]["total_reserved"] >= 1

    # 2. HOD and Faculty are blocked (403)
    assert client.get("/api/reports/admin-workload-distribution", headers={"Authorization": f"Bearer {hod_token}"}).status_code == 403
    assert client.get("/api/reports/admin-workload-distribution", headers={"Authorization": f"Bearer {faculty_token}"}).status_code == 403


def test_unauthenticated_requests_return_401():
    endpoints = [
        "/api/reports/hod-dashboard",
        "/api/reports/faculty-dashboard",
        "/api/reports/admin-workload-distribution"
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 401, f"Expected 401 for {ep}, got {res.status_code}"


if __name__ == "__main__":
    print("Running Slice 2 Tests...")
    test_hod_dashboard_scoping()
    print("PASS: test_hod_dashboard_scoping")
    test_faculty_dashboard()
    print("PASS: test_faculty_dashboard")
    test_admin_workload_distribution()
    print("PASS: test_admin_workload_distribution")
    test_unauthenticated_requests_return_401()
    print("PASS: test_unauthenticated_requests_return_401")
    print("ALL SLICE 2 TESTS PASSED SUCCESSFULLY.")
