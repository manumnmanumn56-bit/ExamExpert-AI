"""
ExamExpert AI — Comprehensive Institutional Reporting Service
SJB Institute of Technology | Office of Controller of Examinations

Implements Module 14 (Slice B):
1. Multi-dimensional real data reporting:
   - Faculty-wise allocations and active workload
   - Department-wise allocations and setter distributions
   - Subject-wise allocation order archive
   - Allocations by status (Approved, Rejected, Pending Approvals, Draft, Cancelled)
   - Internal and External faculty rosters
   - External institution distribution
   - Pending verification faculty with granular reasons
   - Dataset import batches history
2. Role-Based Scoping (Server-Enforced):
   - Admin: Complete institutional data access across all dimensions
   - HOD: Scoped strictly to own department; external faculty reports restricted (HTTP 403)
   - Faculty: Scoped strictly to own personal assignments, profile, and workload
3. Real Data Integrity:
   - Real database calculations only (no mock values)
   - Missing data represented as 'Not provided'
4. Formula Injection Neutralization:
   - Prepends single quote (') to cells starting with '=', '+', '-', '@', '\\t', '\\r'
"""
import io
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from fpdf import FPDF

from ..models import (
    Faculty, Subject, Allocation, AllocationSetter, WorkloadLedger,
    ExternalInstitution, ImportHistory, AuditLog, User
)
from .migration import resolve_department_names
from .eligibility import get_faculty_workload


def sanitize_formula_injection(value: Any) -> Any:
    """
    Prevents CSV / Excel Formula Injection (CSV Injection).
    If a cell value starts with '=', '+', '-', '@', '\\t', or '\\r',
    prefixes a single quote (') so spreadsheet engines treat it as raw text.
    Replaces None or empty strings with 'Not provided'.
    """
    if value is None:
        return "Not provided"
    if isinstance(value, (int, float, bool)):
        return value
    s = str(value)
    if not s or not s.strip():
        return "Not provided"
    if s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s.strip()


def sanitize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitizes an entire row dictionary against formula injection."""
    return {k: sanitize_formula_injection(v) for k, v in row.items()}


# ─── Report Aggregation Services ─────────────────────────────────────────────

def get_summary_report(db: Session, current_user: User) -> Dict[str, Any]:
    """Provides high-level institutional or departmental metrics."""
    alloc_query = db.query(Allocation)
    fac_query = db.query(Faculty)

    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        alloc_query = alloc_query.filter(Allocation.department.in_(dept_variants))
        fac_query = fac_query.filter(Faculty.department.in_(dept_variants), Faculty.faculty_type == "internal")
    elif current_user.role == "Faculty":
        # Faculty sees only their allocations
        alloc_query = alloc_query.join(AllocationSetter).filter(AllocationSetter.faculty_id == current_user.faculty_id)

    allocations = alloc_query.all()
    status_counts = {"Pending HOD Approval": 0, "Approved": 0, "Rejected": 0, "Draft": 0, "Cancelled": 0}
    for a in allocations:
        status_counts[a.status] = status_counts.get(a.status, 0) + 1

    internal_count = fac_query.filter(Faculty.faculty_type == "internal").count()
    external_count = db.query(Faculty).filter_by(faculty_type="external").count() if current_user.role == "Admin" else 0
    pending_verif_count = fac_query.filter(Faculty.eligibility_status.like("%Pending%")).count()

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "role_scope": current_user.role,
        "department_scope": current_user.department if current_user.role == "HOD" else "All",
        "total_allocations": len(allocations),
        "status_breakdown": status_counts,
        "internal_faculty_count": internal_count,
        "external_faculty_count": external_count,
        "pending_verification_count": pending_verif_count
    }


def get_faculty_workload_report(
    db: Session,
    current_user: User,
    academic_year: Optional[str] = "2025-26",
    department: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Lists faculty with their active committed and reserved workloads."""
    query = db.query(Faculty)

    if current_user.role == "Faculty":
        query = query.filter(or_(Faculty.id == current_user.faculty_id, Faculty.email == current_user.email))
    elif current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        query = query.filter(Faculty.department.in_(dept_variants), Faculty.faculty_type == "internal")
    else:  # Admin
        if department:
            dept_variants = resolve_department_names(db, department)
            query = query.filter(Faculty.department.in_(dept_variants))

    faculty_list = query.order_by(Faculty.department, Faculty.name).all()
    rows = []

    for f in faculty_list:
        wl = get_faculty_workload(db, f.id, academic_year)
        rows.append(sanitize_row({
            "Faculty ID": f.id,
            "Employee ID": f.employee_id,
            "Name": f.name,
            "Type": f.faculty_type.capitalize() if f.faculty_type else "Not provided",
            "Department": f.department,
            "Designation": f.designation,
            "Institution": f.institution,
            "Qualification": f.qualification,
            "Experience Years": f.experience_years if f.experience_years is not None else "Not provided",
            "Eligibility Status": f.eligibility_status,
            "Committed Papers": wl["committed"],
            "Reserved Papers": wl["reserved"],
            "Total Active Workload": wl["total_active"],
            "Official Email": f.email,
            "Mobile": f.mobile
        }))

    return rows


