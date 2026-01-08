from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
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
    new_course = Course(
        title=course_data.title,
        description=course_data.description,
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
    if current_user.role == "teacher":
        courses = db.query(Course).filter(Course.teacher_id == current_user.id).offset(skip).limit(limit).all()
    else:
        # Students see courses they're enrolled in
        enrollments = db.query(Enrollment).filter(Enrollment.student_id == current_user.id).all()
        course_ids = [e.course_id for e in enrollments]
        courses = db.query(Course).filter(Course.id.in_(course_ids)).offset(skip).limit(limit).all()
    
    return courses

@router.get("/{course_id}", response_model=CourseDetailResponse)
def get_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Check if user has access to this course
    if current_user.role == "teacher":
        if course.teacher_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this course"
            )
    else:
        enrollment = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == course_id
        ).first()
        if not enrollment:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not enrolled in this course"
            )
    
    return course

@router.put("/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: int,
    course_data: CourseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
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
    
    if course_data.title is not None:
        course.title = course_data.title
    if course_data.description is not None:
        course.description = course_data.description
    if course_data.is_active is not None:
        course.is_active = course_data.is_active
    
    db.commit()
    db.refresh(course)
    
    return course

@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
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