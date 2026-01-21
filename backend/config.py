import os
import sys

def get_base_paths():
    """
    Returns (APP_DIR, DATA_DIR)
    APP_DIR: Where code and static assets (ffmpeg) live
    DATA_DIR: Where persistent user data live (DB, uploads)
    """
    # 1. Base Application Directory (Code/Static Assets)
    if getattr(sys, 'frozen', False):
        APP_DIR = os.path.dirname(sys.executable)
    else:
        # Parent of this config file (which is in backend/)
        APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    # 2. Data Directory (Writeable)
    # Force usage of local 'data' directory to avoid root pollution
    # 2. Data Directory (Writeable)
    # Force usage of local 'data' directory to avoid root pollution
    if os.environ.get('SESSIONAI_ROOT'):
        DATA_DIR = os.environ.get('SESSIONAI_ROOT', '')
    else:
        DATA_DIR = os.path.join(APP_DIR, "data")
        
    return APP_DIR, DATA_DIR

APP_DIR, DATA_DIR = get_base_paths()
FFMPEG_DIR = os.path.join(APP_DIR, "ffmpeg-tools")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "psyco_app.db")

# Create initial directories
for d in [DATA_DIR, UPLOAD_DIR]:
    os.makedirs(d, exist_ok=True)
