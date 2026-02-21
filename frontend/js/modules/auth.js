/**
 * Authentication Module
 * Login, register, logout, recovery, and session validation
 */

import { AppState, updateState, resetAuthState, saveAuthToken } from '../state.js';
import { API_URL, apiPost } from '../api.js';
import { initializeApp } from './patients.js';

/**
 * Check if a user is already registered
 */
export async function checkRegistration() {
    try {
        const res = await fetch(`${API_URL}/auth/check`);
        const data = await res.json();
        AppState.isRegistered = data.has_user;

        const title = document.getElementById('login-title');
        const subtitle = document.getElementById('login-subtitle');
        const btn = document.getElementById('login-btn');
        const links = document.getElementById('login-links');

        if (!AppState.isRegistered) {
            title.innerText = "Configuración Inicial";
            subtitle.innerText = "Crea tu cuenta maestra";
            btn.innerText = "REGISTRAR Y EMPEZAR";
            links.classList.add('hidden');
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

/**
 * Validate if a session token is still valid
 * @param {string} token 
 * @returns {Promise<boolean>}
 */
export async function validateSession(token) {
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

/**
 * Handle login or registration action
 */
export async function handleAuthAction() {
    const userInput = document.getElementById('login-username');
    const passInput = document.getElementById('login-password');
    const errorMsg = document.getElementById('login-error');

    const user = userInput.value;
    const pass = passInput.value;

    if (!user || !pass) return;

    const formData = new FormData();
    formData.append('username', user);
    formData.append('password', pass);

    const endpoint = AppState.isRegistered ? '/auth/login' : '/auth/register';

    try {
        const res = await fetch(`${API_URL}${endpoint}`, {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            const data = await res.json();

            if (AppState.isRegistered) {
                // LOGIN SUCCESS
                saveAuthToken(data.token);

                if (data.username) {
                    localStorage.setItem('psyco_user', data.username);
                }

                document.getElementById('auth-modal').classList.add('hidden');
                document.getElementById('logout-btn').classList.remove('hidden');

                userInput.value = '';
                passInput.value = '';

                updateGreeting();
                initializeApp();
            } else {
                // REGISTER SUCCESS -> Show backup code
                document.getElementById('login-card').classList.add('hidden');
                document.getElementById('backup-card').classList.remove('hidden');
                document.getElementById('display-backup-code').innerText = data.recovery_code;

                userInput.value = user;
                passInput.value = '';

                AppState.isRegistered = true;
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

/**
 * Finish the backup code process after registration
 */
export function finishBackupProcess() {
    document.getElementById('backup-card').classList.add('hidden');
    document.getElementById('login-card').classList.remove('hidden');

    checkRegistration();

    const subtitle = document.getElementById('login-subtitle');
    subtitle.innerText = "¡Registro exitoso! Confirma tu contraseña.";
    subtitle.className = "text-emerald-400 text-sm font-bold animate-pulse";

    setTimeout(() => {
        const passInput = document.getElementById('login-password');
        passInput.focus();
        passInput.select();
    }, 100);
}

/**
 * Copy backup code to clipboard
 */
export function copyBackupCode() {
    const code = document.getElementById('display-backup-code').innerText;
    navigator.clipboard.writeText(code).then(() => {
        alert("Código copiado al portapapeles");
    });
}

/**
 * Toggle between login and recovery mode
 */
export function toggleRecoveryMode() {
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

/**
 * Handle password recovery
 */
export async function handleRecovery() {
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
            document.getElementById('rec-username').value = '';
            document.getElementById('rec-code').value = '';
            document.getElementById('rec-new-password').value = '';
            toggleRecoveryMode();
        } else {
            errorTxt.innerText = "Código incorrecto o usuario perdido";
            errorTxt.classList.remove('hidden');
        }
    } catch {
        errorTxt.classList.remove('hidden');
    }
}

/**
 * Handle user logout
 */
export function handleLogout() {
    resetAuthState();

    document.getElementById('auth-modal').classList.remove('hidden');
    document.getElementById('logout-btn').classList.add('hidden');
    document.getElementById('patient-view').classList.add('hidden');
    document.getElementById('intro-view').classList.remove('hidden');
    document.getElementById('patient-list').innerHTML = '';
    document.getElementById('session-table-body').innerHTML = '';

    document.getElementById('login-username').value = '';
    document.getElementById('login-password').value = '';
}

/**
 * Update the greeting with the username
 */
export function updateGreeting() {
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
