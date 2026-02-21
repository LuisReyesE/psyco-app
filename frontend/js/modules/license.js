/**
 * License Module
 * Subscription management and license activation
 */

import { AppState } from '../state.js';
import { API_URL } from '../api.js';
import { loadModels } from './system.js';

/**
 * Check license status from the server
 */
export async function checkLicenseStatus(isRetry = false) {
    try {
        const res = await fetch(`${API_URL}/system/license`);
        const data = await res.json();
        AppState.currentLicenseTier = data.tier || 'FREE';
        AppState.subscriptionData = data;
        updateSubscriptionUI();

        // Auto-refresh silently if we are a PRO user but cloud info hasn't arrived yet
        // since the backend might be doing a background sync to not slow down the boot.
        if (data.tier === 'PRO' && data.days_remaining === undefined && !isRetry) {
            setTimeout(() => {
                checkLicenseStatus(true);
            }, 3500);
        }
    } catch (e) {
        console.warn("Subscription check failed", e);
    }
}

/**
 * Update the subscription UI based on current tier
 */
export function updateSubscriptionUI() {
    try {
        const statusText = document.getElementById('subscription-status-text');
        const inputContainer = document.getElementById('subscription-input-container');
        const expiringAlert = document.getElementById('subscription-expiring');
        const daysCountdown = document.getElementById('days-countdown');
        const lockIconClinico = document.getElementById('lock-icon-clinico');
        const lockIconPaciente = document.getElementById('lock-icon-paciente');

        if (statusText) {
            if (AppState.currentLicenseTier === 'PRO') {
                const daysRemaining = AppState.subscriptionData?.days_remaining;
                const email = AppState.subscriptionData?.email || '';

                if (daysRemaining !== null && daysRemaining !== undefined) {
                    if (inputContainer) inputContainer.classList.add('hidden');
                    if (expiringAlert) {
                        expiringAlert.classList.remove('hidden');
                        expiringAlert.classList.add('flex');
                    }
                    if (daysCountdown) daysCountdown.innerText = daysRemaining;

                    const alertTitle = expiringAlert ? expiringAlert.querySelector('span') : null;
                    const alertIcon = expiringAlert ? expiringAlert.querySelector('svg') : null;
                    const alertBtn = expiringAlert ? expiringAlert.querySelector('button') : null;

                    if (daysRemaining <= 5) {
                        statusText.innerHTML = `Estado: <span class="text-amber-500 font-bold border border-amber-500/30 px-2 py-0.5 rounded text-xs bg-amber-500/10">PRO - ¡Vence pronto!</span>`;
                        if (expiringAlert) expiringAlert.className = 'flex items-center gap-3 px-4 py-2.5 rounded-xl border transition-all bg-amber-500/10 border-amber-500/30';
                        if (alertTitle) {
                            alertTitle.innerText = "PRO Vence Pronto";
                            alertTitle.className = "text-[10px] text-amber-600 font-bold uppercase tracking-wider";
                        }
                        if (alertIcon) alertIcon.setAttribute("class", "w-5 h-5 text-amber-500 animate-pulse");
                        if (alertBtn) alertBtn.classList.remove("hidden");
                        if (daysCountdown) {
                            daysCountdown.className = "text-lg font-bold text-amber-600";
                            if (daysCountdown.nextElementSibling) daysCountdown.nextElementSibling.className = "text-xs font-medium text-amber-600/80";
                        }
                    } else {
                        statusText.innerHTML = `Estado: <span class="text-emerald-500 font-bold border border-emerald-500/30 px-2 py-0.5 rounded text-xs bg-emerald-500/10">✓ PRO ACTIVA</span>`;
                        if (expiringAlert) expiringAlert.className = 'flex items-center gap-3 px-4 py-2.5 rounded-xl border transition-all bg-highlight border-border';
                        if (alertTitle) {
                            alertTitle.innerText = "Suscripción PRO";
                            alertTitle.className = "text-[10px] text-secondary font-bold uppercase tracking-wider";
                        }
                        if (alertIcon) alertIcon.setAttribute("class", "w-5 h-5 text-brand");
                        if (alertBtn) alertBtn.classList.add("hidden");
                        if (daysCountdown) {
                            daysCountdown.className = "text-lg font-bold text-primary";
                            if (daysCountdown.nextElementSibling) daysCountdown.nextElementSibling.className = "text-xs font-medium text-secondary";
                        }
                    }

                    if (email) {
                        statusText.innerHTML += `<span class="text-xs text-secondary mt-1 block">${email}</span>`;
                    }
                } else {
                    let statusHTML = `Estado: <span class="text-emerald-400 font-bold border border-emerald-500/30 px-2 py-0.5 rounded text-xs">✓ PRO ACTIVA</span>`;
                    if (email) {
                        statusHTML += `<span class="text-xs text-slate-600 mt-1 block">${email}</span>`;
                    }
                    statusText.innerHTML = statusHTML;
                    if (expiringAlert) expiringAlert.classList.add('hidden');
                    if (inputContainer) inputContainer.classList.add('hidden');
                }

                if (lockIconClinico) lockIconClinico.classList.add('hidden');
                if (lockIconPaciente) lockIconPaciente.classList.add('hidden');
            } else {
                statusText.innerHTML = `Estado: <span class="text-slate-400 font-bold">GRATUITA (FREE)</span>`;
                if (inputContainer) inputContainer.classList.remove('hidden');
                if (expiringAlert) {
                    expiringAlert.className = 'hidden';
                }

                if (lockIconClinico) lockIconClinico.classList.remove('hidden');
                if (lockIconPaciente) lockIconPaciente.classList.remove('hidden');
            }
        }
    } catch (err) {
        console.error("Error in updateSubscriptionUI:", err);
    }

    loadModels();
}

