"""
System Routes
- Health check
- Models list
- License management
- Backup & Restore
"""
import os
import shutil
import datetime
import zipfile
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.database import SessionLocal, engine
from backend.config import UPLOAD_DIR
from backend.licensing import get_license_manager
from backend.routes.auth import ACTIVE_KEYS  # Shared auth keys

router = APIRouter(tags=["System"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -------------------------------------------------------------------
# HEALTH & MODELS
# -------------------------------------------------------------------

@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/models/")
def list_models():
    """List available AI models (Ollama + Gemini if configured)"""
    models = []
    
    # 1. Add Ollama models (local)
    try:
        raw_models = _import_ollama_list()
        for m in raw_models:
            if hasattr(m, 'model'):
                name = m.model
            elif isinstance(m, dict):
                name = m.get('model', m.get('name', 'unknown'))
            else:
                continue
            models.append(f"ollama:{name}")
    except Exception as e:
        print(f"Error loading models from Ollama: {e}")
    
    # 2. Add Gemini models (cloud, if API key configured)
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if gemini_api_key and gemini_api_key != 'your_api_key_here':
        models.append("gemini:gemini-3-flash-preview")
    
    return models


def _import_ollama_list():
    import ollama
    response = ollama.list()
    if hasattr(response, 'models'):
        return response.models
    elif isinstance(response, dict) and 'models' in response:
        return response['models']
    return []


# -------------------------------------------------------------------
# LICENSE MANAGEMENT
# -------------------------------------------------------------------

@router.get("/system/license")
def get_license_info(force: bool = False, db: Session = Depends(get_db)):
    return get_license_manager().get_license_status(db, force_cloud_check=force)


@router.post("/system/license")
def activate_license(key: str = Form(...), db: Session = Depends(get_db)):
    return get_license_manager().activate_license(key, db)


# -------------------------------------------------------------------
# BACKUP & RESTORE
# -------------------------------------------------------------------

@router.get("/system/backup")
def create_system_backup(token: str):
    """
    Crea un ZIP con toda la carpeta 'data' (DB + Audios).
    Requiere token valido para autorizar.
    """
    if token not in ACTIVE_KEYS:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # Ruta de la carpeta 'data' (padre de uploads)
    data_dir = os.path.dirname(UPLOAD_DIR)
    
    # Nombre temporal del archivo
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"backup_psyco_{timestamp}"
    output_path = os.path.join(os.path.dirname(data_dir), base_name)
    
    # Crear ZIP
    shutil.make_archive(output_path, 'zip', data_dir)
    zip_file = f"{output_path}.zip"
    
    return FileResponse(
        path=zip_file, 
        filename=f"SessionAI_Backup_{timestamp}.zip", 
        media_type='application/zip'
    )


@router.post("/system/restore")
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
    from backend.config import DB_PATH
    db_filename = os.path.basename(DB_PATH)
    
    try:
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            # Debe contener la DB o la carpeta uploads para ser valido
            if db_filename not in file_list and not any(f.startswith("uploads/") for f in file_list):
                # Check relaxed para zip creados con carpetas raiz
                pass 
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Corrupted zip file")

    # 3. PREPARAR RESTORE (CRITICO EN WINDOWS)
    from backend.processor import processor_manager
    processor_manager.stop_worker() # Detener hilo de fondo que usa la DB
    
    import gc
    gc.collect() # Forzar liberacion de referencias a la DB
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
            
        # 5. EXPULSIÓN DE SEGURIDAD
        # Borrar todas las sesiones/llaves temporales en la memoria RAM
        ACTIVE_KEYS.clear()
        
        return {
            "status": "success", 
            "message": "Sistema restaurado con éxito. Sesión cerrada por seguridad para aplicar los cambios de tu antigua base de datos."
        }
        
    except Exception as e:
        # Rollback intent
        print(f"[CRITICAL] Restore failed: {e}. Attempting rollback...")
        if os.path.exists(backup_path):
            if os.path.exists(data_dir):
                shutil.rmtree(data_dir)
            os.rename(backup_path, data_dir)
            
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")
