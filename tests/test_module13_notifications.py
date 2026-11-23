"""
ExamExpert AI — Module 13 Notifications Automated Test Suite
SJB Institute of Technology | Office of Controller of Examinations

Explicitly verifies:
1. Event-Triggered Notification Creation:
   - Allocation submission triggers In-App notification for departmental HOD (REQUEST_SUBMITTED)
   - HOD approval triggers In-App notification for Admin (REQUEST_APPROVED) and Faculty (FACULTY_ASSIGNED)
   - HOD rejection triggers In-App notification for Admin with rejection reason (REQUEST_REJECTED)
2. Strict User Scoping:
   - Each user retrieves ONLY their personal notifications
   - HOD cannot see Admin or Faculty notifications
   - Faculty cannot see other faculty or administrative notifications
   - Cross-user mark-as-read is strictly blocked
3. Read / Unread Lifecycle:
   - Notifications initialize as unread (is_read=False)
   - Real-time unread count indicator accuracy
   - Single notification mark-as-read with timestamp
   - Bulk mark-all-read
4. Secret & Credential Safety:
   - Notification messages and payloads NEVER contain passwords, OTPs, or SMTP secrets
   - Unauthenticated requests strictly return HTTP 401
"""
import os, sys, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("mod13_")

from fastapi import HTTPException
from sqlalchemy.orm import Session
from backend.app.database import SessionLocal
from backend.app.models import (
    User, Faculty, Subject, Allocation, AllocationSetter,
    InAppNotification, EligibilityRules
)
from backend.app.services.notification_service import (
    notify_request_submitted,
    notify_request_approved,
    notify_request_rejected,
    is_smtp_configured
)
from backend.app.routers.notifications import (
    get_my_notifications,
    get_unread_count,
    mark_notification_read,
    mark_all_notifications_read
)


