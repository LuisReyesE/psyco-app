import os
import shutil
import sys
import json
import datetime
import time
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Depends, HTTPException, Form, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from backend.database import SessionLocal, init_db, Patient, Session as DBSession, User
from backend.processor import processor_manager
from backend.security import (
    get_password_hash, verify_password, derive_key, 
    encrypt_data, decrypt_data, decrypt_file_to_stream
)
import threading
from contextlib import asynccontextmanager

# In-memory "Key Cache" 
ACTIVE_KEYS = {} 

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Add local FFmpeg to PATH
    ffmpeg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ffmpeg-tools", "ffmpeg-8.0.1-essentials_build", "bin"))
    if os.path.exists(ffmpeg_path):
        os.environ["PATH"] = ffmpeg_path + os.pathsep + os.environ["PATH"]
    
    print("Starting up Session AI...")
    processor_manager.start_worker()
    # Load model in background to not block server startup
    threading.Thread(target=processor_manager.load_model, daemon=True).start()
    yield
    print("Shutting down Session AI...")
    processor_manager.is_running = False

app = FastAPI(title="Session AI API", lifespan=lifespan)

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

# --- AUTH & SECURITY HELPERS ---

async def get_current_key(token: str):
    """Retrieves the encryption key from active cache using the token"""
    if not token or token not in ACTIVE_KEYS:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return ACTIVE_KEYS[token]

@app.get("/auth/check")
def check_auth(db: Session = Depends(get_db)):
    """Check if a user exists (if not, FE shows register)"""
    user_count = db.query(User).count()
    return {"has_user": user_count > 0}

@app.post("/auth/register")
def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).count() > 0:
        raise HTTPException(status_code=400, detail="User already exists")
    
    salt = os.urandom(16).hex()
    hashed = get_password_hash(password)
    user = User(username=username, hashed_password=hashed, salt=salt)
    db.add(user)
    db.commit()
    return {"status": "success"}

@app.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Derive the key (don't store it in DB, only in RAM active cache)
    key = derive_key(password, bytes.fromhex(user.salt))
    
    # Simple token
    token = os.urandom(24).hex()
    ACTIVE_KEYS[token] = key
    
    return {"token": token, "username": username}

@app.get("/")
def read_root():
    return {"message": "PsyScript API is running"}

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
    token: str = Form(...),
    file: UploadFile = File(...), 
    model: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    key = await get_current_key(token)
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient: raise HTTPException(status_code=404, detail="Patient not found")

    file_path = os.path.join(UPLOAD_DIR, f"{patient_id}_{int(time.time())}.wav")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    session_record = DBSession(patient_id=patient_id, audio_path=file_path, status="pending")
    db.add(session_record)
    db.commit()
    db.refresh(session_record)

    processor_manager.enqueue_task(session_record.id, model, encryption_key=key)
    return {"session_id": session_record.id, "status": "queued"}

@app.get("/sessions/")
def list_sessions(patient_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)
    
    sessions = db.query(DBSession).filter(DBSession.patient_id == patient_id).all()
    results = []
    for s in sessions:
        item = {
            "id": s.id,
            "status": s.status,
            "created_at": s.created_at,
            "structured_json": s.structured_json
        }
        if s.status == "completed" and s.structured_json and "_encrypted" in s.structured_json:
            try:
                decrypted_str = decrypt_data(s.structured_json["_encrypted"], key)
                item["structured_json"] = json.loads(decrypted_str)
            except: pass
        results.append(item)
    return results

@app.get("/sessions/{session_id}")
def get_session(session_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s: raise HTTPException(status_code=404)
    
    item = {
        "id": s.id,
        "status": s.status,
        "created_at": s.created_at,
        "transcription_raw": s.transcription_raw,
        "structured_json": s.structured_json
    }
    
    if s.status == "completed":
        try:
            if s.transcription_raw:
                item["transcription_raw"] = decrypt_data(s.transcription_raw, key)
            if s.structured_json and "_encrypted" in s.structured_json:
                item["structured_json"] = json.loads(decrypt_data(s.structured_json["_encrypted"], key))
        except: pass
        
    return item

@app.get("/audio/{session_id}")
async def get_audio(session_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s or not s.audio_path: raise HTTPException(status_code=404)
    
    if not s.audio_path.endswith(".enc"):
        if os.path.exists(s.audio_path):
             return StreamingResponse(open(s.audio_path, "rb"), media_type="audio/mpeg")
        raise HTTPException(status_code=404)

    decrypted_bytes = decrypt_file_to_stream(s.audio_path, key)
    from io import BytesIO
    return StreamingResponse(BytesIO(decrypted_bytes), media_type="audio/mp4")

@app.get("/health")
def health_check(): return {"status": "ok"}

@app.post("/sessions/{session_id}/update")
async def update_session_data(session_id: int, token: str = Form(...), data: str = Form(...), db: Session = Depends(get_db)):
    key = await get_current_key(token)
    session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session_record:
        return {"error": "Session not found"}
    
    new_data = json.loads(data)
    existing_json = session_record.structured_json or {}
    
    # If the session is already completed/encrypted, we must re-encrypt the whole block
    if "_encrypted" in existing_json:
        # Decrypt existing to merge
        try:
            curr_str = decrypt_data(existing_json["_encrypted"], key)
            curr_data = json.loads(curr_str)
        except:
            curr_data = {}
        
        # Merge
        updated_data = {**curr_data, **new_data}
        # Encrypt back
        encrypted_str = encrypt_data(json.dumps(updated_data), key)
        session_record.structured_json = {"_encrypted": encrypted_str}
    else:
        # Not encrypted yet (rare if status is completed, but possible)
        session_record.structured_json = {**existing_json, **new_data}
    
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
