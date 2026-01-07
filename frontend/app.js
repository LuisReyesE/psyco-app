const API_URL = "http://localhost:8000";
let selectedPatientId = null;
let currentSessionId = null;
let mediaRecorder;
let audioChunks = [];
let recordingInterval;
let startTime;
let allPatients = []; // For filtering
let pendingAudioFile = null;

// Health Check
async function checkServerStatus() {
    const dot = document.getElementById('status-dot');
    const text = document.querySelector('.btn-status span:last-child');
    try {
        const res = await fetch(`${API_URL}/health`);
        if (res.ok) {
            dot.className = "w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.5)]";
            text.innerText = "Servidor Activo";
            text.className = "text-emerald-400";
        } else {
            throw new Error();
        }
    } catch (e) {
        dot.className = "w-2 h-2 rounded-full bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.5)] animate-pulse";
        text.innerText = "Desconectado (Click Reintentar)";
        text.className = "text-rose-400";
    }
}

function formatDuration(seconds) {
    if (!seconds && seconds !== 0) return "-";
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    checkServerStatus();
    loadPatients().then(() => {
        // Recover state
        const savedId = sessionStorage.getItem('activePatientId');
        const savedName = sessionStorage.getItem('activePatientName');
        if (savedId && savedName) {
            selectPatient(parseInt(savedId), savedName);
        }
    });
    loadModels();

    // Polling
    setInterval(checkServerStatus, 5000);
    setInterval(() => {
        if (selectedPatientId) loadSessions(selectedPatientId);
    }, 5000); // 5s to follow processing in real time
});

async function loadModels() {
    try {
        const res = await fetch(`${API_URL}/models/`);
        const models = await res.json();
        const select = document.getElementById('model-select');
        select.innerHTML = '<option value="">Automático (Recomendado)</option>';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            const displayName = m.replace('ollama:', '');
            opt.innerText = displayName;

            // Default select gemma3 (any 4b variant)
            if (displayName.toLowerCase().includes('gemma3')) {
                opt.selected = true;
                console.log("Setting default model to:", m);
            }
            select.appendChild(opt);
        });
    } catch (e) {
        console.error("Error loading models", e);
    }
}

async function loadPatients() {
    try {
        const response = await fetch(`${API_URL}/patients/`);
        allPatients = await response.json();
        renderPatients(allPatients);
    } catch (e) {
        console.error("Error loading patients", e);
    }
}

function renderPatients(patients) {
    const list = document.getElementById('patient-list');
    list.innerHTML = '';

    if (patients.length === 0) {
        list.innerHTML = '<div class="text-center py-10 text-slate-600 text-xs">No hay pacientes</div>';
        return;
    }

    patients.forEach(p => {
        const div = document.createElement('div');
        div.className = `patient-item p-4 rounded-xl cursor-pointer transition-all duration-300 flex justify-between items-center group ${selectedPatientId === p.id ? 'selected' : 'hover:bg-slate-800/30'}`;
        div.innerHTML = `
            <div class="flex flex-col flex-1" onclick="selectPatient(${p.id}, '${p.full_name}')">
                <span class="font-bold text-sm ${selectedPatientId === p.id ? 'text-indigo-400' : 'text-slate-200 group-hover:text-indigo-300'}">${p.full_name}</span>
                <span class="text-[9px] text-slate-500 uppercase tracking-tighter">Ficha Clínica</span>
            </div>
            <div class="flex items-center gap-2">
                <button onclick="deletePatient(event, ${p.id}, '${p.full_name}')" class="p-1 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-rose-500/20 rounded text-slate-500 hover:text-rose-400" title="Eliminar Paciente">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                    </svg>
                </button>
                <div class="opacity-0 group-hover:opacity-100 transition-opacity">
                    <svg class="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                    </svg>
                </div>
            </div>
        `;
        list.appendChild(div);
    });
}

async function deletePatient(event, id, name) {
    event.stopPropagation();
    if (!confirm(`¿Estás seguro de eliminar al paciente "${name}"? Se borrarán todas sus sesiones de forma permanente.`)) return;

    try {
        const response = await fetch(`${API_URL}/patients/${id}`, { method: 'DELETE' });
        if (response.ok) {
            if (selectedPatientId === id) {
                selectedPatientId = null;
                sessionStorage.removeItem('activePatientId');
                sessionStorage.removeItem('activePatientName');
                document.getElementById('intro-view').classList.remove('hidden');
                document.getElementById('patient-view').classList.add('hidden');
            }
            loadPatients();
        }
    } catch (e) {
        console.error("Error deleting patient", e);
    }
}

function filterPatients() {
    const term = document.getElementById('patient-search').value.toLowerCase();
    const filtered = allPatients.filter(p => p.full_name.toLowerCase().includes(term));
    renderPatients(filtered);
}

