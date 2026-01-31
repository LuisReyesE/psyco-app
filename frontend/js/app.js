const API_URL = "http://127.0.0.1:8000";
let selectedPatientId = null;
let currentSessionId = null;
let mediaRecorder;
let audioChunks = [];
let recordingInterval;
let startTime;
let allPatients = [];
let pendingAudioFile = null;

// Chunked recording support (real-time)
let recordingMimeType = '';
let recordingExtension = '';

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
    // 1. Verificar registro/autenticación PRIMERO (loading screen visible)
    await checkRegistration();

    // 1.5 Verificar validez del Token (backend RAM check)
    if (authToken) {
        const isValid = await validateSession(authToken);
        if (!isValid) {
            console.warn("Token local inválido o expirado. Forzando logout.");
            authToken = null;
            localStorage.removeItem('psyco_token');
            sessionStorage.removeItem('psyco_token');
        }
    }

    // 2. Ahora mostrar UI correcto basado en el estado
    if (authToken) {
        document.getElementById('auth-modal').classList.add('hidden');
        document.getElementById('logout-btn').classList.remove('hidden');
        updateGreeting();
        initializeApp();
    } else {
        document.getElementById('auth-modal').classList.remove('hidden');
        document.getElementById('logout-btn').classList.add('hidden');
    }

    // 3. Ocultar loading screen con transición suave
    const loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
        loadingScreen.style.transition = 'opacity 0.3s ease';
        loadingScreen.style.opacity = '0';
        setTimeout(() => loadingScreen.remove(), 300);
    }

    // 4. Activar AudioContext al primer movimiento/clic
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

    checkServerStatus();
    setInterval(checkServerStatus, 5000);
    startSmartPolling();

    // Listener para backup confirmation
    document.getElementById('backup-confirm').addEventListener('change', (e) => {
        const btn = document.getElementById('backup-continue-btn');
        btn.disabled = !e.target.checked;
        if (!e.target.checked) btn.classList.add('cursor-not-allowed', 'bg-slate-700', 'text-slate-400');
        else btn.classList.remove('cursor-not-allowed', 'bg-slate-700', 'text-slate-400'), btn.classList.add('bg-emerald-600', 'text-white', 'hover:bg-emerald-700');
    });
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
        const links = document.getElementById('login-links');

        if (!isRegistered) {
            title.innerText = "Configuración Inicial";
            subtitle.innerText = "Crea tu cuenta maestra";
            btn.innerText = "REGISTRAR Y EMPEZAR";
            links.classList.add('hidden'); // No recovery link on register
        } else {
            title.innerText = "Acceso Profesional";
            subtitle.innerText = "Ingresa tus credenciales maestras";
            btn.innerText = "INICIAR SESIÓN";
            links.classList.remove('hidden');
        }
    } catch (e) {
        console.error("Auth check failed", e);
    }
}

async function validateSession(token) {
    if (!token) return false;
    const formData = new FormData();
    formData.append('token', token);
    try {
        const res = await fetch(`${API_URL}/auth/verify`, { method: 'POST', body: formData });
        return res.ok;
    } catch {
        return false;
    }
}

async function handleAuthAction() {
    const userInput = document.getElementById('login-username');
    const passInput = document.getElementById('login-password');
    const errorMsg = document.getElementById('login-error');

    const user = userInput.value;
    const pass = passInput.value;

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
                // LOGIN EXITOSO
                authToken = data.token;
                localStorage.setItem('psyco_token', authToken);
                sessionStorage.setItem('psyco_token', authToken);

                // Store username for greeting
                if (data.username) {
                    localStorage.setItem('psyco_user', data.username);
                }

                document.getElementById('auth-modal').classList.add('hidden');
                document.getElementById('logout-btn').classList.remove('hidden');

                // Clear inputs for security
                userInput.value = '';
                passInput.value = '';

                updateGreeting();
                initializeApp();
            } else {
                // REGISTRO EXITOSO -> MOSTRAR BACKUP CODE
                document.getElementById('login-card').classList.add('hidden');
                document.getElementById('backup-card').classList.remove('hidden');
                document.getElementById('display-backup-code').innerText = data.recovery_code;

                // Auto-fill username for UX next time
                userInput.value = user;
                passInput.value = '';

                // Set flag locally so next time app reloads it shows login screen
                isRegistered = true;
            }
        } else {
            errorMsg.classList.remove('hidden');
            passInput.classList.add('shake', 'border-rose-500');
            setTimeout(() => {
                errorMsg.classList.add('hidden');
                passInput.classList.remove('shake', 'border-rose-500');
            }, 2000);
        }
    } catch (e) {
        console.error("Auth action failed", e);
    }
}

