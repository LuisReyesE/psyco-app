import os
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, JSON, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Base directory (root of the project)
# Usamos un método más robusto para encontrar la raíz real del proyecto
current_file_path = os.path.abspath(__file__)
backend_dir = os.path.dirname(current_file_path)
BASE_DIR = os.path.dirname(backend_dir)
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, 'psyco_app.db')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

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
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    salt = Column(String) # For key derivation
    created_at = Column(DateTime, default=datetime.datetime.now)

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
