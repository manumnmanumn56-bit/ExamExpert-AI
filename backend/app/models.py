"""
ExamExpert AI — SQLAlchemy ORM Models
Core models for Authentication, Faculty, Syllabus, Allocation, and Logs.
"""
from datetime import datetime
from sqlalchemy import (Column, Integer, String, Float, Boolean, Text,
                        DateTime, ForeignKey)
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True)
    email = Column(String(200), unique=True, index=True)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(50), default="Admin")  # 'Admin' | 'HOD' | 'Faculty'
    department = Column(String(200), nullable=True)  # For HOD/Faculty scoping (e.g. 'MCA', 'CSE')
    full_name = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    failed_attempts = Column(Integer, default=0)
    is_locked = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_activated = Column(Boolean, default=True)
    activation_token = Column(String(100), nullable=True)
    reset_token = Column(String(100), nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class OTPToken(Base):
    __tablename__ = "otp_tokens"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(200), index=True)
    otp_code = Column(String(10), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Faculty(Base):
    __tablename__ = "faculty"
    id = Column(Integer, primary_key=True, index=True)
    db_serial_no = Column(String(50), unique=True, index=True)
    employee_id = Column(String(50))
    name = Column(String(200), nullable=False)
    designation = Column(String(100))
    department = Column(String(200))
    institution = Column(String(300))
    faculty_type = Column(String(20), nullable=False)  # 'internal' | 'external'
    qualification = Column(String(300))
    experience_years = Column(Float)
    eligibility_status = Column(String(80))   # Qualified | Not Qualified | Cannot Verify
    expertise_text = Column(Text)             # raw expertise string
    course_history_text = Column(Text)        # raw "Subject: N, ..." string
    assumed_times_handled = Column(Integer)   # external faculty assumed total
    scheme = Column(String(100))
    address = Column(Text)
    email = Column(String(200))
    mobile = Column(String(50))
    is_available = Column(Boolean, default=True)
    provenance_file = Column(String(300))
    created_at = Column(DateTime, default=datetime.utcnow)

    course_history = relationship("FacultyCourseHistory", back_populates="faculty",
                                  cascade="all, delete-orphan")
    expertise_tags = relationship("FacultyExpertise", back_populates="faculty",
                                  cascade="all, delete-orphan")


class FacultyCourseHistory(Base):
    __tablename__ = "faculty_course_history"
    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id", ondelete="CASCADE"))
    course_title = Column(String(300))
    times_handled = Column(Integer)
    faculty = relationship("Faculty", back_populates="course_history")


class FacultyExpertise(Base):
    __tablename__ = "faculty_expertise"
    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id", ondelete="CASCADE"))
    tag = Column(String(200))
    faculty = relationship("Faculty", back_populates="expertise_tags")


class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    course_code = Column(String(50), index=True)
    title = Column(String(300), nullable=False)
    department = Column(String(200))
    scheme = Column(String(50))
    academic_year = Column(String(20))
    semester = Column(String(20))
    course_type = Column(String(50))
    credits = Column(Integer)
    verification_status = Column(Text)
    source_notes = Column(Text)


class EligibilityRules(Base):
    __tablename__ = "eligibility_rules"
    id = Column(Integer, primary_key=True)
    min_experience_years = Column(Float, default=10.0)
    phd_fasttrack_min_exp = Column(Float, default=5.0)
    max_papers_per_faculty = Column(Integer, default=2)
    max_internal_papers = Column(Integer, default=2)
    max_external_papers = Column(Integer, default=2)
    require_parity = Column(Boolean, default=True)
    otp_policy = Column(String(30), default="ALL_ROLES")  # ALL_ROLES | ADMIN_ONLY | OFF
    external_allowed_institutions = Column(Text, nullable=True)  # JSON list of allowed institutions
    active_academic_year = Column(String(20), default="2025-26")
    upcoming_academic_year = Column(String(20), default="2026-27")
    updated_at = Column(DateTime, default=datetime.utcnow)


class Allocation(Base):
    __tablename__ = "allocations"
    id = Column(Integer, primary_key=True, index=True)
    reference_number = Column(String(50), unique=True)
    academic_year = Column(String(20))
    department = Column(String(200))
    semester = Column(String(20))
    subject_id = Column(Integer, ForeignKey("subjects.id"))
    exam_type = Column(String(80), default="End Semester Examination")
    total_required = Column(Integer)
    internal_required = Column(Integer)
    external_required = Column(Integer)
    allocation_mode = Column(String(30), default="Balanced")  # Balanced | Internal Only | External Only
    # JSON arrays of faculty IDs (preserved for backward compatibility)
    internal_faculty_ids = Column(Text)
    external_faculty_ids = Column(Text)
    min_handled = Column(Integer, default=1)
    allocation_ratio = Column(String(30))
    status = Column(String(50), default="Draft")  # Draft | Pending HOD Approval | Approved | Rejected | Confirmed | Cancelled
    submission_deadline = Column(String(50))
    submitted_by = Column(String(100))
    exception_reason = Column(Text)
    exception_approved_by = Column(String(100))
    hod_remarks = Column(Text, nullable=True)
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime)
    subject = relationship("Subject")
    setters = relationship("AllocationSetter", back_populates="allocation", cascade="all, delete-orphan")


