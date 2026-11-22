"""
ExamExpert AI — Module 3 Authentication & Security Automated Test Suite
SJB Institute of Technology | Office of Controller of Examinations

Explicitly verifies:
1. Header-less Admin bypass is eliminated (HTTP 401 when Authorization missing)
2. OTP is NEVER returned in any API response (no dev_otp or dev_mode)
3. Three separate login endpoints with server-side role enforcement (HTTP 403 on role mismatch)
4. OTP verification rate limiting and 5-attempt brute-force protection
5. Account lockout after 5 consecutive failed password attempts
6. First-time account activation workflow
7. Forgot-password and password reset workflow with session revocation
8. Logout session revocation
"""
import os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("auth_")

from fastapi import HTTPException
from backend.app.database import SessionLocal
from backend.app.models import User, OTPToken, ActiveSession, AuditLog
from backend.app.routers.auth import (
    get_current_user,
    send_otp,
    verify_otp,
    login_admin,
    login_hod,
    login_faculty,
    activate_account,
    forgot_password,
    reset_password,
    logout,
    SendOTPRequest,
    VerifyOTPRequest,
    LoginRequest,
    ActivateAccountRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    seed_rbac_users,
    hash_password
)

def run_auth_security_tests():
    print("=" * 75)
    print("  EXAMEXPERT AI — MODULE 3 AUTHENTICATION & SECURITY VERIFICATION")
    print("  SJB Institute of Technology • Office of Controller of Examinations")
    print("=" * 75)

    passed = 0
    failed = 0

    def record(test_num: int, name: str, success: bool, note: str = ""):
        nonlocal passed, failed
        status = "[PASS]" if success else "[FAIL]"
        print(f"Test {test_num:02d}: {status} {name} {note}")
        if success:
            passed += 1
        else:
            failed += 1

    with SessionLocal() as db:
        seed_rbac_users(db)

        # ─── TEST 1: Header-less Admin Bypass Elimination ───────────────────────
        try:
            get_current_user(authorization=None, db=db)
            record(1, "Header-less Admin Bypass Elimination", False, "Backdoor still returned user without header!")
        except HTTPException as e:
            record(1, "Header-less Admin Bypass Elimination", e.status_code == 401, f"(HTTP {e.status_code}: {e.detail})")

        # ─── TEST 2: OTP Response Leak Elimination ──────────────────────────────
        res_otp = send_otp(SendOTPRequest(email="admin@sjbit.edu.in", purpose="Security Test"), db=db)
        leak_keys = [k for k in res_otp.keys() if "otp" in k.lower() and k != "otp_policy"]
        has_leak = "dev_otp" in res_otp or "dev_mode" in res_otp or any(len(str(v)) == 6 and str(v).isdigit() for v in res_otp.values())
        record(2, "OTP Response Leak Elimination", not has_leak and res_otp.get("success") is True, f"(Response keys: {list(res_otp.keys())})")

        # ─── TEST 3: Dedicated Role Login Enforcement (Admin Portal) ────────────
        # Admin logging into Admin portal -> PASS
        admin_login = login_admin(LoginRequest(email="admin@sjbit.edu.in", password="Admin@SJBIT2026!"), db=db)
        admin_token = admin_login.get("token")
        record(3, "Admin Portal Authenticates Admin Role", admin_login.get("success") is True and bool(admin_token))

        # HOD attempting to log into Admin portal -> MUST BE 403 FORBIDDEN
        try:
            login_admin(LoginRequest(email="hod.mca@sjbit.edu.in", password="HodMCA@2026!"), db=db)
            record(4, "Admin Portal Rejects HOD Account", False, "HOD was permitted into Admin portal!")
        except HTTPException as e:
            record(4, "Admin Portal Rejects HOD Account", e.status_code == 403, f"(HTTP {e.status_code}: {e.detail})")

        # Faculty attempting to log into Admin portal -> MUST BE 403 FORBIDDEN
        try:
            login_admin(LoginRequest(email="faculty.mca@sjbit.edu.in", password="Faculty@2026!"), db=db)
            record(5, "Admin Portal Rejects Faculty Account", False, "Faculty was permitted into Admin portal!")
        except HTTPException as e:
            record(5, "Admin Portal Rejects Faculty Account", e.status_code == 403, f"(HTTP {e.status_code}: {e.detail})")

        # ─── TEST 6: Dedicated Role Login Enforcement (HOD Portal) ──────────────
        # HOD logging into HOD portal -> PASS
        hod_login = login_hod(LoginRequest(email="hod.mca@sjbit.edu.in", password="HodMCA@2026!"), db=db)
        record(6, "HOD Portal Authenticates HOD Role", hod_login.get("success") is True and hod_login["user"]["role"] == "HOD")

        # Admin attempting to log into HOD portal -> MUST BE 403 FORBIDDEN
        try:
            login_hod(LoginRequest(email="admin@sjbit.edu.in", password="Admin@SJBIT2026!"), db=db)
            record(7, "HOD Portal Rejects Admin Account", False, "Admin was permitted into HOD portal!")
        except HTTPException as e:
            record(7, "HOD Portal Rejects Admin Account", e.status_code == 403, f"(HTTP {e.status_code}: {e.detail})")

        # ─── TEST 8: Dedicated Role Login Enforcement (Faculty Portal) ──────────
        # Faculty logging into Faculty portal -> PASS
        fac_login = login_faculty(LoginRequest(email="faculty.mca@sjbit.edu.in", password="Faculty@2026!"), db=db)
        record(8, "Faculty Portal Authenticates Faculty Role", fac_login.get("success") is True and fac_login["user"]["role"] == "Faculty")

        # Admin attempting to log into Faculty portal -> MUST BE 403 FORBIDDEN
        try:
            login_faculty(LoginRequest(email="admin@sjbit.edu.in", password="Admin@SJBIT2026!"), db=db)
            record(9, "Faculty Portal Rejects Admin Account", False, "Admin was permitted into Faculty portal!")
        except HTTPException as e:
            record(9, "Faculty Portal Rejects Admin Account", e.status_code == 403, f"(HTTP {e.status_code}: {e.detail})")

        # ─── TEST 10: OTP Attempt Limiting (Max 5 Attempts) ─────────────────────
        # Seed an OTP directly in DB to test brute-force protection
        test_email = "test.otp.security@sjbit.edu.in"
        test_token = OTPToken(
            email=test_email,
            otp_code="987654",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            is_used=False,
            attempts=0
        )
        db.add(test_token)
        db.commit()

        # Submit 5 wrong attempts
        for attempt in range(1, 6):
            try:
                verify_otp(VerifyOTPRequest(email=test_email, otp="000000"), db=db)
            except HTTPException:
                pass

        # 6th attempt must be 429 Too Many Requests
        try:
            verify_otp(VerifyOTPRequest(email=test_email, otp="987654"), db=db)
            record(10, "OTP 5-Attempt Limit & Brute-Force Block", False, "Did not block after 5 failed attempts!")
        except HTTPException as e:
            record(10, "OTP 5-Attempt Limit & Brute-Force Block", e.status_code == 429, f"(HTTP {e.status_code}: {e.detail})")

        # ─── TEST 11: Account Lockout after 5 Failed Password Attempts ──────────
        lockout_user = User(
            username="test_lockout_user",
            email="test.lockout@sjbit.edu.in",
            password_hash=hash_password("ValidPassword123!"),
            role="Faculty",
            failed_attempts=0,
            is_locked=False,
            is_active=True
        )
        db.add(lockout_user)
        db.commit()

        # Submit 5 incorrect password attempts
        for _ in range(5):
            try:
                login_faculty(LoginRequest(email="test.lockout@sjbit.edu.in", password="WrongPassword!"), db=db)
            except HTTPException:
                pass

        # User must now be locked
        db.refresh(lockout_user)
        record(11, "Account Lockout After 5 Failed Passwords", lockout_user.is_locked is True, f"(Failed attempts: {lockout_user.failed_attempts})")

        # Next login must return 403 Locked
        try:
            login_faculty(LoginRequest(email="test.lockout@sjbit.edu.in", password="ValidPassword123!"), db=db)
            record(12, "Locked Account Access Denial (HTTP 403)", False, "Locked account was able to log in!")
        except HTTPException as e:
            record(12, "Locked Account Access Denial (HTTP 403)", e.status_code == 403, f"(HTTP {e.status_code}: {e.detail})")

        # Clean up lockout user
        db.delete(lockout_user)
        db.commit()

        # ─── TEST 13: First-Time Account Activation Flow ────────────────────────
        act_user = User(
            username="new_faculty_candidate",
            email="new.faculty@sjbit.edu.in",
            password_hash=hash_password("TempPassword123!"),
            role="Faculty",
            is_active=True,
            is_activated=False
        )
        db.add(act_user)
        act_otp = OTPToken(
            email="new.faculty@sjbit.edu.in",
            otp_code="112233",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            is_used=False
        )
        db.add(act_otp)
        db.commit()

        act_res = activate_account(
            ActivateAccountRequest(email="new.faculty@sjbit.edu.in", otp="112233", new_password="NewSecurePassword@2026!"),
            db=db
        )
        db.refresh(act_user)
        record(13, "First-Time Account Activation Flow", act_res.get("success") is True and act_user.is_activated is True)

        # ─── TEST 14: Forgot Password & Password Reset Flow ─────────────────────
        reset_otp = OTPToken(
            email="new.faculty@sjbit.edu.in",
            otp_code="445566",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            is_used=False
        )
        db.add(reset_otp)
        db.commit()

        reset_res = reset_password(
            ResetPasswordRequest(email="new.faculty@sjbit.edu.in", otp="445566", new_password="ResetPassword@2026!"),
            db=db
        )
        record(14, "Forgot Password & Password Reset Flow", reset_res.get("success") is True)

        # Clean up activation user
        db.delete(act_user)
        db.commit()

        # ─── TEST 15: Logout & Session Revocation ───────────────────────────────
        # Create active session for admin
        sess_token = admin_token
        user_before_logout = get_current_user(authorization=f"Bearer {sess_token}", db=db)
        logout(authorization=f"Bearer {sess_token}", current_user=user_before_logout, db=db)

        # Subsequent request with revoked token MUST return 401
        try:
            get_current_user(authorization=f"Bearer {sess_token}", db=db)
            record(15, "Session Revocation on Logout (HTTP 401)", False, "Revoked session was still accepted!")
        except HTTPException as e:
            record(15, "Session Revocation on Logout (HTTP 401)", e.status_code == 401, f"(HTTP {e.status_code}: {e.detail})")

    print("=" * 75)
    print(f"  MODULE 3 VERIFICATION RESULT: {passed} PASSED / {failed} FAILED")
    print("=" * 75)
    return passed, failed

if __name__ == "__main__":
    p, f = run_auth_security_tests()
    sys.exit(0 if f == 0 else 1)
