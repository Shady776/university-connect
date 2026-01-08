from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Enrollment, Course, User
from ..schemas import EnrollmentCreate, EnrollmentResponse
from ..oauth2 import get_current_user, get_current_student, get_current_teacher

router = APIRouter(prefix="/enrollments", tags=["Enrollments"])

@router.post("/", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
def enroll_in_course(
    enrollment_data: EnrollmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    # Check if course exists
    course = db.query(Course).filter(Course.id == enrollment_data.course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Check if already enrolled
    existing_enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == enrollment_data.course_id
    ).first()
    
    if existing_enrollment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already enrolled in this course"
        )
    
    new_enrollment = Enrollment(
        student_id=current_user.id,
        course_id=enrollment_data.course_id
    )
    
    db.add(new_enrollment)
    db.commit()
    db.refresh(new_enrollment)
    
    return new_enrollment

@router.get("/my-courses", response_model=List[EnrollmentResponse])
def get_my_enrollments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    enrollments = db.query(Enrollment).filter(Enrollment.student_id == current_user.id).all()
    return enrollments

@router.get("/course/{course_id}/students", response_model=List[EnrollmentResponse])
def get_course_students(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    # Verify teacher owns this course
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
    
    enrollments = db.query(Enrollment).filter(Enrollment.course_id == course_id).all()
    return enrollments

@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def unenroll(
    enrollment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment not found"
        )
    
    if enrollment.student_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only unenroll yourself"
        )
    
    db.delete(enrollment)
    db.commit()
    
    return None