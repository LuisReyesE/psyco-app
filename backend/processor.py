import os
import json
import ollama
import time
import threading
import queue
import re
import subprocess
from faster_whisper import WhisperModel
from sqlalchemy.orm import Session
from backend.database import SessionLocal, Session as DBSession
from backend.security import encrypt_data, encrypt_file
from backend.config import FFMPEG_DIR

# Lazy import for anonymizer (only loaded when Gemini is used)
_anonymizer_module = None

def get_anonymizer():
    """Lazy load anonymizer module to avoid loading spaCy unless needed"""
    global _anonymizer_module
    if _anonymizer_module is None:
        from backend import anonymizer
        _anonymizer_module = anonymizer
    return _anonymizer_module

# Singleton for the processor manager
class AudioProcessorManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AudioProcessorManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.model = None
        self.task_queue = queue.Queue()
        self.worker_thread = None
        self.is_running = False
        if not self._initialized:
             self._initialized = True
        
        # Forzamos CPU
        self.device = "cpu"
        self.compute_type = "int8"
        
        # Detect FFmpeg path
        self.ffmpeg_path = self._find_ffmpeg()
        print(f"FFmpeg detected at: {self.ffmpeg_path}")

    def _find_ffmpeg(self):
        """Locates ffmpeg.exe in the tools temporary/local folder"""
        # Start searching from the configured FFMPEG_DIR
        for root, _, files in os.walk(FFMPEG_DIR):
            if "ffmpeg.exe" in files:
                return os.path.join(root, "ffmpeg.exe")
                
        return "ffmpeg"

    def load_model(self):
        """Loads the whisper model into memory"""
        if self.model is None:
            print("Loading Whisper model into RAM/VRAM...")
            start = time.time()
            self.model = WhisperModel("small", device=self.device, compute_type=self.compute_type)
            end = time.time()
            print(f"Model loaded in {round(end - start, 2)}s using {self.device}")

    def start_worker(self):
        """Starts the background worker thread"""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.is_running = True
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            print("Background worker thread started.")

    def enqueue_task(self, session_id: int, selected_model: str = None, encryption_key: bytes = None):
        """Adds a new session to the processing queue"""
        db = SessionLocal()
        try:
            session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
            if session_record:
                session_record.status = "queued"
                db.commit()
        finally:
            db.close()
            
        self.task_queue.put((session_id, selected_model, encryption_key))
        print(f"Session {session_id} added to queue. Queue size: {self.task_queue.qsize()}")

    def _worker_loop(self):
        """Continuous loop processing tasks from the queue"""
        while self.is_running:
            try:
                task = self.task_queue.get(timeout=1)
                session_id, selected_model, encryption_key = task
                
                try:
                    self._process_single_task(session_id, selected_model, encryption_key)
                except Exception as e:
                    print(f"Error processing session {session_id}: {str(e)}")
                finally:
                    self.task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Worker loop error: {str(e)}")
                time.sleep(2)

    def _preprocess_audio(self, input_path):
        """
        Lógica de Pre-procesamiento con FFmpeg:
        - Si es opus/ogg: No realiza conversión (Zero-copy).
        - Si es otro formato: Convierte a opus optimizado para voz (16kHz, mono, 12k).
        """
        ext = input_path.rsplit('.', 1)[-1].lower()
        
        # Caso 1: Ya es compatible nativamente (WhatsApp / Grabación Nativa)
        if ext in ['opus', 'ogg']:
            print(f"Optimización: Formato {ext} detectado, usando Zero-copy.")
            return input_path
            
        # Caso 2: Otros formatos (.mp3, .mp4, .wav, .webm)
        output_path = input_path.rsplit('.', 1)[0] + "_opt.opus"
        print(f"Convirtiendo {input_path} a formato optimizado .opus...")
        try:
            # Comando optimizado: ffmpeg -i entrada -vn -c:a libopus -ar 16000 -ac 1 -b:a 12k salida.opus
            subprocess.run([
                self.ffmpeg_path, '-y', '-i', input_path, 
                '-vn', '-c:a', 'libopus', 
                '-ar', '16000', '-ac', '1', 
                '-b:a', '12k', output_path
            ], check=True, capture_output=True)
            return output_path
        except Exception as e:
            print(f"Error en pre-procesamiento FFmpeg: {e}")
            return input_path # Fallback al original si falla la conversión

    def _process_with_ollama(self, transcript: str, model_name: str, transcribe_duration: float) -> dict:
        """
        Process transcript with local Ollama model.
        No anonymization needed - all data stays local.
        """
        system_prompt = (
            "Eres un asistente psicológico experto. Tu tarea es redactar una nota de evolución clínica en un ÚNICO PÁRRAFO de PROSA CONTINUA.\n"
            "ES MUY IMPORTANTE: NO uses formato JSON dentro del texto. NO uses llaves {}, ni corchetes, ni comillas innecesarias.\n"
            "Debes responder EXCLUSIVAMENTE con un objeto JSON válido con esta única clave:\n"
            '{"nota_clinica": "El texto del párrafo aquí..."}'
        )
        
        user_prompt = f"Conversación clínica:\n\n{transcript}"
        
        try:
            start_gen = time.time()
            response = ollama.generate(
                model=model_name, 
                system=system_prompt, 
                prompt=user_prompt, 
                format='json', 
                options={'temperature': 0.1}
            )
            gen_duration = round(time.time() - start_gen, 2)
            
            response_text = response.get('response', '')
            try:
                # Clean markdown code blocks
                clean_text = re.sub(r'```(?:json)?\s*', '', response_text).replace('```', '').strip()
                data = json.loads(clean_text)
                
                # Add metrics
                data["_metrics"] = {
                    "transcription_time": transcribe_duration,
                    "generation_time": gen_duration,
                    "total_time": round(transcribe_duration + gen_duration, 2),
                    "device": self.device
                }
                data["_model_file"] = model_name
                data["_provider"] = "ollama"
                return data
                
            except Exception as e:
                print(f"JSON Parse failed: {e}. Falling back to raw text.")
                return {
                    "nota_clinica": response_text, 
                    "_warning": "Formato no estructurado (JSON fallido)",
                    "_raw": response_text,
                    "_provider": "ollama"
                }
        except Exception as e:
            return {"error": f"Ollama Error: {str(e)}"}

    def _process_with_gemini(self, transcript: str, patient_name: str, transcribe_duration: float) -> tuple:
        """
        Process transcript with Gemini API (cloud).
        Uses anonymization to protect sensitive data before sending to cloud.
        
        Returns:
            tuple: (final_json, secret_map)
        """
        try:
            anonymizer = get_anonymizer()
            result, secret_map = anonymizer.process_with_gemini(transcript, patient_name)
            
            # Add transcription metrics
            if '_generation_time' in result:
                gen_duration = result.pop('_generation_time')
                result["_metrics"] = {
                    "transcription_time": transcribe_duration,
                    "generation_time": gen_duration,
                    "total_time": round(transcribe_duration + gen_duration, 2),
                    "device": self.device
                }
            
            result["_model_file"] = "gemini-3-flash-preview"
            return result, secret_map
            
        except Exception as e:
            import traceback
            print(f"Gemini processing error: {traceback.format_exc()}")
            return {"error": f"Gemini Error: {str(e)}"}, {}

    def _process_single_task(self, session_id: int, selected_model: str = None, encryption_key: bytes = None):
        """Main processing logic for a single session"""
        db = SessionLocal()
        try:
            session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
            if not session_record:
                return

            if self.model is None:
                self.load_model()

            # 1. PRE-PROCESSING PHASE
            print(f"--- [Session {session_id}] Phase: Pre-processing ---")
            original_audio_path = session_record.audio_path
            audio_path = self._preprocess_audio(original_audio_path)
            
            # 2. TRANSCRIPTION PHASE
            print(f"--- [Session {session_id}] Phase: Transcribing ---")
            session_record.status = "transcribing"
            db.commit()

            start_transcribe = time.time()
            
            # Parámetros de Inferencia Optimizados:
            # beam_size=1 (Modo búsqueda rápida)
            # vad_filter=True (Detección de voz para ignorar silencios)
            segments, info = self.model.transcribe(
                audio_path, 
                beam_size=1, 
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            # entonces que mejoras podemos hacer al sistema, dame mejoras en cuestion de arquitectura, codigo, ui/ux
            transcript_text = ""
            for segment in segments:
                transcript_text += f"[{segment.start:.2f}s - {segment.end:.2f}s] {segment.text}\n"

            end_transcribe = time.time()
            transcribe_duration = round(end_transcribe - start_transcribe, 2)
            
            # Temporary storage (will be encrypted later)
            session_record.transcription_raw = transcript_text
            db.commit()

            # 2. ANALYSIS PHASE
            print(f"--- [Session {session_id}] Phase: Analyzing ---")
            session_record.status = "analyzing"
            db.commit()

            MAX_CHARS = 40000 
            safe_transcript = transcript_text
            if len(transcript_text) > MAX_CHARS:
                safe_transcript = transcript_text[:MAX_CHARS] + "\n[...]"

            patient_name = session_record.patient.full_name if (session_record.patient and session_record.patient.full_name) else "Paciente"
            
            # Determine AI provider and model
            final_json = {}
            secret_map = None
            
            if selected_model and selected_model.startswith("gemini:"):
                # === GEMINI FLOW (with anonymization) ===
                print(f"--- [Session {session_id}] Using Gemini (anonymized) ---")
                final_json, secret_map = self._process_with_gemini(
                    safe_transcript, patient_name, transcribe_duration
                )
            else:
                # === OLLAMA FLOW (local, no anonymization) ===
                model_name = selected_model.replace("ollama:", "") if selected_model else "gemma3:4b"
                print(f"--- [Session {session_id}] Using Ollama: {model_name} ---")
                final_json = self._process_with_ollama(
                    safe_transcript, model_name, transcribe_duration
                )
            
            # Store anonymization map if used
            if secret_map:
                session_record.anonymization_map = secret_map

            # 3. ENCRYPTION & CLEANUP PHASE
            print(f"--- [Session {session_id}] Phase: Securing ---")
            session_record.status = "securing"
            db.commit()

            if encryption_key:
                # Cifrar datos de texto
                session_record.transcription_raw = encrypt_data(transcript_text, encryption_key)
                session_record.structured_json = {"_encrypted": encrypt_data(json.dumps(final_json), encryption_key)}
                
                # Cifrar el archivo de audio (el que usamos para transcribir, que ya es Opus)
                enc_path = encrypt_file(audio_path, encryption_key)
                session_record.audio_path = enc_path

                # LIMPIEZA RIGUROSA:
                # 1. Eliminar el archivo original subido (si es distinto al de audio_path)
                if original_audio_path != audio_path and os.path.exists(original_audio_path):
                    os.remove(original_audio_path)
                
                # 2. Eliminar el archivo que se cifró (ya quedó guardado como .enc)
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            else:
                # Caso sin cifrado (emergencia/desarrollo)
                session_record.structured_json = final_json
                if original_audio_path != audio_path and os.path.exists(original_audio_path):
                    os.remove(original_audio_path)
                session_record.audio_path = audio_path

            session_record.status = "completed"
            db.commit()

        except Exception as e:
            db.rollback()
            import traceback
            print(f"Global worker error: {traceback.format_exc()}")
            session_record.status = "error"
            session_record.structured_json = {"error": str(e)}
            db.commit()
        finally:
            db.close()

# Export a function that creates/returns the manager
processor_manager = AudioProcessorManager()
