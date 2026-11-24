"""
ExamExpert AI -- PDF Allocation Order Generator
Generates official SJBIT Controller of Examinations Question Paper Setter appointment order.
"""
import os
from fpdf import FPDF
from datetime import datetime

def _sanitize(text: str) -> str:
    if not text:
        return ""
    t = str(text).replace("—", "--").replace("–", "-").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return t.encode("latin-1", "replace").decode("latin-1")

class AllocationOrderPDF(FPDF):
    def header(self):
        # Institutional Border
        self.set_line_width(0.8)
        self.set_draw_color(15, 44, 89) # Navy
        self.rect(5, 5, 200, 287)
        self.set_line_width(0.2)
        self.rect(6.5, 6.5, 197, 284)

        # Header Title
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(15, 44, 89) # Deep Navy
        self.cell(0, 7, "SJB INSTITUTE OF TECHNOLOGY", ln=True, align="C")
        
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(80, 80, 80)
        self.cell(0, 4.5, "(An Autonomous Institution Affiliated to Visvesvaraya Technological University, Belagavi)", ln=True, align="C")
        self.cell(0, 4.5, "Accredited by NAAC with 'A+' Grade | BGS Health & Education City, Kengeri, Bengaluru - 560060", ln=True, align="C")
        
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(0, 86, 179) # Royal Blue
        self.cell(0, 6.5, "OFFICE OF THE CONTROLLER OF EXAMINATIONS (COE)", ln=True, align="C")
        
        # Horizontal Rule
        self.set_draw_color(15, 44, 89)
        self.set_line_width(0.5)
        self.line(12, 32, 198, 32)
        self.ln(5)

    def footer(self):
        self.set_y(-18)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, "Strictly Confidential -- System Generated Order by ExamExpert AI | SJBIT Autonomous", align="C")


