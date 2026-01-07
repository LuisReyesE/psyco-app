import os
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, JSON, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Base directory (root of the project)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'psyco_app.db')}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.datetime.now)
    
    sessions = relationship("Session", back_populates="patient", cascade="all, delete-orphan")

class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id", ondelete="CASCADE"))
    audio_path = Column(String)
    transcription_raw = Column(Text, nullable=True)
    structured_json = Column(JSON, nullable=True)
    status = Column(String, default="pending") # pending, processing, completed, error
    created_at = Column(DateTime, default=datetime.datetime.now)

    patient = relationship("Patient", back_populates="sessions")

def init_db():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
