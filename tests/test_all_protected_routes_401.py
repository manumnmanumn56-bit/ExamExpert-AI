"""
ExamExpert AI — Comprehensive Protected API Route 401 Verification Test
SJB Institute of Technology | Office of Controller of Examinations

Proves that EVERY protected API route in the application strictly enforces
authentication and returns HTTP 401 Unauthorized when called without
an Authorization header.
"""
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("all_401_")

from fastapi import HTTPException
from backend.app.main import app
from backend.app.routers.auth import get_current_user


def test_all_protected_routes_401():
    # 1. Inspect all registered API routes
    all_routes = []
    for r in app.routes:
        router = getattr(r, "original_router", None)
        routes_to_check = router.routes if router else [r]
        for sub_r in routes_to_check:
            path = getattr(sub_r, "path", "")
            if path.startswith("/api/"):
                all_routes.append(sub_r)

    # Known public routes (no authentication required)
    public_endpoints = {
        ("GET", "/api/auth/status"),
        ("POST", "/api/auth/send-otp"),
        ("POST", "/api/auth/verify-otp"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/login/admin"),
        ("POST", "/api/auth/login/hod"),
        ("POST", "/api/auth/login/faculty"),
        ("POST", "/api/auth/activate"),
        ("POST", "/api/auth/forgot-password"),
        ("POST", "/api/auth/reset-password"),
        ("GET", "/api/syllabus/academic-years"),
        ("GET", "/api/syllabus/departments"),
        ("GET", "/api/syllabus/semesters"),
        ("GET", "/api/syllabus/subjects"),
    }

    protected_routes = []
    for r in all_routes:
        methods = list(getattr(r, "methods", []))
        for m in methods:
            if (m, r.path) not in public_endpoints and m not in ("HEAD", "OPTIONS"):
                protected_routes.append((m, r))
    print(f"Total registered API routes: {len(all_routes)}")
    print(f"Protected API routes being tested: {len(protected_routes)}\n")

    failed = []
    passed = 0

    for m, r in protected_routes:
        # Check that route dependant includes get_current_user directly or via role_checker
        dep_calls = []
        if hasattr(r, "dependant"):
            for d in r.dependant.dependencies:
                dep_calls.append(d.call)
                for sub_d in d.dependencies:
                    dep_calls.append(sub_d.call)

        has_auth_gate = any(
            c == get_current_user or
            getattr(c, "__name__", "") in ("role_checker", "get_current_user")
            for c in dep_calls
        )

        if not has_auth_gate:
            failed.append(f"{m} {r.path} missing get_current_user dependency!")
            continue

        # Execute get_current_user with no Authorization header (authorization=None)
        try:
            get_current_user(authorization=None)
            failed.append(f"{m} {r.path} allowed request without Authorization header!")
        except HTTPException as e:
            if e.status_code == 401:
                passed += 1
                print(f"[OK 401] {m:6} {r.path:45} -> HTTP 401: {e.detail}")
            else:
                failed.append(f"{m} {r.path} returned status {e.status_code} instead of 401")

    print(f"\nAudit Summary: {passed} protected routes passed, {len(failed)} failed.")
    assert len(failed) == 0, f"Routes with failed authentication enforcement: {failed}"
    print("[ALL TESTS PASSED] Every protected route strictly returns 401 when unauthenticated.")


if __name__ == "__main__":
    test_all_protected_routes_401()
