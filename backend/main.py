import os
import shutil
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from typing import Optional
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, HTTPException, Form

# Add local FFmpeg to PATH
ffmpeg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ffmpeg-tools", "ffmpeg-8.0.1-essentials_build", "bin"))
if os.path.exists(ffmpeg_path):
    os.environ["PATH"] = ffmpeg_path + os.pathsep + os.environ["PATH"]

from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from backend.database import SessionLocal, init_db, Patient, Session as DBSession
from backend.processor import process_audio_task

app = FastAPI(title="PsyScript Local API")

# CORS for local frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base directory (root of the project)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Initialize DB
init_db()

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/")
def read_root():
    return {"message": "PsyScript Local API is running"}

@app.post("/patients/")
def create_patient(name: str, db: Session = Depends(get_db)):
    patient = Patient(full_name=name)
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient

@app.get("/patients/")
def list_patients(db: Session = Depends(get_db)):
    return db.query(Patient).all()

@app.delete("/patients/{patient_id}")
def delete_patient(patient_id: int, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    # Manually delete audio files for all sessions
    for session in patient.sessions:
        if session.audio_path and os.path.exists(session.audio_path):
            try:
                os.remove(session.audio_path)
            except Exception:
                pass
    
    db.delete(patient)
    db.commit()
    return {"message": "Patient and all sessions deleted"}

@app.get("/models/")
def list_models():
    models = []
    
    # Ollama models ONLY
    try:
        import requests
        res = requests.get("http://localhost:11434/api/tags", timeout=2)
        if res.ok:
            data = res.json()
            for m in data.get("models", []):
                models.append(f"ollama:{m['name']}")
    except Exception:
        pass # Ollama might not be running
        
    return models

@app.post("/upload/{patient_id}")
async def upload_audio(
    patient_id: int, 
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...), 
    model: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    # Check if patient exists
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    file_path = os.path.join(UPLOAD_DIR, f"{patient_id}_{file.filename}")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Create session record
    session_record = DBSession(
        patient_id=patient_id,
        audio_path=file_path,
        status="pending"
    )
    db.add(session_record)
    db.commit()
    db.refresh(session_record)

    # Start background processing
    background_tasks.add_task(process_audio_task, session_record.id, model)

    return {"session_id": session_record.id, "status": "processing"}

@app.get("/sessions/")
def list_sessions(patient_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(DBSession)
    if patient_id:
        query = query.filter(DBSession.patient_id == patient_id)
    return query.all()

@app.get("/sessions/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)):
    session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session_record:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_record

@app.post("/sessions/{session_id}/update")
def update_session_data(session_id: int, data: dict, db: Session = Depends(get_db)):
    session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session_record:
        return {"error": "Session not found"}
    
    # Merge the new clinical narrative with existing metadata (metrics, model info)
    existing_json = session_record.structured_json or {}
    # Combine existing (preserving _metrics, _model_used) with new data
    updated_json = {**existing_json, **data}
    
    session_record.structured_json = updated_json
    db.commit()
    return {"status": "success"}

@app.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session_record:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Try to delete audio file
    if session_record.audio_path and os.path.exists(session_record.audio_path):
        try:
            os.remove(session_record.audio_path)
        except Exception:
            pass # Keep going if file delete fails
            
    db.delete(session_record)
    db.commit()
    return {"message": "Session deleted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