function selectPatient(id, name) {
    if (!id) return;
    selectedPatientId = id;

    // Save state for persistence
    sessionStorage.setItem('activePatientId', id);
    sessionStorage.setItem('activePatientName', name);

    console.log("Persistence: Selected", id);

    // UI Switches
    const intro = document.getElementById('intro-view');
    const pview = document.getElementById('patient-view');
    if (intro) intro.classList.add('hidden');
    if (pview) pview.classList.remove('hidden');

    document.getElementById('active-patient-name').innerText = name;

    // Load their history
    loadSessions(id);

    // Refresh sidebar for selection highlight
    renderPatients(allPatients);
}

async function createPatient() {
    const nameInput = document.getElementById('patient-name-input');
    const name = nameInput.value.trim();
    if (!name) return;

    try {
        const response = await fetch(`${API_URL}/patients/?name=${encodeURIComponent(name)}`, { method: 'POST' });
        if (response.ok) {
            nameInput.value = '';
            hideNewPatientModal();
            loadPatients();
        }
    } catch (e) {
        console.error("Error creating patient", e);
    }
}

async function loadSessions(patientId) {
    try {
        const response = await fetch(`${API_URL}/sessions/?patient_id=${patientId}`);
        const sessions = await response.json();
        const body = document.getElementById('session-table-body');
        document.getElementById('session-count').innerText = sessions.length;

        body.innerHTML = '';
        if (sessions.length === 0) {
            body.innerHTML = '<tr><td colspan="3" class="px-6 py-10 text-center text-slate-500 text-xs italic">No hay sesiones grabadas para este paciente</td></tr>';
            return;
        }

        let hasProcessing = false;
        sessions.reverse().forEach(s => {
            const row = document.createElement('tr');
            row.className = "hover:bg-slate-800/40 transition-all group";

            let statusMarkup = "";
            let durationText = "-";
            const struct = s.structured_json || {};

            if (s.status === 'completed') {
                statusMarkup = `<span class="bg-emerald-500/10 text-emerald-500 text-[9px] px-2 py-0.5 rounded-full font-bold border border-emerald-500/20">COMPLETO</span>`;
                if (struct._metrics) {
                    const total = Math.round(struct._metrics.total_time);
                    durationText = `<span class="text-xs text-slate-400" title="Trans: ${formatDuration(struct._metrics.transcription_time)} | IA: ${formatDuration(struct._metrics.generation_time)}">${formatDuration(total)}</span>`;
                }
            } else if (s.status === 'processing') {
                statusMarkup = `<span class="bg-rose-500/10 text-rose-500 text-[9px] px-2 py-0.5 rounded-full font-bold border border-rose-500/20 animate-pulse">PROCESANDO</span>`;
                // Calculate elapsed time (assume local time from backend)
                const elapsed = Math.floor((Date.now() - new Date(s.created_at).getTime()) / 1000);
                durationText = `<span class="text-xs text-rose-400 animate-pulse">${formatDuration(elapsed)}...</span>`;
                hasProcessing = true;
            } else {
                statusMarkup = `<span class="bg-slate-500/10 text-slate-500 text-[9px] px-2 py-0.5 rounded-full font-bold border border-slate-500/20">ERROR</span>`;
                durationText = `<span class="text-xs text-slate-500">Error</span>`;
            }

            row.innerHTML = `
                <td class="px-6 py-4">${statusMarkup}</td>
                <td class="px-6 py-4">
                    <div class="flex flex-col">
                        <span class="text-slate-100 text-sm font-medium">${new Date(s.created_at).toLocaleDateString()}</span>
                        <span class="text-[10px] text-slate-500">${new Date(s.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                </td>
                <td class="px-6 py-4">${durationText}</td>
                <td class="px-6 py-4 text-right">
                    <div class="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onclick="openSession(${s.id})" class="bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600 hover:text-white px-3 py-1.5 rounded-lg text-xs font-bold transition-all">Detalles</button>
                        <button onclick="deleteSession(${s.id})" class="p-1.5 hover:bg-rose-500/20 text-slate-600 hover:text-rose-400 rounded-lg transition-all" title="Eliminar">🗑️</button>
                    </div>
                </td>
            `;
            body.appendChild(row);
        });
    } catch (e) {
        console.error("Error loading sessions", e);
    }
}

async function uploadFile(file) {
    if (!selectedPatientId) {
        console.error("No patient selected for upload");
        return;
    }

    console.log("Uploading file for patient:", selectedPatientId);
    const formData = new FormData();
    formData.append('file', file);

    const modelSelect = document.getElementById('model-select');
    if (modelSelect.value) {
        formData.append('model', modelSelect.value);
    }

    try {
        const response = await fetch(`${API_URL}/upload/${selectedPatientId}`, {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        loadSessions(selectedPatientId);
    } catch (e) {
        console.error("Upload failed", e);
        alert("Error al subir archivo");
    }
}

function showConfirmModal(file) {
    pendingAudioFile = file;
    const modelSelect = document.getElementById('model-select');
    const modelName = modelSelect.options[modelSelect.selectedIndex]?.text || "Automático";
    document.getElementById('confirm-model-name').innerText = modelName;
    document.getElementById('confirm-modal').classList.remove('hidden');
}

function confirmUpload() {
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

document.getElementById('audio-input').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) showConfirmModal(file);
    e.target.value = '';
});

