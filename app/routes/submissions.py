from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime
from uuid import UUID
import cloudinary
import cloudinary.uploader
import os
from dotenv import load_dotenv
from ..database import get_db
from ..models import Submission, Assignment, User, Enrollment, SubmissionStatus
from ..schemas import (
    SubmissionResponse, 
    SubmissionDetailResponse,
    SubmissionManualGrade,
    SubmissionGrade,
    SubmissionAIGradeRequest
)
from ..oauth2 import get_current_user, get_current_student, get_current_teacher
import asyncio
from ..services.ai_grading_service import AIGradingService

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/submissions", tags=["Submissions"])

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

@router.post("/", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
async def submit_assignment(
    assignment_id: str = Form(...),
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """
    Submit an assignment with either text content or file upload.
    Students must be enrolled in the course to submit.
    """
    # Convert assignment_id string to UUID
    try:
        assignment_uuid = UUID(assignment_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid assignment ID format"
        )
    
    # Validate that either content or file is provided
    if not content and not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either content or file must be provided"
        )
    
    # Verify assignment exists
    assignment = db.query(Assignment).filter(Assignment.id == assignment_uuid).first()
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    # Verify student is enrolled in the course
    enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == assignment.course_id
    ).first()
    
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not enrolled in this course"
        )
    
    # Check if already submitted
    existing_submission = db.query(Submission).filter(
        Submission.assignment_id == assignment_uuid,
        Submission.student_id == current_user.id
    ).first()
    
    if existing_submission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already submitted this assignment. Use update endpoint to modify."
        )
    
    # Handle file upload to Cloudinary
    file_url = None
    if file:
        try:
            # Upload file to Cloudinary
            upload_result = cloudinary.uploader.upload(
                file.file,
                folder=f"submissions/{assignment_uuid}",
                resource_type="auto",
                public_id=f"{current_user.id}_{datetime.utcnow().timestamp()}"
            )
            file_url = upload_result.get("secure_url")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file: {str(e)}"
            )
    
    # Determine submission status
    submission_status = SubmissionStatus.SUBMITTED
    if assignment.due_date and datetime.utcnow() > assignment.due_date:
        submission_status = SubmissionStatus.LATE
    
    new_submission = Submission(
        assignment_id=assignment_uuid,
        student_id=current_user.id,
        content=content,
        file_url=file_url,
        status=submission_status
    )
    
    db.add(new_submission)
    db.commit()
    db.refresh(new_submission)
    
    return new_submission


@router.post("/{submission_id}/grade/ai", response_model=SubmissionResponse)
async def grade_submission_with_ai(
    submission_id: UUID,
    grade_request: SubmissionAIGradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )
    
    # Verify teacher owns the course
    if submission.assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only grade submissions for your own courses"
        )
    
    # Check if submission has content
    if not submission.content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot grade submission without text content. AI grading only works for text submissions."
        )
    
    # Get assignment details
    assignment = submission.assignment
    
    # Use criteria from request
    criteria = grade_request.criteria
    
    if not criteria:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide grading criteria for AI grading"
        )
    
    try:
        # Initialize AI grading service
        ai_service = AIGradingService()
        
        # Grade the submission
        grading_result = await ai_service.grade_submission(
            submission_content=submission.content,
            assignment_title=assignment.title,
            assignment_description=assignment.description or "",
            max_score=assignment.max_score,
            criteria=criteria
        )
        
        # Update submission with AI grading results
        submission.score = grading_result["score"]
        submission.feedback = grading_result["feedback"]
        submission.status = SubmissionStatus.GRADED
        submission.graded_at = datetime.utcnow()
        
        db.commit()
        db.refresh(submission)
        
        return submission
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI grading failed: {str(e)}"
        )


@router.get("/my-submissions", response_model=List[SubmissionDetailResponse])
def get_my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Get all submissions for the current student with full assignment details"""
    submissions = db.query(Submission).options(
        joinedload(Submission.assignment).joinedload(Assignment.course),
        joinedload(Submission.student)
    ).filter(Submission.student_id == current_user.id).all()
    
    return submissions

@router.get("/assignment/{assignment_id}", response_model=List[SubmissionDetailResponse])
def get_assignment_submissions(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Get all submissions for an assignment (teacher only)"""
    # Verify assignment exists and teacher owns the course
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignment not found"
        )
    
    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view submissions for your own courses"
        )
    
    submissions = db.query(Submission).filter(Submission.assignment_id == assignment_id).all()
    return submissions

