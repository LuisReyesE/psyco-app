const { app, BrowserWindow, Tray, Menu, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const axios = require('axios');

let mainWindow;
let tray = null;
let pyProc = null;
let logStream = null;
const PY_PORT = 8000;
const BACKEND_TIMEOUT_MS = 120000;

function getAppDataPath() {
    if (app.isPackaged) {
        return app.getPath('userData');
    }
    return __dirname;
}

function getLogPath() {
    return path.join(getAppDataPath(), 'server.log');
}

function writeLog(message) {
    const timestamp = new Date().toISOString();
    const logMessage = '[' + timestamp + '] ' + message + '\n';
    if (logStream) {
        logStream.write(logMessage);
    }
    console.log(message);
}

function createPyProc() {
    const appDataPath = getAppDataPath();
    const logPath = getLogPath();

    if (!fs.existsSync(appDataPath)) {
        fs.mkdirSync(appDataPath, { recursive: true });
    }

    // ROTACIÓN DE LOGS: Guardar 1 backup y empezar fresco
    if (fs.existsSync(logPath)) {
        const backupPath = logPath + '.old';
        try {
            if (fs.existsSync(backupPath)) fs.unlinkSync(backupPath);
            fs.renameSync(logPath, backupPath);
        } catch (e) {
            console.error("No se pudo rotar logs:", e);
        }
    }

    // 'w' flag crea nuevo archivo (o trunca), pero como ya rotamos, es archivo fresco.
    // Usamos 'a' por seguridad de no perder nada si la rotación falló silenciosamente,
    // pero en la práctica será un archivo nuevo.
    logStream = fs.createWriteStream(logPath, { flags: 'a' });
    writeLog('==================================================');
    writeLog('Session AI - Iniciando servidor');
    writeLog('App Data Path: ' + appDataPath);

    let pythonExe;
    let backendScript;

    if (app.isPackaged) {
        pythonExe = path.join(process.resourcesPath, 'python_runtime', 'python.exe');
        backendScript = path.join(process.resourcesPath, 'backend', 'main.py');
    } else {
        pythonExe = path.join(__dirname, 'python_runtime', 'python.exe');
        backendScript = path.join(__dirname, 'backend', 'main.py');
    }

    writeLog('Python: ' + pythonExe);
    writeLog('Backend: ' + backendScript);

    pyProc = spawn(pythonExe, [backendScript], {
        env: Object.assign({}, process.env, {
            PYTHONUNBUFFERED: '1',
            SESSIONAI_ROOT: appDataPath
        }),
        windowsHide: true
    });

    pyProc.stdout.on('data', function (data) {
        writeLog('[PY] ' + data.toString().trim());
    });

    pyProc.stderr.on('data', function (data) {
        writeLog('[PY_ERR] ' + data.toString().trim());
    });

    pyProc.on('error', function (err) {
        writeLog('[ERROR] No se pudo iniciar Python: ' + err.message);
    });

    pyProc.on('exit', function (code) {
        writeLog('[EXIT] Python termino con codigo: ' + code);
    });
}

function createTray() {
    const iconPath = path.join(__dirname, 'frontend', 'assets', 'branding', 'session_ai.ico');

    try {
        tray = new Tray(iconPath);

        const contextMenu = Menu.buildFromTemplate([
            {
                label: 'Abrir Session AI',
                click: function () {
                    if (mainWindow) {
                        mainWindow.show();
                        mainWindow.focus();
                    }
                }
            },
            { type: 'separator' },
            {
                label: 'Ver Logs',
                click: function () {
                    shell.openPath(getLogPath());
                }
            },
            {
                label: 'Abrir carpeta de datos',
                click: function () {
                    shell.openPath(getAppDataPath());
                }
            },
            { type: 'separator' },
            {
                label: 'Salir',
                click: function () {
                    app.quit();
                }
            }
        ]);

        tray.setToolTip('Session AI');
        tray.setContextMenu(contextMenu);

        tray.on('double-click', function () {
            if (mainWindow) {
                mainWindow.show();
                mainWindow.focus();
            }
        });
    } catch (e) {
        writeLog('[WARN] No se pudo cargar icono de tray: ' + e.message);
    }
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1280,
        height: 800,
        backgroundColor: '#0f172a',
        icon: path.join(__dirname, 'frontend', 'assets', 'branding', 'session_ai.ico'),
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js')
        },
        show: false
    });

    mainWindow.setMenuBarVisibility(false);

    let attempts = 0;
    const maxAttempts = BACKEND_TIMEOUT_MS / 1000;

    const checkBackend = setInterval(function () {
        attempts++;
        axios.get('http://127.0.0.1:' + PY_PORT + '/health')
            .then(function () {
                clearInterval(checkBackend);
                const htmlPath = path.join(__dirname, 'frontend', 'index.html');
                writeLog('Backend respondio. Cargando: ' + htmlPath);

                // Esperar a que la página esté completamente renderizada
                mainWindow.once('ready-to-show', function () {
                    writeLog('Ventana lista para mostrar');
                    mainWindow.show();
                });

                mainWindow.loadFile(htmlPath);
            })
            .catch(function () {
                if (attempts % 10 === 0) {
                    writeLog('Esperando al backend... (' + attempts + 's)');
                }

                if (attempts >= maxAttempts) {
                    clearInterval(checkBackend);
                    writeLog('TIMEOUT: El backend no respondio');
                    mainWindow.loadURL('data:text/html,<html><body style="background:#0f172a;color:white;text-align:center;padding:50px;font-family:sans-serif;"><h1 style="color:#ef4444;">Error</h1><p>El servidor no inicio en ' + (BACKEND_TIMEOUT_MS / 1000) + ' segundos</p></body></html>');
                    mainWindow.show();
                }
            });
    }, 1000);

    mainWindow.on('closed', function () {
        mainWindow = null;
    });

    mainWindow.on('close', function (event) {
        if (!app.isQuitting) {
            event.preventDefault();
            mainWindow.hide();
        }
    });
}

const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
    app.quit();
} else {
    app.on('second-instance', (event, commandLine, workingDirectory) => {
        // Alguien intentó ejecutar una segunda instancia, enfocamos nuestra ventana principal
        if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            if (!mainWindow.isVisible()) mainWindow.show();
            mainWindow.focus();
        }
    });

    app.on('ready', function () {
        createPyProc();
        createTray();
        createWindow();
    });
}

app.on('before-quit', function () {
    app.isQuitting = true;
});

app.on('will-quit', function () {
    if (pyProc !== null) {
        writeLog('Apagando servidor Python...');
        pyProc.kill();
        pyProc = null;
    }
    if (logStream) {
        logStream.end();
    }
});

app.on('window-all-closed', function () {
    // Mantener en tray
});

app.on('activate', function () {
    if (mainWindow) {
        mainWindow.show();
    }
});