def generate_allocation_pdf(alloc_data: dict, output_path: str) -> str:
    pdf = AllocationOrderPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(12, 12, 12)

    # Document Reference & Date
    pdf.set_y(35)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(15, 44, 89)
    pdf.cell(100, 5, f"Ref No: {_sanitize(alloc_data.get('reference_number', 'SJBIT-COE-ORDER'))}", ln=False)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 5, f"Date: {datetime.now().strftime('%d %B %Y')}", ln=True, align="R")

    # Confidential Order Title
    pdf.ln(3)
    pdf.set_fill_color(254, 240, 138) # Light Amber
    pdf.set_draw_color(245, 158, 11) # Amber
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(15, 44, 89)
    pdf.cell(0, 7, "APPOINTMENT ORDER -- QUESTION PAPER SETTING (THEORY EXAM)", border=1, ln=True, align="C", fill=True)
    pdf.ln(3)

    # Examination Metadata Box
    subj = alloc_data.get("subject", {})
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(226, 232, 240)
    pdf.rect(12, pdf.get_y(), 186, 26, style="FD")
    
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(40, 6, "Academic Year:", border=0)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(50, 6, _sanitize(str(alloc_data.get("academic_year"))), border=0)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(40, 6, "Department:", border=0)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(0, 6, _sanitize(str(alloc_data.get("department"))), ln=True)

    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(40, 6, "Semester & Scheme:", border=0)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(50, 6, _sanitize(f"Sem {alloc_data.get('semester')} | {subj.get('scheme', 'Autonomous')} Scheme"), border=0)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(40, 6, "Course Type:", border=0)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(0, 6, _sanitize(str(subj.get("course_type", "Core"))), ln=True)

    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(40, 6, "Course Code & Title:", border=0)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(0, 86, 179)
    pdf.cell(0, 6, _sanitize(f"{subj.get('code', '')} - {subj.get('title', '')}"), ln=True)
    pdf.set_text_color(50, 50, 50)
    pdf.ln(5)

    # Parity & Quota Notice
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(22, 163, 74) # Green
    pdf.cell(0, 5, _sanitize(f"Statutory Quota Compliance: {alloc_data.get('allocation_ratio', '50% Internal / 50% External')} (Target Parity Met)"), ln=True)
    pdf.set_text_color(40, 40, 40)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.multi_cell(0, 4.5, "By order of the Board of Examiners (BOE), the following faculty members are hereby appointed as Question Paper Setters for the aforementioned theory examination. Setters must prepare question paper sets strictly adhering to Bloom's taxonomy and scheme syllabus guidelines.")
    pdf.ln(3)

    # Section A: Internal Faculty Table
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(15, 44, 89)
    pdf.cell(0, 6, "SECTION A -- ALLOCATED INTERNAL FACULTY (SJBIT)", ln=True)
    
    pdf.set_fill_color(241, 245, 249)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(10, 6, "Sl", border=1, fill=True, align="C")
    pdf.cell(50, 6, "Faculty Name", border=1, fill=True)
    pdf.cell(45, 6, "Designation", border=1, fill=True)
    pdf.cell(50, 6, "Institution / Department", border=1, fill=True)
    pdf.cell(31, 6, "Role / Set", border=1, fill=True, ln=True, align="C")

    pdf.set_font("Helvetica", "", 8)
    int_list = alloc_data.get("internal_faculty", [])
    for idx, f in enumerate(int_list, 1):
        pdf.cell(10, 6, str(idx), border=1, align="C")
        pdf.cell(50, 6, _sanitize(f.get("name", "N/A"))[:28], border=1)
        pdf.cell(45, 6, _sanitize(f.get("designation", "Faculty"))[:26], border=1)
        pdf.cell(50, 6, "SJBIT, Bengaluru", border=1)
        role_label = f"Internal Setter (Set {chr(64 + idx)})"
        if f.get("is_manual_override"):
            role_label = f"Manual Exception (Set {chr(64 + idx)})"
        pdf.cell(31, 6, role_label, border=1, ln=True, align="C")
    pdf.ln(3)

    # Section B: External Faculty Table
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(15, 44, 89)
    pdf.cell(0, 6, "SECTION B -- ALLOCATED EXTERNAL FACULTY (UNIVERSITY / SISTER COLLEGES)", ln=True)

    pdf.set_fill_color(241, 245, 249)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(10, 6, "Sl", border=1, fill=True, align="C")
    pdf.cell(50, 6, "Faculty Name", border=1, fill=True)
    pdf.cell(45, 6, "Designation", border=1, fill=True)
    pdf.cell(50, 6, "External Institution", border=1, fill=True)
    pdf.cell(31, 6, "Role / Set", border=1, fill=True, ln=True, align="C")

    pdf.set_font("Helvetica", "", 8)
    ext_list = alloc_data.get("external_faculty", [])
    for idx, f in enumerate(ext_list, 1):
        pdf.cell(10, 6, str(idx), border=1, align="C")
        pdf.cell(50, 6, _sanitize(f.get("name", "N/A"))[:28], border=1)
        pdf.cell(45, 6, _sanitize(f.get("designation", "Faculty"))[:26], border=1)
        pdf.cell(50, 6, _sanitize(f.get("institution", "External University"))[:28], border=1)
        role_label = f"External Setter (Set {chr(64 + len(int_list) + idx)})"
        if f.get("is_manual_override"):
            role_label = f"Manual Exception (Set {chr(64 + len(int_list) + idx)})"
        pdf.cell(31, 6, role_label, border=1, ln=True, align="C")
    pdf.ln(4)

    if alloc_data.get("has_manual_override") or alloc_data.get("exception_reason"):
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(180, 83, 9)
        pdf.multi_cell(0, 4.5, _sanitize(f"Special Administrative Provision: Manual exception candidate(s) authorized by COE. Note: {alloc_data.get('exception_reason', 'Shortage exception documented.')}"))
        pdf.ln(3)

    # Instructions Box
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(15, 44, 89)
    pdf.cell(0, 5, "Instructions & Statutory Guidelines:", ln=True)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 4, "1. Question papers must be prepared strictly in accordance with official SJBIT curriculum scheme & course outcomes.", ln=True)
    pdf.cell(0, 4, "2. A detailed scheme of evaluation and marking solution must accompany each question paper set.", ln=True)
    pdf.cell(0, 4, "3. Remuneration of Rs. 2,500/- per set will be disbursed through direct institutional bank transfer upon BOE scrutiny.", ln=True)
    pdf.cell(0, 4, "4. Absolute confidentiality must be maintained under the provisions of the Karnataka State Universities Act.", ln=True)
    pdf.ln(6)

    # Signatures
    pdf.set_y(250)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(15, 44, 89)
    pdf.cell(62, 5, "Chairman, Board of Examiners", align="C")
    pdf.cell(62, 5, "Dean (Academics)", align="C")
    pdf.cell(62, 5, "Controller of Examinations", align="C", ln=True)
    
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(62, 4, "SJBIT, Bengaluru", align="C")
    pdf.cell(62, 4, "SJBIT, Bengaluru", align="C")
    pdf.cell(62, 4, "SJBIT, Bengaluru", align="C", ln=True)

    pdf.output(output_path)
    return output_path
