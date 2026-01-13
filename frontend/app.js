const API_URL = "http://127.0.0.1:8000";
let selectedPatientId = null;
let currentSessionId = null;
let mediaRecorder;
let audioChunks = [];
let recordingInterval;
let startTime;
let allPatients = [];
let pendingAudioFile = null;

// Auth State - Usar localStorage para mayor persistencia en Edge
let authToken = localStorage.getItem('psyco_token') || sessionStorage.getItem('psyco_token') || null;
let isRegistered = false;

// Polling State
let sessionPollingInterval = null;
let hasActiveProcessing = false;
let completedSessionsList = new Set(); // Para rastrear cuáles ya notificamos
let isFirstLoad = true;

// Initial load
document.addEventListener('DOMContentLoaded', async () => {
    // 1. Mostrar estado inicial basado en token existente
    if (authToken) {
        document.getElementById('login-modal').classList.add('hidden');
        document.getElementById('logout-btn').classList.remove('hidden');
        initializeApp();
    } else {
        document.getElementById('login-modal').classList.remove('hidden');
        document.getElementById('logout-btn').classList.add('hidden');
    }

    // 2. Activar AudioContext al primer movimiento/clic
    const unlockAudio = () => {
        if (!window.globalAudioCtx) {
            window.globalAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
            console.log("🔊 Sistema de audio desbloqueado");
        }
        if (window.globalAudioCtx.state === 'suspended') {
            window.globalAudioCtx.resume();
        }
        window.removeEventListener('click', unlockAudio);
        window.removeEventListener('keydown', unlockAudio);
    };
    window.addEventListener('click', unlockAudio);
    window.addEventListener('keydown', unlockAudio);

    await checkRegistration();
    checkServerStatus();
    setInterval(checkServerStatus, 5000);
    startSmartPolling();
});

// No inicializar aquí para evitar bloqueos preventivos
window.globalAudioCtx = null;

async function checkRegistration() {
    try {
        const res = await fetch(`${API_URL}/auth/check`);
        const data = await res.json();
        isRegistered = data.has_user;

        const title = document.getElementById('login-title');
        const subtitle = document.getElementById('login-subtitle');
        const btn = document.getElementById('login-btn');

        if (!isRegistered) {
            title.innerText = "Configuración Inicial";
            subtitle.innerText = "Crea tu cuenta de administrador local";
            btn.innerText = "REGISTRAR Y EMPEZAR";
        } else {
            title.innerText = "Acceso Profesional";
            subtitle.innerText = "Ingresa tus credenciales maestras";
            btn.innerText = "INICIAR SESIÓN";
        }
    } catch (e) {
        console.error("Auth check failed", e);
    }
}

