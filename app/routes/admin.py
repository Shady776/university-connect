from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, timedelta
from ..database import get_db
from ..models import User, Course, Assignment, Submission, Enrollment, UserRole, SubmissionStatus
from ..schemas import (
    UserCreate, UserResponse, CourseResponse, AssignmentResponse, 
    SubmissionDetailResponse, EnrollmentResponse, SystemOverview,
    RecentActivity, TopCourse, TeacherPerformance, StudentPerformance,
    UserStats, CourseStats, AssignmentStats, SubmissionStats, EnrollmentStats
)
from ..oauth2 import get_current_admin
from passlib.context import CryptContext

router = APIRouter(prefix="/admin", tags=["Admin"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

# ==================== USER MANAGEMENT ====================

@router.post("/users/teacher", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_teacher(
    teacher_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Admin can create teacher accounts"""
    # Check if user exists
    existing_user = db.query(User).filter(
        (User.email == teacher_data.email) | (User.username == teacher_data.username)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email or username already exists"
        )
    
    # Force role to be teacher
    hashed_pwd = hash_password(teacher_data.password)
    new_teacher = User(
        email=teacher_data.email,
        username=teacher_data.username,
        full_name=teacher_data.full_name,
        role=UserRole.TEACHER,
        hashed_password=hashed_pwd
    )
    
    db.add(new_teacher)
    db.commit()
    db.refresh(new_teacher)
    
    return new_teacher

@router.post("/users/student", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_student(
    student_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Admin can create student accounts"""
    existing_user = db.query(User).filter(
        (User.email == student_data.email) | (User.username == student_data.username)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email or username already exists"
        )
    
    hashed_pwd = hash_password(student_data.password)
    new_student = User(
        email=student_data.email,
        username=student_data.username,
        full_name=student_data.full_name,
        role=UserRole.STUDENT,
        hashed_password=hashed_pwd
    )
    
    db.add(new_student)
    db.commit()
    db.refresh(new_student)
    
    return new_student

@router.get("/users", response_model=List[UserResponse])
def get_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
    role: Optional[UserRole] = None,
    skip: int = 0,
    limit: int = 100
):
    """Get all users with optional role filter"""
    query = db.query(User)
    
    if role:
        query = query.filter(User.role == role)
    
    users = query.offset(skip).limit(limit).all()
    return users

@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Get specific user details"""
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return user

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Delete a user (cannot delete self or other admins)"""
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself"
        )
    
    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete other admins"
        )
    
    db.delete(user)
    db.commit()
    
    return None

# ==================== COURSE MANAGEMENT ====================

@router.get("/courses", response_model=List[CourseResponse])
def get_all_courses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 100
):
    """Get all courses in the system"""
    courses = db.query(Course).offset(skip).limit(limit).all()
    return courses

@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Delete any course"""
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    db.delete(course)
    db.commit()
    
    return None

# ==================== ASSIGNMENT MANAGEMENT ====================

@router.get("/assignments", response_model=List[AssignmentResponse])
def get_all_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 100
):
    """Get all assignments in the system"""
    assignments = db.query(Assignment).offset(skip).limit(limit).all()
    return assignments

@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Delete any assignment"""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    db.delete(assignment)
    db.commit()
    
    return None

# ==================== SUBMISSION MANAGEMENT ====================

@router.get("/submissions", response_model=List[SubmissionDetailResponse])
def get_all_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
    status_filter: Optional[SubmissionStatus] = None,
    skip: int = 0,
    limit: int = 100
):
    """Get all submissions with optional status filter"""
    query = db.query(Submission)
    
    if status_filter:
        query = query.filter(Submission.status == status_filter)
    
    submissions = query.offset(skip).limit(limit).all()
    return submissions

@router.delete("/submissions/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Delete any submission"""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )
    
    db.delete(submission)
    db.commit()
    
    return None

# ==================== ENROLLMENT MANAGEMENT ====================

@router.get("/enrollments", response_model=List[EnrollmentResponse])
def get_all_enrollments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
    skip: int = 0,
    limit: int = 100
):
    """Get all enrollments"""
    enrollments = db.query(Enrollment).offset(skip).limit(limit).all()
    return enrollments

