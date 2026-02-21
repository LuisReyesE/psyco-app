/**
 * Recording Module
 * Real-time audio recording with chunked streaming
 */

import { AppState } from '../state.js';
import { API_URL } from '../api.js';
import { loadSessions } from './sessions.js';

/**
 * Toggle recording on/off
 */
export async function toggleRecording() {
    // If we are recording (or paused), STOP everything
    if (AppState.mediaRecorder && (AppState.mediaRecorder.state === 'recording' || AppState.isPaused)) {
        stopRecording();
    } else {
        const { showConfirmModal } = await import('./sessions.js');
        showConfirmModal('record');
    }
}

/**
 * Start a new recording session
 */
export async function startRecording() {
    try {
        if (!AppState.selectedPatientId || !AppState.authToken) {
            alert("Selecciona un paciente primero");
            return;
        }

        // 1. Setup server recording context
        const formData = new FormData();
        formData.append('token', AppState.authToken);
        const model = document.getElementById('model-select').value;
        if (model) formData.append('model', model);

        const res = await fetch(`${API_URL}/recording/${AppState.selectedPatientId}/start`, {
            method: 'POST',
            body: formData
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || "Error al iniciar sesión en el servidor");
        }

        const data = await res.json();
        AppState.activeSessionId = data.session_id;
        AppState.chunksSent = 0;
        AppState.audioChunks = []; // keep empty state just in case
        AppState.isPaused = false;
        AppState.totalPausedTime = 0;
        console.log(`📹 Server recording session started (ID: ${AppState.activeSessionId})`);

        // 2. Get audio stream
        AppState.audioStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true
            }
        });

        // Detect supported format
        AppState.recordingMimeType = 'audio/webm;codecs=opus';
        AppState.recordingExtension = 'webm';

        if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
            AppState.recordingMimeType = 'audio/ogg;codecs=opus';
            AppState.recordingExtension = 'ogg';
        }

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

        // 3. Start first chunk recorder
        startStreamingChunkRecorder(AppState.audioStream, 0, chunkCountEl, chunkListEl);
        startChunkRotation(chunkCountEl, chunkListEl);

        // Change Icon to STOP
        document.getElementById('record-icon-bg').innerHTML = `
            <svg class="w-8 h-8 text-rose-400" fill="currentColor" viewBox="0 0 24 24">
                <path d="M6 6h12v12H6z" />
            </svg>
        `;

        document.getElementById('record-card').classList.add('border-rose-500');
        document.getElementById('record-title').innerText = "Detener o Pausar";
        AppState.startTime = Date.now();

        requestAnimationFrame(updateTimer);

    } catch (err) {
        console.error(err);
        alert("Error al iniciar grabación: " + err.message);
        AppState.activeSessionId = null;
    }
}

/**
 * Stop the current recording
 */
function stopRecording() {
    if (AppState.chunkingInterval) {
        clearInterval(AppState.chunkingInterval);
        AppState.chunkingInterval = null;
    }

    if (AppState.mediaRecorder && AppState.mediaRecorder.state === 'recording') {
        AppState.mediaRecorder.stop();
    }

    if (AppState.audioStream) {
        AppState.audioStream.getTracks().forEach(t => t.stop());
        AppState.audioStream = null;
    }

    // Reset UI
    document.getElementById('record-card').classList.remove('border-rose-500', 'border-amber-500');

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

    if (AppState.recordingInterval) {
        clearInterval(AppState.recordingInterval);
    }

    document.getElementById('pause-btn').classList.add('hidden');
    resetPauseUI();

    document.getElementById('chunk-progress-container').classList.add('hidden');

    // Send finish signal
    setTimeout(async () => {
        if (AppState.activeSessionId && AppState.activeSessionId !== 'local') {
            console.log(`🏁 Finalizando sesión de streaming ${AppState.activeSessionId} con ${AppState.chunksSent} chunks...`);

            const formData = new FormData();
            formData.append('token', AppState.authToken);
            formData.append('total_chunks', AppState.chunksSent);

            try {
                const finishRes = await fetch(`${API_URL}/recording/${AppState.activeSessionId}/finish`, {
                    method: 'POST',
                    body: formData
                });

                if (finishRes.ok) {
                    console.log(`✅ Streaming session finished`);
                    loadSessions(AppState.selectedPatientId);
                } else {
                    console.error("❌ Failed to finish session");
                }
            } catch (e) {
                console.error("Error finishing session:", e);
            }

            AppState.activeSessionId = null;
            AppState.chunksSent = 0;
            AppState.audioChunks = [];
            AppState.isPaused = false;
            AppState.totalPausedTime = 0;
        }
    }, 500);
}

/**
 * Start chunk rotation timer (30 seconds per chunk)
 */
