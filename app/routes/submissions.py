from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import datetime, timezone
from uuid import UUID
import cloudinary
import cloudinary.uploader
import os
from dotenv import load_dotenv
from ..database import get_db
from ..models import Submission, Assignment, User, Enrollment, SubmissionStatus, NotificationType
from ..schemas import (
    SubmissionResponse,
    SubmissionDetailResponse,
    SubmissionManualGrade,
    SubmissionGrade,
    SubmissionAIGradeRequest
)
from ..oauth2 import get_current_user, get_current_student, get_current_teacher
from ..services.ai_grading_service import AIGradingService
from ..utils.file_validation import validate_upload_file
from ..utils.file_extraction import extract_gradable_text, fetch_file_bytes, ExtractionError, TEXT_EXTENSIONS
from .Notifications import fan_out

load_dotenv()

router = APIRouter(prefix="/submissions", tags=["Submissions"])

# Submissions can be documents, archives, images of handwritten work, or
# source code — TEXT_EXTENSIONS covers the code/text formats AI grading
# knows how to read (kept in file_extraction.py as the single source of
# truth so the two stay in sync).
SUBMISSION_ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'ppt', 'pptx', 'zip', 'rar',
    'png', 'jpg', 'jpeg'
} | TEXT_EXTENSIONS

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)


# ── Internal helper — builds the graded notification for a single submission ──

def _notify_graded(db, submission: Submission) -> None:
    """Call just before db.commit() in any grade endpoint."""
    assignment = submission.assignment
    fan_out(
        db,
        student_ids=[str(submission.student_id)],
        type=NotificationType.ASSIGNMENT_GRADED,
        title=f"Assignment graded — {assignment.course.course_code}",
        message=(
            f'Your submission for "{assignment.title}" has been graded. '
            f'You scored {submission.score}/{assignment.max_score}. Tap to view your feedback.'
        ),
        assignment_id=str(assignment.id),
        course_id=str(assignment.course_id),
    )


