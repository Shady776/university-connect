from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func
from typing import List
from uuid import UUID
from datetime import datetime, timezone, timedelta
import json
import random

from ..database import get_db
from ..models import (
    Test, TestQuestion, TestAttempt, TestAnswer, Course,
    Enrollment, User, UserRole, TestStatus, QuestionType,
    TestAttemptStatus, NotificationType,
)
from ..schemas import (
    TestCreate, TestUpdate, TestResponse, TestDetailResponse,
    TestAttemptStart, TestAttemptSubmit, TestAttemptResponse,
    TestAttemptDetailResponse, TestAttemptWithQuestionsResponse,
    TestQuestionResponse, TestQuestionWithAnswerResponse,
    TestAttemptGrade, TestStatistics, StudentTestAttemptInfo,
    TheoryAnswerGrade,
    TestAnswerWithQuestionResponse,
    TestQuestionInAnswer,
)
from ..oauth2 import get_current_user, get_current_teacher, get_current_student
from .Notifications import fan_out, get_enrolled_student_ids

router = APIRouter(prefix="/tests", tags=["Tests"])


def make_aware(dt):
    """Convert naive datetime to timezone-aware UTC datetime"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ===== TEACHER ENDPOINTS =====

@router.post("/", response_model=TestResponse, status_code=status.HTTP_201_CREATED)
def create_test(
    test_data: TestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Teacher creates a new test for their course (starts as DRAFT — no notification yet)."""
    course = db.query(Course).filter(Course.id == str(test_data.course_id)).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    if course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only create tests for your own courses")

    new_test = Test(
        course_id=str(test_data.course_id),
        title=test_data.title,
        description=test_data.description,
        test_type=test_data.test_type,
        duration_minutes=test_data.duration_minutes,
        total_marks=test_data.total_marks,
        randomize_questions=test_data.randomize_questions,
        randomize_options=test_data.randomize_options,
        start_time=test_data.start_time,
        end_time=test_data.end_time,
        status=TestStatus.DRAFT,
        created_by=current_user.id
    )

    db.add(new_test)
    db.flush()

    for idx, question_data in enumerate(test_data.questions):
        question = TestQuestion(
            test_id=new_test.id,
            question_type=question_data.question_type,
            question_text=question_data.question_text,
            marks=question_data.marks,
            order_index=idx,
            options=json.dumps(question_data.options) if question_data.options else None,
            correct_answer=question_data.correct_answer,
            acceptable_answers=json.dumps(question_data.acceptable_answers) if question_data.acceptable_answers else None
        )
        db.add(question)

    db.commit()
    db.refresh(new_test)

    test_response = TestResponse.model_validate(new_test)
    test_response.question_count = len(test_data.questions)

    return test_response


