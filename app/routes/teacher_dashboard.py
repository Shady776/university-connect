from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ..database import get_db
from ..models import User, Course, Assignment, Submission, Enrollment, SubmissionStatus, UserRole
from ..schemas import (
    UserResponse, CourseResponse, AssignmentResponse, 
    CourseCreate, AssignmentCreate
)
from ..oauth2 import get_current_user
from pydantic import BaseModel

router = APIRouter(prefix="/teacher/dashboard", tags=["Teacher Dashboard"])

# Dashboard Statistics Schema
class TeacherDashboardStats(BaseModel):
    active_courses: int
    total_students: int
    active_assignments: int
    pending_grading: int

class RecentSubmissionItem(BaseModel):
    student_name: str
    student_initials: str
    file_name: str
    submitted_at: datetime
    assignment_title: str
    course_code: str

class TeacherDashboardResponse(BaseModel):
    stats: TeacherDashboardStats
    recent_submissions: List[RecentSubmissionItem]


@router.get("/", response_model=TeacherDashboardResponse)
async def get_teacher_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get teacher dashboard with statistics and recent activity
    """
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")
    
    # Get active courses count
    active_courses = db.query(Course).filter(
        Course.teacher_id == current_user.id,
        Course.is_active == True
    ).count()
    
    # Get total unique students enrolled in teacher's courses
    total_students = db.query(func.count(func.distinct(Enrollment.student_id))).join(
        Course, Enrollment.course_id == Course.id
    ).filter(
        Course.teacher_id == current_user.id
    ).scalar() or 0
    
    # Get active assignments count
    active_assignments = db.query(Assignment).join(
        Course, Assignment.course_id == Course.id
    ).filter(
        Course.teacher_id == current_user.id,
        Assignment.is_active == True
    ).count()
    
    # Get pending grading count (submissions that are submitted but not graded)
    pending_grading = db.query(Submission).join(
        Assignment, Submission.assignment_id == Assignment.id
    ).join(
        Course, Assignment.course_id == Course.id
    ).filter(
        Course.teacher_id == current_user.id,
        Submission.status == SubmissionStatus.SUBMITTED
    ).count()
    
    # Get recent submissions (last 10)
    recent_submissions_query = db.query(
        Submission,
        User.full_name,
        User.username,
        Assignment.title.label('assignment_title'),
        Course.course_code
    ).join(
        Assignment, Submission.assignment_id == Assignment.id
    ).join(
        Course, Assignment.course_id == Course.id
    ).join(
        User, Submission.student_id == User.id
    ).filter(
        Course.teacher_id == current_user.id,
        Submission.submitted_at.isnot(None)  # Only get actually submitted items
    ).order_by(
        Submission.submitted_at.desc()
    ).limit(10).all()
    
    recent_submissions = []
    for submission, student_name, student_username, assignment_title, course_code in recent_submissions_query:
        # Generate initials from student name or username
        if student_name:
            initials = ''.join([word[0].upper() for word in student_name.split()[:2]])
        else:
            initials = student_username[:2].upper()
        
        # Determine what to display based on submission type
        if submission.file_url:
            # If there's a file, just say "file"
            display_text = "file"
        elif submission.content:
            # If it's text content, show preview (first ~30 characters)
            content_preview = submission.content.strip()
            if len(content_preview) > 30:
                # Find a good breaking point (space) near 30 chars
                space_index = content_preview.find(' ', 25)
                if space_index > 0 and space_index < 35:
                    display_text = content_preview[:space_index] + "..."
                else:
                    display_text = content_preview[:30] + "..."
            else:
                display_text = content_preview
        else:
            display_text = "submission"
        
        # Ensure submitted_at is timezone-aware (convert to UTC if naive)
        submitted_at = submission.submitted_at
        if submitted_at.tzinfo is None:
            # If datetime is naive, assume it's UTC
            submitted_at = submitted_at.replace(tzinfo=timezone.utc)
        
        recent_submissions.append(RecentSubmissionItem(
            student_name=student_name or student_username,
            student_initials=initials,
            file_name=display_text,
            submitted_at=submitted_at,
            assignment_title=assignment_title,
            course_code=course_code or "N/A"
        ))
    
    stats = TeacherDashboardStats(
        active_courses=active_courses,
        total_students=total_students,
        active_assignments=active_assignments,
        pending_grading=pending_grading
    )
    
    return TeacherDashboardResponse(
        stats=stats,
        recent_submissions=recent_submissions
    )


# Quick Actions - Course Creation
@router.post("/quick-actions/create-course", response_model=CourseResponse)
async def quick_create_course(
    course: CourseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Quick action to create a new course from dashboard
    """
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")
    
    # Create the course
    new_course = Course(
        **course.model_dump(),
        teacher_id=current_user.id,
        instructor=current_user.full_name or current_user.username
    )
    
    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    
    return new_course


# Quick Actions - Assignment Creation
@router.post("/quick-actions/create-assignment", response_model=AssignmentResponse)
async def quick_create_assignment(
    assignment: AssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Quick action to create a new assignment from dashboard
    """
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")
    
    # Verify the course belongs to the teacher
    course = db.query(Course).filter(
        Course.id == assignment.course_id,
        Course.teacher_id == current_user.id
    ).first()
    
    if not course:
        raise HTTPException(
            status_code=404, 
            detail="Course not found or you don't have permission to add assignments to it"
        )
    
    # Create the assignment
    new_assignment = Assignment(**assignment.model_dump())
    
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)
    
    return new_assignment


# Get teacher's courses for quick action dropdown
@router.get("/courses-list", response_model=List[CourseResponse])
async def get_teacher_courses_list(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get simplified list of teacher's courses for quick actions
    """
    if current_user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Access denied. Teachers only.")
    
    courses = db.query(Course).filter(
        Course.teacher_id == current_user.id,
        Course.is_active == True
    ).order_by(Course.created_at.desc()).all()
    
    return courses