function finishBackupProcess() {
    // Al terminar de guardar el backup, pedimos login normal para confirmar que se sabe la contraseña
    document.getElementById('backup-card').classList.add('hidden');
    document.getElementById('login-card').classList.remove('hidden');

    // Forzamos actualización de UI a "Login Mode"
    checkRegistration();

    // UX: Mostrar mensaje de éxito en lugar de alert invasivo (que rompe el foco)
    const subtitle = document.getElementById('login-subtitle');
    subtitle.innerText = "¡Registro exitoso! Confirma tu contraseña.";
    subtitle.className = "text-emerald-400 text-sm font-bold animate-pulse";

    // Auto-focus en el password para que el usuario solo escriba y entre
    setTimeout(() => {
        const passInput = document.getElementById('login-password');
        passInput.focus();
        passInput.select();
    }, 100);
}

function copyToClipboard() {
    const code = document.getElementById('display-backup-code').innerText;
    navigator.clipboard.writeText(code).then(() => {
        alert("Código copiado al portapapeles");
    });
}

function toggleRecoveryMode() {
    const loginCard = document.getElementById('login-card');
    const recCard = document.getElementById('recovery-card');

    if (recCard.classList.contains('hidden')) {
        loginCard.classList.add('hidden');
        recCard.classList.remove('hidden');
    } else {
        recCard.classList.add('hidden');
        loginCard.classList.remove('hidden');
    }
}

async function handleRecovery() {
    const username = document.getElementById('rec-username').value;
    const code = document.getElementById('rec-code').value;
    const newPass = document.getElementById('rec-new-password').value;
    const errorTxt = document.getElementById('rec-error');

    if (!username || !code || !newPass) return;

    const formData = new FormData();
    formData.append('username', username);
    formData.append('recovery_code', code);
    formData.append('new_password', newPass);

    try {
        const res = await fetch(`${API_URL}/auth/recover`, { method: 'POST', body: formData });
        if (res.ok) {
            alert('Contraseña restablecida correctamente. Inicia sesión con tus nuevas credenciales.');
            // Clear inputs
            document.getElementById('rec-username').value = '';
            document.getElementById('rec-code').value = '';
            document.getElementById('rec-new-password').value = '';
            toggleRecoveryMode(); // Volver al login
        } else {
            errorTxt.innerText = "Código incorrecto o usuario perdido";
            errorTxt.classList.remove('hidden');
        }
    } catch {
        errorTxt.classList.remove('hidden');
    }
}

function handleUnauthorized() {
    console.warn("Sesión expirada o servidor reiniciado. Solicitando re-autenticación.");
    if (sessionPollingInterval) clearInterval(sessionPollingInterval);
    document.getElementById('auth-modal').classList.remove('hidden');
    document.getElementById('login-subtitle').innerText = "Tu sesión ha expirado.";
    document.getElementById('login-subtitle').classList.add('text-rose-400');
}

function handleLogout() {
    authToken = null;
    localStorage.removeItem('psyco_token');
    localStorage.removeItem('psyco_user'); // Clear username
    sessionStorage.removeItem('psyco_token');
    sessionStorage.removeItem('activePatientId');
    sessionStorage.removeItem('activePatientName');
    selectedPatientId = null;

    document.getElementById('auth-modal').classList.remove('hidden');
    document.getElementById('logout-btn').classList.add('hidden');
    document.getElementById('patient-view').classList.add('hidden');
    document.getElementById('intro-view').classList.remove('hidden');
    document.getElementById('patient-list').innerHTML = '';
    document.getElementById('session-table-body').innerHTML = '';

    // Reset login UI
    document.getElementById('login-username').value = '';
    document.getElementById('login-password').value = '';
}