@router.get("/{submission_id}", response_model=SubmissionDetailResponse)
def get_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific submission"""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )
    
    # Verify access
    if current_user.role == "student":
        if submission.student_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own submissions"
            )
    else:
        if submission.assignment.course.teacher_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view submissions for your own courses"
            )
    
    return submission

@router.put("/{submission_id}", response_model=SubmissionResponse)
async def update_submission(
    submission_id: UUID,
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Update a submission (before grading)"""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )
    
    if submission.student_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own submissions"
        )
    
    if submission.status == SubmissionStatus.GRADED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update a graded submission"
        )
    
    # Update content if provided
    if content is not None:
        submission.content = content
    
    # Handle file upload if provided
    if file:
        try:
            # Delete old file from Cloudinary if exists
            if submission.file_url:
                try:
                    public_id = submission.file_url.split('/')[-1].split('.')[0]
                    cloudinary.uploader.destroy(f"submissions/{submission.assignment_id}/{public_id}")
                except Exception:
                    pass  # Continue even if old file deletion fails
            
            # Upload new file
            upload_result = cloudinary.uploader.upload(
                file.file,
                folder=f"submissions/{submission.assignment_id}",
                resource_type="auto",
                public_id=f"{current_user.id}_{datetime.utcnow().timestamp()}"
            )
            submission.file_url = upload_result.get("secure_url")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file: {str(e)}"
            )
    
    submission.submitted_at = datetime.utcnow()
    
    db.commit()
    db.refresh(submission)
    
    return submission

@router.post("/{submission_id}/grade/manual", response_model=SubmissionResponse)
def grade_submission_manually(
    submission_id: UUID,
    grade_data: SubmissionManualGrade,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Manual grading by teacher with percentage or direct score
    """
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )
    
    if submission.assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only grade submissions for your own courses"
        )
    
    # Calculate score based on percentage or direct score
    if grade_data.percentage is not None:
        if grade_data.percentage < 0 or grade_data.percentage > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Percentage must be between 0 and 100"
            )
        calculated_score = (grade_data.percentage / 100) * submission.assignment.max_score
    elif grade_data.score is not None:
        if grade_data.score > submission.assignment.max_score:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Score cannot exceed maximum score of {submission.assignment.max_score}"
            )
        calculated_score = grade_data.score
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either percentage or score must be provided"
        )
    
    submission.score = calculated_score
    submission.feedback = grade_data.feedback
    submission.status = SubmissionStatus.GRADED
    submission.graded_at = datetime.utcnow()
    
    db.commit()
    db.refresh(submission)
    
    return submission

# Legacy endpoint for backward compatibility
@router.post("/{submission_id}/grade", response_model=SubmissionResponse)
def grade_submission(
    submission_id: UUID,
    grade_data: SubmissionGrade,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Legacy grading endpoint - redirects to manual grading"""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )
    
    if submission.assignment.course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only grade submissions for your own courses"
        )
    
    if grade_data.score > submission.assignment.max_score:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Score cannot exceed maximum score of {submission.assignment.max_score}"
        )
    
    submission.score = grade_data.score
    submission.feedback = grade_data.feedback
    submission.status = SubmissionStatus.GRADED
    submission.graded_at = datetime.utcnow()
    
    db.commit()
    db.refresh(submission)
    
    return submission

@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Delete a submission (before grading)"""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )
    
    if submission.student_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own submissions"
        )
    
    if submission.status == SubmissionStatus.GRADED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a graded submission"
        )
    
    # Delete file from Cloudinary if exists
    if submission.file_url:
        try:
            public_id = submission.file_url.split('/')[-1].split('.')[0]
            cloudinary.uploader.destroy(f"submissions/{submission.assignment_id}/{public_id}")
        except Exception:
            pass  # Continue with deletion even if Cloudinary delete fails
    
    db.delete(submission)
    db.commit()
    
    return None