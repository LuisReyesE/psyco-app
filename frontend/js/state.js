/**
 * Global Application State
 * Centralized state management for the Session AI app
 */

export const AppState = {
    // Authentication
    authToken: localStorage.getItem('psyco_token') || sessionStorage.getItem('psyco_token') || null,
    isRegistered: false,

    // Patient Management
    selectedPatientId: null,
    allPatients: [],

    // Session Management
    currentSessionId: null,
    sessionPollingInterval: null,
    hasActiveProcessing: false,
    completedSessionsList: new Set(),
    isFirstLoad: true,

    // License
    currentLicenseTier: 'FREE',
    subscriptionData: null,

    // Recording State
    mediaRecorder: null,
    audioStream: null,
    audioChunks: [],
    activeSessionId: null,
    chunksSent: 0,
    startTime: null,
    recordingInterval: null,
    chunkingInterval: null,
    recordingMimeType: '',
    recordingExtension: '',

    // Pause State
    isPaused: false,
    pauseStartTime: 0,
    totalPausedTime: 0,

    // Upload
    pendingAudioFile: null,
    confirmActionType: null,

    // Audio Context
    globalAudioCtx: null
};

/**
 * Update state with partial updates
 * @param {Object} updates - Partial state to merge
 */
export function updateState(updates) {
    Object.assign(AppState, updates);
}

/**
 * Reset auth state (logout)
 */
export function resetAuthState() {
    AppState.authToken = null;
    AppState.selectedPatientId = null;
    AppState.allPatients = [];
    AppState.currentSessionId = null;
    localStorage.removeItem('psyco_token');
    localStorage.removeItem('psyco_user');
    sessionStorage.removeItem('psyco_token');
    sessionStorage.removeItem('activePatientId');
    sessionStorage.removeItem('activePatientName');
}

/**
 * Save auth token to storage
 * @param {string} token 
 */
export function saveAuthToken(token) {
    AppState.authToken = token;
    localStorage.setItem('psyco_token', token);
    sessionStorage.setItem('psyco_token', token);
}
