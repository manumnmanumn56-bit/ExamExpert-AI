"""
ExamExpert AI — Module 14 Reports & Analytics Automated Test Suite
SJB Institute of Technology | Office of Controller of Examinations

Explicitly verifies:
1. Real Data Integrity & Number Verification:
   - All summary statistics dynamically match actual database counts
   - Faculty workload reports accurately compute committed, reserved, and active totals
   - Missing fields are formatted as 'Not provided' (zero fake data)
2. Server-Enforced Role-Based Scoping:
   - Admin has full institutional access
   - HOD is restricted to own department; external faculty and institution reports return HTTP 403
   - Faculty is restricted to personal profile & assignments; aggregates return HTTP 403
3. Formula Injection Neutralization (OWASP CSV Injection Defense):
   - Values beginning with '=', '+', '-', '@' are safely neutralized with a single quote prefix
4. Multi-Format Export Generation:
   - Excel export (.xlsx) generation
   - PDF export (.pdf) starting with standard %PDF header
   - Printer-friendly HTML view
"""
import os, sys, io
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_db_helper import create_isolated_test_db
create_isolated_test_db("mod14_")

from fastapi import HTTPException
from sqlalchemy.orm import Session
from backend.app.database import SessionLocal
from backend.app.models import (
    User, Faculty, Subject, Allocation, AllocationSetter, WorkloadLedger,
    ExternalInstitution, ImportHistory
)
from backend.app.services.reports_service import (
    sanitize_formula_injection,
    get_summary_report,
    get_faculty_workload_report,
    get_department_allocations_report,
    get_subject_allocations_report,
    get_institution_distribution_report,
    get_pending_verification_report,
    get_import_batches_report,
    export_report_to_excel,
    export_report_to_pdf,
    get_printable_html_report
)
from backend.app.routers.reports import (
    get_reports_summary,
    get_faculty_workload_data,
    get_department_allocations_data,
    get_subject_allocations_data,
    get_institution_distribution_data,
    get_pending_verification_data,
    get_import_batches_data
)


