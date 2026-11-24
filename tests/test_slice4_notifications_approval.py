"""
Slice 4 Tests: Notifications on approval.
Verifies:
1. In-app notification created per assigned faculty upon HOD approval.
2. Graceful SMTP fallback:
   - When SMTP not configured in .env, email_status is 'NOT_CONFIGURED'.
   - When faculty has no email on record, email_status is 'no email on record'.
3. SMS adapter:
   - When SMS not configured in .env, returns 'SMS not configured'.
   - When faculty has no phone on record, returns 'no phone on record'.
4. Security: No secrets, credentials, or internal SMTP passwords exposed in API responses.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("test_slice4_")

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import get_db
from backend.app.models import (
    User, Faculty, Subject, Allocation, AllocationSetter,
    InAppNotification, WorkloadLedger
)
from backend.app.services.notification_service import (
    try_send_email, try_send_sms, notify_request_approved
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


def test_notifications_on_hod_approval():
    db = next(get_db())
    try:
        # Create faculty with email & phone
        fac1 = db.query(Faculty).filter_by(email="fac_s4_with_email@sjbit.edu.in").first()
        if not fac1:
            fac1 = Faculty(
                name="Dr. S4 With Contact",
                email="fac_s4_with_email@sjbit.edu.in",
                mobile="9888877777",
                faculty_type="internal",
                department="CSE",
                institution="SJBIT",
                designation="Professor",
                qualification="Ph.D",
                experience_years=12.0,
                is_available=True
            )
            db.add(fac1)
            db.commit()
            db.refresh(fac1)

        # Create faculty WITHOUT email or phone (None)
        fac2 = db.query(Faculty).filter_by(name="Prof. S4 No Contact").first()
        if not fac2:
            fac2 = Faculty(
                name="Prof. S4 No Contact",
                email=None,
                mobile=None,
                faculty_type="internal",
                department="CSE",
                institution="SJBIT",
                designation="Assistant Professor",
                qualification="M.Tech",
                experience_years=5.0,
                is_available=True
            )
            db.add(fac2)
            db.commit()
            db.refresh(fac2)

        # Ensure User account for fac1 exists
        u_fac1 = db.query(User).filter_by(email=fac1.email).first()
        if not u_fac1:
            u_fac1 = User(
                username="fac_s4_1",
                email=fac1.email,
                password_hash=hash_password("TestSecret123"),
                role="Faculty",
                department="CSE",
                faculty_id=fac1.id,
                full_name=fac1.name,
                is_active=True
            )
            db.add(u_fac1)
            db.commit()
            db.refresh(u_fac1)

        # Ensure User account for fac2 exists
        u_fac2 = db.query(User).filter_by(faculty_id=fac2.id).first()
        if not u_fac2:
            u_fac2 = User(
                username="fac_s4_2",
                email="fac_s4_2_temp@sjbit.edu.in",
                password_hash=hash_password("TestSecret123"),
                role="Faculty",
                department="CSE",
                faculty_id=fac2.id,
                full_name=fac2.name,
                is_active=True
            )
            db.add(u_fac2)
            db.commit()
            db.refresh(u_fac2)

        # Create Subject
        subj = db.query(Subject).filter_by(course_code="21CS81").first()
        if not subj:
            subj = Subject(
                course_code="21CS81",
                title="Advanced Cybersecurity",
                department="CSE",
                semester="8",
                academic_year="2025-26",
                scheme="2021",
                credits=4
            )
            db.add(subj)
            db.commit()
            db.refresh(subj)

        # Create Allocation in Pending HOD Approval
        alloc = Allocation(
            reference_number="SJBIT-CSE-S4-NOTIF",
            subject_id=subj.id,
            academic_year="2025-26",
            department="CSE",
            semester="8",
            status="Pending HOD Approval",
            total_required=2
        )
        db.add(alloc)
        db.commit()
        db.refresh(alloc)

        # Add setters
        s1 = AllocationSetter(
            allocation_id=alloc.id,
            faculty_id=fac1.id,
            faculty_type="internal",
            assigned_order=1,
            status="Nominated"
        )
        s2 = AllocationSetter(
            allocation_id=alloc.id,
            faculty_id=fac2.id,
            faculty_type="internal",
            assigned_order=2,
            status="Nominated"
        )
        db.add_all([s1, s2])
        db.commit()

        # Add reserved ledger entries
        db.add(WorkloadLedger(faculty_id=fac1.id, academic_year="2025-26", entry_type="RESERVED", delta=1))
        db.add(WorkloadLedger(faculty_id=fac2.id, academic_year="2025-26", entry_type="RESERVED", delta=1))
        db.commit()

        alloc_id = alloc.id
        fac1_user_id = u_fac1.id
        fac2_user_id = u_fac2.id
    finally:
        db.close()

    hod_token = get_token("HOD", "hod_cse@sjbit.edu.in", "CSE")

    # Ensure SMTP and SMS are unset in test environment
    os.environ.pop("SMTP_HOST", None)
    os.environ.pop("SMS_PROVIDER", None)

    # HOD approves the allocation
    res_approve = client.post(
        f"/api/allocation/{alloc_id}/approve",
        json={"remarks": "Approved with notification verification"},
        headers={"Authorization": f"Bearer {hod_token}"}
    )
    assert res_approve.status_code == 200, f"Approve error: {res_approve.text}"

    # Verify notifications were created in database
    db = next(get_db())
    try:
        notifs = db.query(InAppNotification).filter(
            InAppNotification.entity_id == alloc_id,
            InAppNotification.event_type == "FACULTY_ASSIGNED"
        ).all()
        assert len(notifs) >= 2, f"Expected notifications for both setters, got {len(notifs)}"

        notif_fac1 = [n for n in notifs if n.user_id == fac1_user_id][0]
        assert "Appointed as Question Paper Setter" in notif_fac1.title
        # SMTP was not configured, so status must be NOT_CONFIGURED
        assert notif_fac1.email_status == "NOT_CONFIGURED"

        # Check adapter responses directly for missing credentials
        assert try_send_email(None, "Subject", "Body") == "no email on record"
        assert try_send_email("", "Subject", "Body") == "no email on record"
        assert try_send_sms(None, "Body") == "no phone on record"
        assert try_send_sms("9876543210", "Body") == "SMS not configured"

    finally:
        db.close()


def test_no_credentials_exposed_in_api():
    faculty_token = get_token("Faculty", "fac_s4_with_email@sjbit.edu.in", "CSE")
    res = client.get("/api/notifications/my", headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 200
    res_text = res.text
    # Strictly ensure no SMTP/SMS credentials appear in JSON responses
    assert "SMTP_PASSWORD" not in res_text
    assert "SECRET_KEY" not in res_text
    assert "SMS_API_KEY" not in res_text


if __name__ == "__main__":
    print("Running Slice 4 Tests...")
    test_notifications_on_hod_approval()
    print("PASS: test_notifications_on_hod_approval")
    test_no_credentials_exposed_in_api()
    print("PASS: test_no_credentials_exposed_in_api")
    print("ALL SLICE 4 TESTS PASSED SUCCESSFULLY.")
