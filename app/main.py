from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routes import (auth, courses, assignments, users, submissions, enrollments, 
                     admin, dashboard, announcements, teacher_dashboard, course_materials, test, warnings, Notifications)
from contextlib import asynccontextmanager
from app.utils.admin import setup_admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
        setup_admin()
        yield
    finally:
        print("shutting down")


app = FastAPI(
    title="Learning Management System API",
    description="A comprehensive LMS backend for teachers and students",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database


# Include routers
app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(assignments.router)
app.include_router(enrollments.router)
app.include_router(submissions.router)
app.include_router(admin.router)
app.include_router(dashboard.router)
app.include_router(teacher_dashboard.router)
app.include_router(users.router)
app.include_router(announcements.router)
app.include_router(course_materials.router)
app.include_router(test.router)
app.include_router(warnings.router)
app.include_router(Notifications.router)

@app.get("/")
def root():
    return {
        "message": "Welcome to the Learning Management System API",
        "docs": "/docs",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)