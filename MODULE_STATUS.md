# ExamExpert AI — Implementation & Verification Status Tracker

**Institution:** SJB Institute of Technology, Bengaluru  
**Office:** Office of the Controller of Examinations  
**Major Project:** Automated Faculty Matching & Question Paper Setter Allocation System  
**Last Updated:** 2026-11-22  

---

## Status Summary by Module & Slice

| Module / Slice | Title | Status | Test Suite | Evidence & Scope |
| :--- | :--- | :---: | :--- | :--- |
| **Module 1** | Project Initialization & Cleanup | **DONE** | `tests/verify_step1.py` | Standalone FastAPI architecture, directory cleanup. |
| **Module 2** | Database Layer & Schema | **DONE** | `tests/verify_module2_data_layer.py` | SQLAlchemy models, SQLite persistence, schema migrations. |
| **Module 3** | Authentication & Security | **DONE** | `tests/test_auth_security.py` | RBAC, Bcrypt passwords, session revocation, OTP rate-limiting. |
| **Module 4** | Admin Dashboard & Users | **DONE** | `tests/test_module4_admin_users.py` | Account creation, lockout management, user audit trail. |
| **Module 5** | Academic Subject Master | **DONE** | `tests/test_module5_subject_master.py` | Curriculum catalogue, VTU/Autonomous scheme scoping. |
| **Module 6** | Faculty Management | **DONE** | `tests/test_module6_faculty_management.py` | Internal/External roster, institution whitelist governance. |
| **Module 7** | Excel Import & Verification | **DONE** | `tests/test_module7_excel_import.py` | Dry-run preview, conflict handling, rejected reports. |
| **Module 8** | Faculty-Subject Expertise Mapping | **DONE** | `tests/test_module8_expertise_mapping.py` | Tiered generation (EXACT, SPECIALIZATION, RELATED), review UI. |
| **Module 9 (Slice 1)** | Eligibility Policy & Workload Management | **DONE** | `tests/test_module9_eligibility.py` | Dynamic DB policy, capacities, append-only workload ledger triggers, candidate matrix. |
| **Module 10 (Slice 2)** | Deterministic Matching Engine | **DONE** | `tests/test_module10_matching.py` | 9-level deterministic ranking, no arbitrary scores, explainable criteria reasons, RBAC. |
| **Module 11 (Slice 3)** | Allocation Request & Recommendation UI | **DONE** | `tests/test_module11_allocation.py` | Mode splits (50:50, Internal/External only), MCA 4-sem rule, RESERVED ledger entries. |
| **Module 12 (Slice 4)** | HOD Approval Workflow & Audit Trail | **DONE** | `tests/test_module12_hod_approval.py` | Pending approvals tab, COMMITTED / RELEASED ledger decisions, audit trail. |
| **Module 13 (Slice A)** | In-App & Email Notifications | **DONE** | `tests/test_module13_notifications.py` | In-app alerts (submitted, approved, rejected, assigned), personal inbox, unread counts, SMTP fallback. |
| **Module 14 (Slice B)** | Real Data Reports & Analytics | **DONE** | `tests/test_module14_reports.py` | Multi-dimensional real data reports, RBAC scoping, Excel/PDF/print exports, formula injection safety. |
| **Module 15 (Slice C)** | Acceptance Testing & Security Review | **DONE** | `tests/test_module15_acceptance.py` | Admin test execution runner on temp isolated DB, path-traversal defense, 3-min ceiling, SECURITY_AUDIT.md. |
| **Slice D (Cleanup)** | Data Integrity & Governance Cleanup | **DONE** | `tests/test_sliceD_cleanup.py` | Nagamani S workbook email match, syllabus title key (0 conflict dry-run), tiered mappings & untouched RELATED purge. |

---

## Slice D (Cleanup Fixes) Architecture Highlights

- **Item A: Faculty Record Email & User Linking**:
  - `Faculty` record email for Dr. Nagamani S matches the source workbook (`nagamanis@sjbit.edu.in`).
  - User account `faculty_mca` (`faculty.mca@sjbit.edu.in`) is linked directly via `User.faculty_id == Faculty.id` (ID 45).
  - Faculty login remains fully functional with credentials (`Faculty@2026!`).
