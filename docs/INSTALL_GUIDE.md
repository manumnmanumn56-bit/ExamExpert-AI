# ExamExpert AI — Installation & Development Environment Setup Guide
**SJB Institute of Technology, Bengaluru | Autonomous MCA Major Project**  
**Office of the Controller of Examinations (COE)**  

This document details the complete environment setup and local deployment process for developers, examination administrators, and system evaluators.

---

## 1. System Requirements

- **Operating System:** Windows 10/11, Ubuntu 20.04/22.04 LTS, or macOS 12+
- **Python Runtime:** Python 3.11, 3.12, or 3.13 (Python 3.11+ required)
- **Disk Space:** Minimum 500 MB free space for application, virtual environment, and database
- **Memory (RAM):** 2 GB minimum (4 GB recommended)
- **Web Browser:** Modern browser supporting ES6 modules (Chrome, Edge, Firefox, Safari)

---

## 2. Step-by-Step Installation

### Step 1: Clone Repository
Open your preferred terminal / PowerShell and clone the project repository:
```bash
git clone <repository_url>
cd ExamExpert-AI
```

### Step 2: Create Python Virtual Environment
Creating an isolated virtual environment ensures clean dependency isolation:

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
*Note: If PowerShell displays an execution policy error, enable local script execution with:*
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**On Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Required Dependencies
Install the required production packages specified in `requirements.txt`:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### Core Package Listing:
- `fastapi` & `uvicorn[standard]`: Asynchronous web server and REST API engine
- `sqlalchemy`: Relational Object-Relational Mapping (ORM)
- `pandas` & `openpyxl`: Excel ingestion, conflict analysis, and formula neutralization
- `fpdf2`: Programmatic PDF appointment order and report generation
- `passlib[bcrypt]`: Secure salted password hashing
- `pyjwt`: Cryptographic session token issuance and verification
- `pydantic` & `pydantic-settings`: Data validation and environment settings

### Step 4: Configure Environment Variables
Copy the provided environment template into `.env`:
```bash
cp .env.example .env
```
*(On Windows PowerShell, use `Copy-Item .env.example .env`).*

Verify that `.env` contains valid development defaults. (Refer to [ENV_GUIDE.md](file:///c:/Users/manum/Desktop/ExamExpert-AI/docs/ENV_GUIDE.md) for full configuration details).

### Step 5: Start Application Server
Start the Uvicorn ASGI server:
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

On initial startup, the application's lifespan handler automatically:
1. Initializes SQLite tables according to SQLAlchemy model metadata.
2. Applies any pending schema migrations.
3. Seeds initial statutory eligibility policies and system settings.
4. Generates the default COE administrator account (`admin@sjbit.edu.in`).
5. Ingests source dataset workbooks (`SJBIT college data internal faculty.xlsx`, `External Faculty college data.xlsx`, `SJBIT_All_Academic_Years sylabus.xlsx`) if tables are empty.

### Step 6: Verify Web Application Access
Open your web browser and navigate to:
```
http://localhost:8000
```
The ExamExpert AI examination portal login page should render immediately.

---

## 3. Running Automated Tests
Run the isolated acceptance test suite to confirm end-to-end functionality:
```powershell
# Run acceptance test suite
.\.venv\Scripts\python.exe tests/test_module15_acceptance.py

# Run cleanup fixes test suite
.\.venv\Scripts\python.exe tests/test_sliceD_cleanup.py
```
*All tests run inside a sandboxed temporary database (`tempfile.gettempdir()`) and will never modify your primary working database.*