async function handleAuthAction() {
    const user = document.getElementById('login-username').value;
    const pass = document.getElementById('login-password').value;
    const errorMsg = document.getElementById('login-error');

    if (!user || !pass) return;

    const formData = new FormData();
    formData.append('username', user);
    formData.append('password', pass);

    const endpoint = isRegistered ? '/auth/login' : '/auth/register';

    try {
        const res = await fetch(`${API_URL}${endpoint}`, {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            const data = await res.json();
            if (isRegistered) {
                authToken = data.token;
                localStorage.setItem('psyco_token', authToken);
                sessionStorage.setItem('psyco_token', authToken);
                document.getElementById('login-modal').classList.add('hidden');
                document.getElementById('logout-btn').classList.remove('hidden');
                initializeApp();
            } else {
                // Just registered, now login
                isRegistered = true;
                handleAuthAction();
            }
        } else {
            errorMsg.classList.remove('hidden');
            setTimeout(() => errorMsg.classList.add('hidden'), 3000);
        }
    } catch (e) {
        console.error("Auth action failed", e);
    }
}

function handleUnauthorized() {
    // En lugar de un logout total, solo mostramos el modal de login
    // para re-autenticar sin perder la vista actual (Paciente/Sesión)
    console.warn("Sesión expirada o servidor reiniciado. Solicitando re-autenticación.");
    document.getElementById('login-modal').classList.remove('hidden');
    document.getElementById('login-subtitle').innerText = "Tu sesión ha expirado. Por favor, ingresa de nuevo.";
    document.getElementById('login-subtitle').classList.add('text-rose-400');
}

function handleLogout() {
    authToken = null;
    localStorage.removeItem('psyco_token');
    sessionStorage.removeItem('psyco_token');
    sessionStorage.removeItem('activePatientId');
    sessionStorage.removeItem('activePatientName');
    selectedPatientId = null;

    document.getElementById('login-modal').classList.remove('hidden');
    document.getElementById('logout-btn').classList.add('hidden');
    document.getElementById('patient-view').classList.add('hidden');
    document.getElementById('intro-view').classList.remove('hidden');
    document.getElementById('patient-list').innerHTML = '';
    document.getElementById('session-table-body').innerHTML = '';
}

function initializeApp() {
    loadPatients().then(() => {
        const savedId = sessionStorage.getItem('activePatientId');
        const savedName = sessionStorage.getItem('activePatientName');
        if (savedId && savedName) {
            selectPatient(parseInt(savedId), savedName);
        }
    });
    loadModels();
}

// Health Check
async function checkServerStatus() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    try {
        const res = await fetch(`${API_URL}/health`);
        if (res.ok) {
            dot.className = "w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.5)]";
            text.innerText = "Servidor Activo";
        } else throw new Error();
    } catch (e) {
        dot.className = "w-2 h-2 rounded-full bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.5)] animate-pulse";
        text.innerText = "Desconectado";
    }
}

// Smart Polling System
function startSmartPolling() {
    // Verificar cada 5 segundos si necesitamos actualizar
    sessionPollingInterval = setInterval(() => {
        if (selectedPatientId && authToken) {
            checkAndUpdateSessions();
        }
    }, 5000);
}

async function checkAndUpdateSessions() {
    if (!authToken || !selectedPatientId) return;

    // Cargar sesiones y verificar si hay procesamiento activo
    const wasProcessing = hasActiveProcessing;

    try {
        const response = await fetch(`${API_URL}/sessions/?patient_id=${selectedPatientId}&token=${authToken}`);

        if (response.status === 401) {
            handleUnauthorized();
            return;
        }

        const sessions = await response.json();

        // Detectar si alguna sesión acaba de completarse
        sessions.forEach(s => {
            if (s.status === 'completed') {
                if (!completedSessionsList.has(s.id)) {
                    // Si no estaba en la lista y no es la primera carga, ¡notificamos!
                    if (!isFirstLoad) {
                        console.log("🎯 Sesión completada detectada:", s.id);
                        playNotificationSound();
                        showVisualToast(`Sesión completada para el paciente`);
                    }
                    completedSessionsList.add(s.id);
                }
            }
        });

        isFirstLoad = false;

        // Actualizar la UI
        renderSessionsTable(sessions);

        // Verificar si hay procesamiento activo (para los logs de polling)
        checkForActiveProcessing(sessions);

        // Si cambió de procesando a no procesando, hacer una actualización final
        if (wasProcessing && !hasActiveProcessing) {
            console.log('✅ Procesamiento completado');
        }
    } catch (e) {
        console.error("Error en polling:", e);
    }
}