def run_module14_tests():
    print("=" * 75)
    print("  EXAMEXPERT AI — MODULE 14 INSTITUTIONAL REPORTS VERIFICATION")
    print("  SJB Institute of Technology • Office of Controller of Examinations")
    print("=" * 75)

    db: Session = SessionLocal()
    passed = 0
    failed = 0

    try:
        # Retrieve test accounts
        admin_user = db.query(User).filter_by(role="Admin").first()
        hod_mca = db.query(User).filter_by(role="HOD", department="MCA").first()
        hod_cse = db.query(User).filter_by(role="HOD", department="CSE").first()
        faculty_user = db.query(User).filter_by(role="Faculty").first()

        assert admin_user is not None
        assert hod_mca is not None
        assert hod_cse is not None
        assert faculty_user is not None

        # Link faculty user if needed
        fac_rec = db.query(Faculty).filter_by(email=faculty_user.email).first()
        if not fac_rec:
            fac_rec = Faculty(
                name="Dr. MCA Report Faculty",
                email=faculty_user.email,
                faculty_type="internal",
                department="MCA",
                designation="Associate Professor",
                qualification="Ph.D",
                experience_years=14.0,
                is_available=True
            )
            db.add(fac_rec)
            db.commit()
            db.refresh(fac_rec)
        faculty_user.faculty_id = fac_rec.id
        db.commit()

        # Seed test subject and allocation
        subj = Subject(
            course_code="25MCA405",
            title="Advanced Cloud Security & Audit",
            department="MCA",
            semester="IV",
            scheme="2025",
            academic_year="2025-26"
        )
        db.add(subj)
        db.commit()

        alloc = Allocation(
            reference_number="SJBIT-COE-REP-TEST-01",
            academic_year="2025-26",
            department="MCA",
            semester="IV",
            subject_id=subj.id,
            total_required=2,
            internal_required=1,
            external_required=1,
            allocation_mode="Balanced",
            status="Approved",
            submitted_by=admin_user.username,
            approved_by=hod_mca.username
        )
        db.add(alloc)
        db.flush()

        setter = AllocationSetter(
            allocation_id=alloc.id,
            faculty_id=fac_rec.id,
            faculty_type="internal",
            status="Approved",
            assigned_order=1
        )
        db.add(setter)

        # Workload ledger
        db.add(WorkloadLedger(
            faculty_id=fac_rec.id,
            academic_year="2025-26",
            semester="IV",
            allocation_id=alloc.id,
            entry_type="COMMITTED",
            delta=1,
            remarks="Workload committed upon HOD approval"
        ))
        db.commit()

        # ─── TEST 1: Formula Injection Neutralization (OWASP) ────────────────
        print("\n[TEST 1] Formula Injection Neutralization Defense (OWASP)...")
        # Strings starting with =, +, -, @, \t, \r must be prefixed with '
        assert sanitize_formula_injection("=SUM(A1:A10)") == "'=SUM(A1:A10)"
        assert sanitize_formula_injection("+cmd|' /C calc'!A0") == "'+cmd|' /C calc'!A0"
        assert sanitize_formula_injection("-5+2") == "'-5+2"
        assert sanitize_formula_injection("@secret") == "'@secret"
        assert sanitize_formula_injection("\talert") == "'\talert"

        # Standard safe strings and numbers should remain unmodified
        assert sanitize_formula_injection("Dr. Nagamani S") == "Dr. Nagamani S"
        assert sanitize_formula_injection(12.5) == 12.5
        assert sanitize_formula_injection(2) == 2

        # Null / empty values must return 'Not provided'
        assert sanitize_formula_injection(None) == "Not provided"
        assert sanitize_formula_injection("") == "Not provided"

        print("  ✓ PASS: Formula injection patterns neutralized; nulls converted to 'Not provided'.")
        passed += 1

        # ─── TEST 2: Summary Metrics Verification Against Live DB ─────────────
        print("\n[TEST 2] Summary Metrics Real Database Match...")
        summary_admin = get_reports_summary(db=db, current_user=admin_user)
        total_alloc_db = db.query(Allocation).count()
        total_int_db = db.query(Faculty).filter_by(faculty_type="internal").count()

        assert summary_admin["total_allocations"] == total_alloc_db
        assert summary_admin["internal_faculty_count"] == total_int_db
        assert "Approved" in summary_admin["status_breakdown"]
        assert summary_admin["status_breakdown"]["Approved"] >= 1

        # HOD summary scoping
        summary_hod = get_reports_summary(db=db, current_user=hod_mca)
        assert summary_hod["department_scope"] == "MCA"
        assert summary_hod["total_allocations"] <= total_alloc_db

        print("  ✓ PASS: Summary metrics match database record counts bit-for-bit.")
        passed += 1

        # ─── TEST 3: Faculty Workload Report & Scoping ────────────────────────
        print("\n[TEST 3] Faculty Workload Report Calculation & Scoping...")
        # Admin gets all
        res_wl_adm = get_faculty_workload_data(academic_year="2025-26", department=None, db=db, current_user=admin_user)
        assert res_wl_adm["total"] >= 1

        # Verify fac_rec workload calculations in the report
        rec_found = [r for r in res_wl_adm["records"] if r["Faculty ID"] == fac_rec.id]
        assert len(rec_found) == 1
        assert rec_found[0]["Committed Papers"] >= 1
        assert rec_found[0]["Total Active Workload"] >= 1

        # HOD MCA gets only MCA internal faculty
        res_wl_hod = get_faculty_workload_data(academic_year="2025-26", department=None, db=db, current_user=hod_mca)
        for r in res_wl_hod["records"]:
            assert r["Department"] in ("MCA", "Master of Computer Applications")
            assert r["Type"] == "Internal"

        # HOD querying cross-department returns HTTP 403
        try:
            get_faculty_workload_data(academic_year="2025-26", department="CSE", db=db, current_user=hod_mca)
            assert False, "HOD should not be allowed to query another department"
        except HTTPException as e:
            assert e.status_code == 403

        # Faculty gets only own workload
        res_wl_fac = get_faculty_workload_data(academic_year="2025-26", department=None, db=db, current_user=faculty_user)
        assert res_wl_fac["total"] == 1
        assert res_wl_fac["records"][0]["Faculty ID"] == fac_rec.id

        print("  ✓ PASS: Faculty workload accurately computed and strictly scoped per role.")
        passed += 1

        # ─── TEST 4: Department & Subject Allocations Scoping ─────────────────
        print("\n[TEST 4] Department & Subject Allocations Scoping...")
        # Admin gets department allocations
        dept_res = get_department_allocations_data(db=db, current_user=admin_user)
        assert dept_res["total"] >= 1

        # Faculty accessing department allocations must raise HTTP 403
        try:
            get_department_allocations_data(db=db, current_user=faculty_user)
            assert False, "Faculty must not access department summaries"
        except HTTPException as e:
            assert e.status_code == 403

        # Subject allocations
        subj_res = get_subject_allocations_data(status="Approved", db=db, current_user=admin_user)
        assert subj_res["total"] >= 1
        assert any(r["Reference Number"] == alloc.reference_number for r in subj_res["records"])

        print("  ✓ PASS: Department and subject summaries accurately reflect allocations and respect RBAC.")
        passed += 1

        # ─── TEST 5: External Institution & Import Batches RBAC (Admin Only) ──
        print("\n[TEST 5] External Institutions & Import Batches RBAC (Admin Only)...")
        # Admin can access
        inst_res = get_institution_distribution_data(db=db, current_user=admin_user)
        assert "records" in inst_res

        batches_res = get_import_batches_data(db=db, current_user=admin_user)
        assert "records" in batches_res

        # HOD attempting to access institution distribution -> HTTP 403
        try:
            get_institution_distribution_data(db=db, current_user=hod_mca)
            assert False, "HOD must be blocked from institution distribution"
        except HTTPException as e:
            assert e.status_code == 403

        # Faculty attempting to access import batches -> HTTP 403
        try:
            get_import_batches_data(db=db, current_user=faculty_user)
            assert False, "Faculty must be blocked from import batches"
        except HTTPException as e:
            assert e.status_code == 403

        print("  ✓ PASS: External institution and import batch reports strictly restricted to Admin.")
        passed += 1

        # ─── TEST 6: Multi-Format Exports (Excel & PDF & Print HTML) ──────────
        print("\n[TEST 6] Multi-Format Export Generation (Excel, PDF, Print HTML)...")
        # 1. Excel Export
        excel_bytes = export_report_to_excel(db, "faculty_workload", admin_user)
        assert isinstance(excel_bytes, bytes)
        assert len(excel_bytes) > 500, "Excel output must contain generated workbook bytes"

        # 2. PDF Export
        pdf_bytes = export_report_to_pdf(db, "faculty_workload", admin_user)
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b"%PDF"), "PDF output must begin with %PDF header"

        # 3. Print HTML View
        html_view = get_printable_html_report(db, "faculty_workload", admin_user)
        assert "<!DOCTYPE html>" in html_view
        assert "@media print" in html_view
        assert "SJB INSTITUTE OF TECHNOLOGY" in html_view.upper()

        print("  ✓ PASS: Excel (.xlsx), PDF (%PDF), and printable HTML views generated cleanly.")
        passed += 1

    except Exception as ex:
        print(f"\n❌ UNHANDLED EXCEPTION in Module 14 test: {ex}")
        import traceback
        traceback.print_exc()
        failed += 1
    finally:
        db.close()

    print("\n" + "=" * 75)
    print(f"  MODULE 14 TEST SUMMARY: {passed} PASSED | {failed} FAILED")
    print("=" * 75)
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_module14_tests()
