from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from .models import UserRole, SubmissionStatus

class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    role: UserRole

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: Optional[int] = None

# Admin Statistics Schemas
class UserStats(BaseModel):
    total: int
    teachers: int
    students: int

class CourseStats(BaseModel):
    total: int
    active: int

class AssignmentStats(BaseModel):
    total: int

class SubmissionStats(BaseModel):
    total: int
    graded: int
    pending: int

class EnrollmentStats(BaseModel):
    total: int

class SystemOverview(BaseModel):
    users: UserStats
    courses: CourseStats
    assignments: AssignmentStats
    submissions: SubmissionStats
    enrollments: EnrollmentStats

class RecentActivity(BaseModel):
    period_days: int
    new_users: int
    new_courses: int
    new_assignments: int
    new_submissions: int
    new_enrollments: int

class TopCourse(BaseModel):
    course_id: int
    course_title: str
    teacher_id: int
    enrollment_count: int

class TeacherPerformance(BaseModel):
    teacher_id: int
    teacher_name: Optional[str]
    teacher_username: str
    courses_count: int
    assignments_count: int
    pending_grading: int

class StudentPerformance(BaseModel):
    student_id: int
    student_name: Optional[str]
    student_username: str
    average_score: float
    total_submissions: int

# Course Schemas
class CourseBase(BaseModel):
    title: str
    description: Optional[str] = None

class CourseCreate(CourseBase):
    pass

class CourseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class CourseResponse(CourseBase):
    id: int
    teacher_id: int
    created_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True

class CourseDetailResponse(CourseResponse):
    teacher: UserResponse
    assignments: List["AssignmentResponse"] = []

# Enrollment Schemas
class EnrollmentCreate(BaseModel):
    course_id: int

class EnrollmentResponse(BaseModel):
    id: int
    student_id: int
    course_id: int
    enrolled_at: datetime
    course: CourseResponse
    
    class Config:
        from_attributes = True

# Assignment Schemas
class AssignmentBase(BaseModel):
    title: str
    description: Optional[str] = None
    max_score: float = 100.0
    due_date: Optional[datetime] = None

class AssignmentCreate(AssignmentBase):
    course_id: int

class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    max_score: Optional[float] = None
    due_date: Optional[datetime] = None
    is_active: Optional[bool] = None

class AssignmentResponse(AssignmentBase):
    id: int
    course_id: int
    created_at: datetime
    is_active: bool
    
    class Config:
        from_attributes = True

class AssignmentDetailResponse(AssignmentResponse):
    course: CourseResponse
    submissions: List["SubmissionResponse"] = []

# Submission Schemas
class SubmissionBase(BaseModel):
    content: Optional[str] = None
    file_url: Optional[str] = None

class SubmissionCreate(SubmissionBase):
    assignment_id: int

class SubmissionUpdate(BaseModel):
    content: Optional[str] = None
    file_url: Optional[str] = None

class SubmissionGrade(BaseModel):
    """Legacy grading schema - for backward compatibility"""
    score: float
    feedback: Optional[str] = None

class SubmissionManualGrade(BaseModel):
    """
    Schema for manual grading - teacher can provide either percentage or direct score
    """
    percentage: Optional[float] = None  # Grade as percentage (0-100)
    score: Optional[float] = None  # Direct score value
    feedback: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "percentage": 85.5,
                "feedback": "Great work! Well-structured answer with clear explanations."
            }
        }

class SubmissionAIGradeRequest(BaseModel):
    """
    Schema for AI grading request - teacher provides rubric and criteria
    """
    rubric: Optional[str] = None  # Grading rubric
    criteria: Optional[str] = None  # Additional grading criteria
    
    class Config:
        json_schema_extra = {
            "example": {
                "rubric": "Focus on: 1) Correct implementation (40%), 2) Code quality (30%), 3) Documentation (30%)",
                "criteria": "Bonus points for creative solutions and error handling"
            }
        }

class SubmissionResponse(SubmissionBase):
    id: int
    assignment_id: int
    student_id: int
    status: SubmissionStatus
    score: Optional[float] = None
    feedback: Optional[str] = None
    submitted_at: datetime
    graded_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class SubmissionDetailResponse(SubmissionResponse):
    student: UserResponse
    assignment: AssignmentResponse