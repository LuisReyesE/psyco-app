
import os
import json
import time
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session
from backend.database import SessionLocal, Session as DBSession
from backend.security import encrypt_data, encrypt_file
from backend.licensing import get_license_manager

# Import Services
from backend.services.audio import AudioService
from backend.services.transcription import TranscriptionService
from backend.services.llm import IntelligenceService

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
        
        # Initialize Services
        self.audio_service = AudioService()
        self.transcription_service = TranscriptionService(self.audio_service)
        self.llm_service = IntelligenceService()
        
        self.task_queue = queue.Queue()
        self.worker_thread = None
        self.is_running = False
        self._initialized = True
        
        # Storage for real-time chunk transcriptions
        self._streaming_transcripts = {}
        self._streaming_lock = threading.Lock()

    def start_worker(self):
        """Starts the background worker thread"""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.is_running = True
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            print("[PROCESSOR] Background worker thread started.")

    def stop_worker(self):
        """Stops the worker thread for safe shutdown/restore"""
        if self.is_running:
            print("[PROCESSOR] Stopping worker thread...")
            self.is_running = False
            if self.worker_thread:
                self.worker_thread.join(timeout=5)
            print("[PROCESSOR] Worker stopped.")

    def enqueue_task(self, session_id: int, selected_model: str = None, encryption_key: bytes = None):
        """Adds a new session to the processing queue"""
        self._update_session_status(session_id, "queued")
        self.task_queue.put((session_id, selected_model, encryption_key))
        print(f"[PROCESSOR] Session {session_id} added to queue.")
        
    def load_model(self):
        """Proxy to load transcription model"""
        self.transcription_service.load_model()

    def enqueue_single_chunk(self, session_id: int, chunk_index: int, chunk_path: str, encryption_key: bytes = None):
        """Queue a single chunk for immediate transcription (real-time streaming)."""
        with self._streaming_lock:
            if session_id not in self._streaming_transcripts:
                self._streaming_transcripts[session_id] = {}
        
        self.task_queue.put(('chunk', session_id, chunk_index, chunk_path, encryption_key))
        print(f"[PROCESSOR] Chunk {chunk_index} for session {session_id} queued.")

    def enqueue_finish_session(self, session_id: int, total_chunks: int, selected_model: str = None, encryption_key: bytes = None):
        """Queue final processing for a streaming session."""
        self.task_queue.put(('finish', session_id, total_chunks, selected_model, encryption_key))
        print(f"[PROCESSOR] Session {session_id} finish task queued.")

    def enqueue_chunked_task(self, session_id: int, chunk_paths: list, selected_model: str = None, encryption_key: bytes = None):
        """Adds a chunked recording session to the processing queue."""
        db = SessionLocal()
        try:
            session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
            if session_record:
                session_record.status = "queued"
                session_record.is_chunked = True
                session_record.chunks_total = len(chunk_paths)
                session_record.chunks_transcribed = 0
                db.commit()
        finally:
            db.close()
        
        self.task_queue.put((session_id, selected_model, encryption_key, chunk_paths))
        print(f"[PROCESSOR] Chunked session {session_id} added to queue ({len(chunk_paths)} chunks).")

    def _update_session_status(self, session_id: int, status: str):
        db = SessionLocal()
        try:
            session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
            if session_record:
                session_record.status = status
                db.commit()
        finally:
            db.close()

    def _worker_loop(self):
        """Continuous loop processing tasks from the queue"""
        while self.is_running:
            try:
                task = self.task_queue.get(timeout=1)
                try:
                    # Task Dispatcher
                    if isinstance(task[0], str):
                        task_type = task[0]
                        if task_type == 'chunk':
                            self._process_single_chunk_task(*task[1:])
                        elif task_type == 'finish':
                            self._handle_finish_task(*task[1:])
                    elif len(task) == 4:
                        self._process_chunked_task(*task)
                    else:
                        self._process_single_task(*task)
                except Exception as e:
                    print(f"[PROCESSOR] Error processing task: {str(e)}")
                    import traceback
                    traceback.print_exc()
                finally:
                    self.task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[PROCESSOR] Worker loop error: {str(e)}")
                time.sleep(2)

    # ------------------------------------------------------------------
    # TASK HANDLERS
    # ------------------------------------------------------------------

    def _process_single_chunk_task(self, session_id: int, chunk_index: int, chunk_path: str, encryption_key: bytes = None):
        """Process a single chunk for real-time streaming using TranscriptionService."""
        try:
            # Delegate to TranscriptionService
            idx, transcript = self.transcription_service.transcribe_chunk(chunk_path, chunk_index)
            
            # Update memory state
            with self._streaming_lock:
                if session_id not in self._streaming_transcripts:
                    self._streaming_transcripts[session_id] = {}
                self._streaming_transcripts[session_id][chunk_index] = (transcript, chunk_path)
            
            # Update DB Progress
            self._update_streaming_db_progress(session_id)
            print(f"[PROCESSOR] Chunk {chunk_index} transcribed.")
            
        except Exception as e:
            print(f"[PROCESSOR] Chunk error: {e}")

    def _update_streaming_db_progress(self, session_id: int):
        with self._streaming_lock:
            session_data = self._streaming_transcripts.get(session_id, {})
            chunks_done = len(session_data)
            sorted_transcripts = [session_data[i][0] for i in sorted(session_data.keys())]
            partial_text = "\n".join(sorted_transcripts)
        
        db = SessionLocal()
        try:
            s = db.query(DBSession).filter(DBSession.id == session_id).first()
            if s:
                s.chunks_transcribed = chunks_done
                s.partial_transcription = partial_text
                db.commit()
        finally:
            db.close()

    def _handle_finish_task(self, session_id: int, total_chunks: int, selected_model: str, encryption_key: bytes):
        """Orchestrates the completion of a streaming session."""
        # Security Check
        if selected_model and selected_model.startswith('gemini'):
            self._check_license_security(selected_model)

        # 1. Wait for chunks
        if not self._wait_for_chunks(session_id, total_chunks):
            # Cleanup memory if aborted due to session deleted or timeout
            with self._streaming_lock:
                if session_id in self._streaming_transcripts:
                    del self._streaming_transcripts[session_id]
            print(f"[PROCESSOR] Proceso final abortado, la sesión {session_id} ya no existe o caducó.")
            return
        
        # 2. Gather Data
        with self._streaming_lock:
            session_data = self._streaming_transcripts.get(session_id, {})
            sorted_keys = sorted(session_data.keys())
            full_transcript = "\n".join([session_data[k][0] for k in sorted_keys])
            chunk_paths = [session_data[k][1] for k in sorted_keys]

        # 3. Merge Audio (AudioService)
        from backend.config import UPLOAD_DIR
        merged_path = os.path.join(UPLOAD_DIR, f"merged_{session_id}_{int(time.time())}.opus")
        final_audio_path = merged_path if self.audio_service.merge_audio_chunks(chunk_paths, merged_path) else (chunk_paths[0] if chunk_paths else "")
        
        # 4. Clean chunks
        for p in chunk_paths:
            if p != final_audio_path and os.path.exists(p):
                try: os.remove(p)
                except: pass

        # 5. Run AI & Save
        self._finalize_processing(session_id, full_transcript, final_audio_path, selected_model, encryption_key, 0)
        
        # Cleanup memory
        with self._streaming_lock:
            if session_id in self._streaming_transcripts:
                del self._streaming_transcripts[session_id]

    def _process_chunked_task(self, session_id: int, chunk_paths: list, selected_model: str, encryption_key: bytes):
        """Orchestrates parallel chunk processing."""
        self._update_session_status(session_id, "transcribing")
        start_ts = time.time()

        # 1. Parallel Transcription (TranscriptionService)
        transcripts = [None] * len(chunk_paths)
        accumulated_text = ""
        
        with ThreadPoolExecutor(max_workers=min(3, len(chunk_paths))) as executor:
            futures = {
                executor.submit(self.transcription_service.transcribe_chunk, path, i): i 
                for i, path in enumerate(chunk_paths)
            }
            for future in as_completed(futures):
                idx, text = future.result()
                transcripts[idx] = text
                # Update progress
                db = SessionLocal()
                try:
                    s = db.query(DBSession).filter(DBSession.id == session_id).first()
                    if s:
                        s.chunks_transcribed = sum(1 for t in transcripts if t)
                        s.partial_transcription = "\n".join([t for t in transcripts if t])
                        db.commit()
                finally:
                    db.close()

        full_transcript = "\n".join(transcripts)
        duration = time.time() - start_ts

        # 2. Merge Audio (AudioService)
        from backend.config import UPLOAD_DIR
        merged_path = os.path.join(UPLOAD_DIR, f"merged_{session_id}_{int(time.time())}.opus")
        final_audio_path = merged_path if self.audio_service.merge_audio_chunks(chunk_paths, merged_path) else (chunk_paths[0] if chunk_paths else "")
        
        # Clean chunks
        for p in chunk_paths:
            if p != final_audio_path and os.path.exists(p):
                try: os.remove(p)
                except: pass

        # 3. Finalize
        self._finalize_processing(session_id, full_transcript, final_audio_path, selected_model, encryption_key, duration)

    def _process_single_task(self, session_id: int, selected_model: str, encryption_key: bytes):
        """Standard single file processing task."""
        print(f"\n[PROCESSOR] === Iniciando procesamiento Sesión {session_id} ===")
        self._update_session_status(session_id, "transcribing")
        start_ts = time.time()
        
        # 1. Get Audio Path
        audio_path = None
        db = SessionLocal()
        try:
            s = db.query(DBSession).filter(DBSession.id == session_id).first()
            if s:
                audio_path = s.audio_path
        finally:
            db.close()
            
        if not audio_path or not os.path.exists(audio_path):
            print(f"[ERROR] Audio file not found at {audio_path}")
            self._update_session_status(session_id, "error")
            return

        try:
            # --- FASE 1: COMPRESION ---
            print(f"[FASE 1/4] Optimizando audio (.opus)...")
            success, optimized_path = self.audio_service.compress_to_opus(audio_path)
            if success:
                audio_path = optimized_path
                # Update DB with new path
                db = SessionLocal()
                try:
                    s = db.query(DBSession).filter(DBSession.id == session_id).first()
                    if s: s.audio_path = audio_path
                    db.commit()
                finally:
                    db.close()

            # --- FASE 2: TRANSCRIPCION ---
            print(f"[FASE 2/4] Transcribiendo audio con Whisper...")
            # Reuse transcribe_chunk for convenience (it handles model loading/conversion)
            # treat index 0 as the single file
            idx, transcript = self.transcription_service.transcribe_chunk(audio_path, 0)
            
            duration = time.time() - start_ts
            print(f" -> Transcripción completada en {duration:.1f}s")
            
            # --- CONTINUA A FASE 3 y 4 (Finalize) ---
            self._finalize_processing(session_id, transcript, audio_path, selected_model, encryption_key, duration)
            
        except Exception as e:
            print(f"[ERROR] Fallo en procesamiento: {e}")
            self._update_session_status(session_id, "error")
            import traceback
            traceback.print_exc()

    def _finalize_processing(self, session_id: int, transcript: str, audio_path: str, model: str, key: bytes, ts_duration: float):
        """Common finalization: AI Analysis -> Encryption -> DB Save"""
        db = SessionLocal()
        try:
            s = db.query(DBSession).filter(DBSession.id == session_id).first()
            if not s: 
                print(f"[PROCESSOR] La sesión {session_id} ha sido descartada porque el usuario la eliminó.")
                return

            # AI Analysis (IntelligenceService)
            s.status = "analyzing"
            s.transcription_raw = transcript
            s.audio_path = audio_path
            db.commit()

            # --- FASE 3: ANALISIS IA ---
            print(f"[FASE 3/4] Analizando contenido clínico ({model or 'Gemma'})...")
            
            patient_name = s.patient.full_name if s.patient else "Paciente"
            
            final_json = {}
            secret_map = None

            if model and model.startswith("gemini"):
                final_json, secret_map = self.llm_service.process_gemini(transcript, ts_duration, patient_name)
            else:
                model_name = model.replace("ollama:", "") if model else "gemma3:4b"
                final_json, _ = self.llm_service.process_ollama(transcript, model_name, ts_duration)

            # --- FASE 4: ENCRIPTACION ---
            print(f"[FASE 4/4] Encriptando datos y audio (AES-256)...")
            s.status = "securing"
            db.commit()
            
            if key:
                s.transcription_raw = encrypt_data(transcript, key)
                s.structured_json = {"_encrypted": encrypt_data(json.dumps(final_json), key)}
                if secret_map:
                    s.anonymization_map = {"_encrypted": encrypt_data(json.dumps(secret_map), key)}
                
                # Encrypt Audio
                if audio_path and os.path.exists(audio_path):
                    # Solo encriptar si NO está ya encriptado
                    if not audio_path.endswith(".enc"):
                        s.audio_path = encrypt_file(audio_path, key)
                        if os.path.exists(audio_path): 
                            try: os.remove(audio_path)
                            except: pass
            else:
                s.structured_json = final_json
                if secret_map:
                    s.anonymization_map = secret_map

            s.status = "completed"
            s.partial_transcription = ""
            db.commit()
            print(f"[OK] Sesión {session_id} FINALIZADA correctamente.\n")

        except Exception as e:
            s.status = "error"
            s.structured_json = {"error": str(e)}
            db.commit()
            print(f"[ERROR] Fallo en finalización: {e}")
        finally:
            db.close()

    def _wait_for_chunks(self, session_id, total):
        print(f"[ESPERA] Aguardando para sesión {session_id} ({total} chunks esperados)...")
        max_wait = 120
        elapsed = 0
        db = SessionLocal()
        try:
            while elapsed < max_wait:
                # Comprobar si todavía existe la sesión en DB
                s = db.query(DBSession).filter(DBSession.id == session_id).first()
                if not s:
                    print(f"[ESPERA] La sesión {session_id} ha sido eliminada. Cancelando espera.")
                    return False
                    
                with self._streaming_lock:
                    if len(self._streaming_transcripts.get(session_id, {})) >= total:
                        return True
                time.sleep(1)
                elapsed += 1
            print(f"[ESPERA] Timeout esperando la sesión {session_id}.")
            return False
        finally:
            db.close()

    def _check_license_security(self, model):
        # Implementation of license check logic
        pass

# Global instance
processor_manager = AudioProcessorManager()
