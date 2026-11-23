# ExamExpert AI — REST API Reference Guide
**SJB Institute of Technology, Bengaluru | Autonomous MCA Major Project**  
**Office of the Controller of Examinations (COE)**  

This document details all REST endpoints provided by the ExamExpert AI backend application, including methods, URL paths, authorization scopes, request payloads, and response definitions.

---

## 1. Authentication & Session Security (`/api/auth`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/login/{role}` | Public | Authenticates user into dedicated role portal (`admin`, `hod`, `faculty`). |
| `POST` | `/api/auth/request-otp` | Public | Generates and sends a single-use 6-digit OTP with 10-minute validity. |
| `POST` | `/api/auth/verify-otp` | Public | Validates OTP code against email record. |
| `POST` | `/api/auth/activate-account` | Public | First-time account activation and password setup using OTP. |
| `POST` | `/api/auth/forgot-password` | Public | Initiates password reset via verification OTP. |
| `POST` | `/api/auth/reset-password` | Public | Completes password reset using verified OTP. |
| `POST` | `/api/auth/logout` | Authenticated | Revokes current JWT session token server-side in `ActiveSession`. |
| `GET` | `/api/auth/me` | Authenticated | Retrieves profile of currently authenticated user. |

---

## 2. Institutional Administration & Governance (`/api/admin`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/admin/dashboard-stats` | Admin | Retrieves live system-wide operational analytics directly from DB. |
| `GET` | `/api/admin/users` | Admin | Lists institutional user accounts with lockout and activity status. |
| `POST` | `/api/admin/users` | Admin | Provisions a new institutional user (`Admin`, `HOD`, or `Faculty`). |
| `PUT` | `/api/admin/users/{id}` | Admin | Modifies user account parameters, role, or department. |
| `PUT` | `/api/admin/users/{id}/unlock` | Admin | Unlocks an account locked due to failed login attempts. |
| `PUT` | `/api/admin/users/{id}/toggle-active` | Admin | Activates or deactivates user access. |
| `GET` | `/api/admin/audit-logs` | Admin | Queries immutable system audit trail with pagination and filters. |

---

## 3. Syllabus & Course Master (`/api/syllabus`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/syllabus/academic-years` | Authenticated | Lists available academic years and active cycle. |
| `GET` | `/api/syllabus/departments` | Authenticated | Lists departments offering courses for an academic year. |
| `GET` | `/api/syllabus/semesters` | Authenticated | Lists semesters offered (enforces MCA 4-sem constraint). |
| `GET` | `/api/syllabus/courses` | Authenticated | Retrieves courses matching cascading filters. |
| `POST` | `/api/syllabus/courses` | Admin | Creates a new course in syllabus master. |
| `PUT` | `/api/syllabus/courses/{id}` | Admin | Modifies course details with duplicate detection. |
| `DELETE` | `/api/syllabus/courses/{id}` | Admin | Soft/hard deletes course if no active allocations reference it. |
| `POST` | `/api/syllabus/import-excel` | Admin | Dry-run preview and batch ingestion of syllabus workbooks. |

---

## 4. Faculty Management & Rosters (`/api/faculty`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/faculty` | Authenticated | Queries faculty roster with filters (department, internal/external, eligibility). |
| `GET` | `/api/faculty/{id}` | Authenticated | Retrieves detailed profile, experience history, and expertise tags. |
| `POST` | `/api/faculty` | Admin | Manually creates a new faculty member profile. |
| `PUT` | `/api/faculty/{id}` | Admin | Updates faculty designation, experience, or contact information. |
| `GET` | `/api/faculty/institutions/whitelist` | Admin | Lists vetted external institutions and approval status. |
| `POST` | `/api/faculty/institutions/whitelist` | Admin | Updates or adds an external institution to the approved roster. |

---

## 5. Expertise Mappings (`/api/mappings`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/mappings` | Authenticated | Queries mappings by status (`SUGGESTED`, `CONFIRMED`, `REJECTED`). |
| `POST` | `/api/mappings/generate-suggestions` | Admin | Batch generates `EXACT_EXPERIENCE` and `SPECIALIZATION` suggestions. |
| `POST` | `/api/mappings/generate-related/{subject_id}` | Admin | Generates on-demand `RELATED` curriculum domain mappings for a subject. |
| `POST` | `/api/mappings/purge-untouched-related` | Admin | Purges unreviewed `SUGGESTED` `RELATED` rows from database. |
| `PUT` | `/api/mappings/{id}/status` | Admin | Confirms or rejects an individual expertise mapping. |

---

## 6. Allocation & Matching Engine (`/api/allocation`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/allocation/match-candidates` | Authenticated | Executes 9-level deterministic matching for selected course. |
| `POST` | `/api/allocation/create-request` | Admin | Generates draft allocation recommendation and reserves workload. |
| `POST` | `/api/allocation/{id}/submit-to-hod` | Admin | Submits allocation to departmental HOD and triggers alert. |
| `GET` | `/api/allocation/pending-approvals` | HOD, Admin | Lists allocations awaiting departmental review. |
| `POST` | `/api/allocation/{id}/approve` | HOD | Approves allocation order, committing workload ledger entries. |
| `POST` | `/api/allocation/{id}/replace-setter` | HOD | Swaps a recommended setter with documented justification. |
| `POST` | `/api/allocation/{id}/reject` | HOD | Rejects allocation order with mandatory documented reason. |
| `GET` | `/api/allocation/history` | Authenticated | Retrieves historical confirmed and archived allocation orders. |

---

## 7. In-App Notifications (`/api/notifications`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/notifications/my` | Authenticated | Retrieves user's personal in-app notification inbox. |
| `GET` | `/api/notifications/unread-count` | Authenticated | Returns integer count of unread notifications for badge display. |
| `PUT` | `/api/notifications/{id}/read` | Authenticated | Marks a single notification as read. |
| `POST` | `/api/notifications/mark-all-read` | Authenticated | Marks all unread notifications in user's inbox as read. |

---

## 8. Reports & Analytics (`/api/reports`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/reports/summary` | Authenticated | Multi-dimensional statistical summary (RBAC-scoped). |
| `GET` | `/api/reports/faculty-workload` | Authenticated | Workload balance report with committed and reserved totals. |
| `GET` | `/api/reports/department-allocations`| Authenticated | Allocations breakdown by academic department. |
| `GET` | `/api/reports/institution-distribution`| Admin | External examiner distribution across colleges. |
| `GET` | `/api/reports/pending-verification` | Admin | External faculty with unverified credentials. |
| `GET` | `/api/reports/export-excel` | Authenticated | Exports neutralized Excel report (`.xlsx`). |
| `GET` | `/api/reports/export-pdf` | Authenticated | Generates formal PDF executive report. |
| `GET` | `/api/reports/download-pdf/{id}` | Authenticated | Generates official question-paper appointment order PDF. |

---

## 9. Automated Acceptance Test Runner (`/api/acceptance`)

| Method | Endpoint | Access Scope | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/acceptance/test-suites` | Admin | Lists catalog of authorized acceptance test suites. |
| `POST` | `/api/acceptance/run-test` | Admin | Executes single whitelisted test suite in isolated temporary DB. |
| `POST` | `/api/acceptance/run-all` | Admin | Sequentially executes all acceptance test suites. |
