from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Float, Enum, Boolean, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import enum
import uuid

Base = declarative_base()

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"

class SubmissionStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    GRADED = "GRADED"
    LATE = "LATE"

class AnnouncementType(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    SUCCESS = "success"
    URGENT = "urgent"

# Department Enum
class Department(str, enum.Enum):
    CSC = "CSC"  # Computer Science
    SEN = "SEN"  # Software Engineering
    IFT = "IFT"  # Information Technology
    CYB = "CYB"  # Cybersecurity

# Semester Enum
class Semester(str, enum.Enum):
    FIRST = "1st"
    SECOND = "2nd"

class TestType(str, enum.Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    SUBJECTIVE = "subjective"
    THEORY = "theory"
    MIXED = "mixed"

class TestStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    INACTIVE = "inactive"

class QuestionType(str, enum.Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_IN_BLANK = "fill_in_blank"
    THEORY = "theory"

class TestAttemptStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    GRADED = "graded"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(Enum(UserRole), nullable=False)
    matric_number = Column(String, unique=True, index=True, nullable=False)
    department = Column(Enum(Department), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    taught_courses = relationship("Course", back_populates="teacher", foreign_keys="Course.teacher_id")
    enrollments = relationship("Enrollment", back_populates="student")
    submissions = relationship("Submission", back_populates="student")
    announcements = relationship("Announcement", back_populates="author")

class Course(Base):
    __tablename__ = "courses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String, nullable=False)
    course_code = Column(String, index=True, nullable=True)
    description = Column(Text, nullable=True)
    department = Column(Enum(Department), nullable=False)
    semester = Column(Enum(Semester), nullable=False)
    instructor = Column(String, nullable=True)
    schedule = Column(String, nullable=True)
    location = Column(String, nullable=True)
    credits = Column(Integer, default=3, nullable=False)
    teacher_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    materials = relationship("CourseMaterial", back_populates="course", cascade="all, delete-orphan")
    teacher = relationship("User", back_populates="taught_courses", foreign_keys=[teacher_id])
    assignments = relationship("Assignment", back_populates="course", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="course", cascade="all, delete-orphan")

class Enrollment(Base):
    __tablename__ = "enrollments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    enrolled_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    student = relationship("User", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")

class Assignment(Base):
    __tablename__ = "assignments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    max_score = Column(Float, default=100.0, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    course = relationship("Course", back_populates="assignments")
    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan")

class Submission(Base):
    __tablename__ = "submissions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    assignment_id = Column(UUID(as_uuid=True), ForeignKey("assignments.id"), nullable=False)
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=True)
    file_url = Column(String, nullable=True)
    status = Column(Enum(SubmissionStatus), default=SubmissionStatus.SUBMITTED, nullable=False)
    score = Column(Float, nullable=True)
    feedback = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    graded_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    assignment = relationship("Assignment", back_populates="submissions")
    student = relationship("User", back_populates="submissions")

class Announcement(Base):
    __tablename__ = "announcements"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    announcement_type = Column(Enum(AnnouncementType), default=AnnouncementType.INFO, nullable=False)
    author_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    author = relationship("User", back_populates="announcements")
    
class CourseMaterial(Base):
    __tablename__ = "course_materials"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    file_url = Column(String, nullable=False)
    file_type = Column(String, nullable=True)  # pdf, doc, ppt, etc.
    file_size = Column(Integer, nullable=True)  # in bytes
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    course = relationship("Course", back_populates="materials")
    uploader = relationship("User")
    
class Test(Base):
    __tablename__ = "tests"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    course_id = Column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    test_type = Column(Enum(TestType), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    total_marks = Column(Float, default=100.0, nullable=False)
    randomize_questions = Column(Boolean, default=True, nullable=False)
    randomize_options = Column(Boolean, default=True, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(Enum(TestStatus), default=TestStatus.DRAFT, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    
    course = relationship("Course", backref="tests")
    creator = relationship("User", foreign_keys=[created_by])
    questions = relationship("TestQuestion", back_populates="test", cascade="all, delete-orphan")
    attempts = relationship("TestAttempt", back_populates="test", cascade="all, delete-orphan")

class TestQuestion(Base):
    __tablename__ = "test_questions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    test_id = Column(UUID(as_uuid=True), ForeignKey("tests.id"), nullable=False)
    question_type = Column(Enum(QuestionType), nullable=False)
    question_text = Column(Text, nullable=False)
    marks = Column(Float, nullable=False)
    order_index = Column(Integer, nullable=False)
    options = Column(Text, nullable=True)  # JSON string for MCQ options
    correct_answer = Column(String, nullable=True)
    acceptable_answers = Column(Text, nullable=True)  # JSON string for subjective
    
    test = relationship("Test", back_populates="questions")
    answers = relationship("TestAnswer", back_populates="question", cascade="all, delete-orphan")

class TestAttempt(Base):
    __tablename__ = "test_attempts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    test_id = Column(UUID(as_uuid=True), ForeignKey("tests.id"), nullable=False)
    student_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(Enum(TestAttemptStatus), default=TestAttemptStatus.IN_PROGRESS, nullable=False)
    score = Column(Float, nullable=True)
    total_marks = Column(Float, nullable=False)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    graded_at = Column(DateTime(timezone=True), nullable=True)
    time_taken_minutes = Column(Integer, nullable=True)
    invalidation_reason = Column(Text, nullable=True)
    
    test = relationship("Test", back_populates="attempts")
    student = relationship("User")
    answers = relationship("TestAnswer", back_populates="attempt", cascade="all, delete-orphan")

class TestAnswer(Base):
    __tablename__ = "test_answers"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    attempt_id = Column(UUID(as_uuid=True), ForeignKey("test_attempts.id"), nullable=False)
    question_id = Column(UUID(as_uuid=True), ForeignKey("test_questions.id"), nullable=False)
    answer_text = Column(Text, nullable=True)
    is_correct = Column(Boolean, nullable=True)
    marks_obtained = Column(Float, nullable=True)
    teacher_feedback = Column(Text, nullable=True)
    
    attempt = relationship("TestAttempt", back_populates="answers")
    question = relationship("TestQuestion", back_populates="answers")