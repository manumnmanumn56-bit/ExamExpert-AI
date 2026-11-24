# ExamExpert AI — Autonomous Examination Question-Paper-Setter Allocation Platform
**SJB Institute of Technology, Bengaluru | Autonomous MCA Major Project**  
**Office of the Controller of Examinations (COE)**  

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/ORM-SQLAlchemy-D71F00.svg?style=flat&logo=sqlalchemy)](https://www.sqlalchemy.org)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003B57.svg?style=flat&logo=sqlite)](https://www.sqlite.org)
[![Vanilla JS](https://img.shields.io/badge/Frontend-Vanilla%20ES6+-F7DF1E.svg?style=flat&logo=javascript)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![License: Institutional](https://img.shields.io/badge/License-SJBIT%20Autonomous-blue.svg)](#)

---

## 📌 Project Overview
**ExamExpert AI** is an institutional governance and workflow automation platform engineered specifically for the Office of the Controller of Examinations at SJB Institute of Technology (SJBIT), Bengaluru. 

The system automates the selection, deterministic matching, conflict checking, workload balancing, and appointment of examination question-paper setters across Autonomous and VTU curricular schemes. It enforces statutory examination policies, provides explainable 9-level hierarchical ranking, guarantees confidential two-phase HOD approvals, and maintains an immutable audit trail for every operational decision.

---

## 🚀 Key Architectural Capabilities

1. **Role-Based Examination Portal (RBAC)**:
   - Dedicated authentication flows and server-enforced access boundaries for **Admin (COE)**, **HOD**, and **Faculty**.
   - Session revocation on logout, 5-attempt brute-force account lockout, and bcrypt password encryption.
2. **Deterministic 9-Level Faculty Matching Engine**:
   - Zero arbitrary numerical scores or black-box algorithms.
   - Candidates are ranked strictly by: (1) Exact subject experience, (2) Specialization, (3) Confirmed related domain, (4) Lower combined workload, (5) Subject rotation, (6) Course experience, (7) Total experience, (8) Recorded paper-setting history, and (9) Deterministic ID tie-breaker.
3. **Statutory Policy & MCA 4-Semester Constraint**:
   - Enforces the statutory VTU/Autonomous rule restricting MCA offerings strictly to Semesters I–IV.
   - Dynamic eligibility engine supporting PhD fast-track service exemptions and external institution whitelist verification.
4. **Append-Only Workload Ledger**:
   - Tracks faculty paper-setting capacity across three atomic states: `RESERVED` upon recommendation, `COMMITTED` upon HOD approval, and `RELEASED` upon rejection or cancellation.
5. **Two-Phase HOD Approval Workflow**:
   - Department-scoped review interface allowing HODs to approve allocations, swap recommended setters, or reject orders with mandatory documented justification.
6. **Multi-Format Export & OWASP Formula Neutralization**:
   - One-click export to Excel (`.xlsx`), PDF (`.pdf`), and `@media print` printable HTML views.
   - All spreadsheet exports sanitize formula injection vectors (`=`, `+`, `-`, `@`, `\t`, `\r`).
7. **In-App Event Notification Hub**:
   - Real-time alerts for allocation submissions, HOD decisions, and faculty setter appointments with unread badges.
8. **Isolated Acceptance Test Runner & Security Engine**:
   - Admin-only test execution interface running integration suites inside temporary isolated databases (`tempfile.gettempdir()`) bounded by a 3-minute execution ceiling.

---

## 🏗️ Technology Stack

| Layer | Component | Description |
| :--- | :--- | :--- |
| **Backend** | Python 3.11+ / FastAPI | High-performance asynchronous REST API framework |
| **Data Layer** | SQLAlchemy 2.0 / SQLite 3 | Relational database persistence with atomic transactions |
| **Security** | PyJWT / Passlib (Bcrypt) / Secrets | Cryptographic session tokens, password hashing, and RBAC |
| **ETL & Office** | Pandas / OpenPyXL / FPDF | Excel ingestion, schema validation, and PDF generation |
| **Frontend** | Vanilla ES6+ / HTML5 / CSS3 | Zero-framework responsive web interface with custom UI |

---

## 📂 Documentation Directory (`docs/`)

Comprehensive technical and operational manuals are available in the [docs/](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs) folder:

- 📖 [User Manual (Admin, HOD, Faculty)](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/USER_MANUAL.md) — Step-by-step role guides.
- ⚙️ [Installation & Quickstart Guide](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/INSTALL_GUIDE.md) — Development environment setup.
- 🔐 [Environment Configuration (.env Guide)](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/ENV_GUIDE.md) — Configuration parameters and security keys.
- 🔄 [Fresh Database Rebuild Guide](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/FRESH_DB_REBUILD.md) — Initializing clean databases from workbooks.
- 🗄️ [Database Schema Specification](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/SCHEMA_DOCUMENT.md) — Table definitions, relationships, and triggers.
- 🌐 [API Reference Guide](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/API_REFERENCE.md) — Exhaustive REST endpoint documentation.
- ⚖️ [Statutory Rules & Matching Algorithms](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/RULES_AND_ALGORITHMS.md) — Detailed deterministic matching logic.
- 🛡️ [Security Audit Report](file:///c:/Users/manum/Desktop/ExamExpert-AI/SECURITY_AUDIT.md) — Formal vulnerability assessments and mitigations.
- 🚀 [Deployment & Known Limitations](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/DEPLOYMENT_AND_LIMITATIONS.md) — Production hosting and COE policy flags.

---

## ⚡ Quickstart

```bash
# 1. Clone repository and navigate to root
git clone <repository_url>
cd ExamExpert-AI

# 2. Activate virtual environment
.\.venv\Scripts\Activate.ps1  # Windows PowerShell
# or: source .venv/bin/activate  # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the application
uvicorn backend.app.main:app --reload --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser to access the Examination Portal.

---

## 👥 Default Accounts

| Role | Username | Email | Credentials |
| :--- | :--- | :--- | :--- |
| **Admin** | `coe_admin` | `admin@sjbit.edu.in` | *(see your .env)* |
| **HOD** | `hod_mca` | `hod.mca@sjbit.edu.in` | *(see your .env)* |
| **Faculty** | `faculty_mca` | `faculty.mca@sjbit.edu.in` | *(see your .env)* |

---

## 🏛️ Institutional Governance
Developed under the guidance of the Department of Master of Computer Applications and the Office of the Controller of Examinations, **SJB Institute of Technology, BGS Health & Education City, Dr. Vishnuvardhan Road, Kengeri, Bengaluru — 560060**.