// Función para notificación visual (Toast)
function showVisualToast(message) {
    const toast = document.createElement('div');
    toast.className = "fixed top-8 right-8 bg-emerald-600 text-white px-6 py-4 rounded-2xl shadow-2xl z-[200] animate-in slide-in-from-top-10 duration-500 font-bold flex items-center gap-3 border border-emerald-400/30";
    toast.innerHTML = `
        <div class="bg-white/20 p-2 rounded-lg">
            <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 22a10 10 0 1 1 0-20 10 10 0 0 1 0 20zm-2-7l-4-4L4.59 12.41 10 17.82l9-9L17.59 7.41 10 15z"/></svg>
        </div>
        <div>
            <p class="text-xs opacity-80 uppercase tracking-widest">¡Proceso Finalizado!</p>
            <p class="text-sm font-bold">${message}</p>
        </div>
    `;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('animate-out', 'fade-out', 'slide-out-to-top-10');
        setTimeout(() => toast.remove(), 500);
    }, 6000);
}

// Nueva función para reproducir un sonido sintético elegante
function playNotificationSound() {
    try {
        if (!window.globalAudioCtx) {
            console.warn("AudioContext no inicializado aún por interacción del usuario.");
            return;
        }

        const audioCtx = window.globalAudioCtx;
        if (audioCtx.state === 'suspended') {
            audioCtx.resume();
        }

        const oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();

        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(880, audioCtx.currentTime);
        oscillator.frequency.exponentialRampToValueAtTime(440, audioCtx.currentTime + 0.5);

        gainNode.gain.setValueAtTime(0.15, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.5);

        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);

        oscillator.start();
        oscillator.stop(audioCtx.currentTime + 0.5);

        console.log("🔔 Notificación: SONANDO AHORA");
    } catch (err) {
        console.error("No se pudo reproducir el sonido:", err);
    }
}

function renderSessionsTable(sessions) {
    const body = document.getElementById('session-table-body');
    document.getElementById('session-count').innerText = sessions.length;

    body.innerHTML = '';
    if (sessions.length === 0) {
        body.innerHTML = '<tr><td colspan="4" class="px-6 py-10 text-center text-slate-500 text-xs italic">No hay sesiones grabadas para este paciente</td></tr>';
        return;
    }

    // Usar una copia para el reverse y no afectar el array original
    [...sessions].reverse().forEach(s => {
        const row = document.createElement('tr');
        row.className = "hover:bg-slate-800/40 transition-all group";

        let statusMarkup = "";
        let durationText = "-";
        const struct = s.structured_json || {};

        if (s.status === 'completed') {
            statusMarkup = `<span class="bg-emerald-500/10 text-emerald-500 text-[9px] px-2 py-0.5 rounded-full font-bold border border-emerald-500/20">PROTEGIDO</span>`;
            if (struct._metrics) {
                durationText = `<span class="text-xs text-slate-400">${formatDuration(struct._metrics.total_time)}</span>`;
            }
        } else if (['queued', 'transcribing', 'analyzing', 'securing'].includes(s.status)) {
            const colors = { queued: 'amber', transcribing: 'rose', analyzing: 'indigo', securing: 'emerald' };
            const text = { queued: 'EN COLA', transcribing: 'TRANSCRIBIENDO', analyzing: 'ANALIZANDO', securing: 'CIFRANDO' };
            const c = colors[s.status];
            statusMarkup = `<span class="bg-${c}-500/40 text-${c}-400 text-[9px] px-2 py-0.5 rounded-full font-bold border border-${c}-500/20 animate-pulse">${text[s.status]}</span>`;
            durationText = `<span class="text-[10px] text-${c}-400 italic">Procesando...</span>`;
        } else {
            statusMarkup = `<span class="bg-rose-500/10 text-rose-500 text-[9px] px-2 py-0.5 rounded-full font-bold border border-rose-500/20">ERROR</span>`;
        }

        row.innerHTML = `
            <td class="px-6 py-4">${statusMarkup}</td>
            <td class="px-6 py-4">
                <div class="flex flex-col">
                    <span class="text-slate-100 text-sm font-medium">${new Date(s.created_at).toLocaleDateString()}</span>
                    <span class="text-[10px] text-slate-500 italic">${new Date(s.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                </div>
            </td>
            <td class="px-6 py-4">${durationText}</td>
            <td class="px-6 py-4 text-right">
                <div class="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onclick="openSession(${s.id})" class="bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600 hover:text-white px-4 py-1.5 rounded-lg text-xs font-bold transition-all">Abrir</button>
                    <button onclick="deleteSession(event, ${s.id})" class="p-1.5 hover:bg-rose-500/10 rounded text-slate-600 hover:text-rose-400 transition-all">
                        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                    </button>
                </div>
            </td>
        `;
        body.appendChild(row);
    });
}

