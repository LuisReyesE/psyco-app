import os
import threading
import webbrowser
import pystray
from PIL import Image
import uvicorn
import sys

# Agregar el directorio raíz al path para que encuentre el backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.main import app

def launch_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

def open_app(icon, item):
    webbrowser.open("http://localhost:8000/frontend/index.html")

def on_quit(icon, item):
    icon.stop()
    os._exit(0)

def create_vibrant_icon():
    # Crear una imagen con degradado para un look premium
    from PIL import ImageDraw
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Dibujar un círculo vibrante (Morado/Azul Neón como la App)
    for i in range(size):
        color = (100 - i, 50, 255 - i) # Degradado
        draw.ellipse([i//2, i//2, size-i//2, size-i//2], outline=color)
    
    # Dibujar una "S" blanca estilizada en el centro
    # (Si no hay fuentes, dibujamos una forma básica)
    draw.text((size//4, size//10), "S", fill="white", align="center", font_size=40)
    
    return image

def main():
    # Iniciar servidor en segundo plano
    server_thread = threading.Thread(target=launch_server, daemon=True)
    server_thread.start()

    # Intentar cargar icono original, si falla o queremos el premium:
    # Intentar cargar icono original desde la nueva ubicación de assets
    icon_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets", "branding", "favicon.ico")
    try:
        if os.path.exists(icon_path):
            image = Image.open(icon_path).convert("RGBA")
        else:
            image = create_vibrant_icon()
    except:
        image = create_vibrant_icon()

    # Crear el menú del icono
    menu = pystray.Menu(
        pystray.MenuItem("Abrir Session AI", open_app),
        pystray.MenuItem("Salir", on_quit)
    )

    icon = pystray.Icon("Session AI", image, "Session AI", menu)
    
    # Abrir la web automáticamente al iniciar
    webbrowser.open(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")))
    
    icon.run()

if __name__ == "__main__":
    main()