@router.delete("/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_enrollment(
    enrollment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Delete any enrollment"""
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment not found"
        )
    
    db.delete(enrollment)
    db.commit()
    
    return None

# ==================== STATISTICS & ANALYTICS ====================

@router.get("/statistics/overview", response_model=SystemOverview)
def get_system_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Get overall system statistics"""
    total_users = db.query(User).count()
    total_teachers = db.query(User).filter(User.role == UserRole.TEACHER).count()
    total_students = db.query(User).filter(User.role == UserRole.STUDENT).count()
    total_courses = db.query(Course).count()
    active_courses = db.query(Course).filter(Course.is_active == True).count()
    total_assignments = db.query(Assignment).count()
    total_submissions = db.query(Submission).count()
    graded_submissions = db.query(Submission).filter(Submission.status == SubmissionStatus.GRADED).count()
    pending_submissions = db.query(Submission).filter(Submission.status == SubmissionStatus.PENDING).count()
    total_enrollments = db.query(Enrollment).count()
    
    return SystemOverview(
        users=UserStats(
            total=total_users,
            teachers=total_teachers,
            students=total_students
        ),
        courses=CourseStats(
            total=total_courses,
            active=active_courses
        ),
        assignments=AssignmentStats(
            total=total_assignments
        ),
        submissions=SubmissionStats(
            total=total_submissions,
            graded=graded_submissions,
            pending=pending_submissions
        ),
        enrollments=EnrollmentStats(
            total=total_enrollments
        )
    )

@router.get("/statistics/recent-activity", response_model=RecentActivity)
def get_recent_activity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
    days: int = 7
):
    """Get activity statistics for the last N days"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    new_users = db.query(User).filter(User.created_at >= cutoff_date).count()
    new_courses = db.query(Course).filter(Course.created_at >= cutoff_date).count()
    new_assignments = db.query(Assignment).filter(Assignment.created_at >= cutoff_date).count()
    new_submissions = db.query(Submission).filter(Submission.submitted_at >= cutoff_date).count()
    new_enrollments = db.query(Enrollment).filter(Enrollment.enrolled_at >= cutoff_date).count()
    
    return RecentActivity(
        period_days=days,
        new_users=new_users,
        new_courses=new_courses,
        new_assignments=new_assignments,
        new_submissions=new_submissions,
        new_enrollments=new_enrollments
    )

@router.get("/statistics/top-courses", response_model=List[TopCourse])
def get_top_courses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
    limit: int = 10
):
    """Get courses with most enrollments"""
    top_courses = db.query(
        Course,
        func.count(Enrollment.id).label("enrollment_count")
    ).join(Enrollment, Course.id == Enrollment.course_id)\
     .group_by(Course.id)\
     .order_by(desc("enrollment_count"))\
     .limit(limit)\
     .all()
    
    result = []
    for course, count in top_courses:
        result.append(TopCourse(
            course_id=course.id,
            course_title=course.title,
            teacher_id=course.teacher_id,
            enrollment_count=count
        ))
    
    return result

@router.get("/statistics/teacher-performance", response_model=List[TeacherPerformance])
def get_teacher_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Get performance metrics for all teachers"""
    teachers = db.query(User).filter(User.role == UserRole.TEACHER).all()
    
    result = []
    for teacher in teachers:
        courses_count = db.query(Course).filter(Course.teacher_id == teacher.id).count()
        assignments_count = db.query(Assignment).join(Course)\
            .filter(Course.teacher_id == teacher.id).count()
        
        # Count submissions that need grading
        pending_grading = db.query(Submission).join(Assignment).join(Course)\
            .filter(
                Course.teacher_id == teacher.id,
                Submission.status.in_([SubmissionStatus.SUBMITTED, SubmissionStatus.LATE])
            ).count()
        
        result.append(TeacherPerformance(
            teacher_id=teacher.id,
            teacher_name=teacher.full_name,
            teacher_username=teacher.username,
            courses_count=courses_count,
            assignments_count=assignments_count,
            pending_grading=pending_grading
        ))
    
    return result

@router.get("/statistics/student-performance", response_model=List[StudentPerformance])
def get_student_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
    limit: int = 20
):
    """Get top performing students by average score"""
    students = db.query(
        User,
        func.avg(Submission.score).label("avg_score"),
        func.count(Submission.id).label("submission_count")
    ).join(Submission, User.id == Submission.student_id)\
     .filter(
         User.role == UserRole.STUDENT,
         Submission.status == SubmissionStatus.GRADED,
         Submission.score.isnot(None)
     )\
     .group_by(User.id)\
     .order_by(desc("avg_score"))\
     .limit(limit)\
     .all()
    
    result = []
    for student, avg_score, submission_count in students:
        result.append(StudentPerformance(
            student_id=student.id,
            student_name=student.full_name,
            student_username=student.username,
            average_score=round(avg_score, 2) if avg_score else 0,
            total_submissions=submission_count
        ))
    
    return result