# ── POST / ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
async def submit_assignment(
    assignment_id: str = Form(...),
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Submit an assignment with either text content or file upload."""
    try:
        assignment_uuid = UUID(assignment_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assignment ID format")

    if not content and not file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either content or file must be provided")

    assignment = db.query(Assignment).filter(Assignment.id == str(assignment_uuid)).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.course_id == assignment.course_id
    ).first()
    if not enrollment:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not enrolled in this course")

    existing = db.query(Submission).filter(
        Submission.assignment_id == str(assignment_uuid),
        Submission.student_id == current_user.id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already submitted this assignment. Use update endpoint to modify.")

    file_url = None
    if file:
        validate_upload_file(file, allowed_extensions=SUBMISSION_ALLOWED_EXTENSIONS, max_size_bytes=50 * 1024 * 1024)
        try:
            upload_result = cloudinary.uploader.upload(
                file.file,
                folder=f"submissions/{assignment_uuid}",
                resource_type="auto",
                public_id=f"{current_user.id}_{datetime.utcnow().timestamp()}"
            )
            file_url = upload_result.get("secure_url")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to upload file: {str(e)}")

    submission_status = SubmissionStatus.SUBMITTED
    if assignment.due_date and datetime.now(timezone.utc) > assignment.due_date:
        submission_status = SubmissionStatus.LATE

    new_submission = Submission(
        assignment_id=str(assignment_uuid),
        student_id=str(current_user.id),
        content=content,
        file_url=file_url,
        status=submission_status
    )
    db.add(new_submission)
    db.commit()
    db.refresh(new_submission)
    return new_submission


# ── Static-segment GET routes (must come before /{submission_id}) ─────────────

@router.get("/my-submissions", response_model=List[SubmissionDetailResponse])
def get_my_submissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Get all submissions for the current student with full assignment details."""
    return db.query(Submission).options(
        joinedload(Submission.assignment).joinedload(Assignment.course),
        joinedload(Submission.student)
    ).filter(Submission.student_id == current_user.id).all()


@router.get("/assignment/{assignment_id}", response_model=List[SubmissionDetailResponse])
def get_assignment_submissions(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Get all submissions for an assignment (teacher only)."""
    assignment = db.query(Assignment).filter(Assignment.id == str(assignment_id)).first()
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    if assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view submissions for your own courses")

    return db.query(Submission).filter(Submission.assignment_id == str(assignment_id)).all()


@router.get("/student/{student_id}/course/{course_id}", response_model=List[SubmissionDetailResponse])
def get_student_course_submissions(
    student_id: UUID,
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    from ..models import Course
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only view submissions for your own courses")

    return db.query(Submission).options(
        joinedload(Submission.assignment),
        joinedload(Submission.student)
    ).join(Assignment).filter(
        Submission.student_id == str(student_id),
        Assignment.course_id == str(course_id)
    ).all()


# ── Dynamic /{submission_id} routes (must come last) ──────────────────────────

@router.get("/{submission_id}", response_model=SubmissionDetailResponse)
def get_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if current_user.role == "student":
        if submission.student_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own submissions")
    else:
        if submission.assignment.course.teacher_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view submissions for your own courses")

    return submission


@router.put("/{submission_id}", response_model=SubmissionResponse)
async def update_submission(
    submission_id: UUID,
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Update a submission (before grading)."""
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own submissions")

    if submission.status == SubmissionStatus.GRADED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot update a graded submission")

    if content is not None:
        submission.content = content

    if file:
        validate_upload_file(file, allowed_extensions=SUBMISSION_ALLOWED_EXTENSIONS, max_size_bytes=50 * 1024 * 1024)
        try:
            if submission.file_url:
                try:
                    public_id = submission.file_url.split('/')[-1].split('.')[0]
                    cloudinary.uploader.destroy(f"submissions/{submission.assignment_id}/{public_id}")
                except Exception:
                    pass
            upload_result = cloudinary.uploader.upload(
                file.file,
                folder=f"submissions/{submission.assignment_id}",
                resource_type="auto",
                public_id=f"{current_user.id}_{datetime.utcnow().timestamp()}"
            )
            submission.file_url = upload_result.get("secure_url")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to upload file: {str(e)}")

    submission.submitted_at = datetime.utcnow()
    db.commit()
    db.refresh(submission)
    return submission


@router.post("/{submission_id}/grade/ai", response_model=SubmissionResponse)
async def grade_submission_with_ai(
    submission_id: UUID,
    grade_request: SubmissionAIGradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only grade submissions for your own courses")

    if not submission.content and not submission.file_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This submission has no content or file to grade")

    criteria = grade_request.criteria
    if not criteria:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please provide grading criteria for AI grading")

    # Prefer plain text content if present; otherwise pull text out of
    # whatever file the student uploaded (code, PDF, DOCX, or a ZIP project).
    if submission.content:
        gradable_text = submission.content
    else:
        try:
            file_bytes = await fetch_file_bytes(submission.file_url)
            filename = submission.file_url.rsplit("/", 1)[-1]
            gradable_text = extract_gradable_text(file_bytes, filename)
        except ExtractionError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not retrieve the submitted file: {e}")

    try:
        ai_service     = AIGradingService()
        assignment     = submission.assignment
        grading_result = await ai_service.grade_submission(
            submission_content=gradable_text,
            assignment_title=assignment.title,
            assignment_description=assignment.description or "",
            max_score=assignment.max_score,
            criteria=criteria
        )

        submission.score     = grading_result.score
        submission.feedback  = grading_result.feedback
        submission.status    = SubmissionStatus.GRADED
        submission.graded_at = datetime.utcnow()

        # ── TRIGGER 3 (AI single): Notify student ────────────────────────────
        _notify_graded(db, submission)

        db.commit()
        db.refresh(submission)
        return submission

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"AI grading failed: {str(e)}")


@router.post("/{submission_id}/grade/manual", response_model=SubmissionResponse)
def grade_submission_manually(
    submission_id: UUID,
    grade_data: SubmissionManualGrade,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Manual grading by teacher with percentage or direct score."""
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only grade submissions for your own courses")

    if grade_data.percentage is not None:
        if not 0 <= grade_data.percentage <= 100:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Percentage must be between 0 and 100")
        calculated_score = (grade_data.percentage / 100) * submission.assignment.max_score
    elif grade_data.score is not None:
        if grade_data.score > submission.assignment.max_score:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Score cannot exceed maximum score of {submission.assignment.max_score}")
        calculated_score = grade_data.score
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either percentage or score must be provided")

    submission.score     = calculated_score
    submission.feedback  = grade_data.feedback
    submission.status    = SubmissionStatus.GRADED
    submission.graded_at = datetime.utcnow()

    # ── TRIGGER 3 (manual): Notify student ───────────────────────────────────
    _notify_graded(db, submission)

    db.commit()
    db.refresh(submission)
    return submission


@router.post("/{submission_id}/grade", response_model=SubmissionResponse)
def grade_submission(
    submission_id: UUID,
    grade_data: SubmissionGrade,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Legacy grading endpoint."""
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.assignment.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only grade submissions for your own courses")

    if grade_data.score > submission.assignment.max_score:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Score cannot exceed maximum score of {submission.assignment.max_score}")

    submission.score     = grade_data.score
    submission.feedback  = grade_data.feedback
    submission.status    = SubmissionStatus.GRADED
    submission.graded_at = datetime.utcnow()

    # ── TRIGGER 3 (legacy): Notify student ───────────────────────────────────
    _notify_graded(db, submission)

    db.commit()
    db.refresh(submission)
    return submission


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Delete a submission (before grading)."""
    submission = db.query(Submission).filter(Submission.id == str(submission_id)).first()
    if not submission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    if submission.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own submissions")

    if submission.status == SubmissionStatus.GRADED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete a graded submission")

    if submission.file_url:
        try:
            public_id = submission.file_url.split('/')[-1].split('.')[0]
            cloudinary.uploader.destroy(f"submissions/{submission.assignment_id}/{public_id}")
        except Exception:
            pass

    db.delete(submission)
    db.commit()
    return None