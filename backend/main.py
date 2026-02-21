"""
Session AI Backend - Main Application
======================================
FastAPI application with modular routes.

This file only handles:
- App initialization
- Middleware configuration
- Lifespan events (startup/shutdown)
- Router registration
"""
import uvicorn
import sys
import os

# Fuerza codificación UTF-8 para evitar errores de Unicode en Windows (cp1252)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Add project root to sys.path to allow 'from backend.xxx' imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Local imports
from backend.database import engine, Base
from backend.processor import processor_manager
from backend.config import UPLOAD_DIR

# Import routers
from backend.routes import include_routers


# -------------------------------------------------------------------
# DATABASE INITIALIZATION
# -------------------------------------------------------------------

# Create tables if not exist
Base.metadata.create_all(bind=engine)


# -------------------------------------------------------------------
# LIFESPAN EVENTS
# -------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    print("--- Session AI Backend Starting ---")
    print(f"DEBUG: DATA_DIR = {os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))}")
    print(f"DEBUG: UPLOAD_DIR = {UPLOAD_DIR}")
    
    # 1. Avoids delay on first API request (moved to background warmup)
    
    # 2. Start Background Worker Thread
    processor_manager.start_worker()

    # 3. Warmup Heavy Models (Whisper + Anonymizer) in Background
    # Allows app to start instantly while models load silently in parallel
    import threading
    
    def background_warmup():
        print("[WARMUP] Iniciando carga de modelos en segundo plano...")
        try:
            # A. Whisper (Transcription)
            processor_manager.load_model()
            
            # B. LLM/Anonymizer (Analysis)
            processor_manager.llm_service.anonymizer.warmup()
            
            # C. License Manager
            from backend.licensing import get_license_manager
            print("[WARMUP] Inicializando gestor de licencias en segundo plano...")
            get_license_manager()
            
            print("[WARMUP] Todos los modelos están listos en RAM. 🚀")
        except Exception as e:
            print(f"[WARMUP ERROR] {e}")

    threading.Thread(target=background_warmup, daemon=True).start()

    yield
    
    # Shutdown
    print("--- Session AI Backend Stopping ---")


# -------------------------------------------------------------------
# APP INITIALIZATION
# -------------------------------------------------------------------

app = FastAPI(
    title="Session AI",
    description="Clinical session transcription and analysis",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
include_routers(app)


# -------------------------------------------------------------------
# ENTRY POINT
# -------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
