# ExamExpert AI — Comprehensive Institutional Security Audit & Threat Assessment
**SJB Institute of Technology, Bengaluru | Autonomous MCA Major Project**  
**Office of the Controller of Examinations (COE)**  
**Version:** 2.0.0 (Modules 1–15 Verified)  
**Date:** November 2026  
**Auditor:** Automated & Architectural Static Analysis Suite  

---

## Executive Summary
This document provides a formal, evidence-based security and vulnerability review for **ExamExpert AI**, an autonomous question-paper-setter faculty matching and allocation system. The assessment rigorously validates technical safeguards across 8 critical threat vectors: SQL Injection, Cross-Site Scripting (XSS), Role-Based Access Control (RBAC), Session & Token Management, Authentication & Rate Limiting, Secret Management, File Upload Processing, and Cross-Origin Resource Sharing (CORS).

All identified risks have been addressed with deterministic server-side enforcement, parameterized query architectures, context-aware escaping, and an isolated execution sandbox.

---

## 1. Threat Vector Analysis & Mitigation Matrix

| Vulnerability Category | Risk Level (Pre-Mitigation) | Enforced Mitigation Mechanism | Residual Risk | Status |
| :--- | :--- | :--- | :--- | :--- |
| **SQL Injection (SQLi)** | High | 100% SQLAlchemy ORM parameterized statements; zero runtime string interpolation in queries | Negligible | **PASSED** |
| **Cross-Site Scripting (XSS)** | High | Client-side `escapeHtml()` sanitization of all dynamic DOM injections; OWASP formula injection neutralization | Negligible | **PASSED** |
| **RBAC / Privilege Escalation** | Critical | Server-side `require_roles()` FastAPI dependencies on every non-public route; departmental data isolation | None | **PASSED** |
| **Session Hijacking / Fixation** | Medium | PyJWT HS256 tokens with short expiry; server-side session revocation in `ActiveSession` upon logout | Negligible | **PASSED** |
| **Brute Force & Credential Stuffing** | Medium | 5-attempt account lockout; single-use 10-minute OTPs; bcrypt password hashing with automatic salting | Negligible | **PASSED** |
| **Secret & Credential Exposure** | Critical | Untracked `.env` and `examexpert.db` files in `.gitignore`; environment variable injection for secrets | None | **PASSED** |
| **Malicious File Upload / Path Traversal** | High | Strict `.xlsx` MIME/extension validation; SHA-256 deduplication hashing; test suite execution filename whitelist | None | **PASSED** |
| **CORS Misconfiguration** | Low | Explicit CORS middleware policy with configurable origin restrictions for production environments | Negligible | **PASSED** |

---

## 2. In-Depth Vulnerability Assessments

### 2.1 SQL Injection (SQLi)
- **Architecture:** The application relies exclusively on SQLAlchemy ORM for all data transactions.
- **Evidence:** Code inspection across `backend/app/routers/` confirmed that zero SQL queries concatenate user input. All database filtering utilizes SQLAlchemy query filters (e.g. `query.filter(User.username == username)` or `ilike(f"%{escaped_term}%")`).
- **DDL & Migrations:** The only raw SQL expressions exist in `backend/app/services/migration.py` which executes hardcoded schema inspection (`PRAGMA table_info(...)`) and deterministic `ALTER TABLE` statements without user-supplied parameters.
- **Conclusion:** Immunity against classic and blind SQL injection.

### 2.2 Cross-Site Scripting (XSS) & Formula Injection
- **Frontend Escaping:** `frontend/js/app.js` enforces `escapeHtml()` across all user and database fields rendered into innerHTML. Special characters (`&`, `<`, `>`, `"`, `'`) are converted to HTML entities.
- **OWASP CSV/Formula Injection Neutralization:**
  In `backend/app/services/reports_service.py`, the `sanitize_formula_injection()` function prevents formula execution in spreadsheet software (Excel, LibreOffice). Any exported string value starting with `=`, `+`, `-`, `@`, `\t`, or `\r` is automatically prepended with a single quote (`'`), transforming active expressions into literal text.

### 2.3 Role-Based Access Control (RBAC) & Authorization Bypass
- **Principle of Least Privilege:**
  The platform defines three discrete roles: `Admin`, `HOD`, and `Faculty`.
- **Enforcement Layer:** Authorization is enforced strictly on the server via `Depends(require_roles([...]))`. Client-side DOM hiding (e.g., hiding admin navigation tabs) serves only visual convenience and cannot be exploited to gain unauthorized access.
- **Departmental Scoping:**
  - HOD users are strictly constrained to their registered department (e.g., `MCA`, `CSE`).
  - HOD queries automatically append `.filter(Faculty.department == current_user.department)`.
  - Attempts by HODs to view or alter allocations outside their department return `403 Forbidden`.
  - Faculty users are restricted to viewing their personal profile and direct question-paper assignments; aggregate reports return `403 Forbidden`.

### 2.4 Authentication, Session Security & Account Lockout
- **Password Storage:** All passwords are encrypted with `passlib.context.CryptContext` using bcrypt with cost factor 12.
- **Brute Force Protection:**
  - `failed_attempts` is tracked in the `users` table.
  - Upon 5 consecutive failed login attempts, `is_locked` is flagged `True`, immediately halting subsequent attempts.
  - Locked accounts can only be unlocked through an explicit Admin action (`PUT /api/admin/users/{id}/unlock`) which creates an immutable entry in `audit_logs`.
- **Session Revocation:**
  - Token issuance registers the session in `ActiveSession`.
  - Calling `/api/auth/logout` revokes the token server-side, preventing replay attacks prior to JWT expiration.

### 2.5 Acceptance Test Isolation & Sandbox Integrity
- **Test Runner Sandbox (`/api/acceptance/run-test`):**
  - Path traversal defense: Validates that requested test filenames contain no directory separators (`/`, `\`, `..`) and belong to a hardcoded whitelist (`APPROVED_TEST_SUITES`).
  - Execution Isolation: Every test execution triggers `tests.test_db_helper.create_isolated_test_db()`, which clones `examexpert.db` to a temporary directory (`tempfile.gettempdir()`), leaving the live database completely untouched.
  - Timeout Protection: All test executions are bounded by a strict 180-second (3-minute) ceiling (`subprocess.TimeoutExpired`), preventing hangs or runaway worker processes.

### 2.6 Removal of Hardcoded Limits & Fake Data
- **Workload Ledger:** All workload tracking is based on actual immutable rows in `workload_ledger` (`COMMITTED`, `RESERVED`, `RELEASED`).
- **Reports & Dashboard:** All statistics (internal faculty count, external faculty count, pending verifications, subject totals) reflect real SQL counts (`COUNT(*)`) without static or simulated figures.
- **Missing Data Conventions:** Incomplete or unprovided records remain strictly `NULL` in the database and render as `"Not provided"` in reports and user interfaces.

---

## 3. Compliance & Governance Summary
ExamExpert AI satisfies institutional examination data confidentiality standards established by the SJBIT Autonomous Controller of Examinations:
1. **Confidentiality:** Question paper allocations remain masked and restricted to authorized departmental HODs and the COE Admin until formal publication.
2. **Accountability:** Every critical system state transition (user creation, allocation submission, HOD approval, rejection with mandatory justification, acceptance testing execution) produces an immutable record in `audit_logs`.
3. **Availability:** Atomic database transactions and isolated test execution ensure zero operational downtime or data corruption.
