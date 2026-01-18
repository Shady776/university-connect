from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID  # Add this import
from ..database import get_db
from ..models import Announcement, User
from ..schemas import AnnouncementCreate, AnnouncementUpdate, AnnouncementResponse, AnnouncementDetailResponse
from ..oauth2 import get_current_user

router = APIRouter(prefix="/announcements", tags=["Announcements"])

@router.post("/", response_model=AnnouncementResponse, status_code=status.HTTP_201_CREATED)
def create_announcement(
    announcement_data: AnnouncementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Only teachers and admins can create announcements
    if current_user.role not in ["teacher", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only teachers and admins can create announcements"
        )
    
    new_announcement = Announcement(
        title=announcement_data.title,
        content=announcement_data.content,
        announcement_type=announcement_data.announcement_type,
        author_id=current_user.id
    )
    
    db.add(new_announcement)
    db.commit()
    db.refresh(new_announcement)
    
    return new_announcement

@router.get("/", response_model=List[AnnouncementDetailResponse])
def get_all_announcements(
    skip: int = 0,
    limit: int = 10,
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Announcement)
    
    if active_only:
        query = query.filter(Announcement.is_active == True)
    
    announcements = query.order_by(
        Announcement.created_at.desc()
    ).offset(skip).limit(limit).all()
    
    return announcements

@router.get("/{announcement_id}", response_model=AnnouncementDetailResponse)
def get_announcement(
    announcement_id: str,  # Changed to str
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Convert string to UUID
        uuid_id = UUID(announcement_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid announcement ID format"
        )
    
    announcement = db.query(Announcement).filter(
        Announcement.id == uuid_id
    ).first()
    
    if not announcement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found"
        )
    
    return announcement

@router.put("/{announcement_id}", response_model=AnnouncementResponse)
def update_announcement(
    announcement_id: str,  # Changed to str
    announcement_data: AnnouncementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Convert string to UUID
        uuid_id = UUID(announcement_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid announcement ID format"
        )
    
    announcement = db.query(Announcement).filter(
        Announcement.id == uuid_id
    ).first()
    
    if not announcement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found"
        )
    
    # Only author or admin can update
    if announcement.author_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own announcements"
        )
    
    for field, value in announcement_data.dict(exclude_unset=True).items():
        setattr(announcement, field, value)
    
    db.commit()
    db.refresh(announcement)
    
    return announcement

@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_announcement(
    announcement_id: str,  # Changed to str
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Convert string to UUID
        uuid_id = UUID(announcement_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid announcement ID format"
        )
    
    announcement = db.query(Announcement).filter(
        Announcement.id == uuid_id
    ).first()
    
    if not announcement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found"
        )
    
    # Only author or admin can delete
    if announcement.author_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own announcements"
        )
    
    db.delete(announcement)
    db.commit()
    
    return None