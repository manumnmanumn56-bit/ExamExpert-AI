"""
ExamExpert AI — Module 4 Admin Dashboard & User Management Verification Tests
SJB Institute of Technology | Office of Controller of Examinations

Tests:
1. Live dashboard stats computed directly from the database (no hardcoding).
2. User listing (safe projection, no password hash leaks).
3. User creation with validation and audit logging.
4. User editing with self-protection guardrails.
5. Account unlocking and failed-attempt reset.
6. Server-side password reset with session revocation and zero password leaks.
7. User deactivation/reactivation and session revocation.
8. Server-side role enforcement: HOD/Faculty attempting admin operations receive 403.
"""
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("mod4_")

from fastapi import HTTPException
from backend.app.database import SessionLocal
from backend.app.models import User, Faculty, Subject, AuditLog, ActiveSession
from backend.app.routers.admin import (
    get_dashboard_stats,
    list_users,
    create_user,
    update_user,
    unlock_user,
    admin_reset_password,
    deactivate_user,
    activate_user,
    CreateUserRequest,
    UpdateUserRequest,
    AdminResetPasswordRequest
)
from backend.app.routers.auth import seed_rbac_users, verify_password, create_session


def test_module4_admin_user_management():
    db = SessionLocal()
    try:
        # Seed users
        seed_rbac_users(db)

        admin = db.query(User).filter_by(role="Admin").first()
        hod = db.query(User).filter_by(role="HOD", department="CSE").first()
        faculty = db.query(User).filter_by(role="Faculty").first()

        assert admin is not None, "Admin user must exist"
        assert hod is not None, "HOD user must exist"
        assert faculty is not None, "Faculty user must exist"

        print(f"[INIT] Admin: {admin.username}, HOD: {hod.username}, Faculty: {faculty.username}")

        # ─── 1. Test Live Dashboard Stats ─────────────────────────────────────
        stats = get_dashboard_stats(db=db, current_user=admin)
        print(f"[OK] Dashboard Stats: {stats['faculty']}")
        assert stats["faculty"]["internal_count"] == 47, f"Expected 47 internal faculty, got {stats['faculty']['internal_count']}"
        assert stats["faculty"]["external_count"] == 77, f"Expected 77 external faculty, got {stats['faculty']['external_count']}"
        assert stats["faculty"]["total_faculty"] == 124
        assert stats["syllabus"]["total_subjects_count"] == 195
        assert stats["users"]["total_users"] >= 5
        assert "Draft" in stats["allocations"]["by_status"]

        # ─── 2. Test Safe User Listing ────────────────────────────────────────
        user_list = list_users(db=db, current_user=admin)
        assert user_list["total"] >= 5
        for u in user_list["users"]:
            assert "password_hash" not in u, f"CRITICAL LEAK: password_hash exposed in user listing for {u['username']}!"
            assert "reset_token" not in u, f"CRITICAL LEAK: reset_token exposed in user listing for {u['username']}!"
            assert "activation_token" not in u, f"CRITICAL LEAK: activation_token exposed in user listing for {u['username']}!"
            assert "last_login_at" in u
        print(f"[OK] User listing safely returned {user_list['total']} accounts without credential leaks")

        # ─── 3. Test User Creation ────────────────────────────────────────────
        test_uname = "mod4_tester"
        test_email = "mod4_tester@sjbit.edu.in"
        # Cleanup if leftover from earlier run
        existing = db.query(User).filter_by(username=test_uname).first()
        if existing:
            db.delete(existing)
            db.commit()

        req_create = CreateUserRequest(
            username=test_uname,
            email=test_email,
            password="StrongPassword2026!",
            role="Faculty",
            department="CSE",
            full_name="Module 4 Verification Faculty",
            phone="9876543210"
        )
        created = create_user(req=req_create, db=db, current_user=admin)
        assert created["success"] is True
        new_uid = created["user_id"]
        print(f"[OK] Created new user {test_uname} (id={new_uid})")

        # Verify created in DB with Bcrypt hash
        new_u = db.query(User).filter_by(id=new_uid).first()
        assert new_u is not None
        assert new_u.password_hash.startswith(("$2a$", "$2b$", "$2y$"))
        assert verify_password("StrongPassword2026!", new_u.password_hash)

        # Verify audit log
        log = db.query(AuditLog).filter_by(action="ADMIN_USER_CREATED", entity_id=new_uid).first()
        assert log is not None, "Audit log ADMIN_USER_CREATED not found!"
        print(f"[OK] Audit log verified: {log.action} - {log.details}")

        # Test duplicate username rejection
        try:
            create_user(req=req_create, db=db, current_user=admin)
            assert False, "Duplicate user creation should have raised 400!"
        except HTTPException as e:
            assert e.status_code == 400
            print("[OK] Duplicate user properly rejected with 400")

        # ─── 4. Test User Editing ─────────────────────────────────────────────
        req_update = UpdateUserRequest(
            full_name="Updated Faculty Name",
            phone="9123456780",
            department="ISE"
        )
        upd_res = update_user(user_id=new_uid, req=req_update, db=db, current_user=admin)
        assert upd_res["success"] is True

        db.refresh(new_u)
        assert new_u.full_name == "Updated Faculty Name"
        assert new_u.department == "ISE"
        assert new_u.phone == "9123456780"
        print(f"[OK] Updated user {new_u.username} details successfully")

        # Test self-deactivation guardrail
        try:
            update_user(user_id=admin.id, req=UpdateUserRequest(is_active=False), db=db, current_user=admin)
            assert False, "Self-deactivation of admin should have been blocked!"
        except HTTPException as e:
            assert e.status_code == 400
            print("[OK] Admin self-deactivation blocked with 400")

        # ─── 5. Test Account Unlocking ────────────────────────────────────────
        new_u.is_locked = True
        new_u.failed_attempts = 5
        db.commit()

        unlock_res = unlock_user(user_id=new_uid, db=db, current_user=admin)
        assert unlock_res["success"] is True
        db.refresh(new_u)
        assert new_u.is_locked is False
        assert new_u.failed_attempts == 0
        print(f"[OK] Account {new_u.username} unlocked and failed attempts reset to 0")

        # ─── 6. Test Admin Password Reset ─────────────────────────────────────
        # Create active session for user
        token = create_session(new_u, db)
        session_entry = db.query(ActiveSession).filter_by(token=token).first()
        assert session_entry.is_revoked is False

        reset_req = AdminResetPasswordRequest(new_password="NewAdminSetPassword2026!")
        reset_res = admin_reset_password(user_id=new_uid, req=reset_req, db=db, current_user=admin)
        assert reset_res["success"] is True
        assert "NewAdminSetPassword2026!" not in reset_res["message"], "CRITICAL: Plaintext password leaked in message!"

        db.refresh(new_u)
        db.refresh(session_entry)
        assert verify_password("NewAdminSetPassword2026!", new_u.password_hash)
        assert session_entry.is_revoked is True, "User active session should be revoked after admin password reset!"
        print(f"[OK] Server-side password reset verified: new hash valid, session revoked, no password leaks")

        # ─── 7. Test Deactivate and Reactivate ─────────────────────────────────
        deact_res = deactivate_user(user_id=new_uid, db=db, current_user=admin)
        assert deact_res["success"] is True
        db.refresh(new_u)
        assert new_u.is_active is False
        print(f"[OK] User {new_u.username} deactivated successfully")

        act_res = activate_user(user_id=new_uid, db=db, current_user=admin)
        assert act_res["success"] is True
        db.refresh(new_u)
        assert new_u.is_active is True
        print(f"[OK] User {new_u.username} reactivated successfully")

        # ─── 8. Test Non-Admin 403 Enforcement ────────────────────────────────
        from backend.app.routers.auth import require_roles
        admin_guard = require_roles(["Admin"])

        try:
            admin_guard(current_user=hod)
            assert False, "HOD should be blocked by Admin role guard!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] HOD blocked from Admin endpoint with 403: {e.detail}")

        try:
            admin_guard(current_user=faculty)
            assert False, "Faculty should be blocked by Admin role guard!"
        except HTTPException as e:
            assert e.status_code == 403
            print(f"[OK] Faculty blocked from Admin endpoint with 403: {e.detail}")

        # Cleanup test user
        db.delete(new_u)
        db.commit()
        print("[CLEANUP] Test user removed")

        print("\n[ALL MODULE 4 TESTS PASSED] Admin Dashboard Stats & User Management fully verified.")

    finally:
        db.close()


if __name__ == "__main__":
    test_module4_admin_user_management()