function updateGreeting() {
    const username = localStorage.getItem('psyco_user');
    const greetingEl = document.getElementById('user-greeting');
    if (greetingEl) {
        if (username) {
            greetingEl.innerText = `Hola, ${username.charAt(0).toUpperCase() + username.slice(1)}`;
            greetingEl.classList.remove('hidden');
        } else {
            greetingEl.classList.add('hidden');
        }
    }
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
    startSmartPolling();
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
    if (sessionPollingInterval) clearInterval(sessionPollingInterval);
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

// --- PDF EXPORT ---
async function downloadPDF() {
    if (!currentSessionId || !authToken) return;

    // Create a temporary link to trigger download
    const link = document.createElement('a');
    link.href = `${API_URL}/sessions/${currentSessionId}/pdf?token=${authToken}`;
    link.target = '_blank'; // Open in new tab or trigger download
    link.download = `Session_${currentSessionId}.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// --- VISUAL TOAST ---
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

// Nueva función para reproducir un sonido sintético elegante (Melódico Ding-Dong)
function playNotificationSound() {
    try {
        if (!window.globalAudioCtx) {
            console.warn("AudioContext no inicializado");
            return;
        }

        const audioCtx = window.globalAudioCtx;
        if (audioCtx.state === 'suspended') audioCtx.resume();

        const now = audioCtx.currentTime;

        // Primer tono (Ding)
        const osc1 = audioCtx.createOscillator();
        const gain1 = audioCtx.createGain();
        osc1.type = 'sine';
        osc1.frequency.setValueAtTime(659.25, now); // E5
        gain1.gain.setValueAtTime(0, now);
        gain1.gain.linearRampToValueAtTime(0.12, now + 0.05);
        gain1.gain.exponentialRampToValueAtTime(0.01, now + 0.4);
        osc1.connect(gain1);
        gain1.connect(audioCtx.destination);
        osc1.start(now);
        osc1.stop(now + 0.4);

        // Segundo tono (Dong)
        const osc2 = audioCtx.createOscillator();
        const gain2 = audioCtx.createGain();
        osc2.type = 'sine';
        osc2.frequency.setValueAtTime(523.25, now + 0.15); // C5
        gain2.gain.setValueAtTime(0, now + 0.15);
        gain2.gain.linearRampToValueAtTime(0.12, now + 0.2);
        gain2.gain.exponentialRampToValueAtTime(0.01, now + 0.6);
        osc2.connect(gain2);
        gain2.connect(audioCtx.destination);
        osc2.start(now + 0.15);
        osc2.stop(now + 0.6);

        console.log("🔔 Notificación Melódica: SONANDO AHORA");
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

    // Backend sends sorted data (Newest First)
    sessions.forEach(s => {
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
        } else if (s.status === 'recording') {
            const ageMinutes = (Date.now() - new Date(s.created_at).getTime()) / 60000;

            // Check if this is the locally paused session
            const isLocallyPaused = (s.id === activeSessionId && isPaused);

            if (ageMinutes < 90) {
                if (isLocallyPaused) {
                    // PAUSADO (Local state override)
                    statusMarkup = `<span class="bg-amber-500/20 text-amber-400 text-[9px] px-2 py-0.5 rounded-full font-bold border border-amber-500/30">PAUSADO</span>`;
                    durationText = `<span class="text-[10px] text-amber-400 italic">En espera...</span>`;
                } else {
                    // EN VIVO
                    statusMarkup = `<span class="bg-purple-500/30 text-purple-300 text-[9px] px-2 py-0.5 rounded-full font-bold border border-purple-500/40 animate-pulse">EN VIVO</span>`;
                    if (s.chunks_transcribed !== undefined && s.chunks_total !== undefined && s.chunks_total > 0) {
                        durationText = `<span class="text-[10px] text-purple-400 italic">${s.chunks_transcribed}/${s.chunks_total} chunks</span>`;
                    } else {
                        durationText = `<span class="text-[10px] text-purple-400 italic">Grabando...</span>`;
                    }
                }
            } else {
                statusMarkup = `<span class="bg-slate-500/20 text-slate-400 text-[9px] px-2 py-0.5 rounded-full font-bold border border-slate-500/30">ABANDONADA</span>`;
                durationText = `<span class="text-[10px] text-slate-500 italic">Sesión incompleta</span>`;
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
    // Verificar si alguna sesión está en proceso (incluyendo grabación en vivo)
    const processingStates = ['recording', 'queued', 'transcribing', 'analyzing', 'securing'];
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

const formatDuration = (s) => {
    if (!s || isNaN(s)) return '0s';
    if (s < 60) return `${Math.round(s)}s`;
    const m = Math.floor(s / 60);
    const sec = Math.round(s % 60);
    return `${m}m ${sec}s`;
};

async function loadModels() {
    try {
        const res = await fetch(`${API_URL}/models/`);
        const models = await res.json();
        const select = document.getElementById('model-select');
        select.innerHTML = '<option value="">Automático (Gemma 3)</option>';

        // Separate models by provider
        const ollamaModels = models.filter(m => m.startsWith('ollama:'));
        const geminiModels = models.filter(m => m.startsWith('gemini:'));

        // Add Ollama models (local)
        if (ollamaModels.length > 0) {
            const ollamaGroup = document.createElement('optgroup');
            ollamaGroup.label = '🖥️ Local';
            ollamaModels.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                const displayName = m.replace('ollama:', '');
                opt.innerText = displayName;
                if (displayName.toLowerCase().includes('gemma3')) opt.selected = true;
                ollamaGroup.appendChild(opt);
            });
            select.appendChild(ollamaGroup);
        }

        // Add Gemini models (cloud with anonymization)
        if (geminiModels.length > 0) {
            const geminiGroup = document.createElement('optgroup');
            geminiGroup.label = '☁️ Nube + Anonimización';
            geminiModels.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                const displayName = m.replace('gemini:', '');
                opt.innerText = `🔒 ${displayName}`;
                geminiGroup.appendChild(opt);
            });
            select.appendChild(geminiGroup);
        }
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

// --- NEW UI FUNCTIONS ---

function switchTab(tabId) {
    // Buttons
    document.getElementById('tab-btn-clinico').className = tabId === 'clinico'
        ? "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-indigo-400 border-b-2 border-indigo-500 bg-indigo-500/5 transition-all"
        : "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-all";

    document.getElementById('tab-btn-paciente').className = tabId === 'paciente'
        ? "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-indigo-400 border-b-2 border-indigo-500 bg-indigo-500/5 transition-all"
        : "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-slate-500 border-b-2 border-transparent hover:text-slate-300 transition-all";

    // Views
    document.getElementById('view-clinico').classList.toggle('hidden', tabId !== 'clinico');
    document.getElementById('view-paciente').classList.toggle('hidden', tabId !== 'paciente');
}

function copyPatientSummary() {
    const points = document.getElementById('pat-points').value;
    const task = document.getElementById('pat-task').value;

    const niceText = `🌟 *Resumen de tu Sesión*\n\n🧠 *Puntos Clave:*\n${points}\n\n📝 *Tu Misión Semanal:*\n${task}\n\n_Recuerda: El progreso es paso a paso. ¡Nos vemos la próxima!_`;

    navigator.clipboard.writeText(niceText).then(() => {
        alert("¡Copiado! Listo para pegar en WhatsApp.");
    });
}

// --- UPDATED SESSION LOGIC ---

async function openSession(id) {
    currentSessionId = id;
    const player = document.getElementById('modal-audio-player');
    const playBtn = document.getElementById('play-btn');

    // Reset UI
    player.src = '';
    playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
    switchTab('clinico'); // Default tab

    // Reset Fields
    document.getElementById('soap-s').value = '';
    document.getElementById('soap-o').value = '';
    document.getElementById('soap-a').value = '';
    document.getElementById('soap-p').value = '';
    document.getElementById('pat-points').value = '';
    document.getElementById('pat-task').value = '';
    document.getElementById('risks-container').innerHTML = '';
    document.getElementById('sentiment-badge').innerText = 'Estado: --';
    document.getElementById('sentiment-badge').className = 'px-2.5 py-1 rounded-md bg-slate-800 text-[10px] uppercase font-bold text-slate-400 border border-slate-700';

    try {
        const response = await fetch(`${API_URL}/sessions/${id}?token=${authToken}`);
        if (response.status === 401) return handleUnauthorized();
        const data = await response.json();

        // 1. Transcript
        document.getElementById('session-date-display').innerText = `Sesión del: ${new Date(data.created_at).toLocaleString()}`;
        document.getElementById('modal-transcript').innerText = data.transcription_raw || "Esperando transcripción...";

        // 2. Audio
        if (data.status === 'completed' || data.status === 'transcribed') {
            player.src = `${API_URL}/sessions/${id}/audio?token=${authToken}`;
        }

        // 3. Analysis Loading State
        const loader = document.getElementById('analysis-loader');
        const isProcessing = ['queued', 'transcribing', 'analyzing', 'securing'].includes(data.status);
        loader.classList.toggle('hidden', !isProcessing);

        // Disable inputs if processing
        const inputs = document.querySelectorAll('#view-clinico textarea, #view-paciente textarea');
        inputs.forEach(el => el.disabled = isProcessing);


        // 4. Fill Data (if available)
        const struct = data.structured_json || {};

        // Badge Info
        const badge = document.getElementById('model-badge');
        badge.innerText = struct._model_file ? `IA: ${struct._model_file}` : 'IA';
        badge.classList.remove('hidden');

        // --- DUAL MODE HANDLING ---
        if (struct.clinico || struct.paciente) {
            // New Dual Structure
            const clin = struct.clinico || {};
            const pat = struct.paciente || {};
            const suggestions = struct.sugerencias_ia || []; // New field

            document.getElementById('soap-s').value = clin.subjetivo || '';
            document.getElementById('soap-o').value = clin.objetivo || '';
            document.getElementById('soap-a').value = clin.analisis || '';
            document.getElementById('soap-p').value = clin.plan || '';

            // Risks
            const rContainer = document.getElementById('risks-container');
            rContainer.innerHTML = '';
            if (clin.riesgos && Array.isArray(clin.riesgos)) {
                clin.riesgos.forEach(r => {
                    const div = document.createElement('div');
                    const isSafe = r.toLowerCase().includes('ninguno') || r.toLowerCase().includes('bajo') || r.toLowerCase().includes('no se detecta');
                    div.className = `p-2 rounded border text-[10px] font-bold ${isSafe ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/10 text-rose-300 border-rose-500/20'}`;
                    div.innerText = r;
                    rContainer.appendChild(div);
                });
            } else {
                rContainer.innerHTML = '<span class="text-xs text-slate-500 italic">No evaluado</span>';
            }

            // Suggestions (New)
            const sList = document.getElementById('suggestions-list');
            if (sList) {
                sList.innerHTML = '';
                if (suggestions.length > 0) {
                    suggestions.forEach(s => {
                        const li = document.createElement('li');
                        li.innerText = s;
                        sList.appendChild(li);
                    });
                } else {
                    sList.innerHTML = '<span class="text-[10px] text-slate-600 italic">Sin sugerencias adicionales</span>';
                }
            }

            // Patient
            if (pat.puntos_clave && Array.isArray(pat.puntos_clave)) {
                document.getElementById('pat-points').value = pat.puntos_clave.map(p => `• ${p}`).join('\n');
            }
            document.getElementById('pat-task').value = pat.tarea_semana || '';

            // Sentiment
            if (struct.sentimiento) {
                const sBadge = document.getElementById('sentiment-badge');
                // Simple mapping for excitement/color
                let colorClass = 'bg-slate-800 text-slate-300 border-slate-700';
                if (struct.sentimiento.match(/ansioso|triste|preocupado|angustiado/i)) colorClass = 'bg-amber-900/30 text-amber-200 border-amber-500/30';
                else if (struct.sentimiento.match(/feliz|esperanzado|motivado|tranquilo/i)) colorClass = 'bg-emerald-900/30 text-emerald-200 border-emerald-500/30';

                sBadge.innerText = struct.sentimiento;
                sBadge.setAttribute('class', `px-3 py-2 rounded-lg text-xs font-medium border ${colorClass}`);
            }

        } else if (struct.nota_clinica) {
            // Legacy / Fallback (Simple Note)
            document.getElementById('soap-s').value = struct.nota_clinica;
            document.getElementById('soap-o').value = "--- Migrado de versión anterior ---";
        }

        // Icon toggle logic
        playBtn.onclick = () => player.paused ? player.play() : player.pause();
        player.onplay = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`;
        player.onpause = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
        player.onended = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;

        // Handle Save Button
        const saveBtn = document.getElementById('save-btn');
        saveBtn.onclick = () => saveSessionEdits(id);

        document.getElementById('session-modal').classList.remove('hidden');
    } catch (e) {
        console.error("DEBUG: Open session error", e);
        alert("Error al abrir detalle: " + e.message);
    }
}

async function saveSessionEdits(id) {
    const btn = document.getElementById('save-btn');
    const originalText = btn.innerText;
    btn.innerText = "Guardando...";
    btn.disabled = true;

    // Construct Dual JSON
    const dataToSave = {
        clinico: {
            subjetivo: document.getElementById('soap-s').value,
            objetivo: document.getElementById('soap-o').value,
            analisis: document.getElementById('soap-a').value,
            plan: document.getElementById('soap-p').value,
            riesgos: [] // We don't edit risks via text yet, could preserve original if needed
        },
        paciente: {
            puntos_clave: document.getElementById('pat-points').value.split('\n').map(l => l.replace(/^•\s*/, '')).filter(Boolean),
            tarea_semana: document.getElementById('pat-task').value
        }
        // sentiment preserved in backend or needs hidden field
    };

    const formData = new FormData();
    formData.append('token', authToken);
    formData.append('data', JSON.stringify(dataToSave));

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

// Recording & UI Helpers - REAL-TIME STREAMING
// Chunks are sent immediately to server for parallel transcription
let chunkingInterval = null;
let audioStream = null;
let activeSessionId = null;  // Session ID for streaming
let chunksSent = 0;

// --- PAUSE / RESUME LOGIC ---
let isPaused = false;
let pauseStartTime = 0;
let totalPausedTime = 0;

async function toggleRecording() {
    // If we are recording (or paused), STOP everything
    if (mediaRecorder && (mediaRecorder.state === 'recording' || isPaused)) {
        // Stop recording
        if (chunkingInterval) {
            clearInterval(chunkingInterval);
            chunkingInterval = null;
        }

        // Stop current MediaRecorder (triggers final chunk upload)
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }

        // Stop all tracks
        if (audioStream) {
            audioStream.getTracks().forEach(t => t.stop());
            audioStream = null;
        }

        // Reset UI
        document.getElementById('record-card').classList.remove('border-rose-500', 'border-amber-500');

        // Reset Icon to Microphone
        document.getElementById('record-icon-bg').innerHTML = `
            <svg class="w-8 h-8 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z">
                </path>
            </svg>
        `;

        document.getElementById('record-title').innerText = "Grabar en Vivo";
        document.getElementById('record-title').classList.remove('text-amber-500');
        document.getElementById('record-timer-text').innerText = "Inicia grabación directa";
        clearInterval(recordingInterval);

        // Hide Pause Button
        document.getElementById('pause-btn').classList.add('hidden');
        resetPauseUI();

        // Hide progress
        const progressContainer = document.getElementById('chunk-progress-container');
        progressContainer.classList.add('hidden');

        // Send finish signal to server after last chunk uploads
        setTimeout(async () => {
            if (activeSessionId && chunksSent > 0) {
                console.log(`🏁 Finishing session ${activeSessionId} with ${chunksSent} chunks`);

                const formData = new FormData();
                formData.append('token', authToken);
                formData.append('total_chunks', chunksSent.toString());

                try {
                    const finishRes = await fetch(`${API_URL}/recording/${activeSessionId}/finish`, {
                        method: 'POST',
                        body: formData
                    });

                    if (finishRes.ok) {
                        console.log(`✅ Session ${activeSessionId} finish signal sent`);
                        loadSessions(selectedPatientId);
                    }
                } catch (e) {
                    console.error("Error finishing session:", e);
                }

                activeSessionId = null;
                chunksSent = 0;
                isPaused = false;
                totalPausedTime = 0;
            }
        }, 500);

    } else {
        // START RECORDING
        try {
            if (!selectedPatientId || !authToken) {
                alert("Selecciona un paciente primero");
                return;
            }

            // 1. Start recording session on server FIRST
            const model = document.getElementById('model-select').value;
            const formData = new FormData();
            formData.append('token', authToken);
            if (model) formData.append('model', model);

            const startRes = await fetch(`${API_URL}/recording/${selectedPatientId}/start`, {
                method: 'POST',
                body: formData
            });

            if (!startRes.ok) {
                throw new Error("No se pudo iniciar la sesión de grabación");
            }

            const startData = await startRes.json();
            activeSessionId = startData.session_id;
            chunksSent = 0;
            isPaused = false;
            totalPausedTime = 0;
            console.log(`📹 Streaming session started: ${activeSessionId}`);

            // 2. Get audio stream
            audioStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });

            // Detect supported format
            recordingMimeType = 'audio/webm;codecs=opus';
            recordingExtension = 'webm';

            if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
                recordingMimeType = 'audio/ogg;codecs=opus';
                recordingExtension = 'ogg';
            }

            recordingChunks = [];

            // Reset and show chunk progress UI
            const progressContainer = document.getElementById('chunk-progress-container');
            const chunkCountEl = document.getElementById('chunk-count');
            const chunkListEl = document.getElementById('chunk-list');
            chunkCountEl.innerText = '0';
            chunkListEl.innerHTML = '';
            progressContainer.classList.remove('hidden');

            // Show Pause Button
            document.getElementById('pause-btn').classList.remove('hidden');
            resetPauseUI();

            // 3. Start first chunk recorder (streaming mode)
            startStreamingChunkRecorder(audioStream, 0, chunkCountEl, chunkListEl);

            startChunkRotation(chunkCountEl, chunkListEl);

            // Change Icon to STOP (Square)
            document.getElementById('record-icon-bg').innerHTML = `
                <svg class="w-8 h-8 text-rose-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M6 6h12v12H6z" />
                </svg>
            `;

            document.getElementById('record-card').classList.add('border-rose-500');
            document.getElementById('record-title').innerText = "Detener o Pausar";
            startTime = Date.now();

            requestAnimationFrame(updateTimer);

        } catch (err) {
            console.error(err);
            alert("Error al iniciar grabación: " + err.message);
            activeSessionId = null;
        }
    }
}

function startChunkRotation(chunkCountEl, chunkListEl) {
    if (chunkingInterval) clearInterval(chunkingInterval);

    // Set interval to rotate chunks every 30 seconds
    chunkingInterval = setInterval(() => {
        if (mediaRecorder && mediaRecorder.state === 'recording' && !isPaused) {
            const nextChunkIndex = chunksSent;
            console.log(`⏱️ Rotating to chunk ${nextChunkIndex + 1}...`);

            // Stop current recorder (triggers upload)
            mediaRecorder.stop();

            // Start new recorder for next chunk
            setTimeout(() => {
                if (audioStream && audioStream.active && !isPaused) {
                    startStreamingChunkRecorder(audioStream, nextChunkIndex, chunkCountEl, chunkListEl);
                }
            }, 100);
        }
    }, 30000); // 30 seconds per chunk
}

function updateTimer() {
    if ((mediaRecorder && mediaRecorder.state === 'recording') || isPaused) {
        if (!isPaused) {
            const diff = Date.now() - startTime - totalPausedTime;
            document.getElementById('record-timer-text').innerText = `Grabando: ${Math.floor(diff / 1000)}s`;
        }
        requestAnimationFrame(updateTimer);
    }
}

function togglePause() {
    if (!activeSessionId) return;

    if (isPaused) {
        // RESUME
        isPaused = false;
        totalPausedTime += (Date.now() - pauseStartTime);

        console.log("▶️ Resuming recording...");

        // Update UI
        document.getElementById('record-card').classList.replace('border-amber-500', 'border-rose-500');
        document.getElementById('record-title').classList.remove('text-amber-500');
        document.getElementById('record-title').innerText = "Detener y Guardar";

        // Restart Timer Display
        requestAnimationFrame(updateTimer);

        // Reset Pause Button Icon to Pause
        document.getElementById('pause-icon').innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>`;

        // Start new recorder
        const chunkCountEl = document.getElementById('chunk-count');
        const chunkListEl = document.getElementById('chunk-list');
        startStreamingChunkRecorder(audioStream, chunksSent, chunkCountEl, chunkListEl);
        startChunkRotation(chunkCountEl, chunkListEl);

    } else {
        // PAUSE
        isPaused = true;
        pauseStartTime = Date.now();

        console.log("⏸️ Pausing recording...");

        // Stop current chunk (uploads partial)
        if (mediaRecorder && mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }

        // Clear rotation interval
        if (chunkingInterval) {
            clearInterval(chunkingInterval);
            chunkingInterval = null;
        }

        // Update UI
        document.getElementById('record-card').classList.replace('border-rose-500', 'border-amber-500');
        document.getElementById('record-title').classList.add('text-amber-500');
        document.getElementById('record-title').innerText = "Pausado";

        // Change Pause Button Icon to Play
        document.getElementById('pause-icon').innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>`;
    }
}

function resetPauseUI() {
    isPaused = false;
    document.getElementById('pause-icon').innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>`;
    document.getElementById('record-title').classList.remove('text-amber-500');
}

