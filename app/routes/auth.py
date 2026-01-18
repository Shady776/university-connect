from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..schemas import UserCreate, UserResponse, UserLogin, Token
from ..oauth2 import create_access_token
from ..utils.password_hash import hash_password, verify_password
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(prefix="/auth", tags=["Authentication"])


def authenticate_user(db: Session, username: str, password: str):
    """Authenticate a user by username and password"""
    # Convert username to lowercase for case-insensitive lookup
    username_lower = username.lower().strip()
    user = db.query(User).filter(User.username == username_lower).first()
    
    if not user:
        return False
    
    if not verify_password(password, user.hashed_password):
        return False
    
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    # Convert username to lowercase and strip whitespace
    username_lower = user_data.username.lower().strip()
    
    # Validate username is not empty after stripping
    if not username_lower:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username cannot be empty"
        )
    
    # Check if user exists (check with lowercase username)
    existing_user = db.query(User).filter(
        (User.email == user_data.email) | (User.username == username_lower)
    ).first()
    
    if existing_user:
        if existing_user.username == username_lower:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
    
    # Create new user with lowercase username
    hashed_pwd = hash_password(user_data.password)
    new_user = User(
        email=user_data.email,
        username=username_lower,  # Store username in lowercase
        full_name=user_data.full_name,
        matric_number=user_data.matric_number,
        department=user_data.department,
        role=user_data.role,
        hashed_password=hashed_pwd
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    # Authenticate user (username will be converted to lowercase in authenticate_user)
    user = authenticate_user(db, form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Include role in the token payload
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "role": user.role  # Include role in token
        }
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/check-username/{username}")
def check_username_availability(username: str, db: Session = Depends(get_db)):
    """Check if a username is available"""
    # Convert to lowercase and strip whitespace
    username_lower = username.lower().strip()
    
    # Validate username is not empty
    if not username_lower:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username cannot be empty"
        )
    
    # Check if username exists
    existing_user = db.query(User).filter(User.username == username_lower).first()
    
    return {
        "username": username_lower,
        "available": existing_user is None
    }