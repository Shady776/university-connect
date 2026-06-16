from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
from app.config import CONFIG


# SQLALCHEMY_DATABASE_URL = 'sqlite:///./database.db'
SQLALCHEMY_DATABASE_URL =  CONFIG.DB_URL

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in SQLALCHEMY_DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()