import os
import json
import ollama
import time
import threading
import queue
import ctranslate2
import subprocess
from faster_whisper import WhisperModel
from sqlalchemy.orm import Session
from backend.database import SessionLocal, Session as DBSession
from backend.security import encrypt_data, encrypt_file

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
        self._initialized = True
        
        # Hardware detection
        cuda_available = False
        try:
            cuda_available = ctranslate2.get_cuda_device_count() > 0
        except:
            pass
            
        self.device = "cuda" if cuda_available else "cpu"
        self.compute_type = "float16" if self.device == "cuda" else "int8"
        
        print(f"--- AudioProcessorManager Initialized ---")
        print(f"Detection: {'GPU (CUDA)' if self.device == 'cuda' else 'CPU'}")

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

    def _compress_audio(self, input_path):
        """Compresses audio to m4a using FFmpeg"""
        output_path = input_path.rsplit('.', 1)[0] + ".m4a"
        print(f"Compressing {input_path} to {output_path}...")
        try:
            # -y overwrite, -i input, -c:a aac codec, -b:a 64k bitrate (enough for voice)
            subprocess.run(['ffmpeg', '-y', '-i', input_path, '-c:a', 'aac', '-b:a', '64k', output_path], 
                           check=True, capture_output=True)
            return output_path
        except Exception as e:
            print(f"Compression error: {e}")
            return None

    def _process_single_task(self, session_id: int, selected_model: str = None, encryption_key: bytes = None):
        """Main processing logic for a single session"""
        db = SessionLocal()
        try:
            session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
            if not session_record:
                return

            if self.model is None:
                self.load_model()

            # 1. TRANSCRIPTION PHASE
            print(f"--- [Session {session_id}] Phase: Transcribing ---")
            session_record.status = "transcribing"
            db.commit()

            audio_path = session_record.audio_path
            start_transcribe = time.time()
            
            segments, info = self.model.transcribe(audio_path, beam_size=5)
            
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

            model_name = selected_model.replace("ollama:", "") if selected_model else "gemma3:4b"
            patient_name = session_record.patient.full_name if (session_record.patient and session_record.patient.full_name) else "Paciente"
            
            system_prompt = (
                "Eres un asistente psicológico experto. Tu tarea es redactar una nota de evolución clínica en un ÚNICO PÁRRAFO de PROSA CONTINUA.\n"
                "ES MUY IMPORTANTE: NO uses formato JSON dentro del texto. NO uses llaves {}, ni corchetes, ni comillas innecesarias.\n"
                "Debes responder EXCLUSIVAMENTE con un objeto JSON válido con esta única clave:\n"
                '{"nota_clinica": "El texto del párrafo aquí..."}'
            )
            
            user_prompt = f"Conversación con {patient_name}:\n\n{safe_transcript}"
            
            final_json = {}
            try:
                start_gen = time.time()
                response = ollama.generate(model=model_name, system=system_prompt, prompt=user_prompt, format='json', options={'temperature': 0.1})
                gen_duration = round(time.time() - start_gen, 2)
                
                response_text = response.get('response', '')
                try:
                    data = json.loads(response_text)
                    data["_metrics"] = {
                        "transcription_time": transcribe_duration,
                        "generation_time": gen_duration,
                        "total_time": round(transcribe_duration + gen_duration, 2),
                        "device": self.device
                    }
                    data["_model_file"] = model_name
                    final_json = data
                except:
                    final_json = {"nota_clinica": "Error formateando respuesta", "_raw": response_text}
            except Exception as e:
                final_json = {"error": f"Ollama Error: {str(e)}"}

            # 3. ENCRYPTION & COMPRESSION PHASE
            print(f"--- [Session {session_id}] Phase: Securing ---")
            session_record.status = "securing"
            db.commit()

            if encryption_key:
                # Encrypt text data
                session_record.transcription_raw = encrypt_data(transcript_text, encryption_key)
                session_record.structured_json = {"_encrypted": encrypt_data(json.dumps(final_json), encryption_key)}
                
                # Compress and then encrypt audio
                m4a_path = self._compress_audio(audio_path)
                if m4a_path:
                    enc_path = encrypt_file(m4a_path, encryption_key)
                    session_record.audio_path = enc_path
                    # Delete original wav if still exists
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                else:
                    # If compression fails, encrypt original wav as fallback
                    enc_path = encrypt_file(audio_path, encryption_key)
                    session_record.audio_path = enc_path
            else:
                # If no key (shouldn't happen with Option B), just save and compress normally
                session_record.structured_json = final_json
                m4a_path = self._compress_audio(audio_path)
                if m4a_path:
                    session_record.audio_path = m4a_path
                    if os.path.exists(audio_path): os.remove(audio_path)

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