- **Item B: Syllabus Key Matching with Title & Unweakened Duplicate Rule**:
  - Syllabus import matching key includes `title.strip().lower()`.
  - The three `25MCAE3XY` electives (sharing course code but having distinct titles) import cleanly as 3 separate rows.
  - Module 5 duplicate rule remains strictly enforced: true duplicates (same code + title for electives, or same code for core) are rejected with HTTP 400.
  - Verified with fresh dry-runs across all three workbooks: 0 conflicts, 0 to-add, 0 rejected.
- **Item C: Tiered Mapping Generation & Untouched RELATED Deletion**:
  - Batch mapping generator produces strictly `EXACT_EXPERIENCE` and `SPECIALIZATION` mappings (0 `RELATED` in batch).
  - Added on-demand endpoint `POST /api/mappings/generate-related/{subject_id}` (Admin only).
  - Purged 7,898 untouched `SUGGESTED` `RELATED` rows from `examexpert.db`, retaining 190 `EXACT_EXPERIENCE` and 253 `SPECIALIZATION` rows.
  - Institutional `AuditLog` entry created (`MAPPING_BULK_CLEANUP`).

---

## Slice C (Module 15) Architecture Highlights

- **Automated Acceptance Test Runner**:
  - Whitelisted test suite registry covering Modules 1 through 14.
  - Path-traversal defense with rejection of invalid or malicious test targets (HTTP 400).
  - 3-minute hard ceiling timeout on test execution.
  - Isolated database sandboxing (`tempfile.gettempdir()`) via `test_db_helper.py` ensuring zero impact on live production data.
- **Role-Based Execution Security**:
  - Admin: Full privilege to list test catalog and execute individual or all acceptance suites.
  - HOD & Faculty: Access strictly forbidden with HTTP 403.
  - Audit logging of test runs with timing and PASS/FAIL outcomes.
- **Formal Security Audit (`SECURITY_AUDIT.md`)**:
  - Full mitigation analysis across 8 critical threat vectors: SQLi, XSS, RBAC, Sessions, Rate Limiting, Secrets, Uploads, CORS.
  - Complete removal of hardcoded limits, simulated logs, and fake data.

---

## Slice B (Module 14) Architecture Highlights

- **Multi-Dimensional Live Reporting**:
  - Live summaries matching live database record counts bit-for-bit (zero mock data).
  - Faculty workload reports reflecting committed and reserved ledger entries.
  - Department and subject-wise allocation distributions and status archives.
- **Server-Enforced Role Scoping**:
  - Admin: Full institutional access to internal/external faculty rosters, import batches, and institution distribution.
  - HOD: Scoped strictly to own department internal faculty and allocations (external reports return HTTP 403).
  - Faculty: Restricted strictly to own personal profile and assigned allocations (HTTP 403 for others).
- **Formula Injection Neutralization (OWASP)**:
  - Cells starting with `=`, `+`, `-`, `@`, `\t`, `\r` are neutralized with single quote prefixing.
  - Missing data rendered as 'Not provided' (no fake data).
- **Multi-Format Export**:
  - Openpyxl Excel (.xlsx), FPDF executive report (.pdf), and browser-ready `@media print` HTML views.

---

## Slice A (Module 13) Architecture Highlights

- **Event-Driven Notifications**:
  - HOD alerted on new allocation submissions for their department (`REQUEST_SUBMITTED`).
  - Admin alerted on HOD approval (`REQUEST_APPROVED`) and rejection with reasons (`REQUEST_REJECTED`).
  - Appointed Faculty alerted on official paper-setting nominations (`FACULTY_ASSIGNED`).
- **User Privacy & Inbox Scoping**:
  - `GET /api/notifications/my` strictly filters to the authenticated user's records.
  - Cross-user updates are prevented.
  - Real-time unread counts update the header notification badge.