/**
 * Link subscription by email
 */
export async function linkSubscriptionEmail() {
    const email = document.getElementById('subscription-email-input').value.trim();
    const msg = document.getElementById('subscription-msg');

    if (!email || !email.includes('@')) {
        if (msg) {
            msg.classList.remove('hidden');
            msg.innerText = "Por favor ingresa un email válido";
            msg.className = "text-xs text-center text-rose-400 font-bold";
        }
        return;
    }

    if (msg) {
        msg.classList.remove('hidden');
        msg.innerText = "Verificando suscripción...";
        msg.className = "text-xs text-center text-slate-400 animate-pulse";
    }

    const formData = new FormData();
    formData.append('key', email);

    try {
        const res = await fetch(`${API_URL}/system/license`, { method: 'POST', body: formData });
        const data = await res.json();

        if (data.success) {
            if (msg) {
                msg.innerText = "¡Email vinculado correctamente!";
                msg.className = "text-xs text-center text-emerald-400 font-bold";
            }
            AppState.currentLicenseTier = data.tier;
            AppState.subscriptionData = data;
            updateSubscriptionUI();

            setTimeout(() => {
                closeSettingsModal();
                if (data.tier === 'PRO') {
                    alert("¡Suscripción PRO activada! Disfruta todas las funciones.");
                }
            }, 1000);
        } else {
            if (msg) {
                msg.innerText = data.message || "Email no encontrado";
                msg.className = "text-xs text-center text-rose-400 font-bold";
            }
        }
    } catch (e) {
        if (msg) {
            msg.innerText = "Error de conexión";
            msg.className = "text-xs text-center text-rose-400 font-bold";
        }
    }
}

/**
 * Open subscription website
 */
export function openSubscriptionWeb() {
    alert(
        "🌐 Web de Suscripción\n\n" +
        "La página de suscripción estará disponible pronto.\n\n" +
        "Por ahora, contacta al administrador para obtener tu suscripción PRO."
    );
}

/**
 * Refresh subscription status from server
 */
export async function refreshSubscriptionStatus() {
    const btn = document.getElementById('refresh-subscription-btn');
    const statusText = document.getElementById('subscription-status-text');

    if (btn) {
        btn.classList.add('animate-spin');
        btn.disabled = true;
    }

    if (statusText) {
        statusText.innerHTML = `Estado: <span class="text-slate-500 font-mono animate-pulse">ACTUALIZANDO...</span>`;
    }

    try {
        const res = await fetch(`${API_URL}/system/license?force=true`);
        const data = await res.json();

        AppState.currentLicenseTier = data.tier || 'FREE';
        AppState.subscriptionData = data;
        updateSubscriptionUI();

        const msg = document.getElementById('subscription-msg');
        if (msg) {
            msg.classList.remove('hidden');
            msg.innerText = data.tier === 'PRO' ? "✓ Suscripción PRO activa" : "Estado actualizado";
            msg.className = data.tier === 'PRO'
                ? "text-xs text-center text-emerald-400 font-bold"
                : "text-xs text-center text-slate-400";
            setTimeout(() => msg.classList.add('hidden'), 3000);
        }
    } catch (e) {
        console.error("Error refreshing subscription:", e);
        const msg = document.getElementById('subscription-msg');
        if (msg) {
            msg.classList.remove('hidden');
            msg.innerText = "Error al actualizar";
            msg.className = "text-xs text-center text-rose-400 font-bold";
        }
    } finally {
        if (btn) {
            btn.classList.remove('animate-spin');
            btn.disabled = false;
        }
    }
}

/**
 * Alias for backward compatibility
 */
export async function activateLicense() {
    const emailInput = document.getElementById('subscription-email-input');
    const oldInput = document.getElementById('license-key-input');

    if (emailInput && emailInput.value) {
        return linkSubscriptionEmail();
    } else if (oldInput && oldInput.value) {
        const key = oldInput.value.trim();
        const msg = document.getElementById('license-msg') || document.getElementById('subscription-msg');

        const formData = new FormData();
        formData.append('key', key);

        try {
            const res = await fetch(`${API_URL}/system/license`, { method: 'POST', body: formData });
            const data = await res.json();

            if (data.success) {
                AppState.currentLicenseTier = data.tier;
                updateSubscriptionUI();
            }

            if (msg) {
                msg.classList.remove('hidden');
                msg.innerText = data.success ? "¡Activada!" : (data.message || "Error");
                msg.className = data.success
                    ? "text-xs text-center text-emerald-400 font-bold"
                    : "text-xs text-center text-rose-400 font-bold";
            }
        } catch (e) {
            if (msg) {
                msg.classList.remove('hidden');
                msg.innerText = "Error de conexión";
                msg.className = "text-xs text-center text-rose-400 font-bold";
            }
        }
    }
}

/**
 * Open settings modal
 */
export function openSettingsModal() {
    document.getElementById('settings-modal')?.classList.remove('hidden');
}

/**
 * Close settings modal
 */
export function closeSettingsModal() {
    document.getElementById('settings-modal')?.classList.add('hidden');
}
