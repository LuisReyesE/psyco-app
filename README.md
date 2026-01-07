# ScribeClínico AI - Gestión Psicoterapéutica Local

ScribeClínico AI es una herramienta local diseñada para psicólogos que automatiza la transcripción de sesiones y la generación de notas de evolución clínica. Utiliza modelos de Inteligencia Artificial de vanguardia optimizados para funcionar de manera privada y segura en hardware personal.

## ✨ Características Principales
- **Privacidad Total:** Los audios y textos nunca salen de tu computadora.
- **Transcripción Inteligente:** Usa `Faster-Whisper` para convertir voz a texto con alta precisión.
- **Resumen Clínico:** Genera notas de evolución estructuradas usando modelos como `Gemma 3` vía Ollama.
- **Gestión de Pacientes:** Historial completo de sesiones por paciente.
- **Multi-modelo:** Permite elegir entre diferentes modelos de Ollama instalados localmente.

## 📂 Estructura del Proyecto
- `/backend`: Servidor API construido con FastAPI.
- `/frontend`: Interfaz de usuario moderna e interactiva (HTML/JS/Tailwind).
- `/data`: **(Vital)** Contiene la base de datos SQLite y los archivos de audio subidos.
- `/ffmpeg-tools`: Herramientas de sistema para el procesamiento de audio.

## 🚀 Instalación y Configuración

### 1. Requisitos Previos
- **Python 3.9+**
- **Ollama:** Debes tener Ollama instalado y corriendo en tu sistema.
  - Asegúrate de haber descargado al menos un modelo (ej: `ollama pull gemma3:4b`).
- **FFmpeg:** Ya configurado automáticamente dentro de la carpeta `ffmpeg-tools`.

### 2. Configuración del Backend
1. Crea un entorno virtual:
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```
2. Instala las dependencias:
   ```powershell
   pip install -r requirements.txt
   ```

### 3. Ejecución
1. **Iniciar el Servidor:**
   ```powershell
   cd backend
   python main.py
   ```
2. **Abrir la Aplicación:**
   Simplemente abre `frontend/index.html` en tu navegador.

## 🧠 Lógica de Almacenamiento
Toda la información reside en la carpeta `/data`. No borres esta carpeta si deseas conservar los datos de tus pacientes.
- `data/psyco_app.db`: Base de datos relacional (SQLite).
- `data/uploads/`: Archivos de audio originales de las sesiones.

## 🛠️ Desarrollo y Contribución
Este proyecto utiliza una arquitectura separada (Decoupled):
- **API:** FastAPI + SQLAlchemy.
- **IA:** Faster-Whisper (Transcripción) + Ollama (Análisis).
- **Frontend:** VanilaJS con Tailwind CSS.

---
*Desarrollado para ofrecer eficiencia y privacidad en la práctica clínica psicológica.*
