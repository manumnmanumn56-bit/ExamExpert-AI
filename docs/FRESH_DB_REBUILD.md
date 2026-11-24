# ExamExpert AI — Fresh Database Rebuild & Workbook Ingestion Guide
**SJB Institute of Technology, Bengaluru | Autonomous MCA Major Project**  
**Office of the Controller of Examinations (COE)**  

This document provides step-by-step instructions to initialize and populate a fresh, production-ready `examexpert.db` from the source Excel workbooks on a new machine without tracking database binary files in Git.

---

## 1. Overview & Source Datasets

The repository maintains three authoritative institutional Excel workbooks located at the project root:
1. `SJBIT college data internal faculty.xlsx`: Roster of internal SJBIT teaching faculty, designations, experience, and courses taught.
2. `External Faculty college data.xlsx`: Vetted external faculty members across VTU affiliated engineering and MCA colleges.
3. `SJBIT_All_Academic_Years sylabus.xlsx`: Complete curriculum catalog across autonomous and VTU schemes (Semesters I through IV for MCA).

---

## 2. Procedure to Rebuild Fresh Database

### Step 1: Remove Old Database (If Re-initializing)
If an existing or corrupted database file exists:
```bash
# Windows PowerShell
Remove-Item examexpert.db -ErrorAction SilentlyContinue

# Linux / macOS
rm -f examexpert.db
```

### Step 2: Trigger Lifespan Automated Initialization
Run the initialization script or start the FastAPI application once:
```bash
python -c "from backend.app.main import lifespan, app; import asyncio; asyncio.run(lifespan(app).__aenter__())"
```
Or start the server briefly:
```bash
uvicorn backend.app.main:app --port 8000
```

### Step 3: What the Initialization Engine Executes Automatically
1. **Schema Initialization**: `Base.metadata.create_all()` creates all 16 database tables with primary keys, indexes, and foreign keys.
2. **Schema Migration Validation**: `run_database_migrations(db)` confirms column alignment and pragma settings.
3. **Statutory Rules Seeding**: `seed_eligibility_rules(db)` establishes the default COE policy:
   - Minimum Experience: 3.0 years
   - PhD Fast-Track Experience: 1.0 year
   - Maximum Workload: 2 papers per faculty
   - Active Academic Cycle: 2025-26
4. **Root Administrator Provisioning**: `get_or_create_admin(db)` seeds:
   - Username: `coe_admin`
   - Email: `admin@sjbit.edu.in`
   - Role: `Admin`
   - Password: *(see your .env)*
5. **Worksheet Ingestion & Sanitization**:
   - Ingests internal faculty -> 47 records
   - Ingests external faculty -> 77 records
   - Ingests syllabus master -> 195 courses (including distinct 25MCAE3XY electives)
   - Evaluates baseline eligibility status for each candidate.

---

## 3. Post-Rebuild Verification Checklist

Run the verification one-liner to verify exact database counts:
```bash
python -c "from backend.app.database import SessionLocal; from backend.app.models import Faculty, Subject, User; db = SessionLocal(); print('Internal Faculty:', db.query(Faculty).filter_by(faculty_type='internal').count(), '(Expected: 47)'); print('External Faculty:', db.query(Faculty).filter_by(faculty_type='external').count(), '(Expected: 77)'); print('Syllabus Courses:', db.query(Subject).count(), '(Expected: 195)'); print('Users:', db.query(User).count(), '(Expected: >= 1)'); db.close()"
```

Expected Output:
```
Internal Faculty: 47 (Expected: 47)
External Faculty: 77 (Expected: 77)
Syllabus Courses: 195 (Expected: 195)
Users: 4 (Expected: >= 1)
```

Run a fresh dry-run on all workbooks to verify zero conflicts:
```bash
python -c "from backend.app.database import SessionLocal; from backend.app.services.importer import preview_dataset_import; db = SessionLocal();
for f, dt in [('SJBIT college data internal faculty.xlsx', 'internal'), ('External Faculty college data.xlsx', 'external'), ('SJBIT_All_Academic_Years sylabus.xlsx', 'syllabus')]:
    with open(f, 'rb') as fp: res = preview_dataset_import(db, fp.read(), f, dt)
    print(f, '-> Added:', res['to_add_count'], 'Duplicates:', res['duplicate_count'], 'Conflicts:', res['conflict_count'], 'Rejected:', res['rejected_count'])
db.close()"
```

Expected Output:
```
SJBIT college data internal faculty.xlsx -> Added: 0 Duplicates: 47 Conflicts: 0 Rejected: 0
External Faculty college data.xlsx -> Added: 0 Duplicates: 77 Conflicts: 0 Rejected: 0
SJBIT_All_Academic_Years sylabus.xlsx -> Added: 0 Duplicates: 195 Conflicts: 0 Rejected: 0
```
All workbooks report 0 to-add, 0 conflicts, and 0 rejected.
