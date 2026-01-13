@echo off
TITLE Session AI - Sistema Inteligente
cd /d "%~dp0"

echo ===========================================
echo     SESSION AI - INICIANDO SISTEMA
echo ===========================================
echo.

:: 1. Verificar/Descargar FFmpeg
if exist "ffmpeg-tools" goto check_venv
echo [!] No se detecto FFmpeg. Instalando herramientas de audio...
mkdir ffmpeg-tools
curl.exe -L -o "ffmpeg-tools\ffmpeg.zip" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
echo [+] Descomprimiendo...
powershell -Command "Expand-Archive -Path 'ffmpeg-tools\ffmpeg.zip' -DestinationPath 'ffmpeg-tools' -Force"
del "ffmpeg-tools\ffmpeg.zip"
echo.

:check_venv
:: 2. Verificar/Crear Entorno Virtual
if exist "venv_clean\Scripts\activate" goto activate_venv
echo [!] Configurando entorno Python por primera vez...
python -m venv venv_clean
call venv_clean\Scripts\activate
echo [+] Instalando librerias (esto solo ocurre una vez)...
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
goto check_shortcut

:activate_venv
call venv_clean\Scripts\activate

:check_shortcut
:: 3. Asegurar Acceso Directo con Icono
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Session AI.lnk"
set "SHORTCUT_SCRIPT=%~f0"
set "SHORTCUT_WORK=%~dp0"
set "SHORTCUT_ICON=%~dp0frontend\assets\branding\session_ai.ico"

if exist "%SHORTCUT_ICON%" (
    :: Si el icono existe pero el acceso directo no, o si queremos forzar el icono
    powershell -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT_PATH%');$s.TargetPath='%SHORTCUT_SCRIPT%';$s.WorkingDirectory='%SHORTCUT_WORK%';$s.IconLocation='%SHORTCUT_ICON%';$s.Save()"
) else (
    if not exist "%SHORTCUT_PATH%" (
        powershell -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SHORTCUT_PATH%');$s.TargetPath='%SHORTCUT_SCRIPT%';$s.WorkingDirectory='%SHORTCUT_WORK%';$s.Save()"
    )
)
:skip_shortcut

echo [+] Todo listo. Iniciando en la barra de tareas...

:: Lanzar con pythonw (sin ventana negra)
start /b "" venv_clean\Scripts\pythonw.exe backend/launcher.py

exit
