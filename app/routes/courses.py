from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from ..database import get_db
from ..models import Course, User, Enrollment
from ..schemas import CourseCreate, CourseResponse, CourseUpdate, CourseDetailResponse
from ..oauth2 import get_current_user, get_current_teacher

router = APIRouter(prefix="/courses", tags=["Courses"])

@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
def create_course(
    course_data: CourseCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Create a new course. Only teachers can create courses.
    The instructor name is automatically set from the teacher's profile (full_name).
    """
    # Automatically set instructor from teacher's full_name
    instructor_name = current_user.full_name if current_user.full_name else current_user.username
    
    new_course = Course(
        title=course_data.title,
        course_code=course_data.course_code,
        description=course_data.description,
        department=course_data.department,  # NEW: Department field
        semester=course_data.semester,  # NEW: Semester field
        instructor=instructor_name,  # Auto-filled from teacher's profile
        schedule=course_data.schedule,
        location=course_data.location,
        credits=course_data.credits,
        teacher_id=current_user.id
    )
    
    db.add(new_course)
    db.commit()
    db.refresh(new_course)
    
    return new_course

@router.get("/", response_model=List[CourseResponse])
def get_all_courses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100
):
    """
    Get all courses:
    - Teachers see only their own courses
    - Students see all available courses
    """
    if current_user.role == "teacher":
        courses = db.query(Course).filter(
            Course.teacher_id == current_user.id
        ).offset(skip).limit(limit).all()
    else:
        courses = db.query(Course).filter(
            Course.is_active == True
        ).offset(skip).limit(limit).all()
    
    return courses

@router.get("/{course_id}", response_model=CourseDetailResponse)
def get_course(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed information about a specific course.
    Teachers can only view their own courses.
    Students can view any active course.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Access control
    if current_user.role == "teacher":
        if course.teacher_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this course"
            )
    elif current_user.role == "student":
        if not course.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This course is not available"
            )
    
    return course

@router.put("/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: UUID,
    course_data: CourseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Update a course. Only the course teacher can update it.
    Note: instructor field is protected and automatically syncs with teacher's profile.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own courses"
        )
    
    # Update fields if provided
    update_data = course_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(course, field, value)
    
    # Always sync instructor with current teacher's full_name
    course.instructor = current_user.full_name if current_user.full_name else current_user.username
    
    db.commit()
    db.refresh(course)
    
    return course

@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Delete a course. Only the course teacher can delete it.
    This will also delete all associated assignments and enrollments (cascade).
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own courses"
        )
    
    db.delete(course)
    db.commit()
    
    return None

@router.get("/{course_id}/students", response_model=List[dict])
def get_course_students(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Get all students enrolled in a course. Only accessible by the course teacher.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view students in your own courses"
        )
    
    enrollments = db.query(Enrollment).filter(
        Enrollment.course_id == course_id
    ).all()
    
    students = [{
        "student_id": enrollment.student.id,
        "username": enrollment.student.username,
        "full_name": enrollment.student.full_name,
        "email": enrollment.student.email,
        "enrolled_at": enrollment.enrolled_at
    } for enrollment in enrollments]
    
    return students