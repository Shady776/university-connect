from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from ..models import Assignment, Course, User, Enrollment
from ..schemas import AssignmentCreate, AssignmentResponse, AssignmentUpdate, AssignmentDetailResponse
from ..oauth2 import get_current_user, get_current_teacher

router = APIRouter(prefix="/assignments", tags=["Assignments"])

@router.post("/", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(
    assignment_data: AssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    # Verify course exists and teacher owns it
    course = db.query(Course).filter(Course.id == assignment_data.course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only create assignments for your own courses"
        )
    
    new_assignment = Assignment(
        course_id=assignment_data.course_id,
        title=assignment_data.title,
        description=assignment_data.description,
        max_score=assignment_data.max_score,
        due_date=assignment_data.due_date
    )
    
    db.add(new_assignment)
    db.commit()
    db.refresh(new_assignment)
    
    return new_assignment

@router.get("/course/{course_id}", response_model=List[AssignmentResponse])
def get_course_assignments(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Verify user has access to this course
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
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
    
    assignments = db.query(Assignment).filter(Assignment.course_id == course_id).all()
    return assignments

@router.get("/{assignment_id}", response_model=AssignmentDetailResponse)
def get_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    # Verify access
    course = assignment.course
    if current_user.role == "teacher":
        if course.teacher_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this assignment"
            )
    else:
        enrollment = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == course.id
        ).first()
        if not enrollment:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not enrolled in this course"
            )
    
    return assignment

@router.put("/{assignment_id}", response_model=AssignmentResponse)
def update_assignment(
    assignment_id: int,
    assignment_data: AssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update assignments in your own courses"
        )
    
    if assignment_data.title is not None:
        assignment.title = assignment_data.title
    if assignment_data.description is not None:
        assignment.description = assignment_data.description
    if assignment_data.max_score is not None:
        assignment.max_score = assignment_data.max_score
    if assignment_data.due_date is not None:
        assignment.due_date = assignment_data.due_date
    if assignment_data.is_active is not None:
        assignment.is_active = assignment_data.is_active
    
    db.commit()
    db.refresh(assignment)
    
    return assignment

@router.delete("/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete assignments in your own courses"
        )
    
    db.delete(assignment)
    db.commit()
    
    return None