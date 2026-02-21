"""
Session Routes
- Upload audio (single file & chunked)
- Recording (start, chunk, finish)
- List/Get sessions
- Update/Delete sessions
- Audio streaming
- PDF generation
"""
import os
import json
import time
import shutil
import tempfile
from io import BytesIO
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet

from backend.database import SessionLocal, Session as DBSession
from backend.config import UPLOAD_DIR
from backend.security import encrypt_data, decrypt_data, decrypt_file
from backend.processor import processor_manager
from backend.licensing import get_license_manager
from backend.routes.auth import ACTIVE_KEYS  # Shared auth keys

router = APIRouter(tags=["Sessions"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -------------------------------------------------------------------
# UPLOAD ENDPOINTS
# -------------------------------------------------------------------

@router.post("/upload/{patient_id}")
async def upload_audio(
    patient_id: int, 
    token: str = Form(...),
    file: UploadFile = File(...), 
    model: str = Form(None),
    db: Session = Depends(get_db)
):
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)

    # Save temp file
    filename = f"{patient_id}_{int(time.time())}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Check License Limits
    limit_check = get_license_manager().check_usage_limits(db)
    if not limit_check['allowed']:
        raise HTTPException(status_code=403, detail=limit_check['reason'])

    # Create DB Record
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


@router.post("/upload/{patient_id}/chunked")
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
        content_type = chunk.content_type or "audio/webm"
        ext = "ogg" if "ogg" in content_type else "webm"
        
        filename = f"{patient_id}_{timestamp}_chunk{i}.{ext}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(chunk.file, buffer)
        
        chunk_paths.append(file_path)
    
    # Create DB Record
    new_session = DBSession(
        patient_id=patient_id,
        audio_path=chunk_paths[0],
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


# -------------------------------------------------------------------
# REAL-TIME STREAMING RECORDING
# -------------------------------------------------------------------

@router.post("/recording/{patient_id}/start")
async def start_recording_session(
    patient_id: int,
    token: str = Form(...),
    model: str = Form(None),
    db: Session = Depends(get_db)
):
    """Start a new real-time recording session."""
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    # Check License Limits
    limit_check = get_license_manager().check_usage_limits(db)
    if not limit_check['allowed']:
        raise HTTPException(status_code=403, detail=limit_check['reason'])
    
    # Create DB Record for streaming session
    new_session = DBSession(
        patient_id=patient_id,
        audio_path="",
        status="recording",
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


@router.post("/recording/{session_id}/chunk")
async def add_recording_chunk(
    session_id: int,
    token: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Add a chunk to an active recording session."""
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
        session.audio_path = file_path
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


@router.post("/recording/{session_id}/finish")
async def finish_recording_session(
    session_id: int,
    token: str = Form(...),
    total_chunks: int = Form(...),
    db: Session = Depends(get_db)
):
    """Finish a recording session and trigger final processing."""
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update final chunk count
    session.chunks_total = total_chunks
    session.status = "transcribing"
    db.commit()
    
    # Get stored model and key
    model = ACTIVE_KEYS.get(f"session_{session_id}_model")
    enc_key = ACTIVE_KEYS.get(f"session_{session_id}_key", key)
    
    # Queue final processing
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


# -------------------------------------------------------------------
# SESSION CRUD
# -------------------------------------------------------------------

@router.get("/sessions/")
def list_sessions(patient_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
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
                    raw_json = decrypt_data(s.structured_json["_encrypted"], key)
                    data = json.loads(raw_json)
                    metrics = data.get("_metrics")
                elif isinstance(s.structured_json, dict):
                    metrics = s.structured_json.get("_metrics")
                
                if metrics:
                    item["structured_json"] = {"_metrics": metrics}
            except:
                pass
        
        results.append(item)
    
    # Force sort: Newest first
    results.sort(key=lambda x: x['created_at'], reverse=True)
    
    return results


@router.get("/sessions/{session_id}")
def get_session(session_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404)
    
    item = {
        "id": s.id,
        "status": s.status,
        "created_at": s.created_at,
        "transcription_raw": s.transcription_raw,
        "structured_json": s.structured_json,
        "is_chunked": s.is_chunked,
        "chunks_total": s.chunks_total,
        "chunks_transcribed": s.chunks_transcribed
    }
    
    # For chunked sessions in progress, show partial transcription
    if s.is_chunked and s.status in ["transcribing", "queued", "recording", "analyzing", "securing"] and s.partial_transcription:
        item["transcription_raw"] = s.partial_transcription
    
    if s.status == "completed":
        try:
            if s.transcription_raw:
                item["transcription_raw"] = decrypt_data(s.transcription_raw, key)
            if s.structured_json and "_encrypted" in s.structured_json:
                item["structured_json"] = json.loads(decrypt_data(s.structured_json["_encrypted"], key))
        except:
            pass
        
    return item


@router.post("/sessions/{session_id}/update")
def update_session(session_id: int, token: str = Form(...), data: str = Form(...), db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404)
    
    updates = json.loads(data)
    
    # Decrypt current struct to merge
    current_struct = {}
    if s.structured_json and "_encrypted" in s.structured_json:
        try:
            current_struct = json.loads(decrypt_data(s.structured_json["_encrypted"], key))
        except:
            pass
        
    # Merge updates
    current_struct.update(updates)
    
    # Re-encrypt
    s.structured_json = {"_encrypted": encrypt_data(json.dumps(current_struct), key)}
    db.commit()
    return {"status": "updated"}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if s:
        # Try delete file
        if s.audio_path and os.path.exists(s.audio_path):
            try:
                os.remove(s.audio_path)
            except:
                pass
            
        db.delete(s)
        db.commit()
    return {"status": "deleted"}


# -------------------------------------------------------------------
# AUDIO ENDPOINTS
# -------------------------------------------------------------------

@router.get("/sessions/{session_id}/audio")
def get_session_audio(session_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s or not s.audio_path or not os.path.exists(s.audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
        
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix=".opus")
        os.close(temp_fd)
        
        if s.audio_path.endswith(".enc"):
            decrypt_file(s.audio_path, temp_path, key)
            return FileResponse(temp_path, media_type="audio/ogg; codecs=opus")
        else:
            return FileResponse(s.audio_path, media_type="audio/ogg; codecs=opus")
    except Exception as e:
        print(f"Error serving audio: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve audio")


@router.get("/audio/{session_id}")
def get_audio_stream(session_id: int, token: str, db: Session = Depends(get_db)):
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s or not s.audio_path or not os.path.exists(s.audio_path):
        raise HTTPException(status_code=404)
        
    if s.audio_path.endswith(".enc"):
        try:
            with open(s.audio_path, "rb") as f:
                enc_data = f.read()
            
            f = Fernet(key)
            dec_data = f.decrypt(enc_data)
            
            return Response(content=dec_data, media_type="audio/ogg")
        except:
            raise HTTPException(status_code=500, detail="Decrypt fail")
    else:
        return FileResponse(s.audio_path)


# -------------------------------------------------------------------
# PDF GENERATION
# -------------------------------------------------------------------

@router.get("/sessions/{session_id}/pdf")
def generate_session_pdf(session_id: int, token: str, db: Session = Depends(get_db)):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    
    # Auth & Data Fetch
    key = ACTIVE_KEYS.get(token)
    if not key:
        raise HTTPException(status_code=401)
    
    s = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404)
    
    # Decrypt & Parse
    data = {}
    if s.structured_json and "_encrypted" in s.structured_json:
        try:
            data = json.loads(decrypt_data(s.structured_json["_encrypted"], key))
        except:
            pass
    
    clinico = data.get("clinico", {})
    paciente_data = data.get("paciente", {})
    patient_name = s.patient.full_name if s.patient else "Desconocido"
    date_str = s.created_at.strftime("%d/%m/%Y %H:%M")
    
    # PDF Construction
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    styles = getSampleStyleSheet()
    
    # Custom Styles
    styles.add(ParagraphStyle(name='Header', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#4F46E5')))
    styles.add(ParagraphStyle(name='SectionTitle', parent=styles['Heading2'], fontSize=12, textColor=colors.HexColor('#6366F1'), spaceAfter=6))
    styles.add(ParagraphStyle(name='NormalText', parent=styles['Normal'], fontSize=10, leading=14))
    styles.add(ParagraphStyle(name='Label', parent=styles['Normal'], fontSize=8, textColor=colors.gray, textTransform='uppercase'))

    story = []
    
    # Header
    story.append(Paragraph("Session AI | Expediente Clínico", styles['Header']))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>Paciente:</b> {patient_name} &nbsp;|&nbsp; <b>Fecha:</b> {date_str}", styles['NormalText']))
    story.append(Spacer(1, 20))
    
    # SOAP Section
    story.append(Paragraph("Evolución Clínica (SOAP)", styles['SectionTitle']))
    
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
    
    # Risks & Analysis
    if clinico.get('riesgos'):
        story.append(Paragraph("Alertas de Riesgo Detectadas", styles['SectionTitle']))
        risk_text = ", ".join(clinico.get('riesgos', []))
        story.append(Paragraph(risk_text, styles['NormalText']))
        story.append(Spacer(1, 10))

    if data.get('sugerencias_ia'):
        story.append(Paragraph("Sugerencias Asistidas por IA", styles['SectionTitle']))
        for sg in data.get('sugerencias_ia', []):
            story.append(Paragraph(f"• {sg}", styles['NormalText']))
        story.append(Spacer(1, 20))

    # Patient Takeaway
    story.append(Paragraph("Resumen para el Paciente", styles['SectionTitle']))
    if paciente_data.get('puntos_clave'):
        story.append(Paragraph("<b>Puntos Clave:</b>", styles['NormalText']))
        for pt in paciente_data.get('puntos_clave', []):
            story.append(Paragraph(f"• {pt}", styles['NormalText']))
        story.append(Spacer(1, 6))
        
    if paciente_data.get('tarea_semana'):
        story.append(Paragraph(f"<b>Tarea Semanal:</b> {paciente_data.get('tarea_semana')}", styles['NormalText']))

    # Footer
    story.append(Spacer(1, 40))
    story.append(Paragraph("_" * 40, styles['Normal']))
    story.append(Paragraph("Firma del Profesional", styles['Normal']))
    story.append(Spacer(1, 10))
    story.append(Paragraph("<font size=7 color=grey>Documento generado por Session AI. El contenido clínico es responsabilidad del profesional tratante.</font>", styles['Normal']))

    doc.build(story)
    
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(), 
        media_type="application/pdf", 
        headers={"Content-Disposition": f"attachment; filename=Sesion_{session_id}.pdf"}
    )
