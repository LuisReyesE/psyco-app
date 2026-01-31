import uvicorn
import sys
import os

# Add project root to sys.path to allow 'from backend.xxx' imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import shutil
import json
import time
from sqlalchemy.orm import Session

# Local imports
from backend.database import engine, Base, SessionLocal, User, Session as DBSession
from backend.processor import processor_manager
from backend.config import UPLOAD_DIR
from backend.security import (
    get_password_hash, verify_password, derive_key, 
    encrypt_data, decrypt_data, generate_recovery_code
)
from cryptography.fernet import Fernet

# -------------------------------------------------------------------
# CONFIG & INIT
# -------------------------------------------------------------------

# Create tables if not exist
Base.metadata.create_all(bind=engine)

# -------------------------------------------------------------------
# LIFECYCLE
# -------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load model & start worker
    print("--- Session AI Backend Starting ---")
    print(f"DEBUG: DATA_DIR = {os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))}") # Debug line
    print(f"DEBUG: UPLOAD_DIR = {UPLOAD_DIR}")
    
    # 1. Pre-load Model (Heavy operation)
    try:
        processor_manager.load_model()
    except Exception as e:
        print(f"Warning: Failed to pre-load Whisper model: {e}")

    # 2. Start Worker Thread
    processor_manager.start_worker()
    
    yield
    # Shutdown logic (if issues arise, we can add cleanup here)
    print("--- Session AI Backend Stopping ---")

app = FastAPI(lifespan=lifespan)

# CORS Correction (Must be applied after app creation)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-Memory Cache for Decrypted Master Keys
# Format: { token_str: b"master_key_bytes" }
ACTIVE_KEYS = {}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------------------------------------------------------
# AUTHENTICATION ENDPOINTS
# -------------------------------------------------------------------

@app.get("/auth/check")
def check_registration(db: Session = Depends(get_db)):
    """Check if any user is registered (Single User App)"""
    user = db.query(User).first()
    return {"has_user": bool(user)}

@app.post("/auth/register")
def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).first():
        raise HTTPException(status_code=400, detail="User already registered")

    # 1. Generate Universal Master Key (MK)
    master_key = Fernet.generate_key() 
    
    # 2. Setup Recovery Code
    recovery_code = generate_recovery_code() # "ABCD-EFGH-..."
    recovery_salt = os.urandom(16).hex()
    
    # 3. Encrypt MK in Box A (Password Protection)
    salt = os.urandom(16).hex()
    hashed = get_password_hash(password)
    derived_pwd_key = derive_key(password, bytes.fromhex(salt))
    encrypted_mk_pwd = encrypt_data(master_key.decode(), derived_pwd_key)
    
    # 4. Encrypt MK in Box B (Recovery Code Protection)
    derived_rec_key = derive_key(recovery_code, bytes.fromhex(recovery_salt))
    encrypted_mk_rec = encrypt_data(master_key.decode(), derived_rec_key)
    
    user = User(
        username=username, 
        hashed_password=hashed, 
        salt=salt,
        encrypted_master_key=encrypted_mk_pwd,
        recovery_encrypted_master_key=encrypted_mk_rec,
        recovery_salt=recovery_salt
    )
    db.add(user)
    db.commit()
    
    return {"status": "success", "recovery_code": recovery_code}

