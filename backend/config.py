import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_base_paths():
    """
    Returns (APP_DIR, DATA_DIR)
    APP_DIR: Where code and static assets (ffmpeg) live
    DATA_DIR: Where persistent user data live (DB, uploads)
    
    Modes:
    - Packaged (electron-builder): Uses SESSIONAI_ROOT env var set by Electron
    - Development (pnpm start): Uses local ./data folder
    """
    # 1. Base Application Directory (Code/Static Assets)
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        APP_DIR = os.path.dirname(sys.executable)
    else:
        # Running from source - parent of backend/ folder
        APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    # 2. Data Directory (Writeable)
    # Priority:
    # - Development (running from source): Always use ./data
    # - Packaged (frozen executable): Use SESSIONAI_ROOT from Electron
    if getattr(sys, 'frozen', False):
        # Packaged mode: Electron sets SESSIONAI_ROOT to AppData
        DATA_DIR = os.environ.get('SESSIONAI_ROOT', os.path.join(APP_DIR, "data"))
    else:
        # Development mode: Always use local ./data folder
        DATA_DIR = os.path.join(APP_DIR, "data")
        
    return APP_DIR, DATA_DIR

# Initialize paths
APP_DIR, DATA_DIR = get_base_paths()
FFMPEG_DIR = os.path.join(APP_DIR, "ffmpeg-tools")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
DB_PATH = os.path.join(DATA_DIR, "psyco_app.db")

# Create initial directories
for d in [DATA_DIR, UPLOAD_DIR]:
    os.makedirs(d, exist_ok=True)

# Development Flag (True if running from source, False if packaged)
IS_DEV = not getattr(sys, 'frozen', False)