def run_module13_tests():
    print("=" * 75)
    print("  EXAMEXPERT AI — MODULE 13 NOTIFICATIONS SYSTEM VERIFICATION")
    print("  SJB Institute of Technology • Office of Controller of Examinations")
    print("=" * 75)

    db: Session = SessionLocal()
    passed = 0
    failed = 0

    try:
        # Retrieve test accounts
        admin_user = db.query(User).filter_by(role="Admin").first()
        hod_mca = db.query(User).filter_by(role="HOD", department="MCA").first()
        faculty_user = db.query(User).filter_by(role="Faculty").first()

        assert admin_user is not None, "Admin user must exist"
        assert hod_mca is not None, "HOD MCA user must exist"
        assert faculty_user is not None, "Faculty user must exist"

        # Link faculty_user to a faculty record if not already linked
        fac_rec = db.query(Faculty).filter_by(email=faculty_user.email).first()
        if not fac_rec:
            fac_rec = Faculty(
                name=faculty_user.full_name or "Test Faculty",
                email=faculty_user.email,
                faculty_type="internal",
                department="MCA",
                designation="Associate Professor",
                qualification="Ph.D",
                experience_years=12.0,
                is_available=True
            )
            db.add(fac_rec)
            db.commit()
            db.refresh(fac_rec)

        faculty_user.faculty_id = fac_rec.id
        db.commit()

        # Setup test course and allocation
        subj = Subject(
            course_code="25MCA305",
            title="Software Architecture & Design Patterns",
            department="MCA",
            semester="III",
            scheme="2025",
            academic_year="2025-26"
        )
        db.add(subj)
        db.commit()

        alloc = Allocation(
            reference_number="SJBIT-COE-NOTIF-TEST-01",
            academic_year="2025-26",
            department="MCA",
            semester="III",
            subject_id=subj.id,
            allocation_mode="Balanced",
            total_required=2,
            internal_required=1,
            external_required=1,
            status="Pending HOD Approval",
            submitted_by=admin_user.username
        )
        db.add(alloc)
        db.flush()

        setter = AllocationSetter(
            allocation_id=alloc.id,
            faculty_id=fac_rec.id,
            faculty_type="internal",
            status="Nominated",
            assigned_order=1
        )
        db.add(setter)
        db.commit()

        # ─── TEST 1: Event 1 - Request Submitted Notification ────────────────
        print("\n[TEST 1] Event 1: Request Submitted Notification to Department HOD...")
        notifs_sub = notify_request_submitted(db, alloc, subj, admin_user.username)
        db.commit()
        assert len(notifs_sub) >= 1, "At least one HOD notification must be generated"
        hod_notif = notifs_sub[0]
        assert hod_notif.user_id == hod_mca.id, "Notification must be addressed to MCA HOD"
        assert hod_notif.event_type == "REQUEST_SUBMITTED"
        assert "25MCA305" in hod_notif.message
        assert hod_notif.is_read is False

        print("  ✓ PASS: HOD received In-App notification upon allocation submission.")
        passed += 1

        # ─── TEST 2: Event 2 - Request Approved Notification ─────────────────
        print("\n[TEST 2] Event 2: Request Approved Notification to Admin & Appointed Faculty...")
        notifs_app = notify_request_approved(db, alloc, subj, hod_mca.username)
        db.commit()
        assert len(notifs_app) >= 2, "Must generate notifications for both Admin and appointed Faculty"

        admin_notifs = [n for n in notifs_app if n.user_id == admin_user.id]
        fac_notifs = [n for n in notifs_app if n.user_id == faculty_user.id]

        assert len(admin_notifs) >= 1, "Admin must receive approval notification"
        assert admin_notifs[0].event_type == "REQUEST_APPROVED"
        assert "Approved" in admin_notifs[0].title or "Approved" in admin_notifs[0].message

        assert len(fac_notifs) >= 1, "Appointed Faculty must receive appointment notification"
        assert fac_notifs[0].event_type == "FACULTY_ASSIGNED"
        assert "Question Paper Setter" in fac_notifs[0].title

        print("  ✓ PASS: Admin and appointed Faculty received respective notifications upon approval.")
        passed += 1

        # ─── TEST 3: Event 3 - Request Rejected Notification ─────────────────
        print("\n[TEST 3] Event 3: Request Rejected Notification with Reason to Admin...")
        rejection_reason = "Department workload balance requires reselection of internal candidate."
        notifs_rej = notify_request_rejected(db, alloc, subj, hod_mca.username, rejection_reason)
        db.commit()
        assert len(notifs_rej) >= 1
        assert notifs_rej[0].user_id == admin_user.id
        assert notifs_rej[0].event_type == "REQUEST_REJECTED"
        assert rejection_reason in notifs_rej[0].message

        print("  ✓ PASS: Admin received rejection notification including mandatory reason.")
        passed += 1

        # ─── TEST 4: User Scoping Verification ───────────────────────────────
        print("\n[TEST 4] User Scoping Verification (Privacy & Isolation)...")

        # HOD Inbox
        res_hod = get_my_notifications(unread_only=False, limit=50, db=db, current_user=hod_mca)
        assert res_hod["success"] is True
        for n in res_hod["notifications"]:
            # Every notification in HOD inbox must belong to HOD user
            notif_db = db.query(InAppNotification).filter_by(id=n["id"]).first()
            assert notif_db.user_id == hod_mca.id

        # Faculty Inbox
        res_fac = get_my_notifications(unread_only=False, limit=50, db=db, current_user=faculty_user)
        assert res_fac["success"] is True
        for n in res_fac["notifications"]:
            notif_db = db.query(InAppNotification).filter_by(id=n["id"]).first()
            assert notif_db.user_id == faculty_user.id

        # Admin Inbox
        res_adm = get_my_notifications(unread_only=False, limit=50, db=db, current_user=admin_user)
        assert res_adm["success"] is True
        for n in res_adm["notifications"]:
            notif_db = db.query(InAppNotification).filter_by(id=n["id"]).first()
            assert notif_db.user_id == admin_user.id

        # Cross-User Mark Read Prevention
        # Faculty attempts to mark HOD's notification as read
        try:
            mark_notification_read(notification_id=hod_notif.id, db=db, current_user=faculty_user)
            assert False, "Faculty should not be allowed to mark HOD notification as read"
        except HTTPException as e:
            assert e.status_code == 404 or e.status_code == 403

        print("  ✓ PASS: In-app notifications strictly isolated per user; cross-user modification rejected.")
        passed += 1

        # ─── TEST 5: Read / Unread Lifecycle & Counts ────────────────────────
        print("\n[TEST 5] Read / Unread Status Lifecycle & Unread Count...")

        # Check HOD unread count
        count_pre = get_unread_count(db=db, current_user=hod_mca)
        assert count_pre["unread_count"] >= 1

        # Mark single notification as read
        res_read = mark_notification_read(notification_id=hod_notif.id, db=db, current_user=hod_mca)
        assert res_read["success"] is True
        assert res_read["is_read"] is True

        db.refresh(hod_notif)
        assert hod_notif.is_read is True
        assert hod_notif.read_at is not None

        # Verify unread count decremented
        count_post = get_unread_count(db=db, current_user=hod_mca)
        assert count_post["unread_count"] == count_pre["unread_count"] - 1

        # Bulk mark-all-read for Admin
        res_bulk = mark_all_notifications_read(db=db, current_user=admin_user)
        assert res_bulk["success"] is True
        count_adm_post = get_unread_count(db=db, current_user=admin_user)
        assert count_adm_post["unread_count"] == 0

        print("  ✓ PASS: Read/unread status transitions, timestamps, and badge counters operate accurately.")
        passed += 1

        # ─── TEST 6: Secret & Credential Safety (No Leaks) ───────────────────
        print("\n[TEST 6] Secret & Credential Safety Check...")

        all_notifs = db.query(InAppNotification).all()
        forbidden_keywords = ["password", "secret", "smtp_password", "token_hash", "otp_secret", "admin@sjbit2026!"]

        for n in all_notifs:
            full_text = f"{n.title} {n.message}".lower()
            for kw in forbidden_keywords:
                assert kw not in full_text, f"Forbidden keyword '{kw}' detected in notification #{n.id}!"

        # Unauthenticated request test
        try:
            get_my_notifications(unread_only=False, limit=10, db=db, current_user=None)
            assert False, "Unauthenticated request must raise HTTP 401"
        except HTTPException as e:
            assert e.status_code == 401

        print("  ✓ PASS: Zero sensitive secrets in notification payloads; unauthenticated access blocked with HTTP 401.")
        passed += 1

    except Exception as ex:
        print(f"\n❌ UNHANDLED EXCEPTION in Module 13 test: {ex}")
        import traceback
        traceback.print_exc()
        failed += 1
    finally:
        db.close()

    print("\n" + "=" * 75)
    print(f"  MODULE 13 TEST SUMMARY: {passed} PASSED | {failed} FAILED")
    print("=" * 75)
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_module13_tests()
