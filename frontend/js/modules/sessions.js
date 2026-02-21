/**
 * Sessions Module
 * Session CRUD, display, upload, and detail view
 */

import { AppState } from '../state.js';
import { API_URL } from '../api.js';
import { formatDuration } from '../utils/formatter.js';

/**
 * Load sessions for a patient
 * @param {number} patientId 
 */
export async function loadSessions(patientId) {
    if (!AppState.authToken) return;

    try {
        const response = await fetch(`${API_URL}/sessions/?patient_id=${patientId}&token=${AppState.authToken}`);

        if (response.status === 401) {
            // Import dynamically to avoid circular dependency
            const { handleUnauthorized } = await import('./auth.js');
            handleUnauthorized();
            return;
        }

        const sessions = await response.json();

        // Register already completed sessions to avoid notifications on first load
        if (AppState.isFirstLoad) {
            sessions.forEach(s => {
                if (s.status === 'completed') AppState.completedSessionsList.add(s.id);
            });
            AppState.isFirstLoad = false;
        }

        checkForActiveProcessing(sessions);
        renderSessionsTable(sessions);
    } catch (e) {
        console.error("Error loading sessions:", e);
    }
}

/**
 * Render the sessions table
 * @param {Array} sessions 
 */
export function renderSessionsTable(sessions) {
    const body = document.getElementById('session-table-body');
    document.getElementById('session-count').innerText = sessions.length;

    body.innerHTML = '';
    if (sessions.length === 0) {
        body.innerHTML = '<tr><td colspan="4" class="px-6 py-10 text-center text-slate-500 text-xs italic">No hay sesiones grabadas para este paciente</td></tr>';
        return;
    }

    sessions.forEach(s => {
        const row = document.createElement('tr');
        row.className = "hover:bg-highlight transition-all group border-b border-border";

        let statusMarkup = "";
        let durationText = "-";
        const struct = s.structured_json || {};

        if (s.status === 'completed') {
            statusMarkup = `<span class="status-badge badge-success text-[9px] px-2 py-0.5 rounded-full font-bold border">PROTEGIDO</span>`;
            if (struct._metrics) {
                durationText = `<span class="text-xs text-slate-400">${formatDuration(struct._metrics.total_time)}</span>`;
            }
        } else if (s.status === 'recording') {
            const ageMinutes = (Date.now() - new Date(s.created_at).getTime()) / 60000;
            const isLocallyPaused = (s.id === AppState.activeSessionId && AppState.isPaused);

            if (ageMinutes < 90) {
                if (isLocallyPaused) {
                    statusMarkup = `<span class="status-badge badge-warning text-[9px] px-2 py-0.5 rounded-full font-bold border">PAUSADO</span>`;
                    durationText = `<span class="text-[10px] text-amber-400 italic">En espera...</span>`;
                } else {
                    statusMarkup = `<span class="badge-live text-[9px] px-2 py-0.5 rounded-full font-bold border animate-pulse">EN VIVO</span>`;
                    if (s.chunks_transcribed !== undefined && s.chunks_total !== undefined && s.chunks_total > 0) {
                        durationText = `<span class="text-[10px] text-brand italic font-medium">${s.chunks_transcribed}/${s.chunks_total} chunks</span>`;
                    } else {
                        durationText = `<span class="text-[10px] text-brand italic font-medium">Grabando...</span>`;
                    }
                }
            } else {
                statusMarkup = `<span class="status-badge badge-neutral text-[9px] px-2 py-0.5 rounded-full font-bold border">ABANDONADA</span>`;
                durationText = `<span class="text-[10px] text-muted italic">Sesión incompleta</span>`;
            }
        } else if (['queued', 'transcribing', 'analyzing', 'securing'].includes(s.status)) {
            const text = { queued: 'EN COLA', transcribing: 'TRANSCRIBIENDO', analyzing: 'ANALIZANDO', securing: 'CIFRANDO' };
            const badgeClasses = { queued: 'badge-warning', transcribing: 'badge-brand', analyzing: 'badge-brand', securing: 'badge-success' };
            statusMarkup = `<span class="status-badge ${badgeClasses[s.status]} text-[9px] px-2 py-0.5 rounded-full font-bold border animate-pulse">${text[s.status]}</span>`;
            durationText = `<span class="text-[10px] text-secondary italic">Procesando...</span>`;
        } else {
            statusMarkup = `<span class="status-badge badge-danger text-[9px] px-2 py-0.5 rounded-full font-bold border">ERROR</span>`;
        }

        row.innerHTML = `
            <td class="px-6 py-4">${statusMarkup}</td>
            <td class="px-6 py-4">
                <div class="flex flex-col">
                    <span class="text-primary text-sm font-medium">${new Date(s.created_at).toLocaleDateString()}</span>
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

/**
 * Check if any session is currently processing
 * @param {Array} sessions 
 * @returns {boolean}
 */
export function checkForActiveProcessing(sessions) {
    const processingStates = ['recording', 'queued', 'transcribing', 'analyzing', 'securing'];
    const isProcessing = sessions.some(s => processingStates.includes(s.status));

    if (isProcessing !== AppState.hasActiveProcessing) {
        if (isProcessing) {
            console.log('🔄 Procesamiento detectado - Polling activo cada 1s');
            import('./polling.js').then(m => m.forcePollUpdate());
        } else {
            console.log('⏸️ Sin procesamiento - Polling pausado (5s)');
        }
    }

    AppState.hasActiveProcessing = isProcessing;
    return isProcessing;
}

/**
 * Delete a session
 * @param {Event} event 
 * @param {number} id 
 */
export async function deleteSession(event, id) {
    event.stopPropagation();
    if (!confirm("¿Eliminar esta sesión permanentemente?")) return;

    try {
        await fetch(`${API_URL}/sessions/${id}`, { method: 'DELETE' });
        loadSessions(AppState.selectedPatientId);
    } catch (e) {
        console.error("Error deleting session:", e);
    }
}

/**
 * Upload a single audio file
 * @param {File} file 
 */
export async function uploadFile(file) {
    if (!AppState.authToken) return;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('token', AppState.authToken);

    const model = document.getElementById('model-select').value;
    if (model) formData.append('model', model);

    try {
        const res = await fetch(`${API_URL}/upload/${AppState.selectedPatientId}`, { method: 'POST', body: formData });

        if (!res.ok) {
            let errMsg = "Error al subir el archivo";
            try {
                const errData = await res.json();
                if (errData.detail) errMsg = errData.detail;
            } catch (err) { }
            throw new Error(errMsg);
        }

        loadSessions(AppState.selectedPatientId);
    } catch (e) {
        alert("Atención: " + e.message);
    }
}

/**
 * Open session detail modal
 * @param {number} id 
 */
export async function openSession(id) {
    AppState.currentSessionId = id;
    const player = document.getElementById('modal-audio-player');
    const playBtn = document.getElementById('play-btn');

    // Reset UI
    player.src = '';
    playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
    switchTab('free');

    // Reset Fields
    document.getElementById('nota-clinica-free').value = '';
    document.getElementById('soap-s').value = '';
    document.getElementById('soap-o').value = '';
    document.getElementById('soap-a').value = '';
    document.getElementById('soap-p').value = '';
    document.getElementById('pat-points').value = '';
    document.getElementById('pat-task').value = '';

    const risksContainer = document.getElementById('risks-container');
    const suggestionsList = document.getElementById('suggestions-list');
    const sentimentBadge = document.getElementById('sentiment-badge');

    risksContainer.innerHTML = '';
    suggestionsList.innerHTML = '';
    sentimentBadge.innerText = 'Estado: --';
    sentimentBadge.innerText = 'Estado: --';
    sentimentBadge.className = 'w-full status-badge badge-neutral';

    sentimentBadge.parentElement.classList.remove('hidden');
    risksContainer.parentElement.classList.remove('hidden');
    suggestionsList.parentElement.classList.remove('hidden');

    try {
        const response = await fetch(`${API_URL}/sessions/${id}?token=${AppState.authToken}`);
        if (response.status === 401) {
            const { handleUnauthorized } = await import('./auth.js');
            return handleUnauthorized();
        }
        const data = await response.json();

        const json = data.structured_json || {};

        // 1. Transcript
        document.getElementById('session-date-display').innerText = `Sesión del: ${new Date(data.created_at).toLocaleString()}`;
        document.getElementById('modal-transcript').innerText = data.transcription_raw || "Esperando transcripción...";

        // 1.5 Anonymized Transcript (Hidden by default)
        const anonText = (json._anonymized_transcript) ? json._anonymized_transcript : "(No disponible o no se usó anonimización en esta sesión)";
        document.getElementById('modal-transcript-anonymized').innerText = anonText;

        // Reset transcript tab to RAW
        // Note: Function needs to be available globally or we call it here directly if imported
        // Since it's exported from this module, we can call it.
        toggleTranscriptView('raw');

        // 2. Audio
        if (data.status === 'completed' || data.status === 'transcribed') {
            player.src = `${API_URL}/sessions/${id}/audio?token=${AppState.authToken}`;
        }

        // 3. Analysis Loading State
        const loader = document.getElementById('analysis-loader');
        const isProcessing = ['queued', 'transcribing', 'analyzing', 'securing'].includes(data.status);
        loader.classList.toggle('hidden', !isProcessing);

        const inputs = document.querySelectorAll('#view-free textarea, #view-clinico textarea, #view-paciente textarea');
        inputs.forEach(el => el.disabled = isProcessing);

        // 4. Fill Data
        // json is already defined above

        const badge = document.getElementById('model-badge');
        badge.innerText = json._model_file ? `IA: ${json._model_file}` : 'IA';
        badge.classList.remove('hidden');

        document.getElementById('nota-clinica-free').value = json.nota_clinica_free || json.nota_clinica || '';

        const clinico = json.clinico || {};
        document.getElementById('soap-s').value = clinico.subjetivo || '';
        document.getElementById('soap-o').value = clinico.objetivo || '';
        document.getElementById('soap-a').value = clinico.analisis || '';
        document.getElementById('soap-p').value = clinico.plan || '';

        const paciente = json.paciente || {};
        if (paciente.puntos_clave) {
            const txt = Array.isArray(paciente.puntos_clave) ? paciente.puntos_clave.map(x => `• ${x}`).join('\n') : paciente.puntos_clave;
            document.getElementById('pat-points').value = txt;
        }
        if (paciente.tarea_semana) document.getElementById('pat-task').value = paciente.tarea_semana;

        // Sentiment
        if (json.sentimiento) {
            let badgeClass = 'badge-neutral';
            if (json.sentimiento.match(/ansioso|triste|preocupado|angustiado|miedo/i)) badgeClass = 'badge-warning';
            else if (json.sentimiento.match(/feliz|esperanzado|motivado|tranquilo|apertura/i)) badgeClass = 'badge-success';

            sentimentBadge.innerText = json.sentimiento;
            sentimentBadge.className = `w-full status-badge ${badgeClass}`;
        }

        // Risks
        if (clinico.riesgos && Array.isArray(clinico.riesgos) && clinico.riesgos.length > 0) {
            risksContainer.innerHTML = clinico.riesgos.map(r => `
                <div class="status-badge badge-danger flex items-start gap-2">
                     <span class="mt-0.5">•</span> <span>${r}</span>
                </div>
            `).join('');
        } else {
            risksContainer.innerHTML = '<span class="text-xs text-slate-500 italic">No detectados</span>';
        }

        // Suggestions
        if (json.sugerencias_ia && Array.isArray(json.sugerencias_ia) && json.sugerencias_ia.length > 0) {
            suggestionsList.innerHTML = json.sugerencias_ia.map(s => `<li class="pl-2 border-l-2 border-slate-700 py-0.5">${s}</li>`).join('');
        } else {
            suggestionsList.innerHTML = '<span class="text-[10px] text-slate-600 italic">Sin sugerencias</span>';
        }

        // Audio player controls
        playBtn.onclick = () => player.paused ? player.play() : player.pause();
        player.onplay = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`;
        player.onpause = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
        player.onended = () => playBtn.innerHTML = `<svg class="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;

        document.getElementById('save-btn').onclick = () => saveSessionEdits(id);

        // Smart Tab Selection
        if (json._provider === 'gemini' || json._provider === 'cloud' || (clinico && Object.keys(clinico).length > 0 && clinico.subjetivo)) {
            switchTab('clinico');
        } else if (json._provider === 'ollama' || json.nota_clinica || json.nota_clinica_free) {
            switchTab('free');
        } else {
            // "Dejarlo tal cual estaba por defecto para elegir" (FREE)
            switchTab('free');
        }

        document.getElementById('session-modal').classList.remove('hidden');
    } catch (e) {
        console.error("Error opening session:", e);
        alert("Error al abrir detalle: " + e.message);
    }
}

/**
 * Save session edits
 * @param {number} id 
 */
export async function saveSessionEdits(id) {
    const btn = document.getElementById('save-btn');
    const originalText = btn.innerText;
    btn.innerText = "Guardando...";
    btn.disabled = true;

    const dataToSave = {
        nota_clinica_free: document.getElementById('nota-clinica-free').value,
        clinico: {
            subjetivo: document.getElementById('soap-s').value,
            objetivo: document.getElementById('soap-o').value,
            analisis: document.getElementById('soap-a').value,
            plan: document.getElementById('soap-p').value,
            riesgos: []
        },
        paciente: {
            puntos_clave: document.getElementById('pat-points').value.split('\n').map(l => l.replace(/^•\s*/, '')).filter(Boolean),
            tarea_semana: document.getElementById('pat-task').value
        }
    };

    const formData = new FormData();
    formData.append('token', AppState.authToken);
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

/**
 * Download PDF for current session
 */
export async function downloadPDF() {
    if (!AppState.currentSessionId || !AppState.authToken) return;

    const link = document.createElement('a');
    link.href = `${API_URL}/sessions/${AppState.currentSessionId}/pdf?token=${AppState.authToken}`;
    link.target = '_blank';
    link.download = `Session_${AppState.currentSessionId}.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/**
 * Close session modal
 */
export function closeModal() {
    document.getElementById('session-modal').classList.add('hidden');
    document.getElementById('modal-audio-player').pause();
}

/**
 * Switch between tabs in session detail
 * @param {string} tabId 
 */
export function switchTab(tabId) {
    // Import license check dynamically
    import('./license.js').then(({ openSettingsModal }) => {
        const isProTab = (tabId === 'clinico' || tabId === 'paciente');

        if (isProTab && AppState.currentLicenseTier !== 'PRO') {
            openSettingsModal();
            return;
        }

        document.getElementById('tab-btn-free').className = tabId === 'free'
            ? "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-emerald-600 dark:text-emerald-400 border-b-2 border-emerald-500 bg-emerald-500/5 transition-all text-primary"
            : "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-secondary border-b-2 border-transparent hover:text-primary transition-all";

        document.getElementById('tab-btn-clinico').className = tabId === 'clinico'
            ? "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-indigo-600 dark:text-indigo-400 border-b-2 border-indigo-500 bg-indigo-500/5 transition-all text-primary"
            : "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-secondary border-b-2 border-transparent hover:text-primary transition-all";

        document.getElementById('tab-btn-paciente').className = tabId === 'paciente'
            ? "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-indigo-600 dark:text-indigo-400 border-b-2 border-indigo-500 bg-indigo-500/5 transition-all text-primary"
            : "flex-1 py-3 text-[10px] uppercase font-bold tracking-wider text-secondary border-b-2 border-transparent hover:text-primary transition-all";

        document.getElementById('view-free').classList.toggle('hidden', tabId !== 'free');
        document.getElementById('view-clinico').classList.toggle('hidden', tabId !== 'clinico');
        document.getElementById('view-paciente').classList.toggle('hidden', tabId !== 'paciente');
    });
}

/**
 * Update active session modal silently with real-time data
 * Called by polling logic
 * @param {Array} sessions
 */
export async function updateSessionModalSilently() {
    if (!AppState.currentSessionId || !AppState.authToken) return;

    const modalEl = document.getElementById('session-modal');
    if (!modalEl || modalEl.classList.contains('hidden')) return;

    try {
        const response = await fetch(`${API_URL}/sessions/${AppState.currentSessionId}?token=${AppState.authToken}`);
        if (!response.ok) return;

        const data = await response.json();
        const isProcessing = ['recording', 'queued', 'transcribing', 'analyzing', 'securing'].includes(data.status);

        if (isProcessing) {
            const rawContainer = document.getElementById('modal-transcript');

            // Only scroll bottom if user is already at bottom
            const isScrolledToBottom = Math.abs((rawContainer.scrollHeight - rawContainer.scrollTop) - rawContainer.clientHeight) <= 10;

            const txt = data.transcription_raw;
            if (txt && txt.trim() !== "") {
                if (rawContainer.innerText !== txt) {
                    rawContainer.innerText = txt;
                    if (isScrolledToBottom) {
                        rawContainer.scrollTop = rawContainer.scrollHeight;
                    }
                }
            } else {
                if (rawContainer.innerText.includes("Esperando")) {
                    rawContainer.innerText = "Transcribiendo chunks en tiempo real...";
                }
            }
        }
    } catch (e) {
        // Silently fail polling update
    }
}

/**
 * Copy patient summary for WhatsApp
 */
export function copyPatientSummary() {
    const points = document.getElementById('pat-points').value;
    const task = document.getElementById('pat-task').value;

    const niceText = `🌟 *Resumen de tu Sesión*\n\n🧠 *Puntos Clave:*\n${points}\n\n📝 *Tu Misión Semanal:*\n${task}\n\n_Recuerda: El progreso es paso a paso. ¡Nos vemos la próxima!_`;

    navigator.clipboard.writeText(niceText).then(() => {
        alert("¡Copiado! Listo para pegar en WhatsApp.");
    });
}

// Universal confirmation modal for Record / Upload
export function showConfirmModal(actionType, file = null) {
    AppState.confirmActionType = actionType;
    AppState.pendingAudioFile = file;

    // Set visually the chosen model
    const select = document.getElementById('model-select');
    let modelName = 'Modelo Automático';
    if (select && select.options.length > 0) {
        // Find the selected option's text instead of value for a nice name
        modelName = select.options[select.selectedIndex].text;
    }
    document.getElementById('confirm-model-text').innerText = modelName;

    // Set title based on action
    const titleEl = document.getElementById('confirm-modal-title');
    if (actionType === 'record') {
        titleEl.innerText = '¿Iniciar Sesión en Vivo?';
    } else {
        titleEl.innerText = '¿Procesar Audio?';
    }

    document.getElementById('confirm-modal').classList.remove('hidden');
}

export function confirmAction() {
    document.getElementById('confirm-modal').classList.add('hidden');

    if (AppState.confirmActionType === 'upload' && AppState.pendingAudioFile) {
        uploadFile(AppState.pendingAudioFile);
        AppState.pendingAudioFile = null;
    } else if (AppState.confirmActionType === 'record') {
        import('./recording.js').then(m => m.startRecording());
    }

    AppState.confirmActionType = null;
}

export function cancelAction() {
    AppState.pendingAudioFile = null;
    AppState.confirmActionType = null;
    document.getElementById('confirm-modal').classList.add('hidden');
}

/**
 * Toggle between Raw and Anonymized transcript views
 * @param {string} viewType 'raw' | 'anon'
 */
export function toggleTranscriptView(viewType) {
    const rawContainer = document.getElementById('modal-transcript');
    const anonContainer = document.getElementById('modal-transcript-anonymized');

    const btnRaw = document.getElementById('btn-transcript-raw');
    const btnAnon = document.getElementById('btn-transcript-anon');

    if (viewType === 'raw') {
        rawContainer.classList.remove('hidden');
        anonContainer.classList.add('hidden');

        btnRaw.className = "text-[10px] font-bold text-indigo-400 uppercase tracking-widest border-b-2 border-indigo-500 pb-1 transition-all";
        btnAnon.className = "text-[10px] font-bold text-slate-500 uppercase tracking-widest border-b-2 border-transparent pb-1 hover:text-slate-300 transition-all flex items-center gap-1";
    } else {
        rawContainer.classList.add('hidden');
        anonContainer.classList.remove('hidden');

        btnRaw.className = "text-[10px] font-bold text-slate-500 uppercase tracking-widest border-b-2 border-transparent pb-1 hover:text-slate-300 transition-all";
        btnAnon.className = "text-[10px] font-bold text-emerald-400 uppercase tracking-widest border-b-2 border-emerald-500 pb-1 transition-all flex items-center gap-1";
    }
}
