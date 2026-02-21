/**
 * Session AI - Main Entry Point
 * ES6 Module version of app.js
 * 
 * This file initializes the application and exposes necessary functions
 * to the global scope for onclick handlers in HTML.
 */

import { AppState } from './state.js';
import { API_URL } from './api.js';
import { toggleTheme, initTheme } from './modules/theme.js';

// Modules
import {
    checkRegistration,
    validateSession,
    handleAuthAction,
    finishBackupProcess,
    copyBackupCode,
    toggleRecoveryMode,
    handleRecovery,
    handleLogout,
    updateGreeting
} from './modules/auth.js';

import {
    initializeApp,
    loadPatients,
    selectPatient,
    deletePatient,
    createPatient,
    showNewPatientModal,
    hideNewPatientModal,
    goToHome
} from './modules/patients.js';

import {
    loadSessions,
    openSession,
    deleteSession,
    uploadFile,
    saveSessionEdits,
    downloadPDF,
    closeModal,
    switchTab,
    copyPatientSummary,
    showConfirmModal,
    confirmAction,
    cancelAction,
    toggleTranscriptView
} from './modules/sessions.js';

import {
    checkLicenseStatus,
    updateSubscriptionUI,
    linkSubscriptionEmail,
    openSubscriptionWeb,
    refreshSubscriptionStatus,
    activateLicense,
    openSettingsModal,
    closeSettingsModal
} from './modules/license.js';

import {
    toggleRecording,
    togglePause
} from './modules/recording.js';

import {
    checkServerStatus,
    loadModels
} from './modules/system.js';

import { startSmartPolling } from './modules/polling.js';
import { initAudioContext } from './components/toast.js';
import { downloadBackup, handleRestoreSelect } from './modules/backup.js';

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', async () => {
    // 0. Check License & Theme
    initTheme();
    await checkLicenseStatus();

    // 1. Check registration/auth FIRST (loading screen visible)
    await checkRegistration();

    // 1.5 Validate Token (backend RAM check)
    if (AppState.authToken) {
        const isValid = await validateSession(AppState.authToken);
        if (!isValid) {
            console.warn("Token local inválido o expirado. Forzando logout.");
            AppState.authToken = null;
            localStorage.removeItem('psyco_token');
            sessionStorage.removeItem('psyco_token');
        }
    }

    // 2. Show correct UI based on state
    if (AppState.authToken) {
        document.getElementById('auth-modal').classList.add('hidden');
        document.getElementById('logout-btn').classList.remove('hidden');
        updateGreeting();
        initializeApp();
    } else {
        document.getElementById('auth-modal').classList.remove('hidden');
        document.getElementById('logout-btn').classList.add('hidden');
    }

    // 3. Hide loading screen with smooth transition
    const loadingScreen = document.getElementById('loading-screen');
    if (loadingScreen) {
        loadingScreen.style.transition = 'opacity 0.3s ease';
        loadingScreen.style.opacity = '0';
        setTimeout(() => loadingScreen.remove(), 300);
    }

    // 4. Initialize audio context on first interaction
    initAudioContext();

    // 5. Start server health check
    checkServerStatus();
    setInterval(checkServerStatus, 5000);
    startSmartPolling();

    // 6. Backup confirmation listener
    const backupConfirm = document.getElementById('backup-confirm');
    if (backupConfirm) {
        backupConfirm.addEventListener('change', (e) => {
            const btn = document.getElementById('backup-continue-btn');
            btn.disabled = !e.target.checked;
            if (!e.target.checked) {
                btn.classList.add('cursor-not-allowed', 'bg-slate-700', 'text-slate-400');
            } else {
                btn.classList.remove('cursor-not-allowed', 'bg-slate-700', 'text-slate-400');
                btn.classList.add('bg-emerald-600', 'text-white', 'hover:bg-emerald-700');
            }
        });
    }

    // 7. Audio input listener
    const audioInput = document.getElementById('audio-input');
    if (audioInput) {
        audioInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) showConfirmModal('upload', file);
            e.target.value = '';
        });
    }
});

// ============================================
// EXPOSE FUNCTIONS TO GLOBAL SCOPE
// (Required for onclick handlers in HTML)
// ============================================

// Auth
window.handleAuthAction = handleAuthAction;
window.finishBackupProcess = finishBackupProcess;
window.copyToClipboard = copyBackupCode;
window.toggleRecoveryMode = toggleRecoveryMode;
window.handleRecovery = handleRecovery;
window.handleLogout = handleLogout;

// Patients
window.selectPatient = selectPatient;
window.deletePatient = deletePatient;
window.createPatient = createPatient;
window.showNewPatientModal = showNewPatientModal;
window.hideNewPatientModal = hideNewPatientModal;
window.goToHome = goToHome;

// Sessions
window.openSession = openSession;
window.deleteSession = deleteSession;
window.closeModal = closeModal;
window.switchTab = switchTab;
window.downloadPDF = downloadPDF;
window.copyPatientSummary = copyPatientSummary;
window.confirmAction = confirmAction;
window.cancelAction = cancelAction;
window.toggleTranscriptView = toggleTranscriptView;

// Recording
window.toggleRecording = toggleRecording;
window.togglePause = togglePause;

// Theme
window.toggleTheme = toggleTheme;

// License
window.linkSubscriptionEmail = linkSubscriptionEmail;
window.openSubscriptionWeb = openSubscriptionWeb;
window.refreshSubscriptionStatus = refreshSubscriptionStatus;
window.activateLicense = activateLicense;
window.openSettingsModal = openSettingsModal;
window.closeSettingsModal = closeSettingsModal;

// Backup
window.downloadBackup = downloadBackup;
window.handleRestoreSelect = handleRestoreSelect;

// Sessions extra
window.loadSessions = loadSessions;

// Filter patients (inline implementation for now)
window.filterPatients = function () {
    const searchTerm = document.getElementById('patient-search').value.toLowerCase();
    const patientItems = document.querySelectorAll('#patient-list .patient-item');
    patientItems.forEach(item => {
        const name = item.querySelector('span')?.innerText?.toLowerCase() || '';
        item.style.display = name.includes(searchTerm) ? '' : 'none';
    });
};

// Expose selectedPatientId for inline onclick handlers
Object.defineProperty(window, 'selectedPatientId', {
    get: () => AppState.selectedPatientId,
    set: (val) => AppState.selectedPatientId = val
});

console.log("✅ Session AI - Modular version loaded");
