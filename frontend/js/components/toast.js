/**
 * Toast Component
 * Visual notifications and sound effects
 */

import { AppState } from '../state.js';

/**
 * Show a visual toast notification
 * @param {string} message - Message to display
 */
export function showVisualToast(message) {
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

/**
 * Play a melodic notification sound (Ding-Dong)
 */
export function playNotificationSound() {
    try {
        if (!AppState.globalAudioCtx) {
            console.warn("AudioContext no inicializado");
            return;
        }

        const audioCtx = AppState.globalAudioCtx;
        if (audioCtx.state === 'suspended') audioCtx.resume();

        const now = audioCtx.currentTime;

        // First tone (Ding)
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

        // Second tone (Dong)
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

/**
 * Initialize the audio context (call on first user interaction)
 */
export function initAudioContext() {
    const unlockAudio = () => {
        if (!AppState.globalAudioCtx) {
            AppState.globalAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
            console.log("🔊 Sistema de audio desbloqueado");
        }
        if (AppState.globalAudioCtx.state === 'suspended') {
            AppState.globalAudioCtx.resume();
        }
        window.removeEventListener('click', unlockAudio);
        window.removeEventListener('keydown', unlockAudio);
    };
    window.addEventListener('click', unlockAudio);
    window.addEventListener('keydown', unlockAudio);
}
