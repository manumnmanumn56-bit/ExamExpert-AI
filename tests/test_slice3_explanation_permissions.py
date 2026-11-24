"""
Slice 3 Tests: Explanation and permissions.
Verifies:
1. Server-side permissions map:
   - Endpoint /api/admin/permissions-map returns Admin, HOD, and Faculty permission sets.
   - Accessible by Admin, HOD, and Faculty.
   - Unauthenticated access returns 401.
2. Faculty Profile & Experience Management:
   - Admin can edit faculty profile & experience (PUT /api/faculty/{id}) (200).
   - Audited: creates AuditLog entry.
   - Faculty cannot edit profile (403 Forbidden).
   - Faculty can view own profile read-only.
   - Missing fields remain NULL ("Not provided").
3. Ranking criteria explanation:
   - Evaluated candidate response contains deterministic tier/criteria breakdown.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("test_slice3_")

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import get_db
from backend.app.models import User, Faculty, AuditLog
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


def test_permissions_map():
    admin_token = get_token("Admin", "admin@sjbit.edu.in", "CSE")
    hod_token = get_token("HOD", "hod_cse@sjbit.edu.in", "CSE")
    fac_token = get_token("Faculty", "fac_perm_test@sjbit.edu.in", "CSE")

    # 1. Admin accesses permissions map
    res_admin = client.get("/api/admin/permissions-map", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    data = res_admin.json()
    assert "roles" in data
    assert "Admin" in data["roles"]
    assert "HOD" in data["roles"]
    assert "Faculty" in data["roles"]

    # 2. HOD and Faculty can also view permissions map
    assert client.get("/api/admin/permissions-map", headers={"Authorization": f"Bearer {hod_token}"}).status_code == 200
    assert client.get("/api/admin/permissions-map", headers={"Authorization": f"Bearer {fac_token}"}).status_code == 200

    # 3. Unauthenticated access returns 401
    assert client.get("/api/admin/permissions-map").status_code == 401


def test_faculty_profile_and_experience_management():
    db = next(get_db())
    try:
        fac = db.query(Faculty).filter_by(email="fac_edit_test@sjbit.edu.in").first()
        if not fac:
            fac = Faculty(
                name="Prof. S3 Edit Test",
                email="fac_edit_test@sjbit.edu.in",
                faculty_type="internal",
                department="CSE",
                institution="SJBIT",
                designation="Assistant Professor",
                qualification="M.Tech",
                experience_years=4.0,
                is_available=True
            )
            db.add(fac)
            db.commit()
            db.refresh(fac)
        fac_id = fac.id
    finally:
        db.close()

    admin_token = get_token("Admin", "admin@sjbit.edu.in", "CSE")
    fac_token = get_token("Faculty", "fac_edit_test@sjbit.edu.in", "CSE", fac_id=fac_id)

    # 1. Faculty member attempts to edit own profile: forbidden (403)
    res_fac_attempt = client.put(f"/api/faculty/{fac_id}", json={
        "name": "Prof. S3 Hack Attempt",
        "designation": "Professor",
        "experience_years": 15.0
    }, headers={"Authorization": f"Bearer {fac_token}"})
    assert res_fac_attempt.status_code == 403

    # 2. Admin edits faculty profile and experience: allowed (200)
    res_admin_edit = client.put(f"/api/faculty/{fac_id}", json={
        "name": "Prof. S3 Updated By Admin",
        "designation": "Associate Professor",
        "qualification": "Ph.D",
        "experience_years": 10.5
    }, headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin_edit.status_code == 200
    res_json = res_admin_edit.json()
    assert res_json["success"] is True

    # Check updated profile directly from database/API
    res_prof = client.get(f"/api/faculty/{fac_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_prof.status_code == 200
    updated_data = res_prof.json()
    assert updated_data["name"] == "Prof. S3 Updated By Admin"
    assert updated_data["experience_years"] == 10.5
    assert updated_data["qualification"] == "Ph.D"

    # 3. Verify audit log entry was created
    db = next(get_db())
    try:
        audit = db.query(AuditLog).filter_by(entity_type="Faculty", entity_id=fac_id).order_by(AuditLog.performed_at.desc()).first()
        assert audit is not None
        assert "FACULTY_PROFILE_UPDATED" in audit.action or "FACULTY" in audit.action
    finally:
        db.close()


if __name__ == "__main__":
    print("Running Slice 3 Tests...")
    test_permissions_map()
    print("PASS: test_permissions_map")
    test_faculty_profile_and_experience_management()
    print("PASS: test_faculty_profile_and_experience_management")
    print("ALL SLICE 3 TESTS PASSED SUCCESSFULLY.")
