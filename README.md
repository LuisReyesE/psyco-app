# Session AI - Gestión Psicoterapéutica con IA Local

**Session AI** es una herramienta local diseñada para psicólogos que automatiza la transcripción de sesiones y la generación de notas de evolución clínica. Utiliza modelos de Inteligencia Artificial de vanguardia optimizados para funcionar de manera **100% privada y segura** en tu computadora personal.

## ✨ Características Principales

- **🔒 Privacidad Total:** Los audios y textos nunca salen de tu computadora. Cifrado de grado médico.
- **🎙️ Transcripción Inteligente:** Usa `Faster-Whisper` para convertir voz a texto con alta precisión.
- **📝 Notas Clínicas Automáticas:** Genera notas de evolución estructuradas usando modelos como `Gemma 3` vía Ollama.
- **👥 Gestión de Pacientes:** Historial completo de sesiones por paciente con búsqueda rápida.
- **🔐 Autenticación Segura:** Sistema de login con cifrado de datos sensibles.
- **🎯 Multi-modelo:** Permite elegir entre diferentes modelos de IA instalados localmente.
- **💾 Persistencia Local:** Base de datos SQLite con modo WAL para máximo rendimiento.

## 🔐 Seguridad y Privacidad

Session AI implementa múltiples capas de seguridad:
- **Cifrado AES-256** para audios y transcripciones
- **Derivación de claves PBKDF2** con 100,000 iteraciones
- **Hashing bcrypt** para contraseñas
- **Compresión automática** de audios para optimizar espacio
- **Sin conexión a internet** para procesamiento de datos sensibles

## 📂 Estructura del Proyecto

```
psyco-app/
├── backend/              # Servidor API (FastAPI)
│   ├── main.py          # Punto de entrada y rutas
│   ├── database.py      # Modelos y configuración de BD
│   ├── processor.py     # Motor de IA y procesamiento
│   └── security.py      # Funciones de cifrado
├── frontend/            # Interfaz de usuario
│   ├── index.html       # Aplicación principal
│   └── app.js           # Lógica del cliente
├── data/                # ⚠️ DATOS SENSIBLES (no incluir en Git)
│   ├── psyco_app.db     # Base de datos SQLite
│   └── uploads/         # Audios cifrados
├── ffmpeg-tools/        # Herramientas de procesamiento de audio
└── requirements.txt     # Dependencias de Python
```

## 🚀 Instalación y Configuración

### 1. Requisitos Previos

- **Python 3.9+** (recomendado 3.11)
- **Ollama:** Debe estar instalado y corriendo
  ```bash
  # Instalar Ollama desde: https://ollama.ai
  # Descargar un modelo (recomendado):
  ollama pull gemma3:4b
  ```
- **FFmpeg:** Incluido en la carpeta `ffmpeg-tools` (Windows)

### 2. Configuración del Backend

1. **Clonar el repositorio:**
   ```bash
   git clone <tu-repositorio>
   cd psyco-app
   ```

2. **Crear entorno virtual:**
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate  # Windows
   # source venv/bin/activate  # Linux/Mac
   ```

3. **Instalar dependencias:**
   ```powershell
   pip install -r requirements.txt
   ```

### 3. Ejecución

1. **Iniciar el servidor:**
   ```powershell
   cd backend
   python main.py
   ```
   El servidor estará disponible en `http://127.0.0.1:8000`

2. **Abrir la aplicación:**
   - Abre `frontend/index.html` en tu navegador
   - En el primer uso, crea tu usuario y contraseña maestra
   - ⚠️ **Importante:** Guarda tu contraseña en un lugar seguro. Sin ella, no podrás acceder a los datos cifrados.

## 🧠 Flujo de Trabajo

1. **Registro inicial:** Crea tu cuenta de administrador local
2. **Agregar paciente:** Registra un nuevo paciente en el sistema
3. **Grabar/Subir sesión:** Graba en vivo o sube un archivo de audio
4. **Procesamiento automático:**
   - Transcripción con Faster-Whisper
   - Análisis con modelo de Ollama
   - Cifrado y compresión de datos
5. **Revisar y editar:** Accede a las notas generadas y ajústalas según necesites

## 📊 Tecnologías Utilizadas

### Backend
- **FastAPI** - Framework web moderno y rápido
- **SQLAlchemy** - ORM para gestión de base de datos
- **Faster-Whisper** - Transcripción de audio optimizada
- **Ollama** - Modelos de lenguaje local
- **Cryptography** - Cifrado de datos sensibles
- **Passlib + Bcrypt** - Hashing seguro de contraseñas

### Frontend
- **Vanilla JavaScript** - Sin frameworks pesados
- **Tailwind CSS** - Diseño moderno y responsivo
- **HTML5 Audio API** - Grabación y reproducción

### Base de Datos
- **SQLite** con modo WAL - Máximo rendimiento y concurrencia

## 🛠️ Desarrollo y Contribución

### Arquitectura
- **API REST:** Comunicación cliente-servidor vía HTTP
- **Procesamiento asíncrono:** Cola de tareas en segundo plano
- **Cifrado en RAM:** Las claves nunca se almacenan en disco

### Comandos útiles
```bash
# Verificar estado del servidor
curl http://127.0.0.1:8000/health

# Ver documentación de la API
# Abrir en navegador: http://127.0.0.1:8000/docs
```

## ⚠️ Consideraciones Importantes

1. **Backup de datos:** La carpeta `/data` contiene toda tu información. Haz copias de seguridad regularmente.
2. **Contraseña maestra:** No hay forma de recuperar datos si olvidas tu contraseña. Guárdala en un lugar seguro.
3. **Requisitos de hardware:**
   - Mínimo: 8GB RAM, CPU de 4 núcleos
   - Recomendado: 16GB RAM, GPU NVIDIA (para transcripción más rápida)
4. **Modelos de Ollama:** Cada modelo ocupa entre 2-8GB. Asegúrate de tener espacio suficiente.

## 🐛 Solución de Problemas

### El servidor no inicia
- Verifica que el puerto 8000 no esté en uso
- Asegúrate de estar en el entorno virtual activado

### Error de "Module not found"
```bash
pip install -r requirements.txt --upgrade
```

### Ollama no responde
```bash
# Verificar que Ollama esté corriendo
ollama list
```

### Base de datos bloqueada
- El modo WAL está activado automáticamente
- Si persiste, cierra todas las instancias del servidor

## 📄 Licencia

Este proyecto es de código privado. Todos los derechos reservados.

## 👨‍💻 Desarrollado por

**ALCHEMY LAB** - Soluciones de IA para profesionales de la salud

---

*Session AI - Privacidad y eficiencia en la práctica clínica psicológica*
