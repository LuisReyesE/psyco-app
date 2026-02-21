
"""
Servicio de Transcripción de Audio
Responsable de cargar y ejecutar el modelo de Whisper de forma eficiente.
"""
import os
import time
import threading
from backend.services.audio import AudioService

class TranscriptionService:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TranscriptionService, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, audio_service: AudioService = None):
        if self._initialized:
            return
        
        self.model = None
        self.device = None
        self.compute_type = None
        self.audio_service = audio_service
        self._initialized = True

    def load_model(self):
        """Lazy loads the Whisper model into RAM/VRAM"""
        if self.model is None:
            import torch
            from faster_whisper import WhisperModel
            
            # Auto-detect device if not yet done
            if self.device is None:
                if torch.cuda.is_available():
                    self.device = "cuda"
                    self.compute_type = "float16" # FP16 is faster on GPU
                    print("[TRANSCRIPTION] Hardware detectado: GPU (CUDA activado)")
                else:
                    self.device = "cpu"
                    self.compute_type = "int8"
                    print("[TRANSCRIPTION] Hardware detectado: CPU")
                    
            print(f"[TRANSCRIPTION] Loading Whisper model into {self.device.upper()}...")
            start = time.time()
            
            model_args = {
                "device": self.device,
                "compute_type": self.compute_type
            }
            
            if self.device == "cpu":
                # CTranslate2 por defecto limita a 4 hilos. Configurarlo para usar todos reduce la latencia.
                threads = os.cpu_count() or 4
                model_args["cpu_threads"] = max(threads, 4)
                print(f"[TRANSCRIPTION] Usando {model_args['cpu_threads']} hilos para acelerar transcripción")
                
            self.model = WhisperModel("small", **model_args)
            end = time.time()
            print(f"[TRANSCRIPTION] Model loaded in {round(end - start, 2)}s using {self.device}")

    def transcribe_chunk(self, chunk_path: str, chunk_index: int) -> tuple:
        """
        Transcribe a single audio chunk using Whisper.
        Handles format conversion internally.
        
        Returns:
            (chunk_index, transcript_text)
        """
        if not self.model:
            self.load_model()
            
        # 1. Convert/Ensure clean WAV
        processed_path = chunk_path
        created_temp = False
        
        if self.audio_service:
            success, proc_path = self.audio_service.convert_chunk_to_wav(chunk_path, chunk_index)
            if success:
                processed_path = proc_path
                created_temp = True
            else:
                print(f"[TRANSCRIPTION] Chunk {chunk_index}: Failed audio conversion, trying raw transcription")
        
        # 2. Transcribe
        try:
            segments, _ = self.model.transcribe(
                processed_path,
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            transcript = ""
            for segment in segments:
                transcript += f"[{segment.start:.2f}s - {segment.end:.2f}s] {segment.text}\n"
            
            transcript = transcript.strip() if transcript.strip() else "[Silencio detectado]"
            return (chunk_index, transcript)
            
        except Exception as e:
            print(f"[TRANSCRIPTION] Error processing chunk {chunk_index}: {e}")
            return (chunk_index, f"[Error en chunk {chunk_index}: {str(e)[:50]}]")
            
        finally:
            # 3. Cleanup temp file if created
            if created_temp and processed_path != chunk_path and os.path.exists(processed_path):
                try:
                    os.remove(processed_path)
                except:
                    pass
