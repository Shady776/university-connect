# routers/course_materials.py
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import cloudinary.uploader
import requests
from io import BytesIO
from ..database import get_db
from ..models import CourseMaterial, Course, User
from ..schemas import CourseMaterialResponse, CourseMaterialDetailResponse
from ..oauth2 import get_current_user, get_current_teacher
from app.config import CONFIG

router = APIRouter(prefix="/course-materials", tags=["Course Materials"])

cloudinary.config(
    cloud_name=CONFIG.CLOUDINARY_CLOUD_NAME,
    api_key=CONFIG.CLOUDINARY_API_KEY,
    api_secret=CONFIG.CLOUDINARY_API_SECRET
)

@router.post("/", response_model=CourseMaterialResponse, status_code=status.HTTP_201_CREATED)
async def upload_course_material(
    course_id: UUID = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Upload course material. Only the course teacher can upload materials.
    """
    # Verify course exists and user is the teacher
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    if course.teacher_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only upload materials to your own courses"
        )
    
    # Validate file type
    allowed_extensions = ['pdf', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'zip', 'rar']
    file_extension = file.filename.split('.')[-1].lower()
    
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed types: {', '.join(allowed_extensions)}"
        )
    
    try:
        # Upload to Cloudinary with public access
        result = cloudinary.uploader.upload(
            file.file,
            folder=f"course_materials/{course_id}",
            resource_type="raw",
            type="upload",  # This makes it public
            access_mode="public",  # Explicitly set public access
            public_id=f"{title.replace(' ', '_')}_{file.filename}"
        )
        
        # Create database record
        new_material = CourseMaterial(
            course_id=course_id,
            title=title,
            description=description,
            file_url=result['secure_url'],
            file_type=file_extension,
            file_size=result.get('bytes'),
            uploaded_by=current_user.id
        )
        
        db.add(new_material)
        db.commit()
        db.refresh(new_material)
        
        return new_material
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )

@router.get("/course/{course_id}", response_model=List[CourseMaterialResponse])
def get_course_materials(
    course_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all materials for a course. Accessible by enrolled students and the course teacher.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    materials = db.query(CourseMaterial).filter(
        CourseMaterial.course_id == course_id,
        CourseMaterial.is_active == True
    ).order_by(CourseMaterial.uploaded_at.desc()).all()
    
    return materials

@router.get("/{material_id}", response_model=CourseMaterialDetailResponse)
def get_material_detail(
    material_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed information about a specific material.
    """
    material = db.query(CourseMaterial).filter(CourseMaterial.id == material_id).first()
    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Material not found"
        )
    
    return material

# routers/course_materials.py - Fixed download endpoint

@router.get("/{material_id}/download")
async def download_material(
    material_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Download a course material file by streaming from Cloudinary.
    """
    material = db.query(CourseMaterial).filter(CourseMaterial.id == material_id).first()
    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Material not found"
        )
    
    # Verify user has access to this course
    course = db.query(Course).filter(Course.id == material.course_id).first()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )
    
    try:
        # Fetch file from Cloudinary
        response = requests.get(material.file_url, stream=True, timeout=60)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch file from storage. Status: {response.status_code}"
            )
        
        # Map file extensions to MIME types
        content_types = {
            'pdf': 'application/pdf',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'ppt': 'application/vnd.ms-powerpoint',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'txt': 'text/plain',
            'zip': 'application/zip',
            'rar': 'application/x-rar-compressed'
        }
        
        content_type = content_types.get(material.file_type.lower(), 'application/octet-stream')
        
        # Create safe filename
        safe_filename = f"{material.title.replace(' ', '_').replace('/', '_')}.{material.file_type}"
        
        # Stream the response
        def iterfile():
            try:
                for chunk in response.iter_content(chunk_size=65536):  # 64KB chunks
                    if chunk:
                        yield chunk
            finally:
                response.close()
        
        return StreamingResponse(
            iterfile(),
            media_type=content_type,
            headers={
                'Content-Disposition': f'attachment; filename="{safe_filename}"',
                'Content-Type': content_type,
                'Cache-Control': 'no-cache',
            }
        )
        
    except requests.Timeout:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Request to storage timed out"
        )
    except requests.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch file from storage: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Download failed: {str(e)}"
        )

@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material(
    material_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_teacher)
):
    """
    Delete a course material. Only the uploader can delete it.
    """
    material = db.query(CourseMaterial).filter(CourseMaterial.id == material_id).first()
    
    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Material not found"
        )
    
    if material.uploaded_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own uploaded materials"
        )
    
    try:
        # Delete from Cloudinary
        public_id = material.file_url.split('/')[-1].split('.')[0]
        cloudinary.uploader.destroy(public_id, resource_type="raw")
        
        # Delete from database
        db.delete(material)
        db.commit()
        
        return None
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete material: {str(e)}"
        )