class AllocationSetter(Base):
    __tablename__ = "allocation_setters"
    id = Column(Integer, primary_key=True, index=True)
    allocation_id = Column(Integer, ForeignKey("allocations.id", ondelete="CASCADE"), nullable=False, index=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id", ondelete="CASCADE"), nullable=False, index=True)
    faculty_type = Column(String(20), nullable=False)  # 'internal' | 'external'
    status = Column(String(50), default="Nominated")   # 'Nominated' | 'Approved' | 'Rejected' | 'Replaced'
    verified_handled_count = Column(Integer, nullable=True)
    assigned_order = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    allocation = relationship("Allocation", back_populates="setters")
    faculty = relationship("Faculty")


class WorkloadLedger(Base):
    __tablename__ = "workload_ledger"
    id = Column(Integer, primary_key=True, index=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id", ondelete="CASCADE"), nullable=False, index=True)
    academic_year = Column(String(20), nullable=False, index=True)
    semester = Column(String(20), nullable=True, index=True)  # Scoped per semester exam cycle
    allocation_id = Column(Integer, ForeignKey("allocations.id", ondelete="SET NULL"), nullable=True, index=True)
    entry_type = Column(String(30), nullable=False)  # 'RESERVED' | 'COMMITTED' | 'RELEASED'
    delta = Column(Integer, default=1)               # +1 for reservation/commit, -1 for release
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    faculty = relationship("Faculty")
    allocation = relationship("Allocation")


class ExternalInstitution(Base):
    __tablename__ = "external_institutions"
    id = Column(Integer, primary_key=True)
    name = Column(String(300), unique=True, index=True, nullable=False)
    is_allowed = Column(Boolean, default=True)  # Admin-configurable whitelist
    created_at = Column(DateTime, default=datetime.utcnow)


class DepartmentMapping(Base):
    __tablename__ = "department_mappings"
    id = Column(Integer, primary_key=True)
    short_code = Column(String(50), unique=True, index=True, nullable=False)   # e.g., 'MCA', 'CSE', 'ISE', 'AIML'
    full_name = Column(String(200), unique=True, nullable=False)              # e.g., 'Master of Computer Applications', 'Computer Science & Engineering'
    created_at = Column(DateTime, default=datetime.utcnow)


class FacultySubjectMapping(Base):
    __tablename__ = "faculty_subject_mappings"
    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    mapping_type = Column(String(50), default="SPECIALIZATION", index=True)  # 'EXACT_EXPERIENCE' | 'SPECIALIZATION' | 'RELATED'
    expertise_type = Column(String(50), default="Primary")  # For backward compatibility
    status = Column(String(30), default="SUGGESTED", index=True)  # 'SUGGESTED' | 'CONFIRMED' | 'REJECTED'
    suggestion_reason = Column(String(500), nullable=True)
    times_handled = Column(Integer, default=0)
    is_confirmed = Column(Boolean, default=False)
    confirmed_by = Column(String(100), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    faculty = relationship("Faculty")
    subject = relationship("Subject")


class AllocationConflict(Base):
    __tablename__ = "allocation_conflicts"
    id = Column(Integer, primary_key=True)
    allocation_id = Column(Integer, ForeignKey("allocations.id"))
    conflict_type = Column(String(80))
    severity = Column(String(20))  # Critical | Warning
    description = Column(Text)
    resolved = Column(Boolean, default=False)


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    id = Column(Integer, primary_key=True)
    allocation_id = Column(Integer, ForeignKey("allocations.id"))
    faculty_id = Column(Integer, ForeignKey("faculty.id"))
    faculty_name = Column(String(200))
    channel = Column(String(20))   # Email | SMS
    recipient = Column(String(200))
    message_preview = Column(Text)
    status = Column(String(30))    # Sent | Simulated | Failed | Pending
    is_simulated = Column(Boolean, default=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text)


class ImportHistory(Base):
    __tablename__ = "import_history"
    id = Column(Integer, primary_key=True)
    file_name = Column(String(300))
    file_hash = Column(String(64))
    file_type = Column(String(30))  # internal | external | syllabus
    total_rows = Column(Integer)
    valid_rows = Column(Integer)
    duplicate_rows = Column(Integer)
    skipped_rows = Column(Integer)
    imported_at = Column(DateTime, default=datetime.utcnow)
    imported_by = Column(String(100), nullable=True)
    conflicts_count = Column(Integer, default=0, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    action = Column(String(100))
    entity_type = Column(String(50))
    entity_id = Column(Integer)
    details = Column(Text)
    performed_at = Column(DateTime, default=datetime.utcnow)


class ActiveSession(Base):
    __tablename__ = "active_sessions"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(128), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User")
