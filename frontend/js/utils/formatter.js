/**
 * Utility Functions
 * Common formatting and helper functions
 */

/**
 * Format seconds to human readable duration
 * @param {number} seconds 
 * @returns {string}
 */
export function formatDuration(seconds) {
    if (!seconds || isNaN(seconds)) return '0s';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const sec = Math.round(seconds % 60);
    return `${m}m ${sec}s`;
}

/**
 * Format date to locale string
 * @param {string} dateString 
 * @returns {string}
 */
export function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString('es-PE');
}

/**
 * Format time to locale string
 * @param {string} dateString 
 * @returns {string}
 */
export function formatTime(dateString) {
    return new Date(dateString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * Copy text to clipboard
 * @param {string} text 
 * @returns {Promise<void>}
 */
export async function copyToClipboard(text) {
    await navigator.clipboard.writeText(text);
}