function checkForActiveProcessing(sessions) {
    // Verificar si alguna sesión está en proceso
    const processingStates = ['queued', 'transcribing', 'analyzing', 'securing'];
    const isProcessing = sessions.some(s => processingStates.includes(s.status));

    // Log solo cuando cambia el estado
    if (isProcessing !== hasActiveProcessing) {
        if (isProcessing) {
            console.log('🔄 Procesamiento detectado - Polling activo cada 5s');
        } else {
            console.log('⏸️ Sin procesamiento - Polling pausado');
        }
    }

    hasActiveProcessing = isProcessing;
    return isProcessing;
}

function formatDuration(seconds) {
    if (!seconds && seconds !== 0) return "-";
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s}s`;
}

async function loadModels() {
    try {
        const res = await fetch(`${API_URL}/models/`);
        const models = await res.json();
        const select = document.getElementById('model-select');
        select.innerHTML = '<option value="">Automático (Gemma 3)</option>';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            const displayName = m.replace('ollama:', '');
            opt.innerText = displayName;
            if (displayName.toLowerCase().includes('gemma3')) opt.selected = true;
            select.appendChild(opt);
        });
    } catch (e) { }
}

async function loadPatients() {
    try {
        const response = await fetch(`${API_URL}/patients/`);
        allPatients = await response.json();
        renderPatients(allPatients);
    } catch (e) { }
}

function renderPatients(patients) {
    const list = document.getElementById('patient-list');
    list.innerHTML = '';
    if (patients.length === 0) {
        list.innerHTML = '<div class="text-center py-10 text-slate-600 text-[10px] uppercase tracking-widest">No hay pacientes</div>';
        return;
    }

    patients.forEach(p => {
        const div = document.createElement('div');
        div.className = `patient-item p-4 rounded-xl cursor-pointer transition-all duration-300 flex justify-between items-center group ${selectedPatientId === p.id ? 'selected' : 'hover:bg-slate-800/30'}`;
        div.innerHTML = `
            <div class="flex flex-col flex-1" onclick="selectPatient(${p.id}, '${p.full_name}')">
                <span class="font-bold text-sm ${selectedPatientId === p.id ? 'text-indigo-400' : 'text-slate-200'}">${p.full_name}</span>
                <span class="text-[9px] text-slate-500 uppercase">Ficha Clínica</span>
            </div>
            <button onclick="deletePatient(event, ${p.id}, '${p.full_name}')" class="p-1.5 opacity-0 group-hover:opacity-100 hover:bg-rose-500/10 rounded text-slate-600 hover:text-rose-400 transition-all">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            </button>
        `;
        list.appendChild(div);
    });
}

async function deletePatient(event, id, name) {
    event.stopPropagation();
    if (!confirm(`¿Estás seguro de eliminar al paciente ${name} y TODAS sus sesiones? Esta acción es irreversible.`)) return;
    try {
        const res = await fetch(`${API_URL}/patients/${id}`, { method: 'DELETE' });
        if (res.ok) {
            if (selectedPatientId === id) {
                selectedPatientId = null;
                sessionStorage.removeItem('activePatientId');
                document.getElementById('patient-view').classList.add('hidden');
                document.getElementById('intro-view').classList.remove('hidden');
            }
            loadPatients();
        }
    } catch (e) { }
}

function selectPatient(id, name) {
    selectedPatientId = id;
    sessionStorage.setItem('activePatientId', id);
    sessionStorage.setItem('activePatientName', name);
    document.getElementById('intro-view').classList.add('hidden');
    document.getElementById('patient-view').classList.remove('hidden');
    document.getElementById('active-patient-name').innerText = name;

    // Resetear el estado de carga al cambiar de paciente para no sonar por sesiones viejas
    completedSessionsList.clear();
    isFirstLoad = true;

    loadSessions(id);
    renderPatients(allPatients);
}

async function loadSessions(patientId) {
    if (!authToken) return;
    try {
        const response = await fetch(`${API_URL}/sessions/?patient_id=${patientId}&token=${authToken}`);
        if (response.status === 401) {
            handleUnauthorized();
            return;
        }
        const sessions = await response.json();

        // Registrar las que ya están completas para no notificarlas al cargar
        if (isFirstLoad) {
            sessions.forEach(s => {
                if (s.status === 'completed') completedSessionsList.add(s.id);
            });
            isFirstLoad = false;
        }

        checkForActiveProcessing(sessions);
        renderSessionsTable(sessions);
    } catch (e) { }
}

async function deleteSession(event, id) {
    event.stopPropagation();
    if (!confirm("¿Eliminar esta sesión permanentemente?")) return;
    try {
        await fetch(`${API_URL}/sessions/${id}`, { method: 'DELETE' });
        loadSessions(selectedPatientId);
    } catch (e) { }
}

async function uploadFile(file) {
    if (!authToken) return;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('token', authToken);
    const model = document.getElementById('model-select').value;
    if (model) formData.append('model', model);

    try {
        await fetch(`${API_URL}/upload/${selectedPatientId}`, { method: 'POST', body: formData });
        // Cargar sesiones inmediatamente - el polling inteligente detectará el procesamiento
        loadSessions(selectedPatientId);
    } catch (e) { alert("Error al subir"); }
}

async function openSession(id) {
    currentSessionId = id;
    const player = document.getElementById('modal-audio-player');
    const playBtn = document.getElementById('play-btn');

    // Reset UI
    player.src = '';
    playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;

    try {
        const response = await fetch(`${API_URL}/sessions/${id}?token=${authToken}`);
        if (response.status === 401) return handleUnauthorized();
        const data = await response.json();

        document.getElementById('session-date-display').innerText = `Sesión del: ${new Date(data.created_at).toLocaleString()}`;
        document.getElementById('modal-transcript').innerText = data.transcription_raw || "Procesando...";

        const struct = data.structured_json || {};
        const badge = document.getElementById('model-badge');
        badge.innerText = struct._model_file ? `IA: ${struct._model_file}` : 'IA';
        badge.classList.remove('hidden');

        const notaArea = document.getElementById('edit-nota-clinica');
        notaArea.value = struct.nota_clinica || "Analizando...";

        // Setup Audio Stream
        player.src = `${API_URL}/audio/${id}?token=${authToken}`;

        // Icon toggle logic
        playBtn.onclick = () => player.paused ? player.play() : player.pause();
        player.onplay = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`;
        player.onpause = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
        player.onended = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;

        // Handle Save Button
        const saveBtn = document.getElementById('save-btn');
        saveBtn.onclick = () => saveSessionEdits(id);

        document.getElementById('session-modal').classList.remove('hidden');
    } catch (e) { }
}