def get_department_allocations_report(db: Session, current_user: User) -> List[Dict[str, Any]]:
    """Summarizes allocations across departments."""
    if current_user.role == "Faculty":
        raise PermissionError("Access Denied: Faculty cannot access departmental summary reports.")

    query = db.query(Allocation)
    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        query = query.filter(Allocation.department.in_(dept_variants))

    allocs = query.all()
    dept_map = {}

    for a in allocs:
        d = a.department or "Unknown"
        if d not in dept_map:
            dept_map[d] = {
                "Department": d,
                "Total Allocations": 0,
                "Approved": 0,
                "Pending Approval": 0,
                "Rejected": 0,
                "Draft": 0,
                "Internal Setters": 0,
                "External Setters": 0
            }
        dept_map[d]["Total Allocations"] += 1
        if a.status == "Approved":
            dept_map[d]["Approved"] += 1
        elif a.status == "Pending HOD Approval":
            dept_map[d]["Pending Approval"] += 1
        elif a.status == "Rejected":
            dept_map[d]["Rejected"] += 1
        elif a.status == "Draft":
            dept_map[d]["Draft"] += 1

        dept_map[d]["Internal Setters"] += a.internal_required or 0
        dept_map[d]["External Setters"] += a.external_required or 0

    return [sanitize_row(v) for v in dept_map.values()]


