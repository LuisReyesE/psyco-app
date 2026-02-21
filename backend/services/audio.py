
"""
Servicio de Gestión de Audio
Responsable de la manipulación, conversión y limpieza de archivos de audio.
"""
import os
import subprocess
import shutil
import tempfile
from backend.config import FFMPEG_DIR

class AudioService:
    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()

    def _find_ffmpeg(self):
        """Locates ffmpeg.exe in the tools temporary/local folder"""
        # Start searching from the configured FFMPEG_DIR
        print(f"[AUDIO-SERVICE] Searching for FFmpeg in: {FFMPEG_DIR}")
        
        if not os.path.exists(FFMPEG_DIR):
            print(f"[AUDIO-SERVICE] WARN: FFMPEG_DIR not found at {FFMPEG_DIR}")
            return "ffmpeg"
            
        for root, _, files in os.walk(FFMPEG_DIR):
            if "ffmpeg.exe" in files:
                found_path = os.path.join(root, "ffmpeg.exe")
                print(f"[AUDIO-SERVICE] Local FFmpeg found: {found_path}")
                return found_path
        
        print(f"[AUDIO-SERVICE] WARN: Local FFmpeg not found. Falling back to system PATH.")
        return "ffmpeg"

    def merge_audio_chunks(self, chunk_paths: list, output_path: str) -> bool:
        """
        Merge multiple audio chunks into a single file using FFmpeg concat.
        """
        if not chunk_paths:
            print("[AUDIO-SERVICE] Ningún audio chunk para unir.")
            return False
            
        if len(chunk_paths) == 1:
            # Solo un chunk, no es necesario hacer merge
            return False

        try:
            # Create a temp file list for FFmpeg concat
            fd, list_path = tempfile.mkstemp(suffix=".txt", prefix=f"concat_list_")
            os.close(fd)
            
            with open(list_path, 'w', encoding='utf-8') as f:
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
            if os.path.exists(list_path):
                os.remove(list_path)
            return True
        except Exception as e:
            print(f"[AUDIO-SERVICE] Error merging audio chunks: {e}")
            if os.path.exists(list_path):
                try: os.remove(list_path)
                except: pass
            return False

    def convert_chunk_to_wav(self, chunk_path: str, chunk_index: int) -> tuple:
        """
        Robustly converts (or validates) an audio chunk for transcription.
        Returns: (success: bool, output_path: str)
        """
        # Whisper (CTranslate2/PyAV) handles WebM/Opus/Ogg natively.
        # Bypass explicit FFmpeg conversion to save 1-2 seconds of latency per chunk.
        ext = chunk_path.lower().split('.')[-1]
        if ext in ['webm', 'ogg', 'opus', 'wav']:
            label = f"Chunk {chunk_index}" if "chunk" in chunk_path else "Archivo original"
            print(f"[AUDIO-SERVICE] {label}: Omitiendo conversión de formato ({ext}), enviando de forma directa a Whisper.")
            return True, chunk_path

        processed_path = chunk_path.rsplit('.', 1)[0] + "_proc.wav"
        
        # Strategy 1: Standard conversion
        try:
            result = subprocess.run([
                self.ffmpeg_path, '-y', '-i', chunk_path,
                '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
                processed_path
            ], capture_output=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(processed_path) and os.path.getsize(processed_path) > 1000:
                return True, processed_path
        except Exception as e:
            pass # Keep trying other strategies
        
        # Strategy 2: Error tolerant (ignore_err)
        try:
            result = subprocess.run([
                self.ffmpeg_path, '-y', 
                '-err_detect', 'ignore_err',
                '-i', chunk_path,
                '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
                processed_path
            ], capture_output=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(processed_path) and os.path.getsize(processed_path) > 1000:
                print(f"[AUDIO-SERVICE] Chunk {chunk_index}: Error-tolerant conversion used")
                return True, processed_path
        except Exception as e:
            pass

        # Strategy 3: Local WebM force format (fixes MediaRecorder issues)
        if chunk_path.endswith('.webm'):
            try:
                result = subprocess.run([
                    self.ffmpeg_path, '-y',
                    '-f', 'webm',
                    '-fflags', '+genpts+igndts',
                    '-i', chunk_path,
                    '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
                    processed_path
                ], capture_output=True, timeout=30)
                
                if result.returncode == 0 and os.path.exists(processed_path) and os.path.getsize(processed_path) > 1000:
                    print(f"[AUDIO-SERVICE] Chunk {chunk_index}: Forced WebM conversion used")
                    return True, processed_path
            except Exception as e:
                pass

        return False, chunk_path # Fallback to original if everything fails

    def compress_to_opus(self, input_path: str) -> tuple:
        """
        Compresses an audio file to OPUS format for storage efficiency.
        Returns: (success: bool, output_path: str)
        """
        try:
            output_path = input_path.rsplit('.', 1)[0] + ".opus"
            
            # If already opus and just needs verification/copy, treat as success or re-encode if needed.
            # For simplicity, if input is already .opus, we check if we want to re-encode slightly or keep it.
            # Let's force re-encode to ensure standard bitrate/vbr unless paths match.
            if input_path == output_path:
                # Create a temp file to re-encode into, then move back
                temp_output = input_path.rsplit('.', 1)[0] + "_temp.opus"
                output_path = temp_output

            print(f"[AUDIO-SERVICE] Compressing to OPUS: {input_path} -> {output_path}")
            
            result = subprocess.run([
                self.ffmpeg_path, '-y', 
                '-i', input_path,
                '-c:a', 'libopus', 
                '-b:a', '32k', 
                '-vbr', 'on',
                '-compression_level', '10',
                output_path
            ], capture_output=True, timeout=120) # Increased timeout for larger files
            
            if result.returncode == 0 and os.path.exists(output_path):
                # If we used a temp file (overwrite case), replace original
                if output_path.endswith("_temp.opus"):
                    original_name = output_path.replace("_temp.opus", ".opus")
                    shutil.move(output_path, original_name)
                    output_path = original_name

                # Remove original legacy file if different extension
                if input_path != output_path and os.path.exists(input_path):
                    try: os.remove(input_path)
                    except: pass
                
                return True, output_path
            else:
                print(f"[AUDIO-SERVICE] OPUS compression failed: {result.stderr.decode()}")
                # Cleanup temp if failed
                if output_path.endswith("_temp.opus") and os.path.exists(output_path):
                    try: os.remove(output_path)
                    except: pass
                return False, input_path
                
        except Exception as e:
            print(f"[AUDIO-SERVICE] Error compressing to OPUS: {e}")
            return False, input_path

