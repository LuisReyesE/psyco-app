/**
 * Polling Module
 * Smart polling for session status updates
 */

import { AppState } from '../state.js';
import { API_URL } from '../api.js';
import { renderSessionsTable, checkForActiveProcessing, updateSessionModalSilently } from './sessions.js';
import { showVisualToast, playNotificationSound } from '../components/toast.js';

/**
 * Start the smart polling system
 */
export function startSmartPolling() {
    // Start with default slow polling
    updatePollingInterval(5000);
}

let currentIntervalMs = 0;

export function forcePollUpdate() {
    if (AppState.sessionPollingInterval) clearInterval(AppState.sessionPollingInterval);
    currentIntervalMs = 0; // Force immediate reset
    checkAndUpdateSessions();
}

/**
 * Updates the polling frequency dynamically
 * @param {number} intervalMs 
 */
function updatePollingInterval(intervalMs) {
    if (currentIntervalMs === intervalMs) return; // No change needed

    if (AppState.sessionPollingInterval) {
        clearInterval(AppState.sessionPollingInterval);
    }

    currentIntervalMs = intervalMs;
    console.log(`[POLLING] Intervalo actualizado a ${intervalMs}ms`);

    AppState.sessionPollingInterval = setInterval(() => {
        if (AppState.selectedPatientId && AppState.authToken) {
            checkAndUpdateSessions();
        }
    }, intervalMs);
}

/**
 * Check for updates and refresh sessions if needed
 */
async function checkAndUpdateSessions() {
    if (!AppState.authToken || !AppState.selectedPatientId) return;

    const wasProcessing = AppState.hasActiveProcessing;

    try {
        const response = await fetch(`${API_URL}/sessions/?patient_id=${AppState.selectedPatientId}&token=${AppState.authToken}`);

        if (response.status === 401) {
            const { handleUnauthorized } = await import('./auth.js');
            handleUnauthorized();
            return;
        }

        const sessions = await response.json();

        // Detect if any session just completed
        sessions.forEach(s => {
            if (s.status === 'completed') {
                if (!AppState.completedSessionsList.has(s.id)) {
                    if (!AppState.isFirstLoad) {
                        console.log("🎯 Sesión completada detectada:", s.id);
                        playNotificationSound();
                        showVisualToast(`Sesión completada para el paciente`);
                    }
                    AppState.completedSessionsList.add(s.id);
                }
            }
        });

        AppState.isFirstLoad = false;

        // Update UI
        renderSessionsTable(sessions);

        // Update interactive Session Modal if open
        updateSessionModalSilently();

        // Check for active processing to adjust polling rate
        const isProcessing = checkForActiveProcessing(sessions);

        // ADAPTIVE POLLING LOGIC
        // If processing (recording/transcribing/etc), poll fast (1s).
        // If idle, poll slow (5s).
        if (isProcessing) {
            updatePollingInterval(1000);
        } else {
            updatePollingInterval(5000);
        }

        if (wasProcessing && !AppState.hasActiveProcessing) {
            console.log('✅ Procesamiento completado - Volviendo a reposo');
        }
    } catch (e) {
        console.error("Error en polling:", e);
    }
}
