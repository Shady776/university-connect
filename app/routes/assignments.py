from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from datetime import datetime
from ..database import get_db
from ..models import Assignment, Course, User, Enrollment, Submission, UserRole
from ..schemas import AssignmentCreate, AssignmentResponse, AssignmentUpdate, AssignmentDetailResponse, SubmissionAIGradeRequest, SubmissionStatus
from ..oauth2 import get_current_user, get_current_teacher, get_current_student
import asyncio
from ..services.ai_grading_service import AIGradingService

router = APIRouter(prefix="/assignments", tags=["Assignments"])

@router.post("/", response_model=AssignmentResponse, status_code=status.HTTP_201_CREATED)
def create_assignment(
    assignment_data: AssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Create a new assignment for a course (teacher only)"""
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


@router.post("/assignment/{assignment_id}/grade/ai-batch")
async def batch_grade_with_ai(
    assignment_id: UUID,
    grade_request: SubmissionAIGradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Batch AI grading for all ungraded submissions in an assignment
    """
    # Verify assignment exists and teacher owns it
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only grade submissions for your own courses"
        )
    
    # Get all ungraded submissions with content
    submissions = db.query(Submission).filter(
        Submission.assignment_id == assignment_id,
        Submission.status != SubmissionStatus.GRADED,
        Submission.content.isnot(None)
    ).all()
    
    if not submissions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ungraded text submissions found for this assignment"
        )
    
    # Use criteria from request
    criteria = grade_request.criteria
    
    if not criteria:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide grading criteria"
        )
    
    try:
        ai_service = AIGradingService()
        graded_count = 0
        failed_count = 0
        
        for submission in submissions:
            try:
                # Grade each submission
                grading_result = await ai_service.grade_submission(
                    submission_content=submission.content,
                    assignment_title=assignment.title,
                    assignment_description=assignment.description or "",
                    max_score=assignment.max_score,
                    criteria=criteria
                )
                
                # Update submission
                submission.score = grading_result["score"]
                submission.feedback = grading_result["feedback"]
                submission.status = SubmissionStatus.GRADED
                submission.graded_at = datetime.utcnow()
                graded_count += 1
                
            except Exception as e:
                failed_count += 1
                print(f"Failed to grade submission {submission.id}: {str(e)}")
                continue
        
        db.commit()
        
        return {
            "message": f"Batch grading completed",
            "total_submissions": len(submissions),
            "graded_successfully": graded_count,
            "failed": failed_count
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch AI grading failed: {str(e)}"
        )

@router.get("/student/my-assignments")
def get_student_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """
    Get all assignments for courses the student is enrolled in,
    with submission status for each assignment
    """
    # Get all courses student is enrolled in
    enrollments = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id
    ).all()
    
    course_ids = [e.course_id for e in enrollments]
    
    if not course_ids:
        return []
    
    # Get all assignments for these courses
    assignments = db.query(Assignment).filter(
        Assignment.course_id.in_(course_ids),
        Assignment.is_active == True
    ).all()
    
    # Build response with submission status
    result = []
    for assignment in assignments:
        # Check if student has submitted this assignment
        submission = db.query(Submission).filter(
            Submission.assignment_id == assignment.id,
            Submission.student_id == current_user.id
        ).first()
        
        # Build assignment dict
        assignment_dict = {
            "id": str(assignment.id),
            "course_id": str(assignment.course_id),
            "title": assignment.title,
            "description": assignment.description,
            "max_score": assignment.max_score,
            "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
            "created_at": assignment.created_at.isoformat(),
            "is_active": assignment.is_active,
            "course_code": assignment.course.course_code if assignment.course else None,
            "status": "Submitted" if submission else "Pending",
            "submission_id": str(submission.id) if submission else None,
            "submitted_at": submission.submitted_at.isoformat() if submission else None,
            "grade": submission.score if submission and submission.status == "GRADED" else None
        }
        
        result.append(assignment_dict)
    
    return result

@router.get("/", response_model=List[AssignmentResponse])
def get_all_assignments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100
):
    """Get assignments (teacher sees their own, students see enrolled courses)"""
    if current_user.role == "teacher":
        # Get courses taught by this teacher
        courses = db.query(Course).filter(Course.teacher_id == current_user.id).all()
        course_ids = [course.id for course in courses]
        assignments = db.query(Assignment).filter(
            Assignment.course_id.in_(course_ids)
        ).offset(skip).limit(limit).all()
    else:
        # Get enrolled courses
        enrollments = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id
        ).all()
        course_ids = [e.course_id for e in enrollments]
        assignments = db.query(Assignment).filter(
            Assignment.course_id.in_(course_ids)
        ).offset(skip).limit(limit).all()
    
    return assignments

@router.get("/{assignment_id}", response_model=AssignmentResponse)
def get_assignment(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Changed from get_current_teacher
):
    """Get a specific assignment by ID (teacher, admin, and enrolled students)"""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    # Get the course to check permissions
    course = db.query(Course).filter(Course.id == assignment.course_id).first()
    
    # Check authorization
    if current_user.role == UserRole.ADMIN:
        # Admins can view any assignment
        pass
    elif current_user.role == UserRole.TEACHER:
        # Teachers can only view assignments from their own courses
        if course.teacher_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view assignments from your own courses"
            )
    elif current_user.role == UserRole.STUDENT:
        # Students can only view assignments from courses they're enrolled in
        enrollment = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == assignment.course_id
        ).first()
        
        if not enrollment:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view assignments from courses you're enrolled in"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized access"
        )
    
    return assignment

@router.put("/{assignment_id}", response_model=AssignmentResponse)
def update_assignment(
    assignment_id: UUID,
    assignment_data: AssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Update an assignment (teacher only)"""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update assignments for your own courses"
        )
    
    # Update fields if provided
    update_data = assignment_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(assignment, field, value)
    
    db.commit()
    db.refresh(assignment)
    
    return assignment

@router.delete("/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Delete an assignment (teacher only)"""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete assignments for your own courses"
        )
    
    db.delete(assignment)
    db.commit()
    
    return None

@router.get("/course/{course_id}", response_model=List[AssignmentResponse])
def get_course_assignments(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all assignments for a specific course"""
    course = db.query(Course).filter(Course.id == course_id).first()
    
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    # Verify access
    if current_user.role == "teacher":
        if course.teacher_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view assignments for your own courses"
            )
    else:
        # Check if student is enrolled
        enrollment = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == course_id
        ).first()
        if not enrollment:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not enrolled in this course"
            )
    
    assignments = db.query(Assignment).filter(
        Assignment.course_id == course_id
    ).all()
    
    return assignments