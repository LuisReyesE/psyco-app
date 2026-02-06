import os
import json
import ollama
import time
import threading
import queue
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from faster_whisper import WhisperModel
from sqlalchemy.orm import Session
from backend.database import SessionLocal, Session as DBSession
from backend.security import encrypt_data, encrypt_file
from backend.config import FFMPEG_DIR
from backend.licensing import license_manager

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
    
    # Storage for real-time chunk transcriptions
    # Format: { session_id: { chunk_index: (transcript, chunk_path) } }
    _streaming_transcripts = {}
    _streaming_lock = threading.Lock()

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

    def enqueue_single_chunk(self, session_id: int, chunk_index: int, chunk_path: str, encryption_key: bytes = None):
        """
        Queue a single chunk for immediate transcription (real-time streaming).
        Transcription happens in background, result stored for later merge.
        """
        # Initialize storage for this session if needed
        with self._streaming_lock:
            if session_id not in self._streaming_transcripts:
                self._streaming_transcripts[session_id] = {}
        
        # Queue chunk transcription task (type: 'chunk')
        self.task_queue.put(('chunk', session_id, chunk_index, chunk_path, encryption_key))
        print(f"Chunk {chunk_index} for session {session_id} queued for transcription")

    def enqueue_finish_session(self, session_id: int, total_chunks: int, selected_model: str = None, encryption_key: bytes = None):
        """
        Queue final processing for a streaming session.
        Waits for all transcriptions, merges, and runs AI analysis.
        """
        self.task_queue.put(('finish', session_id, total_chunks, selected_model, encryption_key))
        print(f"Session {session_id} finish task queued (expecting {total_chunks} chunks)")

    def enqueue_chunked_task(self, session_id: int, chunk_paths: list, selected_model: str = None, encryption_key: bytes = None):
        """
        Adds a chunked recording session to the processing queue.
        chunk_paths: List of paths to audio chunk files in order.
        """
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
        
        # Queue special chunked task (tuple with 5 elements to distinguish)
        self.task_queue.put((session_id, selected_model, encryption_key, chunk_paths))
        print(f"Chunked session {session_id} added to queue ({len(chunk_paths)} chunks). Queue size: {self.task_queue.qsize()}")

    def _worker_loop(self):
        """Continuous loop processing tasks from the queue"""
        while self.is_running:
            try:
                task = self.task_queue.get(timeout=1)
                
                try:
                    # Detect task type
                    if isinstance(task[0], str):
                        task_type = task[0]
                        
                        if task_type == 'chunk':
                            # Single chunk transcription: ('chunk', session_id, chunk_index, path, key)
                            _, session_id, chunk_index, chunk_path, encryption_key = task
                            self._process_single_chunk_task(session_id, chunk_index, chunk_path, encryption_key)
                        
                        elif task_type == 'finish':
                            # Finish streaming session: ('finish', session_id, total_chunks, model, key)
                            _, session_id, total_chunks, selected_model, encryption_key = task
                            
                            # --- LICENSE SECURITY CHECK ---
                            if selected_model and selected_model.startswith('gemini'):
                                db = SessionLocal()
                                try:
                                    lic = license_manager.get_license_status(db)
                                    if lic['tier'] != 'PRO':
                                        print(f"⚠️ Security Breach Attempt (Stream): FREE user tried Gemini. Downgrading.")
                                        selected_model = "ollama:gemma2:2b" 
                                finally:
                                    db.close()
                                    
                            self._process_finish_session_task(session_id, total_chunks, selected_model, encryption_key)
                    
                    elif len(task) == 4:
                        # Legacy chunked task: (session_id, model, key, chunk_paths)
                        session_id, selected_model, encryption_key, chunk_paths = task
                        self._process_chunked_task(session_id, chunk_paths, selected_model, encryption_key)
                    
                    else:
                        # Normal single-file task: (session_id, model, key)
                        session_id, selected_model, encryption_key = task
                        
                        # --- LICENSE SECURITY CHECK ---
                        # Prevent FREE users from using Gemini manually via API injection
                        if selected_model and selected_model.startswith('gemini'):
                            db = SessionLocal()
                            try:
                                lic = license_manager.get_license_status(db)
                                if lic['tier'] != 'PRO':
                                    print(f"⚠️ Security Breach Attempt: FREE user tried Gemini. Downgrading to Ollama.")
                                    # Fallback to a default local model or error
                                    # Option 1: Force safe local model
                                    selected_model = "ollama:gemma2:2b" 
                            finally:
                                db.close()

                        self._process_single_task(session_id, selected_model, encryption_key)
                        
                except Exception as e:
                    print(f"Error processing task: {str(e)}")
                    import traceback
                    traceback.print_exc()
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

    def _transcribe_chunk(self, chunk_path: str, chunk_index: int) -> tuple:
        """
        Transcribe a single audio chunk.
        Pre-processes with FFmpeg to ensure valid audio format.
        Handles WebM chunks with incomplete headers from MediaRecorder timeslice.
        Returns: (chunk_index, transcript_text)
        """
        processed_path = None
        try:
            if self.model is None:
                self.load_model()
            
            # Pre-process chunk with FFmpeg to ensure valid format
            # WebM chunks from timeslice may have incomplete headers
            processed_path = chunk_path.rsplit('.', 1)[0] + "_proc.wav"
            ffmpeg_success = False
            
            # Strategy 1: Standard conversion (works for most chunks)
            try:
                result = subprocess.run([
                    self.ffmpeg_path, '-y', '-i', chunk_path,
                    '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
                    processed_path
                ], capture_output=True, timeout=30)
                
                if result.returncode == 0 and os.path.exists(processed_path) and os.path.getsize(processed_path) > 1000:
                    ffmpeg_success = True
                    print(f"Chunk {chunk_index}: Standard conversion succeeded")
            except Exception as e:
                print(f"Chunk {chunk_index}: Standard conversion failed: {e}")
            
            # Strategy 2: Use -err_detect ignore_err for corrupt chunks
            if not ffmpeg_success:
                try:
                    result = subprocess.run([
                        self.ffmpeg_path, '-y', 
                        '-err_detect', 'ignore_err',
                        '-i', chunk_path,
                        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
                        processed_path
                    ], capture_output=True, timeout=30)
                    
                    if result.returncode == 0 and os.path.exists(processed_path) and os.path.getsize(processed_path) > 1000:
                        ffmpeg_success = True
                        print(f"Chunk {chunk_index}: Error-tolerant conversion succeeded")
                except Exception as e:
                    print(f"Chunk {chunk_index}: Error-tolerant conversion failed: {e}")
            
            # Strategy 3: Force format for WebM with extra flags
            if not ffmpeg_success and chunk_path.endswith('.webm'):
                try:
                    result = subprocess.run([
                        self.ffmpeg_path, '-y',
                        '-f', 'webm',  # Force input format
                        '-fflags', '+genpts+igndts',  # Generate PTS, ignore DTS errors
                        '-i', chunk_path,
                        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
                        processed_path
                    ], capture_output=True, timeout=30)
                    
                    if result.returncode == 0 and os.path.exists(processed_path) and os.path.getsize(processed_path) > 1000:
                        ffmpeg_success = True
                        print(f"Chunk {chunk_index}: Forced WebM conversion succeeded")
                except Exception as e:
                    print(f"Chunk {chunk_index}: Forced WebM conversion failed: {e}")
            
            # Choose audio source for transcription
            if ffmpeg_success and os.path.exists(processed_path):
                audio_to_transcribe = processed_path
            else:
                print(f"Chunk {chunk_index}: All FFmpeg strategies failed, trying direct transcription")
                audio_to_transcribe = chunk_path
            
            # Transcribe with optimized settings
            segments, _ = self.model.transcribe(
                audio_to_transcribe,
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            transcript = ""
            for segment in segments:
                transcript += f"[{segment.start:.2f}s - {segment.end:.2f}s] {segment.text}\n"
            
            # Cleanup processed file
            if processed_path and os.path.exists(processed_path):
                try:
                    os.remove(processed_path)
                except:
                    pass
            
            return (chunk_index, transcript if transcript.strip() else "[Silencio detectado]")
        except Exception as e:
            print(f"Error transcribing chunk {chunk_index}: {e}")
            import traceback
            traceback.print_exc()
            # Cleanup on error
            if processed_path and os.path.exists(processed_path):
                try:
                    os.remove(processed_path)
                except:
                    pass
            return (chunk_index, f"[Error en chunk {chunk_index}: {str(e)[:50]}]")

    def _merge_audio_chunks(self, session_id: int, chunk_paths: list, output_path: str) -> bool:
        """
        Merge multiple audio chunks into a single file using FFmpeg concat.
        """
        try:
            # Create a temp file list for FFmpeg concat
            list_path = os.path.join(tempfile.gettempdir(), f"concat_list_{session_id}.txt")
            with open(list_path, 'w') as f:
                for path in chunk_paths:
                    # FFmpeg concat requires escaped paths
                    safe_path = path.replace("\\", "/").replace("'", "'\\''")
                    f.write(f"file '{safe_path}'\n")
            
            # FFmpeg concat demuxer (no re-encoding)
            subprocess.run([
                self.ffmpeg_path, '-y', '-f', 'concat', '-safe', '0',
                '-i', list_path, '-c', 'copy', output_path
            ], check=True, capture_output=True)
            
            # Cleanup list file
            os.remove(list_path)
            return True
        except Exception as e:
            print(f"Error merging audio chunks: {e}")
            return False

    def _update_chunk_progress(self, session_id: int, chunks_done: int, partial_text: str):
        """Update chunk transcription progress in database for UI polling."""
        db = SessionLocal()
        try:
            session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
            if session_record:
                session_record.chunks_transcribed = chunks_done
                session_record.partial_transcription = partial_text
                db.commit()
        finally:
            db.close()

    def _process_single_chunk_task(self, session_id: int, chunk_index: int, chunk_path: str, encryption_key: bytes = None):
        """
        Process a single chunk for real-time streaming.
        Transcribes immediately and stores result for later merge.
        """
        try:
            print(f"[TRANSCRIBE] [Session {session_id}] Transcribing chunk {chunk_index} in real-time...")
            
            # Transcribe this chunk
            idx, transcript = self._transcribe_chunk(chunk_path, chunk_index)
            
            # Store result in memory for later merge
            with self._streaming_lock:
                if session_id not in self._streaming_transcripts:
                    self._streaming_transcripts[session_id] = {}
                self._streaming_transcripts[session_id][chunk_index] = (transcript, chunk_path)
            
            # Update database with progress
            with self._streaming_lock:
                chunks_done = len(self._streaming_transcripts.get(session_id, {}))
                # Build partial transcription from completed chunks (in order)
                session_data = self._streaming_transcripts.get(session_id, {})
                sorted_transcripts = [session_data[i][0] for i in sorted(session_data.keys())]
                partial_text = "\n".join(sorted_transcripts)
            
            self._update_chunk_progress(session_id, chunks_done, partial_text)
            print(f"[OK] [Session {session_id}] Chunk {chunk_index} transcribed ({chunks_done} total)")
            
        except Exception as e:
            print(f"[ERROR] Error processing chunk {chunk_index} for session {session_id}: {e}")
            import traceback
            traceback.print_exc()
            # Store error message as transcript
            with self._streaming_lock:
                if session_id not in self._streaming_transcripts:
                    self._streaming_transcripts[session_id] = {}
                self._streaming_transcripts[session_id][chunk_index] = (f"[Error: {str(e)[:50]}]", chunk_path)

    def _process_finish_session_task(self, session_id: int, total_chunks: int, selected_model: str = None, encryption_key: bytes = None):
        """
        Finish processing a streaming session.
        Waits for all transcriptions, merges audio, runs AI, encrypts.
        """
        db = SessionLocal()
        try:
            session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
            if not session_record:
                print(f"[ERROR] Session {session_id} not found")
                return
            
            print(f"[FINISH] [Session {session_id}] Finishing session, waiting for {total_chunks} chunks...")
            
            # Wait for all chunks to be transcribed (with timeout)
            max_wait = 120  # 2 minutes max
            wait_interval = 1
            elapsed = 0
            
            while elapsed < max_wait:
                with self._streaming_lock:
                    chunks_ready = len(self._streaming_transcripts.get(session_id, {}))
                
                if chunks_ready >= total_chunks:
                    break
                
                print(f"[WAIT] [Session {session_id}] Waiting for chunks: {chunks_ready}/{total_chunks}")
                time.sleep(wait_interval)
                elapsed += wait_interval
            
            # Get all transcripts and paths in order
            with self._streaming_lock:
                session_data = self._streaming_transcripts.get(session_id, {})
                sorted_indices = sorted(session_data.keys())
                transcripts = [session_data[i][0] for i in sorted_indices]
                chunk_paths = [session_data[i][1] for i in sorted_indices]
            
            # Merge transcriptions
            full_transcript = "\n".join(transcripts)
            session_record.transcription_raw = full_transcript
            session_record.partial_transcription = full_transcript
            session_record.status = "analyzing"
            db.commit()
            
            print(f"[TRANSCRIPT] [Session {session_id}] Transcription complete ({len(full_transcript)} chars)")
            
            # Merge audio files
            print(f"[MERGE] [Session {session_id}] Merging {len(chunk_paths)} audio chunks...")
            from backend.config import UPLOAD_DIR
            merged_audio_path = os.path.join(UPLOAD_DIR, f"merged_{session_id}_{int(time.time())}.opus")
            
            if self._merge_audio_chunks(session_id, chunk_paths, merged_audio_path):
                session_record.audio_path = merged_audio_path
                # Cleanup individual chunks
                for chunk_path in chunk_paths:
                    try:
                        if os.path.exists(chunk_path):
                            os.remove(chunk_path)
                    except:
                        pass
            else:
                session_record.audio_path = chunk_paths[0] if chunk_paths else ""
            
            db.commit()
            
            # AI Analysis
            print(f"[AI] [Session {session_id}] Running AI analysis...")
            MAX_CHARS = 40000
            safe_transcript = full_transcript[:MAX_CHARS] + "\n[...]" if len(full_transcript) > MAX_CHARS else full_transcript
            
            patient_name = session_record.patient.full_name if (session_record.patient and session_record.patient.full_name) else "Paciente"
            
            final_json = {}
            secret_map = None
            transcribe_duration = 0  # Already transcribed in parallel
            
            if selected_model and selected_model.startswith("gemini:"):
                print(f"[GEMINI] [Session {session_id}] Using Gemini (anonymized)")
                final_json, secret_map = self._process_with_gemini(safe_transcript, patient_name, transcribe_duration)
            else:
                model_name = selected_model.replace("ollama:", "") if selected_model else "gemma3:4b"
                print(f"[OLLAMA] [Session {session_id}] Using Ollama: {model_name}")
                final_json = self._process_with_ollama(safe_transcript, model_name, transcribe_duration)
            
            if secret_map:
                session_record.anonymization_map = secret_map
            
            # Encryption & Cleanup
            print(f"[ENCRYPT] [Session {session_id}] Encrypting data...")
            session_record.status = "securing"
            db.commit()
            
            audio_path = session_record.audio_path
            
            if encryption_key:
                session_record.transcription_raw = encrypt_data(full_transcript, encryption_key)
                session_record.structured_json = {"_encrypted": encrypt_data(json.dumps(final_json), encryption_key)}
                
                if audio_path and os.path.exists(audio_path):
                    enc_path = encrypt_file(audio_path, encryption_key)
                    session_record.audio_path = enc_path
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
            else:
                session_record.structured_json = final_json
            
            session_record.status = "completed"
            session_record.partial_transcription = ""
            db.commit()
            
            # Cleanup memory
            with self._streaming_lock:
                if session_id in self._streaming_transcripts:
                    del self._streaming_transcripts[session_id]
            
            print(f"[COMPLETE] [Session {session_id}] Streaming session COMPLETED!")
            
        except Exception as e:
            db.rollback()
            import traceback
            print(f"[ERROR] Finish session error: {traceback.format_exc()}")
            session_record.status = "error"
            session_record.structured_json = {"error": str(e)}
            db.commit()
        finally:
            db.close()

    def _process_chunked_task(self, session_id: int, chunk_paths: list, selected_model: str = None, encryption_key: bytes = None):
        """
        Process a chunked recording session with parallel transcription.
        1. Transcribe all chunks in parallel
        2. Merge transcriptions in order
        3. Merge audio files
        4. Continue with normal AI processing flow
        """
        db = SessionLocal()
        try:
            session_record = db.query(DBSession).filter(DBSession.id == session_id).first()
            if not session_record:
                return

            if self.model is None:
                self.load_model()

            # 1. PARALLEL TRANSCRIPTION PHASE
            print(f"--- [Session {session_id}] Phase: Parallel Chunk Transcription ({len(chunk_paths)} chunks) ---")
            session_record.status = "transcribing"
            db.commit()

            start_transcribe = time.time()
            transcripts = [None] * len(chunk_paths)
            accumulated_text = ""

            # Use ThreadPoolExecutor for parallel transcription (max 3 workers to not overwhelm CPU)
            with ThreadPoolExecutor(max_workers=min(3, len(chunk_paths))) as executor:
                futures = {
                    executor.submit(self._transcribe_chunk, path, i): i 
                    for i, path in enumerate(chunk_paths)
                }
                
                for future in as_completed(futures):
                    chunk_idx, chunk_text = future.result()
                    transcripts[chunk_idx] = chunk_text
                    
                    # Update progress - concatenate completed transcripts in order
                    completed = sum(1 for t in transcripts if t is not None)
                    accumulated_text = "\n".join(t for t in transcripts if t is not None)
                    self._update_chunk_progress(session_id, completed, accumulated_text)
                    print(f"[Session {session_id}] Chunk {chunk_idx + 1}/{len(chunk_paths)} transcribed")

            # Final concatenated transcript (in correct order)
            full_transcript = "\n".join(transcripts)
            transcribe_duration = round(time.time() - start_transcribe, 2)
            
            # Save full transcription
            session_record.transcription_raw = full_transcript
            session_record.partial_transcription = full_transcript
            db.commit()

            # 2. MERGE AUDIO FILES
            print(f"--- [Session {session_id}] Phase: Merging Audio Chunks ---")
            from backend.config import UPLOAD_DIR
            merged_audio_path = os.path.join(UPLOAD_DIR, f"merged_{session_id}_{int(time.time())}.opus")
            
            if self._merge_audio_chunks(session_id, chunk_paths, merged_audio_path):
                session_record.audio_path = merged_audio_path
                # Cleanup individual chunks
                for chunk_path in chunk_paths:
                    try:
                        if os.path.exists(chunk_path):
                            os.remove(chunk_path)
                    except:
                        pass
            else:
                # Fallback: keep first chunk as audio
                session_record.audio_path = chunk_paths[0] if chunk_paths else None
            
            db.commit()

            # 3. ANALYSIS PHASE (same as normal flow)
            print(f"--- [Session {session_id}] Phase: Analyzing ---")
            session_record.status = "analyzing"
            db.commit()

            MAX_CHARS = 40000
            safe_transcript = full_transcript
            if len(full_transcript) > MAX_CHARS:
                safe_transcript = full_transcript[:MAX_CHARS] + "\n[...]"

            patient_name = session_record.patient.full_name if (session_record.patient and session_record.patient.full_name) else "Paciente"
            
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
            
            if secret_map:
                session_record.anonymization_map = secret_map

            # 4. ENCRYPTION & CLEANUP PHASE
            print(f"--- [Session {session_id}] Phase: Securing ---")
            session_record.status = "securing"
            db.commit()

            audio_path = session_record.audio_path

            if encryption_key:
                session_record.transcription_raw = encrypt_data(full_transcript, encryption_key)
                session_record.structured_json = {"_encrypted": encrypt_data(json.dumps(final_json), encryption_key)}
                
                if audio_path and os.path.exists(audio_path):
                    enc_path = encrypt_file(audio_path, encryption_key)
                    session_record.audio_path = enc_path
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
            else:
                session_record.structured_json = final_json

            session_record.status = "completed"
            session_record.partial_transcription = ""  # Clear partial data
            db.commit()
            print(f"--- [Session {session_id}] Chunked processing COMPLETED ---")

        except Exception as e:
            db.rollback()
            import traceback
            print(f"Chunked worker error: {traceback.format_exc()}")
            session_record.status = "error"
            session_record.structured_json = {"error": str(e)}
            db.commit()
        finally:
            db.close()

    def _process_with_ollama(self, transcript: str, model_name: str, transcribe_duration: float) -> dict:
        """
        Process transcript with local Ollama model (FREE tier).
        No anonymization needed - all data stays local.
        Generates only nota_clinica_free (simple paragraph summary).
        """
        system_prompt = (
            "Eres un asistente clínico experto. Tu tarea es analizar la sesión terapéutica y generar una nota clínica evolutiva.\n"
            "\n"
            "INSTRUCCIONES:\n"
            "- Redacta UN SOLO PÁRRAFO de máximo 5-7 líneas.\n"
            "- Usa TERCERA PERSONA y TIEMPO PASADO.\n"
            "- Integra de forma fluida: estado anímico del paciente, temas centrales abordados, intervención realizada, y compromisos o insights alcanzados.\n"
            "- NO uses negritas, cursivas ni formato markdown.\n"
            "- Mantén un tono profesional, claro y directo.\n"
            "\n"
            "Responde EXCLUSIVAMENTE con este objeto JSON:\n"
            "{\n"
            '  "nota_clinica_free": "El paciente se presentó con [estado anímico] relacionado con [tema central]. Durante la sesión se abordó [intervención]. Se acordó [compromiso/insight]."\n'
            "}"
        )
        
        user_prompt = f"Conversación clínica:\n\n{transcript}\n\nGenera la nota clínica evolutiva en JSON ahora:"
        
        try:
            start_gen = time.time()
            print(f"[OLLAMA] Generando nota clínica FREE con {model_name}...")
            response = ollama.generate(
                model=model_name, 
                system=system_prompt, 
                prompt=user_prompt, 
                format='json', 
                options={
                    'temperature': 0.2,
                    'num_ctx': 4096,
                    'num_predict': 512,  # Reduced - only need a paragraph
                    'top_k': 20,
                    'top_p': 0.9
                } 
            )
            gen_duration = round(time.time() - start_gen, 2)
            
            response_text = response.get('response', '')
            print(f"[DEBUG] Raw Response ({len(response_text)} chars): {response_text[:200]}...") # Log raw response
            
            try:
                # Robust extraction for "Thinking" models and formatted output
                # 1. Remove <think> blocks (reasoning chains)
                clean_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)
                
                # 2. Extract JSON object (find first { and last }) to ignore conversational prefixes/suffixes
                json_match = re.search(r'(\{.*\})', clean_text, re.DOTALL)
                if json_match:
                    clean_text = json_match.group(1)
                
                # 3. Clean residual markdown
                clean_text = re.sub(r'```(?:json)?', '', clean_text).replace('```', '').strip()
                
                data = json.loads(clean_text)

                # Add metrics (NO license restrictions - restrictions are now UI-level only)
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