async function toggleRecording() {
    const card = document.getElementById('record-card');
    const iconBg = document.getElementById('record-icon-bg');
    const title = document.getElementById('record-title');
    const timerText = document.getElementById('record-timer-text');

    if (!mediaRecorder || mediaRecorder.state === 'inactive') {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => audioChunks.push(event.data);
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                const file = new File([audioBlob], `vivo_${Date.now()}.wav`, { type: 'audio/wav' });
                showConfirmModal(file);
            };

            mediaRecorder.start();
            card.classList.replace('hover:border-rose-500/40', 'border-rose-500');
            iconBg.classList.replace('bg-rose-600/10', 'bg-rose-600');
            iconBg.querySelector('svg').classList.add('animate-pulse');
            title.innerText = "Detener y Guardar";

            startTime = Date.now();
            recordingInterval = setInterval(() => {
                const diff = Date.now() - startTime;
                const sec = Math.floor(diff / 1000) % 60;
                const min = Math.floor(diff / 60000);
                timerText.innerText = `Grabando: ${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
            }, 1000);

        } catch (err) {
            console.error(err);
            alert("Acceso al micrófono denegado");
        }
    } else {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        card.classList.replace('border-rose-500', 'hover:border-rose-500/40');
        iconBg.classList.replace('bg-rose-600', 'bg-rose-600/10');
        iconBg.querySelector('svg').classList.remove('animate-pulse');
        title.innerText = "Grabar en Vivo";
        timerText.innerText = "Inicia grabación directa";
        clearInterval(recordingInterval);
    }
}

function cleanClinicalNote(data) {
    if (!data) return '';

    // Case 1: The model returned the text under the expected key
    if (data.nota_clinica) {
        let text = data.nota_clinica;
        // If the content of the key is STILL a JSON string (double encoding)
        if (typeof text === 'string' && (text.trim().startsWith('{') || text.trim().startsWith('['))) {
            try {
                const inner = JSON.parse(text);
                return cleanClinicalNote(inner);
            } catch (e) {
                return text.replace(/[{}"[\]]/g, '').trim();
            }
        }
        return text;
    }

    // Case 2: The model returned multiple keys (the breakdown)
    // We join all non-internal keys into a paragraph
    const values = [];
    for (const key in data) {
        if (!key.startsWith('_')) {
            values.push(data[key]);
        }
    }

    if (values.length > 0) {
        return values.join(' ').replace(/[{}"[\]]/g, '').trim();
    }

    return '';
}

async function openSession(id) {
    currentSessionId = id;
    try {
        const response = await fetch(`${API_URL}/sessions/${id}`);
        const data = await response.json();

        document.getElementById('session-date-display').innerText = `Sesión del: ${new Date(data.created_at).toLocaleString()}`;
        document.getElementById('modal-transcript').innerText = data.transcription_raw || "La IA aún no termina la transcripción...";

        const struct = data.structured_json || {};
        const badge = document.getElementById('model-badge');
        if (struct._model_file) {
            badge.innerText = `IA: ${struct._model_file} (${struct._model_used || 'json'})`;
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }

        const notaArea = document.getElementById('edit-nota-clinica');
        if (struct.error) {
            notaArea.value = `Error en análisis IA: ${struct.error}`;
            notaArea.classList.add('text-rose-400');
        } else {
            const cleanedNote = cleanClinicalNote(struct);
            notaArea.value = cleanedNote || (data.status === 'processing' ? 'Analizando conversación...' : 'La IA no pudo generar un resumen esta vez.');
            notaArea.classList.remove('text-rose-400');
        }

        document.getElementById('session-modal').classList.remove('hidden');
    } catch (e) {
        console.error("Error opening session", e);
    }
}

function closeModal() {
    document.getElementById('session-modal').classList.add('hidden');
}

async function saveSessionData() {
    if (!currentSessionId) return;
    const nota = document.getElementById('edit-nota-clinica').value;

    try {
        const response = await fetch(`${API_URL}/sessions/${currentSessionId}/update`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nota_clinica: nota })
        });
        if (response.ok) {
            alert("Nota guardada");
            closeModal();
            loadSessions(selectedPatientId);
        }
    } catch (e) {
        console.error("Error saving", e);
    }
}

document.getElementById('save-btn').onclick = saveSessionData;

async function deleteSession(id) {
    if (!confirm("¿Eliminar registro permanentemente?")) return;
    try {
        const response = await fetch(`${API_URL}/sessions/${id}`, { method: 'DELETE' });
        if (response.ok) loadSessions(selectedPatientId);
    } catch (e) {
        console.error(e);
    }
}

// Modal Helpers
function showNewPatientModal() { document.getElementById('new-patient-modal').classList.remove('hidden'); }
function hideNewPatientModal() { document.getElementById('new-patient-modal').classList.add('hidden'); }
