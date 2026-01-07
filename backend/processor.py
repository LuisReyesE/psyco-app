import os
import json
import ollama
import time
from faster_whisper import WhisperModel
from sqlalchemy.orm import Session
from backend.database import SessionLocal, Session as DBSession

# Audio processor for Whisper and Ollama


def process_audio_task(session_id: int, selected_model: str = None):
    db = SessionLocal()
    session_record = None
    try:
        session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
        if not session_record:
            return

        session_record.status = "processing"
        db.commit()

        audio_path = session_record.audio_path

        # 1. Transcribe with Faster-Whisper
        print(f"Transcribing {audio_path}...")
        start_transcribe = time.time()
        whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, info = whisper_model.transcribe(audio_path, beam_size=5)
        
        transcript_text = ""
        for segment in segments:
            transcript_text += f"[{segment.start:.2f}s - {segment.end:.2f}s] {segment.text}\n"

        end_transcribe = time.time()
        transcribe_duration = round(end_transcribe - start_transcribe, 2)
        
        session_record.transcription_raw = transcript_text
        db.commit()

        # Truncate if too long (approx 40k chars to be safe with model limits)
        MAX_CHARS = 40000 
        safe_transcript = transcript_text
        if len(transcript_text) > MAX_CHARS:
            safe_transcript = transcript_text[:MAX_CHARS] + "\n[...]"

        # 2. LLM Extraction with Ollama (NATIVE JSON MODE)
        model_name = selected_model.replace("ollama:", "") if selected_model else "gemma:2b"
        
        # Get patient name for the narrative
        patient_name = session_record.patient.full_name if session_record.patient else "Paciente"
        
        print(f"Extracting clinical narrative with {model_name}...")
        
        # System Prompt for Narrative Paragraph
        system_prompt = (
            "Eres un asistente psicológico experto. Tu tarea es redactar una nota de evolución clínica en un ÚNICO PÁRRAFO de PROSA CONTINUA (texto fluido).\n"
            "ES MUY IMPORTANTE: NO uses formato JSON dentro del texto. NO uses llaves {}, ni corchetes, ni comillas innecesarias.\n"
            "El párrafo debe ser profesional y natural siguiendo este esquema:\n"
            "[Nombre y Sesión] + [Estado emocional] + [Conflicto central tratado] + [Técnica o intervención del terapeuta] + [Conclusión/Tarea].\n\n"
            "Debes responder EXCLUSIVAMENTE con un objeto JSON válido con esta única clave:\n"
            '{"nota_clinica": "El texto del párrafo aquí..."}'
        )
        
        user_prompt = (
            f"Basado en esta conversación con el paciente {patient_name}, redacta un párrafo clínico de evolución que sea sintético, "
            "profesional y que incluya el estado mental del paciente, el tema principal, la intervención realizada y los pendientes.\n\n"
            f"Transcripción de la sesión:\n{safe_transcript}"
        )
        
        try:
            start_gen = time.time()
            # Use ollama.generate or chat with format='json'
            response = ollama.generate(
                model=model_name,
                system=system_prompt,
                prompt=user_prompt,
                format='json',
                options={
                    'temperature': 0.1,
                }
            )
            end_gen = time.time()
            gen_duration = round(end_gen - start_gen, 2)
            
            response_text = response.get('response', '')
            
            try:
                extracted_data = json.loads(response_text)
                # Success
                extracted_data["_model_used"] = "ollama_json_mode"
                extracted_data["_model_file"] = model_name
                extracted_data["_metrics"] = {
                    "transcription_time": transcribe_duration,
                    "generation_time": gen_duration,
                    "total_time": round(transcribe_duration + gen_duration, 2)
                }
                session_record.structured_json = extracted_data
            except Exception as parse_error:
                print(f"JSON Parse error: {parse_error}")
                session_record.structured_json = {
                    "error": "Error al procesar el formato JSON de la IA",
                    "_raw_reply": response_text
                }

        except Exception as ollama_error:
            db.rollback()
            print(f"Ollama error: {ollama_error}")
            session_record.structured_json = {
                "error": f"Ollama Error: {str(ollama_error)}",
                "_model_file": model_name
            }

        session_record.status = "completed"
        db.commit()

    except Exception as e:
        db.rollback()
        import traceback
        print(f"Global error: {traceback.format_exc()}")
        if session_record:
            try:
                session_record.status = "error"
                session_record.structured_json = {"error": str(e)}
                db.commit()
            except:
                db.rollback()
    finally:
        db.close()
