from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routes import auth, courses, assignments, submissions, enrollments

app = FastAPI(
    title="Learning Management System API",
    description="A comprehensive LMS backend for teachers and students",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
@app.on_event("startup")
def on_startup():
    init_db()

# Include routers
app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(assignments.router)
app.include_router(enrollments.router)
app.include_router(submissions.router)

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