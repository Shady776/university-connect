from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import cloudinary
import cloudinary.uploader
import os
from dotenv import load_dotenv
# import anthropic  # Uncomment for AI grading
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

# Load environment variables
load_dotenv()

router = APIRouter(prefix="/submissions", tags=["Submissions"])

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# # Uncomment for AI grading
# # Configure Anthropic AI
# anthropic_client = anthropic.Anthropic(
#     api_key=os.getenv("ANTHROPIC_API_KEY")
# )

@router.post("/", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
def submit_assignment(
    assignment_id: int = Form(...),
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    # Validate that either content or file is provided
    if not content and not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either content or file must be provided"
        )
    
    # Verify assignment exists
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
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
        Submission.assignment_id == assignment_id,
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
                folder=f"submissions/{assignment_id}",
                resource_type="auto",  # Automatically detect file type
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
        assignment_id=assignment_id,
        student_id=current_user.id,
        content=content,
        file_url=file_url,
        status=submission_status
    )
    
    db.add(new_submission)
    db.commit()
    db.refresh(new_submission)
    
    return new_submission

@router.get("/my-submissions", response_model=List[SubmissionResponse])
def get_my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    submissions = db.query(Submission).filter(Submission.student_id == current_user.id).all()
    return submissions

@router.get("/assignment/{assignment_id}", response_model=List[SubmissionDetailResponse])
def get_assignment_submissions(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
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
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
def update_submission(
    submission_id: int,
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
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
                # Extract public_id from URL and delete
                public_id = submission.file_url.split('/')[-1].split('.')[0]
                cloudinary.uploader.destroy(f"submissions/{submission.assignment_id}/{public_id}")
            
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
    submission_id: int,
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

# # Uncomment for AI grading functionality
# @router.post("/{submission_id}/grade/ai", response_model=SubmissionResponse)
# async def grade_submission_with_ai(
#     submission_id: int,
#     ai_grade_request: SubmissionAIGradeRequest,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_teacher)
# ):
#     """
#     AI-powered auto-grading using Claude
#     Teacher can provide grading rubric and criteria
#     """
#     submission = db.query(Submission).filter(Submission.id == submission_id).first()
#     
#     if not submission:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Submission not found"
#         )
#     
#     if submission.assignment.course.teacher_id != current_user.id:
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="You can only grade submissions for your own courses"
#         )
#     
#     # Prepare content for AI grading
#     submission_content = submission.content or ""
#     if submission.file_url:
#         submission_content += f"\n\nFile URL: {submission.file_url}"
#     
#     # Build AI prompt
#     grading_prompt = f"""
#     You are an expert teacher grading a student assignment. Please evaluate the following submission:
#     
#     Assignment Title: {submission.assignment.title}
#     Assignment Description: {submission.assignment.description}
#     Maximum Score: {submission.assignment.max_score}
#     
#     Student Submission:
#     {submission_content}
#     
#     {f"Grading Rubric: {ai_grade_request.rubric}" if ai_grade_request.rubric else ""}
#     {f"Additional Criteria: {ai_grade_request.criteria}" if ai_grade_request.criteria else ""}
#     
#     Please provide:
#     1. A score out of {submission.assignment.max_score}
#     2. Detailed feedback explaining the grade
#     3. Strengths and areas for improvement
#     
#     Format your response as:
#     SCORE: [numerical score]
#     FEEDBACK: [detailed feedback]
#     """
#     
#     try:
#         # Call Claude AI for grading
#         message = anthropic_client.messages.create(
#             model="claude-sonnet-4-20250514",
#             max_tokens=1500,
#             messages=[
#                 {"role": "user", "content": grading_prompt}
#             ]
#         )
#         
#         ai_response = message.content[0].text
#         
#         # Parse AI response
#         score_line = [line for line in ai_response.split('\n') if line.startswith('SCORE:')]
#         feedback_start = ai_response.find('FEEDBACK:')
#         
#         if score_line and feedback_start != -1:
#             score_str = score_line[0].replace('SCORE:', '').strip()
#             try:
#                 ai_score = float(score_str)
#                 # Ensure score doesn't exceed max
#                 ai_score = min(ai_score, submission.assignment.max_score)
#             except ValueError:
#                 raise HTTPException(
#                     status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                     detail="AI grading failed to parse score"
#                 )
#             
#             ai_feedback = ai_response[feedback_start + 9:].strip()
#             
#             # Update submission with AI grade
#             submission.score = ai_score
#             submission.feedback = f"[AI GRADED]\n\n{ai_feedback}"
#             submission.status = SubmissionStatus.GRADED
#             submission.graded_at = datetime.utcnow()
#             
#             db.commit()
#             db.refresh(submission)
#             
#             return submission
#         else:
#             raise HTTPException(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 detail="AI grading response format error"
#             )
#             
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"AI grading failed: {str(e)}"
#         )

# Legacy endpoint for backward compatibility
@router.post("/{submission_id}/grade", response_model=SubmissionResponse)
def grade_submission(
    submission_id: int,
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
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
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