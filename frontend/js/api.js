/**
 * API Client Module
 * Centralized HTTP client with auth token handling
 */

import { AppState, resetAuthState } from './state.js';

export const API_URL = "http://127.0.0.1:8000";

/**
 * Generic API request with auth handling
 * @param {string} endpoint 
 * @param {Object} options 
 * @returns {Promise<Response>}
 */
export async function apiRequest(endpoint, options = {}) {
    const response = await fetch(`${API_URL}${endpoint}`, options);

    if (response.status === 401) {
        handleUnauthorized();
        throw new Error("Unauthorized");
    }

    return response;
}

/**
 * GET request returning JSON
 * @param {string} endpoint 
 * @returns {Promise<any>}
 */
export async function apiGet(endpoint) {
    const response = await apiRequest(endpoint);
    return response.json();
}

/**
 * POST request with FormData
 * @param {string} endpoint 
 * @param {FormData} formData 
 * @returns {Promise<Response>}
 */
export async function apiPost(endpoint, formData) {
    return apiRequest(endpoint, {
        method: 'POST',
        body: formData
    });
}

/**
 * DELETE request
 * @param {string} endpoint 
 * @returns {Promise<Response>}
 */
export async function apiDelete(endpoint) {
    return apiRequest(endpoint, { method: 'DELETE' });
}

/**
 * Create FormData with auth token
 * @param {Object} data - Key-value pairs to add
 * @returns {FormData}
 */
export function createAuthFormData(data = {}) {
    const formData = new FormData();
    if (AppState.authToken) {
        formData.append('token', AppState.authToken);
    }
    Object.entries(data).forEach(([key, value]) => {
        formData.append(key, value);
    });
    return formData;
}

/**
 * Handle 401 unauthorized response
 */
function handleUnauthorized() {
    console.warn("Sesión expirada o servidor reiniciado. Solicitando re-autenticación.");

    if (AppState.sessionPollingInterval) {
        clearInterval(AppState.sessionPollingInterval);
    }

    document.getElementById('auth-modal').classList.remove('hidden');
    document.getElementById('login-subtitle').innerText = "Tu sesión ha expirado.";
    document.getElementById('login-subtitle').classList.add('text-rose-400');
}
