
// ------------------------------------
// SETTINGS & BACKUP SYSTEM
// ------------------------------------

function openSettingsModal() {
    document.getElementById('settings-modal').classList.remove('hidden');
}

function closeSettingsModal() {
    document.getElementById('settings-modal').classList.add('hidden');
}

async function downloadBackup() {
    if (!authToken) return;

    try {
        const btn = document.querySelector('#settings-modal button[onclick="downloadBackup()"]');
        const originalText = btn.innerHTML;
        btn.innerHTML = `<span class="animate-pulse">Empaquetando...</span>`;
        btn.disabled = true;

        const response = await fetch(`${API_URL}/system/backup?token=${encodeURIComponent(authToken)}`);

        if (response.ok) {
            // Initiate Download
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = response.headers.get('Content-Disposition')?.split('filename=')[1]?.replace(/"/g, '') || `backup_session_ai.zip`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            btn.innerHTML = `<span class="text-emerald-200">¡Descarga Lista!</span>`;
        } else {
            console.error("Backup failed");
            alert("Error: No se pudo generar la copia de seguridad.");
            btn.innerHTML = originalText;
        }

        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }, 3000);

    } catch (e) {
        console.error("Backup error", e);
        alert("Error de conexión al generar backup.");
    }
}

async function handleRestoreSelect(input) {
    const file = input.files[0];
    if (!file) return;

    if (!confirm("⚠️ ¡ADVERTENCIA CRÍTICA! ⚠️\n\nAl restaurar esta copia, se borrarán TODOS los datos actuales (pacientes, sesiones, análisis) y serán reemplazados por los de la copia.\n\n¿Estás seguro de que quieres continuar? Esta acción es IRREVERSIBLE.")) {
        input.value = ''; // Reset input
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('token', authToken);

    // Bloquear UI
    const modal = document.getElementById('settings-modal').querySelector('.custom-card');
    const originalContent = modal.innerHTML;
    modal.innerHTML = `
        <div class="p-12 flex flex-col items-center justify-center space-y-6 text-center">
            <div class="w-16 h-16 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
            <div>
                <h3 class="text-xl font-bold text-white">Restaurando Sistema...</h3>
                <p class="text-slate-400 mt-2">No cierres esta ventana. Esto puede tomar unos segundos.</p>
            </div>
        </div>
    `;

    try {
        const res = await fetch(`${API_URL}/system/restore`, {
            method: 'POST',
            body: formData
        });

        if (res.ok) {
            alert("✅ Restauración completada con éxito.\n\nLa aplicación se recargará ahora.");
            location.reload();
        } else {
            const err = await res.json();
            throw new Error(err.detail || "Error desconocido");
        }
    } catch (e) {
        console.error("Restore failed", e);
        alert(`❌ Error crítico al restaurar: ${e.message}\n\nEl sistema no ha sido modificado.`);
        modal.innerHTML = originalContent; // Restore UI
        input.value = '';
    }
}