async function saveSessionEdits(id) {
    const nota = document.getElementById('edit-nota-clinica').value;
    const btn = document.getElementById('save-btn');
    const originalText = btn.innerText;

    btn.innerText = "Guardando...";
    btn.disabled = true;

    const formData = new FormData();
    formData.append('token', authToken);
    formData.append('data', JSON.stringify({ nota_clinica: nota }));

    try {
        const res = await fetch(`${API_URL}/sessions/${id}/update`, {
            method: 'POST',
            body: formData
        });
        if (res.ok) {
            btn.innerText = "¡Guardado!";
            btn.classList.replace('bg-indigo-600', 'bg-emerald-600');
            setTimeout(() => {
                btn.innerText = originalText;
                btn.classList.replace('bg-emerald-600', 'bg-indigo-600');
                btn.disabled = false;
            }, 2000);
        }
    } catch (e) {
        alert("Error al guardar");
        btn.innerText = originalText;
        btn.disabled = false;
    }
}

function closeModal() {
    document.getElementById('session-modal').classList.add('hidden');
    document.getElementById('modal-audio-player').pause();
}

async function createPatient() {
    const name = document.getElementById('patient-name-input').value.trim();
    if (!name) return;
    try {
        const res = await fetch(`${API_URL}/patients/?name=${encodeURIComponent(name)}`, { method: 'POST' });
        if (res.ok) {
            document.getElementById('patient-name-input').value = '';
            hideNewPatientModal();
            loadPatients();
        }
    } catch (e) { }
}

