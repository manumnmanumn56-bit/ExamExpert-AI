"""
ExamExpert AI — Module 15 Automated Acceptance Test Execution & Security Engine
SJB Institute of Technology | Office of Controller of Examinations

Provides secure administrative interfaces for:
1. Listing official automated test suites (Modules 1 through 14).
2. Admin-triggered live execution of isolated test suites on temporary databases.
3. Path-traversal proof and timeout-guarded test execution (3-minute hard ceiling).
4. Comprehensive audit logging for all test execution activities.
5. Strict server-side RBAC: Admin role required for all operations (403 Forbidden for non-Admin).
"""
import os
import sys
import time
import subprocess
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, AuditLog
from .auth import require_roles

router = APIRouter(prefix="/api/acceptance", tags=["Acceptance Testing & Security"])

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TESTS_DIR = os.path.join(BASE_DIR, "tests")

APPROVED_TEST_SUITES = [
    {
        "id": "test_auth_security",
        "file_name": "test_auth_security.py",
        "module": "Modules 1-3",
        "title": "Authentication, Session Security & OTP Verification",
        "description": "Verifies RBAC access controls, JWT validation, token expiry, login rate limiting, and password hashing security."
    },
    {
        "id": "test_module4_admin_users",
        "file_name": "test_module4_admin_users.py",
        "module": "Module 4",
        "title": "Admin Dashboard & User Management",
        "description": "Verifies institutional user provisioning, account lock/unlock, role updates, and real database summary analytics."
    },
    {
        "id": "test_module5_subject_master",
        "file_name": "test_module5_subject_master.py",
        "module": "Module 5",
        "title": "Subject & Syllabus Master Management",
        "description": "Verifies syllabus cataloguing, semester and scheme constraints, MCA 4-semester rule, and course CRUD."
    },
    {
        "id": "test_module6_faculty_management",
        "file_name": "test_module6_faculty_management.py",
        "module": "Module 6",
        "title": "Internal & External Faculty Profiles",
        "description": "Verifies faculty profile management, experience tracking, external institution vetting, and department scoping."
    },
    {
        "id": "test_module7_excel_import",
        "file_name": "test_module7_excel_import.py",
        "module": "Module 7",
        "title": "Excel Data Ingestion & Sanitization",
        "description": "Verifies workbook uploads, deduplication hashing, data validation, conflict preview, and atomic rollback."
    },
    {
        "id": "test_module8_expertise_mapping",
        "file_name": "test_module8_expertise_mapping.py",
        "module": "Module 8",
        "title": "Subject-Faculty Expertise Mappings",
        "description": "Verifies EXACT_EXPERIENCE, SPECIALIZATION, and RELATED mapping generation, status transitions, and audit logs."
    },
    {
        "id": "test_module9_eligibility",
        "file_name": "test_module9_eligibility.py",
        "module": "Module 9",
        "title": "Faculty Eligibility Policy & Workload Ledger",
        "description": "Verifies statutory eligibility evaluation, PhD fast-track rule, institutional experience criteria, and workload ledger balances."
    },
    {
        "id": "test_module10_matching",
        "file_name": "test_module10_matching.py",
        "module": "Module 10",
        "title": "9-Level Deterministic Matching Engine",
        "description": "Verifies deterministic candidate ranking across all 9 hierarchical levels without arbitrary scores."
    },
    {
        "id": "test_module11_allocation",
        "file_name": "test_module11_allocation.py",
        "module": "Module 11",
        "title": "Allocation Requests & Recommendations",
        "description": "Verifies allocation workflow, balanced 50:50 internal/external splits, shortage handling, and atomic ledger reservations."
    },
    {
        "id": "test_module12_hod_approval",
        "file_name": "test_module12_hod_approval.py",
        "module": "Module 12",
        "title": "HOD 2-Phase Review & Approval Workflow",
        "description": "Verifies HOD department review, setter replacement, rejection with mandatory reason, and ledger commit/rollback."
    },
    {
        "id": "test_module13_notifications",
        "file_name": "test_module13_notifications.py",
        "module": "Module 13",
        "title": "In-App Notifications & Event Alerts",
        "description": "Verifies real-time notifications for submission, approval, rejection, faculty assignment, and unread counts."
    },
    {
        "id": "test_module14_reports",
        "file_name": "test_module14_reports.py",
        "module": "Module 14",
        "title": "Analytics, Reports & Neutralized Exports",
        "description": "Verifies real database report aggregations, RBAC scoping, Excel formula injection neutralization, and PDF generation."
    }
]