@app.post("/auth/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    try:
        # Open Box A
        derived_pwd_key = derive_key(password, bytes.fromhex(user.salt))
        master_key_str = decrypt_data(user.encrypted_master_key, derived_pwd_key)
        master_key = master_key_str.encode()
    except Exception:
        raise HTTPException(status_code=500, detail="Crypto check failed")
    
    token = os.urandom(24).hex()
    ACTIVE_KEYS[token] = master_key # Session uses the Real Master Key
    
    return {"status": "success", "token": token, "username": user.username}

@app.post("/auth/verify")
def verify_token(token: str = Form(...)):
    """Check if token is active in RAM"""
    if token in ACTIVE_KEYS:
        return {"valid": True}
    raise HTTPException(status_code=401, detail="Token invalid")

@app.post("/auth/recover")
def recover_password(
    username: str = Form(...), 
    recovery_code: str = Form(...), 
    new_password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    try:
        # Open Box B
        derived_rec_key = derive_key(recovery_code, bytes.fromhex(user.recovery_salt))
        master_key_str = decrypt_data(user.recovery_encrypted_master_key, derived_rec_key)
        # If we are here, recovery code is correct
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid recovery code")
        
    # Re-encrypt in Box A with New Password
    new_salt = os.urandom(16).hex()
    new_hashed = get_password_hash(new_password)
    derived_new_pwd_key = derive_key(new_password, bytes.fromhex(new_salt))
    
    new_encrypted_mk_pwd = encrypt_data(master_key_str, derived_new_pwd_key)
    
    user.hashed_password = new_hashed
    user.salt = new_salt
    user.encrypted_master_key = new_encrypted_mk_pwd
    db.commit()
    
    return {"status": "recovered"}

# -------------------------------------------------------------------
# PATIENT ENDPOINTS
# -------------------------------------------------------------------

@app.get("/patients/")
def list_patients(db: Session = Depends(get_db)):
    from backend.database import Patient
    return db.query(Patient).all()

@app.post("/patients/")
def create_patient(name: str, db: Session = Depends(get_db)):
    from backend.database import Patient
    p = Patient(full_name=name)
    db.add(p)
    db.commit()
    return p

@app.delete("/patients/{patient_id}")
def delete_patient(patient_id: int, db: Session = Depends(get_db)):
    from backend.database import Patient
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if p:
        # Cascade delete sessions logic is handled by DB FK usually, 
        # but files should be cleaned up. For now assuming simple delete.
        db.delete(p)
        db.commit()
    return {"status": "deleted"}

# -------------------------------------------------------------------
# SESSION & UPLOAD ENDPOINTS (SECURED)
# -------------------------------------------------------------------

@app.post("/upload/{patient_id}")
async def upload_audio(
    patient_id: int, 
    token: str = Form(...),
    file: UploadFile = File(...), 
    model: str = Form(None),
    db: Session = Depends(get_db)
):
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)

    # Save temp file
    filename = f"{patient_id}_{int(time.time())}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Create DB Record
    # We store the temp path initially, processor will encrypt it later
    new_session = DBSession(
        patient_id=patient_id,
        audio_path=file_path,
        status="queued"
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    # Enqueue Task with Key
    processor_manager.enqueue_task(new_session.id, model, encryption_key=key)
    return {"status": "queued", "session_id": new_session.id}

# -------------------------------------------------------------------
# REAL-TIME STREAMING RECORDING (Parallel Transcription)
# -------------------------------------------------------------------

@app.post("/recording/{patient_id}/start")
async def start_recording_session(
    patient_id: int,
    token: str = Form(...),
    model: str = Form(None),
    db: Session = Depends(get_db)
):
    """
    Start a new real-time recording session.
    Returns session_id to use for streaming chunks.
    """
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    # Create DB Record for streaming session
    new_session = DBSession(
        patient_id=patient_id,
        audio_path="",  # Will be set when first chunk arrives
        status="recording",  # New status for active recording
        is_chunked=True,
        chunks_total=0,
        chunks_transcribed=0
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    # Store model preference and encryption key for this session
    ACTIVE_KEYS[f"session_{new_session.id}_model"] = model
    ACTIVE_KEYS[f"session_{new_session.id}_key"] = key
    
    print(f"[STREAM] Started recording session {new_session.id} for patient {patient_id}")
    
    return {
        "status": "recording",
        "session_id": new_session.id
    }

@app.post("/recording/{session_id}/chunk")
async def add_recording_chunk(
    session_id: int,
    token: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Add a chunk to an active recording session.
    Chunk is immediately queued for parallel transcription.
    """
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Detect file extension
    content_type = chunk.content_type or "audio/webm"
    ext = "ogg" if "ogg" in content_type else "webm"
    
    # Save chunk to disk
    timestamp = int(time.time())
    filename = f"{session.patient_id}_{session_id}_chunk{chunk_index}_{timestamp}.{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(chunk.file, buffer)
    
    # Update session chunk count
    session.chunks_total = max(session.chunks_total, chunk_index + 1)
    if not session.audio_path:
        session.audio_path = file_path  # First chunk as reference
    db.commit()
    
    # Get stored model and key for this session
    model = ACTIVE_KEYS.get(f"session_{session_id}_model")
    enc_key = ACTIVE_KEYS.get(f"session_{session_id}_key", key)
    
    # Immediately queue chunk for transcription
    processor_manager.enqueue_single_chunk(session_id, chunk_index, file_path, enc_key)
    
    print(f"[CHUNK] Chunk {chunk_index} received for session {session_id} ({os.path.getsize(file_path)/1024:.1f} KB)")
    
    return {
        "status": "received",
        "chunk_index": chunk_index,
        "session_id": session_id
    }

@app.post("/recording/{session_id}/finish")
async def finish_recording_session(
    session_id: int,
    token: str = Form(...),
    total_chunks: int = Form(...),
    db: Session = Depends(get_db)
):
    """
    Finish a recording session and trigger final processing (AI analysis).
    """
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update final chunk count
    session.chunks_total = total_chunks
    session.status = "transcribing"  # Move from 'recording' to 'transcribing'
    db.commit()
    
    # Get stored model and key
    model = ACTIVE_KEYS.get(f"session_{session_id}_model")
    enc_key = ACTIVE_KEYS.get(f"session_{session_id}_key", key)
    
    # Queue final processing (wait for transcriptions, then analyze)
    processor_manager.enqueue_finish_session(session_id, total_chunks, model, enc_key)
    
    # Cleanup session-specific keys
    ACTIVE_KEYS.pop(f"session_{session_id}_model", None)
    ACTIVE_KEYS.pop(f"session_{session_id}_key", None)
    
    print(f"[FINISH] Recording session {session_id} finished with {total_chunks} chunks")
    
    return {
        "status": "finishing",
        "session_id": session_id,
        "total_chunks": total_chunks
    }

# Legacy chunked upload (all chunks at once - kept for compatibility)
@app.post("/upload/{patient_id}/chunked")
async def upload_audio_chunked(
    patient_id: int,
    token: str = Form(...),
    chunks: list[UploadFile] = File(...),
    model: str = Form(None),
    db: Session = Depends(get_db)
):
    """
    Upload multiple audio chunks from real-time recording.
    Chunks are processed in parallel for faster transcription.
    """
    key = ACTIVE_KEYS.get(token)
    if not key: 
        raise HTTPException(status_code=401)
    
    if not chunks or len(chunks) == 0:
        raise HTTPException(status_code=400, detail="No chunks provided")
    
    # Save each chunk to disk
    chunk_paths = []
    timestamp = int(time.time())
    
    for i, chunk in enumerate(chunks):
        # Detect actual file extension from content type or filename
        content_type = chunk.content_type or "audio/webm"
        if "ogg" in content_type:
            ext = "ogg"
        else:
            ext = "webm"  # Default to webm since browsers usually send this
        
        filename = f"{patient_id}_{timestamp}_chunk{i}.{ext}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(chunk.file, buffer)
        
        chunk_paths.append(file_path)
    
    # Create DB Record (audio_path will be updated after merge)
    new_session = DBSession(
        patient_id=patient_id,
        audio_path=chunk_paths[0],  # Temporary, will be replaced with merged file
        status="queued",
        is_chunked=True,
        chunks_total=len(chunks),
        chunks_transcribed=0
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    # Enqueue Chunked Task
    processor_manager.enqueue_chunked_task(
        new_session.id, 
        chunk_paths, 
        model, 
        encryption_key=key
    )
    
    return {
        "status": "queued", 
        "session_id": new_session.id, 
        "chunks_received": len(chunks)
    }

@app.get("/sessions/")
def list_sessions(patient_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)
    
    sessions = db.query(DBSession).filter(DBSession.patient_id == patient_id).order_by(DBSession.created_at.desc()).all()
    
    # Decrypt metrics for list view
    results = []
    for s in sessions:
        item = {
            "id": s.id,
            "status": s.status,
            "created_at": s.created_at,
            "structured_json": {}
        }
        
        # Try to peek into encrypted metrics
        if s.structured_json:
            try:
                metrics = None
                if isinstance(s.structured_json, dict) and "_encrypted" in s.structured_json:
                    # Decrypt just to get metrics (fast enough for list)
                    raw_json = decrypt_data(s.structured_json["_encrypted"], key)
                    data = json.loads(raw_json)
                    metrics = data.get("_metrics")
                elif isinstance(s.structured_json, dict):
                    metrics = s.structured_json.get("_metrics")
                
                if metrics:
                    item["structured_json"] = {"_metrics": metrics}
            except:
                pass # Ignore decryption errors in list view
        
        results.append(item)
    
    # Force sort: Newest first (Descending)
    results.sort(key=lambda x: x['created_at'], reverse=True)
    
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
        "structured_json": s.structured_json,
        # Chunking info for UI
        "is_chunked": s.is_chunked,
        "chunks_total": s.chunks_total,
        "chunks_transcribed": s.chunks_transcribed
    }
    
    # For chunked sessions in progress, show partial transcription
    if s.is_chunked and s.status in ["transcribing", "queued"] and s.partial_transcription:
        item["transcription_raw"] = s.partial_transcription
    
    if s.status == "completed":
        try:
            if s.transcription_raw:
                item["transcription_raw"] = decrypt_data(s.transcription_raw, key)
            if s.structured_json and "_encrypted" in s.structured_json:
                item["structured_json"] = json.loads(decrypt_data(s.structured_json["_encrypted"], key))
        except: pass
        
    return item

@app.get("/sessions/{session_id}/audio")
def get_session_audio(session_id: int, token: str, db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse, Response
    from backend.security import decrypt_file
    import tempfile
    
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s or not s.audio_path or not os.path.exists(s.audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    try:
        # Decrypt to a temporary file just for streaming
        # We create a named temp file that will be cleaned up
        temp_fd, temp_path = tempfile.mkstemp(suffix=".opus")
        os.close(temp_fd)
        
        # If file ends with .enc, decrypt it. If not, serve directly (legacy/dev)
        if s.audio_path.endswith(".enc"):
            decrypt_file(s.audio_path, temp_path, key)
            
            # Serve the temp file and ensure background cleanup task ? 
            # FastAPI BackgroundTasks can remove it after response.
            # But simpler here: Just serve it as a static file response
            # Windows file locking might be tricky, but FileResponse handles open/close.
            return FileResponse(temp_path, media_type="audio/ogg; codecs=opus")
        else:
            return FileResponse(s.audio_path, media_type="audio/ogg; codecs=opus")
    except Exception as e:
        print(f"Error serving audio: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve audio")

@app.get("/sessions/{session_id}/pdf")
def generate_session_pdf(session_id: int, token: str, db: Session = Depends(get_db)):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Frame
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from io import BytesIO
    from backend.security import decrypt_data
    
    # 1. Auth & Data Fetch
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s: raise HTTPException(status_code=404)
    
    # 2. Decrypt & Parse
    data = {}
    if s.structured_json and "_encrypted" in s.structured_json:
        try:
            data = json.loads(decrypt_data(s.structured_json["_encrypted"], key))
        except: pass
    
    clinico = data.get("clinico", {})
    paciente_data = data.get("paciente", {})
    patient_name = s.patient.full_name if s.patient else "Desconocido"
    date_str = s.created_at.strftime("%d/%m/%Y %H:%M")
    
    # 3. PDF Construction
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    styles = getSampleStyleSheet()
    
    # Custom Styles
    styles.add(ParagraphStyle(name='Header', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#4F46E5')))
    styles.add(ParagraphStyle(name='SectionTitle', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#6366F1'), spaceAfter=6))
    styles.add(ParagraphStyle(name='NormalText', parent=styles['Normal'], fontSize=10, leading=14))
    styles.add(ParagraphStyle(name='Label', parent=styles['Normal'], fontSize=8, textColor=colors.gray, textTransform='uppercase'))
    styles.add(ParagraphStyle(name='RiskTag', parent=styles['Normal'], fontSize=8, textColor=colors.red, backColor=colors.HexColor('#FEF2F2'), borderColor=colors.red, borderWidth=0.5, borderPadding=2))

    story = []
    
    # -- Header --
    story.append(Paragraph("Session AI | Expediente Clínico", styles['Header']))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>Paciente:</b> {patient_name} &nbsp;|&nbsp; <b>Fecha:</b> {date_str}", styles['NormalText']))
    story.append(Spacer(1, 20))
    
    # -- SOAP Section --
    story.append(Paragraph("Evolución Clínica (SOAP)", styles['SectionTitle']))
    
    # Data cleaning for SOAP table
    s_text = Paragraph(clinico.get('subjetivo', 'No registrado'), styles['NormalText'])
    o_text = Paragraph(clinico.get('objetivo', 'No registrado'), styles['NormalText'])
    a_text = Paragraph(clinico.get('analisis', 'No registrado'), styles['NormalText'])
    p_text = Paragraph(clinico.get('plan', 'No registrado').replace('\n', '<br/>'), styles['NormalText'])
    
    data_table = [
        [Paragraph("S - Subjetivo", styles['Label']), s_text],
        [Paragraph("O - Objetivo", styles['Label']), o_text],
        [Paragraph("A - Análisis", styles['Label']), a_text],
        [Paragraph("P - Plan", styles['Label']), p_text]
    ]
    
    t = Table(data_table, colWidths=[1*inch, 5.5*inch])
    t.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LINEBELOW', (0,0), (-1,-2), 0.5, colors.lightgrey),
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ('TOPPADDING', (0,0), (-1,-1), 12),
        ('TEXTCOLOR', (0,0), (0,-1), colors.gray),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))
    
    # -- Risks & Analysis (AI Support) --
    if clinico.get('riesgos'):
        story.append(Paragraph("Alertas de Riesgo Detectadas", styles['SectionTitle']))
        risk_text = ", ".join(clinico.get('riesgos', []))
        story.append(Paragraph(risk_text, styles['NormalText']))
        story.append(Spacer(1, 10))

    if data.get('sugerencias_ia'):
        story.append(Paragraph("Sugerencias Asistidas por IA", styles['SectionTitle']))
        ug_list = data.get('sugerencias_ia', [])
        for sg in ug_list:
             story.append(Paragraph(f"• {sg}", styles['NormalText']))
        story.append(Spacer(1, 20))

    # -- Patient Takeaway --
    story.append(Paragraph("Resumen para el Paciente", styles['SectionTitle']))
    if paciente_data.get('puntos_clave'):
        story.append(Paragraph("<b>Puntos Clave:</b>", styles['NormalText']))
        for pt in paciente_data.get('puntos_clave', []):
            story.append(Paragraph(f"• {pt}", styles['NormalText']))
        story.append(Spacer(1, 6))
        
    if paciente_data.get('tarea_semana'):
        story.append(Paragraph(f"<b>Tarea Semanal:</b> {paciente_data.get('tarea_semana')}", styles['NormalText']))

    # -- Footer / Disclaimer --
    story.append(Spacer(1, 40))
    story.append(Paragraph("_" * 40, styles['Normal']))
    story.append(Paragraph("Firma del Profesional", styles['Normal']))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<font size=7 color=grey>Documento generado por Session AI. El contenido clínico es responsabilidad del profesional tratante.</font>", styles['Normal']))

    doc.build(story)
    
    buffer.seek(0)
    return Response(content=buffer.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=Sesion_{session_id}.pdf"})

@app.post("/sessions/{session_id}/update")
def update_session(session_id: int, token: str = Form(...), data: str = Form(...), db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s: raise HTTPException(status_code=404)
    
    updates = json.loads(data)
    
    # Decrypt current struct to merge
    current_struct = {}
    if s.structured_json and "_encrypted" in s.structured_json:
        try:
            current_struct = json.loads(decrypt_data(s.structured_json["_encrypted"], key))
        except: pass
        
    # Merge updates (nota_clinica mostly)
    current_struct.update(updates)
    
    # Re-encrypt
    s.structured_json = {"_encrypted": encrypt_data(json.dumps(current_struct), key)}
    db.commit()
    return {"status": "updated"}

@app.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if s:
        # Try delete file
        if s.audio_path and os.path.exists(s.audio_path):
            try: os.remove(s.audio_path)
            except: pass
            
        db.delete(s)
        db.commit()
    return {"status": "deleted"}

@app.get("/audio/{session_id}")
def get_audio_stream(session_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key: raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s or not s.audio_path or not os.path.exists(s.audio_path):
        raise HTTPException(status_code=404)
        
    # Decrypt on the fly and stream (Simplification: decrypt to temp and stream)
    # Ideally use a stream decryptor. For now, we decrypt to memory if small, or temp if large.
    # Given secure requirement, memory is better but risky for RAM.
    # Let's verify file ext. If .enc, decrypt.
    
    if s.audio_path.endswith(".enc"):
        try:
            decrypted_path = s.audio_path.replace(".enc", ".temp_play")
            # This is risky for concurrency, but okay for single user MVP.
            # Better: read bytes, decrypt, yield generator.
            
            with open(s.audio_path, "rb") as f:
                enc_data = f.read()
            
            f = Fernet(key)
            dec_data = f.decrypt(enc_data)
            
            from fastapi.responses import Response
            return Response(content=dec_data, media_type="audio/ogg")
        except:
             raise HTTPException(status_code=500, detail="Decrypt fail")
    else:
        # Not encrypted yet (queued?) or legacy
        from fastapi.responses import FileResponse
        return FileResponse(s.audio_path)

@app.get("/models/")
def list_models():
    """List available AI models (Ollama + Gemini if configured)"""
    models = []
    
    # 1. Add Ollama models (local)
    try:
        raw_models = import_ollama_list()
        for m in raw_models:
            # Handle object vs dict
            if hasattr(m, 'model'):
                name = m.model
            elif isinstance(m, dict):
                name = m.get('model', m.get('name', 'unknown'))
            else:
                continue
            # Prefix with ollama: for router identification
            models.append(f"ollama:{name}")
    except Exception as e:
        print(f"Error loading models from Ollama: {e}")
    
    # 2. Add Gemini models (cloud, if API key configured)
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if gemini_api_key and gemini_api_key != 'your_api_key_here':
        models.append("gemini:gemini-3-flash-preview")
    
    return models

def import_ollama_list():
    import ollama
    response = ollama.list()
    # Handle older versions returning dict vs newer returning objects
    if hasattr(response, 'models'):
        return response.models
    elif isinstance(response, dict) and 'models' in response:
        return response['models']
    return []

@app.get("/health")
def health_check():
    return {"status": "ok"}

# -------------------------------------------------------------------
# LIFECYCLE
# -------------------------------------------------------------------


# -------------------------------------------------------------------
# SYSTEM BACKUP & RESTORE
# -------------------------------------------------------------------

@app.get("/system/backup")
def create_system_backup(token: str):
    """
    Crea un ZIP con toda la carpeta 'data' (DB + Audios).
    Requiere token valido para autorizar.
    """
    if token not in ACTIVE_KEYS:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Ruta de la carpeta 'data' (padre de uploads)
    # config.py define UPLOAD_DIR = data/uploads, asi que data es su padre
    data_dir = os.path.dirname(UPLOAD_DIR)
    
    # Nombre temporal del archivo
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"backup_psyco_{timestamp}"
    output_path = os.path.join(os.path.dirname(data_dir), base_name) # Save in root temporarily
    
    # Crear ZIP
    shutil.make_archive(output_path, 'zip', data_dir)
    zip_file = f"{output_path}.zip"
    
    return FileResponse(
        path=zip_file, 
        filename=f"SessionAI_Backup_{timestamp}.zip", 
        media_type='application/zip'
    )

@app.post("/system/restore")
async def restore_system_backup(file: UploadFile = File(...), token: str = Form(...)):
    """
    Recibe un ZIP, verifica su integridad y reemplaza la carpeta 'data'.
    ADVERTENCIA: Destructivo.
    """
    if token not in ACTIVE_KEYS:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files allowed")

    # 1. Guardar ZIP recibido
    data_dir = os.path.dirname(UPLOAD_DIR)
    root_dir = os.path.dirname(data_dir)
    temp_zip_path = os.path.join(root_dir, "temp_restore.zip")
    
    with open(temp_zip_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 2. Validar contenido (Sanity Check)
    import zipfile
    try:
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            # Debe contener la DB o la carpeta uploads para ser valido
            if "psyco_app.db" not in file_list and not any(f.startswith("uploads/") for f in file_list) and not any(f.startswith("/uploads/") for f in file_list):
                 # Relaxed check: just check if it looks like a backup
                 pass 
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Corrupted zip file")

    # 3. PREPARAR RESTORE (CRITICO EN WINDOWS)
    # Soltar el lock de la DB
    engine.dispose()
    
    # Renombrar data actual a backup por seguridad
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(root_dir, f"data_pre_restore_{timestamp}")
    
    try:
        if os.path.exists(data_dir):
            os.rename(data_dir, backup_path)
        
        # 4. Descomprimir nuevo data
        os.makedirs(data_dir, exist_ok=True)
        shutil.unpack_archive(temp_zip_path, data_dir)
        
        # Limpieza
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)
        
        return {"status": "success", "message": "System restored successfully. Please restart app if issues occur."}
        
    except Exception as e:
        # Rollback intent
        print(f"[CRITICAL] Restore failed: {e}. Attempting rollback...")
        if os.path.exists(backup_path):
            if os.path.exists(data_dir):
                shutil.rmtree(data_dir) # Delete partial failed restore
            os.rename(backup_path, data_dir) # Restore original
            
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
