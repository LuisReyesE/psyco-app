import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, JSON, DateTime, Boolean
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from backend.config import DB_PATH
import os

# En Windows, formateamos la ruta para que SQLite no se confunda
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH.replace(os.sep, '/')}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False, "timeout": 30}
)

# Enable WAL mode for better concurrency
from sqlalchemy import event
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")  # Enforce FK constraints
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    
    # Auth basica
    hashed_password = Column(String)
    salt = Column(String) # Salt para derivar clave de la contraseña
    
    # Master Key System (Doble Caja Fuerte)
    # Caja 1: MK cifrada con la contraseña del usuario
    encrypted_master_key = Column(String) 
    
    # Caja 2: MK cifrada con el Código de Recuperación
    recovery_encrypted_master_key = Column(String)
    recovery_salt = Column(String) # Salt específico para el código de recuperación
    
    created_at = Column(DateTime, default=datetime.datetime.now)

    # Licensing System
    license_tier = Column(String, default="FREE")  # FREE | PRO
    license_key = Column(String, nullable=True)    # PRO-XXXX-YYYY
    hardware_id = Column(String, nullable=True)     # To prevent sharing
    last_license_check = Column(DateTime, nullable=True)

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
    anonymization_map = Column(JSON, nullable=True)  # Secret map for Gemini deanonymization
    status = Column(String, default="pending") # pending, processing, completed, error
    created_at = Column(DateTime, default=datetime.datetime.now)
    
    # Chunked recording support (real-time recording)
    is_chunked = Column(Boolean, default=False)
    chunks_total = Column(Integer, default=0)
    chunks_transcribed = Column(Integer, default=0)
    partial_transcription = Column(Text, default="")  # For live UI updates

    patient = relationship("Patient", back_populates="sessions")
