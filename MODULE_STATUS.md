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