APPROVED_FILE_NAMES = {suite["file_name"] for suite in APPROVED_TEST_SUITES}


class RunTestRequest(BaseModel):
    test_file: str


def _execute_test_file(test_file: str, timeout_sec: int = 180) -> dict:
    """Helper to safely execute a whitelisted test file with timeout."""
    test_path = os.path.join(TESTS_DIR, test_file)
    if not os.path.isfile(test_path):
        return {
            "test_file": test_file,
            "status": "FAIL",
            "returncode": -1,
            "stdout": "",
            "stderr": f"Test file not found: {test_file}",
            "duration_seconds": 0.0
        }

    start_time = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, test_path],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=BASE_DIR
        )
        duration = round(time.time() - start_time, 2)
        status_str = "PASS" if proc.returncode == 0 else "FAIL"
        return {
            "test_file": test_file,
            "status": status_str,
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "duration_seconds": duration
        }
    except subprocess.TimeoutExpired as exc:
        duration = round(time.time() - start_time, 2)
        return {
            "test_file": test_file,
            "status": "TIMEOUT",
            "returncode": -1,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": f"Execution timed out after {timeout_sec} seconds.",
            "duration_seconds": duration
        }
    except Exception as ex:
        duration = round(time.time() - start_time, 2)
        return {
            "test_file": test_file,
            "status": "ERROR",
            "returncode": -1,
            "stdout": "",
            "stderr": str(ex),
            "duration_seconds": duration
        }


@router.get("/test-suites")
def list_test_suites(
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Returns the catalog of authorized system acceptance test suites.
    Strictly restricted to Admin role.
    """
    return {
        "success": True,
        "total": len(APPROVED_TEST_SUITES),
        "test_suites": APPROVED_TEST_SUITES
    }


@router.post("/run-test")
def run_single_test(
    req: RunTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Executes a single whitelisted acceptance test file inside a sandboxed temporary database.
    Strictly verifies filename against whitelist to eliminate any path traversal risk.
    Logs execution results in AuditLog.
    """
    clean_file = req.test_file.strip()

    if "/" in clean_file or "\\" in clean_file or ".." in clean_file or clean_file not in APPROVED_FILE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security violation: Test file '{clean_file}' is not in the approved acceptance test catalog."
        )

    result = _execute_test_file(clean_file, timeout_sec=180)

    # Record institutional audit log
    audit_entry = AuditLog(
        action="ACCEPTANCE_TEST_EXECUTED",
        entity_type="TestSuite",
        entity_id=None,
        details=f"Admin '{current_user.username}' ran '{clean_file}'. Status: {result['status']}, ReturnCode: {result['returncode']}, Duration: {result['duration_seconds']}s"
    )
    db.add(audit_entry)
    db.commit()

    return {
        "success": True,
        "result": result
    }


@router.post("/run-all")
def run_all_tests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["Admin"]))
):
    """
    Executes all approved acceptance test suites sequentially on temporary databases.
    Returns aggregated outcomes with individual stdout/stderr logs.
    """
    results = []
    passed = 0
    failed = 0

    for suite in APPROVED_TEST_SUITES:
        res = _execute_test_file(suite["file_name"], timeout_sec=180)
        results.append(res)
        if res["status"] == "PASS":
            passed += 1
        else:
            failed += 1

    audit_entry = AuditLog(
        action="ACCEPTANCE_TEST_ALL_EXECUTED",
        entity_type="TestSuiteCatalog",
        entity_id=None,
        details=f"Admin '{current_user.username}' ran all {len(results)} acceptance suites. Passed: {passed}, Failed: {failed}."
    )
    db.add(audit_entry)
    db.commit()

    return {
        "success": True,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": results
    }