function startStreamingChunkRecorder(stream, chunkIndex, chunkCountEl, chunkListEl) {
    const options = {
        mimeType: recordingMimeType,
        audioBitsPerSecond: 24000
    };

    mediaRecorder = new MediaRecorder(stream, options);
    let chunkData = [];

    mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
            chunkData.push(event.data);
        }
    };

    mediaRecorder.onstop = async () => {
        // Only upload if we have data AND we are still in a valid session
        if (chunkData.length > 0 && activeSessionId) {
            const chunkBlob = new Blob(chunkData, { type: recordingMimeType });
            const currentChunkIndex = chunksSent;  // Use current counter

            console.log(`📤 Uploading chunk ${currentChunkIndex} (${(chunkBlob.size / 1024).toFixed(1)} KB)...`);

            // Upload chunk immediately to server for parallel transcription
            const formData = new FormData();
            formData.append('token', authToken);
            formData.append('chunk_index', currentChunkIndex.toString());
            formData.append('chunk', chunkBlob, `chunk_${currentChunkIndex}.${recordingExtension}`);

            try {
                const res = await fetch(`${API_URL}/recording/${activeSessionId}/chunk`, {
                    method: 'POST',
                    body: formData
                });

                if (res.ok) {
                    chunksSent++; // Increment counter only on success
                    console.log(`✅ Chunk ${currentChunkIndex} uploaded - transcribing in parallel`);

                    // Update visual progress
                    if (chunkCountEl) chunkCountEl.innerText = chunksSent.toString();

                    // Add visual chunk indicator (green = uploading/transcribing)
                    if (chunkListEl) {
                        const chunkBadge = document.createElement('div');
                        chunkBadge.className = 'bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded text-[10px] font-bold animate-in zoom-in-50 duration-200';
                        chunkBadge.innerText = `${chunksSent}`;
                        chunkListEl.appendChild(chunkBadge);
                    }
                } else {
                    console.error(`❌ Failed to upload chunk ${currentChunkIndex}`);
                }
            } catch (e) {
                console.error(`❌ Error uploading chunk ${currentChunkIndex}:`, e);
            }
        }
    };

    mediaRecorder.start();
    console.log(`🎙️ Recording chunk - streaming active`);
}


// ------------------------------------
// UI HELPERS (Modals & Navigation)
// ------------------------------------

function showConfirmModal(file) {
    pendingAudioFile = file;
    document.getElementById('confirm-modal').classList.remove('hidden');
}

function confirmUpload() {
    // Handle single file upload
    if (pendingAudioFile) {
        uploadFile(pendingAudioFile);
        pendingAudioFile = null;
    }
    document.getElementById('confirm-modal').classList.add('hidden');
}

function cancelUpload() {
    pendingAudioFile = null;
    document.getElementById('confirm-modal').classList.add('hidden');
}

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

