"""
ExamExpert AI — Main FastAPI Application
SJB Institute of Technology | Office of Controller of Examinations

Intelligent Faculty Matching & Question Paper Allocation Platform
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .database import engine, Base, SessionLocal
from .models import Faculty, Subject
from .services.importer import (
    import_internal_faculty,
    import_external_faculty,
    import_syllabus,
    seed_eligibility_rules
)
from .services.migration import run_database_migrations
from .routers import syllabus, faculty, allocation, reports, auth, admin, mappings, eligibility, notifications
from .routers.auth import get_or_create_admin

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    bind = db.get_bind()
    # 1. Initialize Tables
    Base.metadata.create_all(bind=bind)

    # 2. Check and seed initial datasets if empty
    try:
        run_database_migrations(db)
        seed_eligibility_rules(db)
        get_or_create_admin(db)

        # Check if faculty imported
        if db.query(Faculty).count() == 0:
            print("[INFO] Seeding initial datasets from source Excel files...")
            int_file = os.path.join(BASE_DIR, "SJBIT college data internal faculty.xlsx")
            ext_file = os.path.join(BASE_DIR, "External Faculty college data.xlsx")
            syl_file = os.path.join(BASE_DIR, "SJBIT_All_Academic_Years sylabus.xlsx")

            if os.path.exists(int_file):
                res_int = import_internal_faculty(db, int_file)
                print(f"[INFO] Internal Faculty imported: {res_int}")
            if os.path.exists(ext_file):
                res_ext = import_external_faculty(db, ext_file)
                print(f"[INFO] External Faculty imported: {res_ext}")
            if os.path.exists(syl_file):
                res_syl = import_syllabus(db, syl_file)
                print(f"[INFO] Syllabus courses imported: {res_syl}")
        else:
            print("[INFO] Database already contains records. Ready.")
    finally:
        db.close()

    yield


app = FastAPI(
    title="ExamExpert AI — SJBIT",
    description="Intelligent Faculty Matching & Question Paper Allocation Platform",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(auth.router)
app.include_router(syllabus.router)
app.include_router(faculty.router)
app.include_router(allocation.router)
app.include_router(reports.router)
app.include_router(admin.router)
app.include_router(mappings.router)
app.include_router(eligibility.router)
app.include_router(notifications.router)

# Mount frontend static directories
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

css_dir = os.path.join(FRONTEND_DIR, "css")
if os.path.exists(css_dir):
    app.mount("/css", StaticFiles(directory=css_dir), name="css")

js_dir = os.path.join(FRONTEND_DIR, "js")
if os.path.exists(js_dir):
    app.mount("/js", StaticFiles(directory=js_dir), name="js")

assets_dir = os.path.join(BASE_DIR, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/login/{role}")
def serve_role_login(role: str):
    role_clean = role.lower()
    if role_clean not in ("admin", "hod", "faculty"):
        raise HTTPException(status_code=404, detail="Invalid login portal.")
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "institution": "SJB Institute of Technology, Bengaluru",
        "office": "Office of Controller of Examinations"
    }