function startChunkRotation(chunkCountEl, chunkListEl) {
    if (AppState.chunkingInterval) clearInterval(AppState.chunkingInterval);

    AppState.chunkingInterval = setInterval(() => {
        if (AppState.mediaRecorder && AppState.mediaRecorder.state === 'recording' && !AppState.isPaused) {
            const nextChunkIndex = AppState.chunksSent;
            console.log(`⏱️ Rotating to chunk ${nextChunkIndex + 1}...`);

            AppState.mediaRecorder.stop();

            setTimeout(() => {
                if (AppState.audioStream && AppState.audioStream.active && !AppState.isPaused) {
                    startStreamingChunkRecorder(AppState.audioStream, nextChunkIndex, chunkCountEl, chunkListEl);
                }
            }, 100);
        }
    }, 30000); // Volvemos a 30 segundos
}

/**
 * Update recording timer display
 */
function updateTimer() {
    // Use chunkingInterval as "isRecording" proxy because mediaRecorder state 
    // flickers to 'inactive' briefly during chunk rotation (causing the loop to break).
    // We stop if:
    // 1. Session is null (failsafe)
    // 2. chunkingInterval is null AND we are NOT paused (meaning we stopped)
    if (AppState.activeSessionId && (AppState.chunkingInterval || AppState.isPaused)) {
        if (!AppState.isPaused) {
            const diff = Date.now() - AppState.startTime - AppState.totalPausedTime;
            document.getElementById('record-timer-text').innerText = `Grabando: ${Math.floor(diff / 1000)}s`;
        }
        requestAnimationFrame(updateTimer);
    }
}

/**
 * Toggle pause/resume recording
 */
export function togglePause() {
    if (!AppState.activeSessionId) return;

    if (AppState.isPaused) {
        // RESUME
        AppState.isPaused = false;
        AppState.totalPausedTime += (Date.now() - AppState.pauseStartTime);

        console.log("▶️ Resuming recording...");

        document.getElementById('record-card').classList.replace('border-amber-500', 'border-rose-500');
        document.getElementById('record-title').classList.remove('text-amber-500');
        document.getElementById('record-title').innerText = "Detener y Guardar";

        requestAnimationFrame(updateTimer);

        document.getElementById('pause-icon').innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>`;

        const chunkCountEl = document.getElementById('chunk-count');
        const chunkListEl = document.getElementById('chunk-list');
        startStreamingChunkRecorder(AppState.audioStream, AppState.chunksSent, chunkCountEl, chunkListEl);
        startChunkRotation(chunkCountEl, chunkListEl);

    } else {
        // PAUSE
        AppState.isPaused = true;
        AppState.pauseStartTime = Date.now();

        console.log("⏸️ Pausing recording...");

        if (AppState.mediaRecorder && AppState.mediaRecorder.state === 'recording') {
            AppState.mediaRecorder.stop();
        }

        if (AppState.chunkingInterval) {
            clearInterval(AppState.chunkingInterval);
            AppState.chunkingInterval = null;
        }

        document.getElementById('record-card').classList.replace('border-rose-500', 'border-amber-500');
        document.getElementById('record-title').classList.add('text-amber-500');
        document.getElementById('record-title').innerText = "Pausado";

        document.getElementById('pause-icon').innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>`;
    }
}

/**
 * Reset pause UI to default state
 */
function resetPauseUI() {
    AppState.isPaused = false;
    document.getElementById('pause-icon').innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>`;
    document.getElementById('record-title').classList.remove('text-amber-500');
}

/**
 * Start a streaming chunk recorder
 */
function startStreamingChunkRecorder(stream, chunkIndex, chunkCountEl, chunkListEl) {
    const options = {
        mimeType: AppState.recordingMimeType,
        audioBitsPerSecond: 24000
    };

    AppState.mediaRecorder = new MediaRecorder(stream, options);
    let chunkData = [];

    AppState.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
            chunkData.push(event.data);
        }
    };

    AppState.mediaRecorder.onstop = async () => {
        if (chunkData.length > 0 && AppState.activeSessionId) {
            const chunkBlob = new Blob(chunkData, { type: AppState.recordingMimeType });
            const currentChunkIndex = AppState.chunksSent;

            console.log(`📤 Enviando chunk ${currentChunkIndex} al backend (${(chunkBlob.size / 1024).toFixed(1)} KB)...`);

            const formData = new FormData();
            formData.append('token', AppState.authToken);
            formData.append('chunk_index', currentChunkIndex);
            formData.append('chunk', chunkBlob, `chunk_${currentChunkIndex}.${AppState.recordingExtension}`);

            fetch(`${API_URL}/recording/${AppState.activeSessionId}/chunk`, {
                method: 'POST',
                body: formData
            }).then(res => {
                if (!res.ok) console.error("Error al enviar el chunk " + currentChunkIndex);
            }).catch(e => console.error("Error de red al enviar el chunk " + currentChunkIndex, e));

            AppState.chunksSent++;

            if (chunkCountEl) chunkCountEl.innerText = AppState.chunksSent.toString();

            if (chunkListEl) {
                const chunkBadge = document.createElement('div');
                chunkBadge.className = 'badge-chunk px-2 py-0.5 rounded text-[10px] font-bold border animate-in zoom-in-50 duration-200';
                chunkBadge.innerText = `${AppState.chunksSent}`;
                chunkListEl.appendChild(chunkBadge);
            }
        }
    };

    AppState.mediaRecorder.start();
    console.log(`🎙️ Recording chunk - streaming active`);
}
