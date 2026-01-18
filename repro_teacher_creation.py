from app.database import SessionLocal, init_db
from app.schemas import UserCreate, UserRole, CourseCreate, Department, Semester
from app.models import User, Course
from app.utils.password_hash import hash_password

def create_teacher_and_course():
    # Initialize DB tables
    init_db()
    
    db = SessionLocal()
    try:
        print("Creating teacher without department/matric...")
        teacher_username = "teachertest_nodept"
        
        # Check if user already exists and delete
        existing = db.query(User).filter(User.username == teacher_username).first()
        if existing:
            # Delete associated courses first maybe? or let cascade handle it?
            # Manually delete courses if cascade not set (Course.teacher_id)
            db.query(Course).filter(Course.teacher_id == existing.id).delete()
            db.delete(existing)
            db.commit()

        # Create Teacher manually (mimicking route logic)
        hashed_pwd = hash_password("password123")
        new_teacher = User(
            email="teacher_nodept@example.com",
            username=teacher_username,
            full_name="Test Teacher NoDept",
            role=UserRole.TEACHER,
            hashed_password=hashed_pwd,
            matric_number=None,
            department=None
        )

        db.add(new_teacher)
        db.commit()
        db.refresh(new_teacher)
        print(f"Teacher created: ID={new_teacher.id}, Dept={new_teacher.department}, Matric={new_teacher.matric_number}")

        # Now try to create a course with this teacher
        print("Attempting to create a course with this teacher...")
        course_data = CourseCreate(
            title="Introduction to Nothingness",
            course_code="NTH101",
            description="A course about nothing",
            department=Department.CSC, # Course has a department
            semester=Semester.FIRST,
            credits=3,
            schedule="Mon 10am",
            location="Room 101"
        )
        
        # Logic from courses.py create_course
        instructor_name = new_teacher.full_name if new_teacher.full_name else new_teacher.username
        
        new_course = Course(
            title=course_data.title,
            course_code=course_data.course_code,
            description=course_data.description,
            department=course_data.department,
            semester=course_data.semester,
            instructor=instructor_name,
            schedule=course_data.schedule,
            location=course_data.location,
            credits=course_data.credits,
            teacher_id=new_teacher.id
        )
        
        db.add(new_course)
        db.commit()
        db.refresh(new_course)
        print(f"Course created successfully: ID={new_course.id}, Instructor={new_course.instructor}")
        
    except Exception as e:
        print(f"Operation failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    create_teacher_and_course()
