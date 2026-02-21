
/**
 * Theme Manager Module
 * Handles light/dark mode toggling and persistence.
 */

export function initTheme() {
    // Check local storage or system preference
    const savedTheme = localStorage.getItem('psyco_theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    // Default to dark if no preference, matching current aesthetic
    const shouldBeDark = savedTheme === 'dark' || (!savedTheme && true);
    // Actually, let's explicit: if 'light' is saved, use light. Otherwise dark.

    if (savedTheme === 'light') {
        document.body.classList.add('light-mode');
    } else {
        document.body.classList.remove('light-mode');
    }

    updateThemeIcon();
}

export function toggleTheme() {
    document.body.classList.toggle('light-mode');
    const isLight = document.body.classList.contains('light-mode');

    localStorage.setItem('psyco_theme', isLight ? 'light' : 'dark');
    updateThemeIcon();
}

function updateThemeIcon() {
    const icon = document.getElementById('theme-toggle-icon');
    if (!icon) return;

    const isLight = document.body.classList.contains('light-mode');

    // SVG for Sun (Light Mode active -> Show Moon to switch to dark? Or show current state?)
    // Usually button shows what you will switch TO, or what current state IS.
    // Let's make the icon represent the CURRENT state.

    if (isLight) {
        // Sun Icon
        icon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />`;
    } else {
        // Moon Icon
        icon.innerHTML = `<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />`;
    }
}