def get_subject_allocations_report(
    db: Session,
    current_user: User,
    status_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Detailed allocation records mapped to subjects."""
    query = db.query(Allocation)

    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        query = query.filter(Allocation.department.in_(dept_variants))
    elif current_user.role == "Faculty":
        query = query.join(AllocationSetter).filter(AllocationSetter.faculty_id == current_user.faculty_id)

    if status_filter:
        query = query.filter(Allocation.status == status_filter)

    allocs = query.order_by(Allocation.created_at.desc()).all()
    rows = []

    for a in allocs:
        subj = a.subject
        setters = db.query(AllocationSetter).filter_by(allocation_id=a.id).all()
        setter_names = ", ".join([s.faculty.name if s.faculty else f"#{s.faculty_id}" for s in setters]) or "None"

        rows.append(sanitize_row({
            "Reference Number": a.reference_number,
            "Academic Year": a.academic_year,
            "Department": a.department,
            "Semester": a.semester,
            "Course Code": subj.course_code if subj else "Not provided",
            "Subject Title": subj.title if subj else "Not provided",
            "Mode": a.allocation_mode or "Balanced",
            "Total Setters": a.total_required,
            "Internal Count": a.internal_required,
            "External Count": a.external_required,
            "Status": a.status,
            "Nominated Setters": setter_names,
            "Submitted By": a.submitted_by,
            "Approved By": a.approved_by,
            "Rejection Reason": a.rejection_reason if a.status == "Rejected" else "Not provided",
            "Created Date": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else "Not provided"
        }))

    return rows


def get_institution_distribution_report(db: Session, current_user: User) -> List[Dict[str, Any]]:
    """External institution distribution report (Admin Only)."""
    if current_user.role != "Admin":
        raise PermissionError("Access Denied: Institution distribution report is restricted to COE Administrators.")

    institutions = db.query(ExternalInstitution).order_by(ExternalInstitution.name).all()
    rows = []

    for inst in institutions:
        fac_count = db.query(Faculty).filter(
            Faculty.faculty_type == "external",
            Faculty.institution.ilike(inst.name)
        ).count()

        rows.append(sanitize_row({
            "Institution ID": inst.id,
            "Institution Name": inst.name,
            "Status": "Approved / Whitelisted" if inst.is_allowed else "Blocked / Disabled",
            "External Faculty Count": fac_count
        }))

    return rows


def get_pending_verification_report(db: Session, current_user: User) -> List[Dict[str, Any]]:
    """Roster of faculty members whose profiles have unverified credentials."""
    if current_user.role == "Faculty":
        raise PermissionError("Access Denied: Faculty cannot view institutional verification rosters.")

    query = db.query(Faculty).filter(Faculty.eligibility_status.like("%Pending%"))

    if current_user.role == "HOD":
        dept_variants = resolve_department_names(db, current_user.department or "")
        query = query.filter(Faculty.department.in_(dept_variants), Faculty.faculty_type == "internal")

    pending_list = query.order_by(Faculty.department, Faculty.name).all()
    rows = []

    for f in pending_list:
        missing = []
        if not f.designation:
            missing.append("Designation missing")
        if f.experience_years is None:
            missing.append("Experience unverified")
        if f.faculty_type == "external" and not f.institution:
            missing.append("Institution missing")

        rows.append(sanitize_row({
            "Faculty ID": f.id,
            "Name": f.name,
            "Type": f.faculty_type.capitalize() if f.faculty_type else "Not provided",
            "Department": f.department,
            "Designation": f.designation,
            "Institution": f.institution,
            "Qualification": f.qualification,
            "Recorded Experience": f.experience_years if f.experience_years is not None else "Not provided",
            "Pending Reasons": "; ".join(missing) if missing else f.eligibility_status,
            "Email": f.email,
            "Mobile": f.mobile
        }))

    return rows


def get_import_batches_report(db: Session, current_user: User) -> List[Dict[str, Any]]:
    """Dataset import batches history (Admin Only)."""
    if current_user.role != "Admin":
        raise PermissionError("Access Denied: Import batch history is restricted to Administrators.")

    batches = db.query(ImportHistory).order_by(ImportHistory.imported_at.desc()).all()
    rows = []

    for b in batches:
        rows.append(sanitize_row({
            "Import ID": b.id,
            "Workbook File": b.file_name,
            "Dataset Type": b.file_type.upper() if b.file_type else "Not provided",
            "Imported By": b.imported_by,
            "Total Rows Processed": b.total_rows,
            "Valid Added Rows": b.valid_rows,
            "Duplicates": b.duplicate_rows,
            "Conflicts Count": b.conflicts_count or 0,
            "Skipped Rows": b.skipped_rows,
            "Verification SHA-256": b.file_hash,
            "Timestamp": b.imported_at.strftime("%Y-%m-%d %H:%M:%S") if b.imported_at else "Not provided"
        }))

    return rows


# ─── Export Generators (Excel & PDF) ─────────────────────────────────────────

def export_report_to_excel(db: Session, report_type: str, current_user: User) -> bytes:
    """Generates a styled, formula-injection-safe Excel workbook."""
    if report_type == "faculty_workload":
        rows = get_faculty_workload_report(db, current_user)
        sheet_name = "Faculty Workload"
    elif report_type == "department_allocations":
        rows = get_department_allocations_report(db, current_user)
        sheet_name = "Department Summary"
    elif report_type == "subject_allocations":
        rows = get_subject_allocations_report(db, current_user)
        sheet_name = "Allocation Archive"
    elif report_type == "institution_distribution":
        rows = get_institution_distribution_report(db, current_user)
        sheet_name = "External Institutions"
    elif report_type == "pending_verification":
        rows = get_pending_verification_report(db, current_user)
        sheet_name = "Pending Verification"
    elif report_type == "import_batches":
        rows = get_import_batches_report(db, current_user)
        sheet_name = "Import Batches"
    else:
        rows = get_faculty_workload_report(db, current_user)
        sheet_name = "Report"

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df = pd.DataFrame(rows) if rows else pd.DataFrame([{"Notice": "No records found matching criteria."}])
        df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

    return out.getvalue()


class SummaryReportPDF(FPDF):
    """Institutional Executive Report PDF generator."""
    def header(self):
        self.set_line_width(0.8)
        self.set_draw_color(15, 44, 89)
        self.rect(5, 5, 200, 287)
        self.set_line_width(0.2)
        self.rect(6.5, 6.5, 197, 284)

        self.set_font("Helvetica", "B", 13)
        self.set_text_color(15, 44, 89)
        self.cell(0, 6, "SJB INSTITUTE OF TECHNOLOGY", ln=True, align="C")

        self.set_font("Helvetica", "", 8)
        self.set_text_color(80, 80, 80)
        self.cell(0, 4, "(Autonomous Institution Affiliated to VTU | Accredited by NAAC 'A+' | Bengaluru)", ln=True, align="C")
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(0, 86, 179)
        self.cell(0, 5, "OFFICE OF THE CONTROLLER OF EXAMINATIONS -- OFFICIAL REPORT", ln=True, align="C")

        self.set_draw_color(15, 44, 89)
        self.set_line_width(0.4)
        self.line(10, 26, 200, 26)
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(120, 120, 120)
        self.cell(0, 4, f"Official Report Generated by ExamExpert AI | Page {self.page_no()}", align="C")


def export_report_to_pdf(db: Session, report_type: str, current_user: User) -> bytes:
    """Renders executive report data into an official PDF document."""
    pdf = SummaryReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(15, 44, 89)
    report_title = report_type.replace("_", " ").title()
    pdf.cell(0, 7, f"REPORT: {report_title.upper()}", ln=True)

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(100, 100, 100)
    scope_str = f"Generated by: {current_user.username} ({current_user.role})"
    if current_user.role == "HOD":
        scope_str += f" | Dept: {current_user.department}"
    pdf.cell(0, 4, f"{scope_str} | Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", ln=True)
    pdf.ln(3)

    if report_type == "faculty_workload":
        rows = get_faculty_workload_report(db, current_user)[:35]  # fit top 35 per page
        headers = ["Faculty Name", "Dept", "Type", "Exp", "Committed", "Reserved", "Active Load"]
        widths = [55, 25, 25, 20, 22, 22, 21]
        keys = ["Name", "Department", "Type", "Experience Years", "Committed Papers", "Reserved Papers", "Total Active Workload"]
    elif report_type == "department_allocations":
        rows = get_department_allocations_report(db, current_user)
        headers = ["Department", "Allocations", "Approved", "Pending", "Rejected", "Internal", "External"]
        widths = [50, 25, 23, 23, 23, 23, 23]
        keys = ["Department", "Total Allocations", "Approved", "Pending Approval", "Rejected", "Internal Setters", "External Setters"]
    else:
        rows = get_subject_allocations_report(db, current_user)[:35]
        headers = ["Ref Number", "Dept", "Sem", "Course", "Status", "Setters"]
        widths = [45, 25, 18, 30, 32, 40]
        keys = ["Reference Number", "Department", "Semester", "Course Code", "Status", "Total Setters"]

    # Table Header
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(240, 244, 248)
    pdf.set_text_color(15, 44, 89)
    for h, w in zip(headers, widths):
        pdf.cell(w, 6, h, border=1, align="C", fill=True)
    pdf.ln()

    # Table Rows
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(30, 30, 30)
    for r in rows:
        for k, w in zip(keys, widths):
            val = str(r.get(k, "Not provided"))[:28]
            pdf.cell(w, 5.5, val, border=1, align="C")
        pdf.ln()

    return bytes(pdf.output())


def get_printable_html_report(db: Session, report_type: str, current_user: User) -> str:
    """Generates clean HTML with print stylesheets for direct browser printing."""
    if report_type == "faculty_workload":
        rows = get_faculty_workload_report(db, current_user)
        title = "Faculty Workload & Allocation Roster"
    elif report_type == "department_allocations":
        rows = get_department_allocations_report(db, current_user)
        title = "Department Allocation Summary"
    elif report_type == "subject_allocations":
        rows = get_subject_allocations_report(db, current_user)
        title = "Subject Allocation Order Archive"
    elif report_type == "pending_verification":
        rows = get_pending_verification_report(db, current_user)
        title = "Pending Verification Faculty Roster"
    elif report_type == "institution_distribution":
        rows = get_institution_distribution_report(db, current_user)
        title = "External Institutions Whitelist Distribution"
    elif report_type == "import_batches":
        rows = get_import_batches_report(db, current_user)
        title = "Dataset ETL Import Batches"
    else:
        rows = get_faculty_workload_report(db, current_user)
        title = "Institutional Report"

    if not rows:
        table_html = "<p style='text-align:center; padding:30px; color:#666;'>No records found.</p>"
    else:
        col_headers = "".join([f"<th>{k}</th>" for k in rows[0].keys()])
        row_trs = []
        for r in rows:
            tds = "".join([f"<td>{v}</td>" for v in r.values()])
            row_trs.append(f"<tr>{tds}</tr>")
        table_html = f"<table class='report-table'><thead><tr>{col_headers}</tr></thead><tbody>{''.join(row_trs)}</tbody></table>"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>ExamExpert AI — {title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 20px; color: #1e293b; }}
    .header {{ text-align: center; border-bottom: 2px solid #0f2c59; padding-bottom: 12px; margin-bottom: 16px; }}
    .header h1 {{ margin: 0; font-size: 20px; color: #0f2c59; text-transform: uppercase; }}
    .header p {{ margin: 4px 0 0 0; font-size: 12px; color: #64748b; }}
    .meta {{ display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 14px; color: #475569; }}
    .report-table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
    .report-table th, .report-table td {{ border: 1px solid #cbd5e1; padding: 6px 8px; text-align: left; }}
    .report-table th {{ background-color: #f1f5f9; color: #0f2c59; font-weight: 600; text-align: center; }}
    .report-table tr:nth-child(even) {{ background-color: #f8fafc; }}
    .actions {{ margin-bottom: 16px; }}
    .btn {{ background: #2563eb; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: 600; cursor: pointer; }}
    @media print {{
      .actions {{ display: none; }}
      body {{ margin: 0; }}
      @page {{ size: A4 landscape; margin: 10mm; }}
    }}
  </style>
</head>
<body>
  <div class="actions">
    <button class="btn" onclick="window.print()">🖨️ Print / Save as PDF</button>
  </div>
  <div class="header">
    <h1>SJB Institute of Technology, Bengaluru</h1>
    <p>Autonomous Institution Affiliated to VTU • Office of the Controller of Examinations</p>
    <p><strong>{title.upper()}</strong></p>
  </div>
  <div class="meta">
    <span>Generated by: <strong>{current_user.username}</strong> ({current_user.role})</span>
    <span>Department Scope: <strong>{current_user.department or 'All Departments'}</strong></span>
    <span>Date: <strong>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</strong></span>
  </div>
  {table_html}
</body>
</html>"""
