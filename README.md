# Session AI 🧠

**Asistente Inteligente para Psicoterapia**

Session AI es una aplicación de escritorio diseñada para optimizar el flujo de trabajo de los psicoterapeutas automatizando la documentación clínica mediante Inteligencia Artificial, garantizando la privacidad y seguridad de los datos.

---

## 🚀 Características Principales

- **Grabación y Transcripción Segura**: Procesamiento de audio local y seguro.
- **Análisis Clínico con IA**: Generación automática de notas SOAP, detección de estado de ánimo y riesgos.
- **Gestión de Pacientes**: Expedientes clínicos organizados y accesibles.
- **Modo Offline**: Funcionalidad core disponible sin conexión a internet.
- **Privacidad Primero**: Encriptación de datos sensibles y anonimización automática.

---

## 🛠️ Arquitectura del Proyecto

El proyecto ha sido refactorizado (Feb 2026) hacia una arquitectura modular y escalable.

### Estructura de Directorios

```
psyco-app/
├── backend/                   # 🐍 Backend FastAPI Modular
│   ├── routes/                # Endpoints (auth, patients, sessions, system)
│   ├── services/              # Lógica de negocio (IA, procesamiento, anonimización)
│   ├── models/                # Modelos de base de datos (SQLAlchemy)
│   ├── main.py                # Inicialización de la app
│   └── ...config y seguridad
│
├── frontend/                  # 💻 Frontend Electron/Web
│   ├── js/
│   │   ├── modules/           # Módulos ES6 (auth, patients, recording, etc.)
│   │   ├── component/         # Componentes UI reutilizables
│   │   ├── main.js            # Entry point principal
│   │   └── api.js             # Cliente HTTP centralizado
│   ├── css/                   # Estilos (TailwindCSS configurado)
│   └── index.html             # Vista principal
│
├── scripts/                   # 🔧 Scripts de mantenimiento y base de datos
├── data/                      # 🗄️ Almacenamiento local (SQLite, audios) - Ignorado por git
└── main.js                    # ⚡ Proceso principal de Electron
```

---

## ⚡ Instalación y Uso

### Prerrequisitos

- **Node.js** (v18+)
- **Python** (v3.10+)
- **FFmpeg** (instalado y en el PATH)

### Configuración

1. **Instalar dependencias de Frontend:**
   ```bash
   pnpm install
   ```

2. **Instalar dependencias de Backend:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configurar Variables de Entorno:**
   Crea un archivo `.env` basado en `.env.example`:
   ```env
   SUPABASE_URL=tu_url
   SUPABASE_KEY=tu_key
   GEMINI_API_KEY=tu_api_key
   ```

### Ejecutar en Desarrollo

```bash
pnpm start
```
Esto iniciará tanto el proceso de Electron como el servidor backend de Python automáticamente.

---

## 🔒 Seguridad

- **Base de Datos**: SQLite encriptada en reposo.
- **Autenticación**: Sistema de login local con tokens de sesión.
- **Backups**: Sistema de exportación cifrada (.zip) para portabilidad.

---

## 📄 Licencia

Propiedad de **Alchemy Lab**. Todos los derechos reservados.
