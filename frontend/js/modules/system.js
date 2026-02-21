/**
 * System Module
 * Health check, models loading, and server status
 */

import { AppState } from '../state.js';
import { API_URL } from '../api.js';

/**
 * Check server health status
 */
export async function checkServerStatus() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');

    try {
        const res = await fetch(`${API_URL}/health`);
        if (res.ok) {
            dot.className = "w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.5)]";
            text.innerText = "Servidor Activo";
        } else {
            throw new Error();
        }
    } catch (e) {
        dot.className = "w-2 h-2 rounded-full bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.5)] animate-pulse";
        text.innerText = "Desconectado";
    }
}

/**
 * Load available AI models
 */
export async function loadModels() {
    try {
        const res = await fetch(`${API_URL}/models/`);
        const models = await res.json();
        const select = document.getElementById('model-select');
        select.innerHTML = '<option value="">Automático (Gemma 3)</option>';

        // Separate models by provider
        const ollamaModels = models.filter(m => m.startsWith('ollama:'));
        const geminiModels = models.filter(m => m.startsWith('gemini:'));

        // Add Ollama models (local)
        if (ollamaModels.length > 0) {
            const ollamaGroup = document.createElement('optgroup');
            ollamaGroup.label = '🖥️ Local';
            ollamaModels.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                const displayName = m.replace('ollama:', '');
                opt.innerText = displayName;
                if (displayName.toLowerCase().includes('gemma3')) opt.selected = true;
                ollamaGroup.appendChild(opt);
            });
            select.appendChild(ollamaGroup);
        }

        // Add Gemini models (cloud with anonymization)
        if (geminiModels.length > 0) {
            const geminiGroup = document.createElement('optgroup');
            geminiGroup.label = '☁️ Nube + Anonimización';
            geminiModels.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                const displayName = m.replace('gemini:', '');

                if (AppState.currentLicenseTier !== 'PRO') {
                    opt.disabled = true;
                    opt.innerText = `🔒 ${displayName} (PRO)`;
                } else {
                    opt.innerText = `🛡️ ${displayName}`;
                }
                geminiGroup.appendChild(opt);
            });
            select.appendChild(geminiGroup);
        }
    } catch (e) {
        console.error("Error loading models:", e);
    }
}