@router.get("/course/{course_id}", response_model=List[TestResponse])
def get_course_tests(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all tests for a specific course"""
    course = db.query(Course).filter(Course.id == str(course_id)).first()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    if current_user.role == UserRole.TEACHER and course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view tests for your own courses")

    if current_user.role == UserRole.STUDENT:
        enrollment = db.query(Enrollment).filter(
            and_(
                Enrollment.student_id == current_user.id,
                Enrollment.course_id == str(course_id)
            )
        ).first()
        if not enrollment:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You must be enrolled in this course")

    tests = db.query(Test).filter(Test.course_id == str(course_id)).all()

    result = []
    for test in tests:
        test_response = TestResponse.model_validate(test)
        test_response.question_count = len(test.questions)
        result.append(test_response)

    return result


# ── Static-segment routes (must come before /{test_id}) ──────────────────────

@router.get("/my-attempts/course/{course_id}", response_model=List[TestAttemptResponse])
def get_my_test_attempts(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Get student's test attempts for a course"""
    attempts = db.query(TestAttempt).join(Test).filter(
        and_(
            Test.course_id == str(course_id),
            TestAttempt.student_id == current_user.id
        )
    ).all()

    return attempts


@router.get("/attempt/{attempt_id}", response_model=TestAttemptDetailResponse)
def get_attempt_detail(
    attempt_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detailed test attempt with answers and questions"""
    attempt = db.query(TestAttempt).options(
        joinedload(TestAttempt.test),
        joinedload(TestAttempt.student),
        joinedload(TestAttempt.answers).joinedload(TestAnswer.question)
    ).filter(TestAttempt.id == str(attempt_id)).first()

    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test attempt not found")

    if current_user.role == UserRole.STUDENT and attempt.student_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view your own attempts")

    if current_user.role == UserRole.TEACHER:
        test = db.query(Test).join(Course).filter(Test.id == attempt.test_id).first()
        if test.course.teacher_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view attempts for your courses")

    return TestAttemptDetailResponse.from_orm_custom(attempt)


@router.post("/attempt/{attempt_id}/grade", response_model=TestAttemptDetailResponse)
def grade_theory_answers(
    attempt_id: UUID,
    grading: TestAttemptGrade,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Grade theory answers for a test attempt"""
    attempt = db.query(TestAttempt).options(
        joinedload(TestAttempt.test),
        joinedload(TestAttempt.answers)
    ).filter(TestAttempt.id == str(attempt_id)).first()

    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test attempt not found")

    test = db.query(Test).join(Course).filter(Test.id == attempt.test_id).first()
    if test.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only grade attempts for your courses")

    for grade in grading.grades:
        answer = db.query(TestAnswer).filter(TestAnswer.id == str(grade.answer_id)).first()
        if answer and answer.attempt_id == str(attempt_id):
            answer.marks_obtained = grade.marks_obtained
            answer.teacher_feedback = grade.feedback
            answer.is_correct = grade.marks_obtained > 0

    total_score = sum(
        answer.marks_obtained for answer in attempt.answers
        if answer.marks_obtained is not None
    )

    attempt.score = total_score
    attempt.status = TestAttemptStatus.GRADED
    attempt.graded_at = datetime.now(timezone.utc)

    # ── Notification hook: notify student their theory test has been graded ───
    percentage = round((total_score / test.total_marks) * 100, 1) if test.total_marks else 0
    fan_out(
        db,
        student_ids=[attempt.student_id],
        type=NotificationType.ASSIGNMENT_GRADED,   # reuse GRADED type — covers tests too
        title=f'"{test.title}" has been graded',
        message=(
            f"Your submission for {test.title} has been graded. "
            f"You scored {total_score}/{test.total_marks} ({percentage}%)."
        ),
        test_id=str(attempt.test_id),
        course_id=test.course_id,
    )
    # ─────────────────────────────────────────────────────────────────────────

    db.commit()
    db.refresh(attempt)

    attempt_with_relations = db.query(TestAttempt).options(
        joinedload(TestAttempt.test),
        joinedload(TestAttempt.student),
        joinedload(TestAttempt.answers).joinedload(TestAnswer.question)
    ).filter(TestAttempt.id == attempt.id).first()

    return TestAttemptDetailResponse.from_orm_custom(attempt_with_relations)


# ── Dynamic /{test_id} routes (must come last) ────────────────────────────────

@router.get("/{test_id}", response_model=TestDetailResponse)
def get_test_detail(
    test_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Get test details with all questions (Teacher only)"""
    test = db.query(Test).options(
        joinedload(Test.course),
        joinedload(Test.creator),
        joinedload(Test.questions)
    ).filter(Test.id == str(test_id)).first()

    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")

    if test.course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only view tests for your own courses")

    questions_with_answers = [
        TestQuestionWithAnswerResponse.from_orm_custom(q)
        for q in sorted(test.questions, key=lambda x: x.order_index)
    ]

    return TestDetailResponse(
        **TestResponse.model_validate(test).model_dump(),
        course=test.course,
        creator=test.creator,
        questions=questions_with_answers
    )


@router.put("/{test_id}", response_model=TestResponse)
def update_test_full(
    test_id: UUID,
    test_data: TestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Fully update a test including questions (replaces existing questions)"""
    test = db.query(Test).filter(Test.id == str(test_id)).first()

    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")

    course = db.query(Course).filter(Course.id == test.course_id).first()
    if course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update tests for your own courses")

    has_attempts = db.query(TestAttempt).filter(TestAttempt.test_id == str(test_id)).first()
    if has_attempts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot fully update a test that has student attempts")

    test.title = test_data.title
    test.description = test_data.description
    test.test_type = test_data.test_type
    test.duration_minutes = test_data.duration_minutes
    test.total_marks = test_data.total_marks
    test.randomize_questions = test_data.randomize_questions
    test.randomize_options = test_data.randomize_options
    test.start_time = test_data.start_time
    test.end_time = test_data.end_time

    db.query(TestQuestion).filter(TestQuestion.test_id == str(test_id)).delete()

    for idx, question_data in enumerate(test_data.questions):
        question = TestQuestion(
            test_id=test.id,
            question_type=question_data.question_type,
            question_text=question_data.question_text,
            marks=question_data.marks,
            order_index=idx,
            options=json.dumps(question_data.options) if question_data.options else None,
            correct_answer=question_data.correct_answer,
            acceptable_answers=json.dumps(question_data.acceptable_answers) if question_data.acceptable_answers else None
        )
        db.add(question)

    db.commit()
    db.refresh(test)

    test_response = TestResponse.model_validate(test)
    test_response.question_count = len(test_data.questions)

    return test_response


@router.patch("/{test_id}", response_model=TestResponse)
def update_test(
    test_id: UUID,
    test_data: TestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Partially update test details (does not modify questions).
    When status changes to ACTIVE, enrolled students are notified.
    """
    test = db.query(Test).filter(Test.id == str(test_id)).first()

    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")

    course = db.query(Course).filter(Course.id == test.course_id).first()
    if course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update tests for your own courses")

    old_status = test.status
    update_data = test_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(test, field, value)

    # ── Notification hook: fire when teacher flips status → ACTIVE ────────────
    new_status = update_data.get("status")
    activating = (
        new_status == TestStatus.ACTIVE
        and old_status != TestStatus.ACTIVE
    )
    if activating:
        student_ids = get_enrolled_student_ids(db, test.course_id)
        duration_msg = f"{test.duration_minutes} min" if test.duration_minutes else "timed"
        start_msg = ""
        if test.start_time:
            aware_start = make_aware(test.start_time)
            start_msg = f" It opens at {aware_start.strftime('%b %d, %H:%M')} UTC."
        fan_out(
            db,
            student_ids=student_ids,
            type=NotificationType.TEST_ACTIVATED,
            title=f'New test available: "{test.title}"',
            message=(
                f'A {duration_msg} test "{test.title}" is now available '
                f"in {course.course_code or course.title}.{start_msg}"
            ),
            test_id=str(test.id),
            course_id=test.course_id,
        )
    # ─────────────────────────────────────────────────────────────────────────

    db.commit()
    db.refresh(test)

    test_response = TestResponse.model_validate(test)
    test_response.question_count = len(test.questions)

    return test_response


@router.delete("/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test(
    test_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """Delete a test"""
    test = db.query(Test).filter(Test.id == str(test_id)).first()

    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")

    course = db.query(Course).filter(Course.id == test.course_id).first()
    if course.teacher_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete tests for your own courses")

    db.delete(test)
    db.commit()

    return None


@router.post("/{test_id}/start", response_model=TestAttemptWithQuestionsResponse)
def start_test(
    test_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Student starts a test attempt"""
    test = db.query(Test).options(
        joinedload(Test.questions)
    ).filter(Test.id == str(test_id)).first()

    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")

    enrollment = db.query(Enrollment).filter(
        and_(
            Enrollment.student_id == current_user.id,
            Enrollment.course_id == test.course_id
        )
    ).first()

    if not enrollment:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You must be enrolled in the course to take this test")

    existing_attempt = db.query(TestAttempt).filter(
        and_(
            TestAttempt.test_id == str(test_id),
            TestAttempt.student_id == current_user.id
        )
    ).first()

    if existing_attempt:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already attempted this test")

    if test.status != TestStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Test is not active")

    now = datetime.now(timezone.utc)
    start_time = make_aware(test.start_time)
    end_time = make_aware(test.end_time)

    if start_time and now < start_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Test has not started yet")

    if end_time and now > end_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Test has expired")

    new_attempt = TestAttempt(
        test_id=str(test_id),
        student_id=str(current_user.id),
        status=TestAttemptStatus.IN_PROGRESS,
        total_marks=test.total_marks,
        started_at=now
    )

    db.add(new_attempt)
    db.commit()
    db.refresh(new_attempt)

    questions = list(test.questions)
    if test.randomize_questions:
        random.shuffle(questions)

    student_questions = []
    for question in questions:
        q_data = TestQuestionResponse.from_orm_custom(question)
        if test.randomize_options and question.question_type == QuestionType.MULTIPLE_CHOICE and q_data.options:
            random.shuffle(q_data.options)
        student_questions.append(q_data)

    return TestAttemptWithQuestionsResponse(
        **TestAttemptResponse.model_validate(new_attempt).model_dump(),
        questions=student_questions,
        time_remaining_minutes=test.duration_minutes
    )


@router.post("/{test_id}/submit", response_model=TestAttemptDetailResponse)
def submit_test(
    test_id: UUID,
    submission: TestAttemptSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_student)
):
    """Student submits test answers"""
    attempt = db.query(TestAttempt).filter(
        and_(
            TestAttempt.test_id == str(test_id),
            TestAttempt.student_id == current_user.id,
            TestAttempt.status == TestAttemptStatus.IN_PROGRESS
        )
    ).first()

    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active test attempt found")

    test = db.query(Test).options(
        joinedload(Test.questions)
    ).filter(Test.id == str(test_id)).first()

    now = datetime.now(timezone.utc)
    started_at = make_aware(attempt.started_at)
    time_taken = int((now - started_at).total_seconds() / 60)

    if submission.invalidated:
        attempt.status = TestAttemptStatus.INVALIDATED
        attempt.score = 0
        attempt.submitted_at = now
        attempt.time_taken_minutes = time_taken
        attempt.invalidation_reason = submission.invalidation_reason

        for answer_data in submission.answers:
            question = db.query(TestQuestion).filter(
                TestQuestion.id == str(answer_data.question_id)
            ).first()

            if not question or question.test_id != str(test_id):
                continue

            test_answer = TestAnswer(
                attempt_id=attempt.id,
                question_id=str(answer_data.question_id),
                answer_text=answer_data.answer_text,
                is_correct=False,
                marks_obtained=0.0
            )
            db.add(test_answer)

        db.commit()
        db.refresh(attempt)

        attempt = db.query(TestAttempt).options(
            joinedload(TestAttempt.answers).joinedload(TestAnswer.question)
        ).filter(TestAttempt.id == attempt.id).first()

        return TestAttemptDetailResponse.from_orm_custom(attempt)

    if time_taken > test.duration_minutes:
        attempt.status = TestAttemptStatus.EXPIRED
        attempt.score = 0
        attempt.submitted_at = now
        attempt.time_taken_minutes = time_taken
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Test time has expired")

    total_score = 0.0
    has_theory_questions = False

    for answer_data in submission.answers:
        question = db.query(TestQuestion).filter(
            TestQuestion.id == str(answer_data.question_id)
        ).first()

        if not question or question.test_id != str(test_id):
            continue

        test_answer = TestAnswer(
            attempt_id=attempt.id,
            question_id=str(answer_data.question_id),
            answer_text=answer_data.answer_text
        )

        if question.question_type == QuestionType.MULTIPLE_CHOICE:
            student_answer = (answer_data.answer_text or '').strip().lower()
            correct_answer = (question.correct_answer or '').strip().lower()
            is_correct = student_answer == correct_answer and student_answer != ''
            test_answer.is_correct = is_correct
            test_answer.marks_obtained = question.marks if is_correct else 0.0
            total_score += test_answer.marks_obtained

        elif question.question_type == QuestionType.FILL_IN_BLANK:
            acceptable_answers = json.loads(question.acceptable_answers) if question.acceptable_answers else []
            if question.correct_answer:
                acceptable_answers.append(question.correct_answer)

            student_answer = (answer_data.answer_text or '').strip().lower()
            is_correct = any(
                student_answer == acceptable.strip().lower()
                for acceptable in acceptable_answers
            ) and student_answer != ''
            test_answer.is_correct = is_correct
            test_answer.marks_obtained = question.marks if is_correct else 0.0
            total_score += test_answer.marks_obtained

        elif question.question_type == QuestionType.THEORY:
            test_answer.is_correct = None
            test_answer.marks_obtained = None
            has_theory_questions = True

        db.add(test_answer)

    attempt.submitted_at = now
    attempt.time_taken_minutes = time_taken

    if has_theory_questions:
        attempt.status = TestAttemptStatus.SUBMITTED
        attempt.score = None
    else:
        # ── Notification hook: auto-graded (no theory) — notify immediately ──
        attempt.status = TestAttemptStatus.GRADED
        attempt.score = total_score
        attempt.graded_at = now
        percentage = round((total_score / test.total_marks) * 100, 1) if test.total_marks else 0
        fan_out(
            db,
            student_ids=[str(current_user.id)],
            type=NotificationType.ASSIGNMENT_GRADED,
            title=f'"{test.title}" results are ready',
            message=(
                f"Your {test.title} has been auto-graded. "
                f"You scored {total_score}/{test.total_marks} ({percentage}%)."
            ),
            test_id=str(test_id),
            course_id=test.course_id,
        )
        # ─────────────────────────────────────────────────────────────────────

    db.commit()
    db.refresh(attempt)

    attempt = db.query(TestAttempt).options(
        joinedload(TestAttempt.answers).joinedload(TestAnswer.question)
    ).filter(TestAttempt.id == attempt.id).first()

    return TestAttemptDetailResponse.from_orm_custom(attempt)


# ===== STATISTICS ENDPOINTS =====

@router.get("/{test_id}/statistics", response_model=TestStatistics)
def get_test_statistics(
    test_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get test statistics including enrolled vs attempted students"""
    test = db.query(Test).filter(Test.id == str(test_id)).first()

    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")

    course = db.query(Course).filter(Course.id == test.course_id).first()
    if current_user.role == UserRole.TEACHER and course.teacher_id != current_user.id:
            raise HTTPException(403, "You can only view statistics for your courses")

    total_enrolled = db.query(func.count(Enrollment.id)).filter(
        Enrollment.course_id == test.course_id
    ).scalar()

    attempts = db.query(TestAttempt).filter(TestAttempt.test_id == str(test_id)).all()

    total_attempted = len(attempts)
    total_completed = len([a for a in attempts if a.status in [TestAttemptStatus.SUBMITTED, TestAttemptStatus.GRADED]])
    total_in_progress = len([a for a in attempts if a.status == TestAttemptStatus.IN_PROGRESS])
    graded_attempts = [a for a in attempts if a.status == TestAttemptStatus.GRADED and a.score is not None]

    average_score = None
    highest_score = None
    lowest_score = None

    if graded_attempts:
        scores = [a.score for a in graded_attempts]
        average_score = sum(scores) / len(scores)
        highest_score = max(scores)
        lowest_score = min(scores)

    return TestStatistics(
        test_id=test_id,
        test_title=test.title,
        total_enrolled=total_enrolled,
        total_attempted=total_attempted,
        total_not_attempted=total_enrolled - total_attempted,
        total_completed=total_completed,
        total_in_progress=total_in_progress,
        average_score=average_score,
        highest_score=highest_score,
        lowest_score=lowest_score
    )


@router.get("/{test_id}/students-status", response_model=List[StudentTestAttemptInfo])
def get_students_test_status(
    test_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of enrolled students and their test attempt status"""
    test = db.query(Test).filter(Test.id == str(test_id)).first()

    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test not found")

    course = db.query(Course).filter(Course.id == test.course_id).first()
    if current_user.role == UserRole.TEACHER and course.teacher_id != current_user.id:
            raise HTTPException(403, "You can only view statistics for your courses")

    enrollments = db.query(Enrollment).options(
        joinedload(Enrollment.student)
    ).filter(Enrollment.course_id == test.course_id).all()

    attempts = db.query(TestAttempt).filter(TestAttempt.test_id == str(test_id)).all()
    attempts_dict = {attempt.student_id: attempt for attempt in attempts}

    result = []
    for enrollment in enrollments:
        student = enrollment.student
        attempt = attempts_dict.get(student.id)

        result.append(StudentTestAttemptInfo(
            student_id=student.id,
            student_name=student.full_name,
            student_username=student.username,
            matric_number=student.matric_number,
            department=student.department,
            has_attempted=attempt is not None,
            attempt_id=attempt.id if attempt else None,
            attempt_status=attempt.status if attempt else None,
            score=attempt.score if attempt else None,
            submitted_at=attempt.submitted_at if attempt else None
        ))

    return result