// Recording & UI Helpers
async function toggleRecording() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') {
        try {
            // Optimización de captura: 16kHz Mono
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });

            // Verificar formatos soportados (Priorizar OGG/OPUS)
            let mimeType = 'audio/webm;codecs=opus';
            let extension = 'webm';

            if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
                mimeType = 'audio/ogg;codecs=opus';
                extension = 'ogg';
            }

            const options = {
                mimeType: mimeType,
                audioBitsPerSecond: 16000 // 16kbps optimización para voz
            };

            mediaRecorder = new MediaRecorder(stream, options);
            audioChunks = [];
            mediaRecorder.ondataavailable = (event) => audioChunks.push(event.data);
            mediaRecorder.onstop = () => {
                const blob = new Blob(audioChunks, { type: mimeType });
                const fileName = `vivo_${Date.now()}.${extension}`;
                const file = new File([blob], fileName, { type: mimeType });
                showConfirmModal(file);
            };

            mediaRecorder.start();
            document.getElementById('record-card').classList.add('border-rose-500');
            document.getElementById('record-title').innerText = "Detener y Guardar";
            startTime = Date.now();
            recordingInterval = setInterval(() => {
                const diff = Date.now() - startTime;
                document.getElementById('record-timer-text').innerText = `Grabando: ${Math.floor(diff / 1000)}s`;
            }, 1000);
        } catch (err) {
            console.error(err);
            alert("Error al iniciar grabación: " + err.message);
        }
    } else {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(t => t.stop());
        document.getElementById('record-card').classList.remove('border-rose-500');
        document.getElementById('record-title').innerText = "Grabar en Vivo";
        clearInterval(recordingInterval);
    }
}

function showConfirmModal(file) { pendingAudioFile = file; document.getElementById('confirm-modal').classList.remove('hidden'); }
function confirmUpload() { if (pendingAudioFile) { uploadFile(pendingAudioFile); pendingAudioFile = null; } document.getElementById('confirm-modal').classList.add('hidden'); }
function cancelUpload() { pendingAudioFile = null; document.getElementById('confirm-modal').classList.add('hidden'); }
function showNewPatientModal() { document.getElementById('new-patient-modal').classList.remove('hidden'); }
function hideNewPatientModal() { document.getElementById('new-patient-modal').classList.add('hidden'); }

document.getElementById('audio-input').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) showConfirmModal(file);
    e.target.value = '';
});

function goToHome() {
    if (!authToken) return; // No hacer nada si no está logueado

    // Limpiar selección de paciente
    selectedPatientId = null;
    sessionStorage.removeItem('activePatientId');
    sessionStorage.removeItem('activePatientName');

    // Mostrar vista de inicio
    document.getElementById('patient-view').classList.add('hidden');
    document.getElementById('intro-view').classList.remove('hidden');

    // Quitar selección visual de pacientes
    document.querySelectorAll('.patient-item').forEach(item => {
        item.classList.remove('selected');
    });
}