- **Credential & Secret Protection**:
  - Zero OTPs, passwords, or SMTP secrets exposed in notification payloads or message logs.
  - Transparent banner displayed if SMTP is unconfigured in `.env`.

---

## Slice 4 (Module 12) Architecture Highlights

- **HOD Scoped Decision Authority**:
  - `GET /api/allocation/pending-approvals`: HOD sees requests strictly for their own department; Admin sees all requests.
  - Cross-department decisions strictly return HTTP 403.
- **Atomic Workload Ledger Transitions**:
  - Approval: In one atomic transaction, marks status `Approved`, writes `COMMITTED` (+1), and writes `RELEASED` (-1) to clear reservation while establishing active workload obligation.
  - Rejection: In one atomic transaction, requires reason (min 3 chars), marks status `Rejected`, and writes `RELEASED` (-1) to release reservation.
- **Double-Decision Protection**:
  - Only requests in `Pending HOD Approval` can be approved or rejected. Attempting to decide an already decided request raises HTTP 409.
- **Cancellation**:
  - `POST /api/allocation/{id}/cancel` safely releases reserved or committed workload and logs audit records.
- **UI Integration**:
  - Modular `Pending Approvals` tab visible to HOD and Admin.
  - Approve action and Reject modal with required reason.
  - Toast notifications throughout (no `alert()`).

---

## Slice 3 (Module 11) Architecture Highlights

- **MCA 4-Semester Curriculum Rule Validation**:
  - Validated server-side in `validate_mca_semester`: Semesters I, II, III, IV pass; Semesters V–VIII strictly return HTTP 422.
- **Allocation Modes & Shortage Handling**:
  - Balanced 50:50 mode enforces equal parity between internal and external faculty pools.
  - Transparent shortage reallocation fills deficits from other eligible candidates without lowering eligibility.
  - Internal Only and External Only modes supported.
- **Relational AllocationSetters**:
  - Replaced plain JSON arrays with relational `AllocationSetter` entities tracking `assigned_order`, `faculty_type`, and `status`.
- **Workload Reservation & Lifecycle**:
  - `POST /api/allocation/create-request` creates requests in `Draft` or `Recommended` status.
  - `POST /api/allocation/{id}/submit` atomically transitions status to `Pending HOD Approval` and writes `RESERVED` (`delta=1`) rows in the append-only `workload_ledger`.
  - Faculty workload capacity limits strictly prevent over-allocation (HTTP 422).
- **Direct HOD Bypass Removed**:
  - Direct status transitions to "Confirmed" removed; all orders submit to `Pending HOD Approval`.

---

## Slice 2 (Module 10) Architecture Highlights

- **Deterministic 9-Level Priority Hierarchy**:
  1. `EXACT_EXPERIENCE` confirmed mapping (Tier 1)
  2. `SPECIALIZATION` confirmed mapping (Tier 2)
  3. `RELATED` confirmed mapping (Tier 3)
  4. Lower combined workload (`committed + reserved` from `workload_ledger`)
  5. Avoid repeating same subject (fresh appointment ranks ahead of repeat setter)
  6. Higher relevant course handling count (`times_handled`)
  7. Higher total teaching experience (`experience_years`)
  8. Previous paper-setting experience (`assumed_times_handled`)
  9. Deterministic tie-breaker: Faculty ID ascending
- **Exclusions**:
  - Only `ELIGIBLE` candidates (passed Module 9 rules engine) are recommended.
  - `PENDING VERIFICATION` and `NOT ELIGIBLE` candidates are strictly segregated with transparent reasons and are never recommendable.
  - External candidates from disabled whitelist institutions are automatically excluded.
- **Explainability**:
  - Removed all arbitrary 0-100 scores from `matcher.py` and UI.
  - Every recommendation includes granular, per-criterion audit reasons.
- **Server-Side RBAC**:
  - Admin: Can run auto-select across all subjects and departments.
  - HOD: Can run auto-select exclusively for subjects belonging to their own department (cross-department requests return HTTP 403).
  - Faculty: Blocked from running auto-select with HTTP 403.
