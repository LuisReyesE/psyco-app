/**
 * Patients Module
 * Patient CRUD operations and selection
 */

import { AppState, updateState } from '../state.js';
import { API_URL } from '../api.js';
import { loadSessions } from './sessions.js';
import { loadModels } from './system.js';
import { startSmartPolling } from './polling.js';

/**
 * Initialize the application after login
 */
export function initializeApp() {
    loadPatients().then(() => {
        const savedId = sessionStorage.getItem('activePatientId');
        const savedName = sessionStorage.getItem('activePatientName');
        if (savedId && savedName) {
            selectPatient(parseInt(savedId), savedName);
        }
    });
    loadModels();
    startSmartPolling();
}

/**
 * Load all patients from the API
 */
export async function loadPatients() {
    try {
        const response = await fetch(`${API_URL}/patients/`);
        AppState.allPatients = await response.json();
        renderPatients(AppState.allPatients);
    } catch (e) {
        console.error("Error loading patients:", e);
    }
}

/**
 * Render the patient list in the sidebar
 * @param {Array} patients 
 */
export function renderPatients(patients) {
    const list = document.getElementById('patient-list');
    list.innerHTML = '';

    if (patients.length === 0) {
        list.innerHTML = '<div class="text-center py-10 text-slate-600 text-[10px] uppercase tracking-widest">No hay pacientes</div>';
        return;
    }

    patients.forEach(p => {
        const div = document.createElement('div');
        div.className = `patient-item p-4 rounded-xl cursor-pointer transition-all duration-300 flex justify-between items-center group ${AppState.selectedPatientId === p.id ? 'selected' : 'hover:bg-highlight/30'}`;
        div.innerHTML = `
            <div class="flex flex-col flex-1" onclick="selectPatient(${p.id}, '${p.full_name}')">
                <span class="font-bold text-sm ${AppState.selectedPatientId === p.id ? 'text-indigo-400' : 'text-secondary'}">${p.full_name}</span>
                <span class="text-[9px] text-slate-500 uppercase">Ficha Clínica</span>
            </div>
            <button onclick="deletePatient(event, ${p.id}, '${p.full_name}')" class="p-1.5 opacity-0 group-hover:opacity-100 hover:bg-rose-500/10 rounded text-slate-600 hover:text-rose-400 transition-all">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            </button>
        `;
        list.appendChild(div);
    });
}

/**
 * Select a patient and show their sessions
 * @param {number} id 
 * @param {string} name 
 */
export function selectPatient(id, name) {
    AppState.selectedPatientId = id;
    sessionStorage.setItem('activePatientId', id);
    sessionStorage.setItem('activePatientName', name);

    document.getElementById('intro-view').classList.add('hidden');
    document.getElementById('patient-view').classList.remove('hidden');
    document.getElementById('active-patient-name').innerText = name;

    // Reset load state to avoid notifications for old sessions
    AppState.completedSessionsList.clear();
    AppState.isFirstLoad = true;

    loadSessions(id);
    renderPatients(AppState.allPatients);
}

/**
 * Delete a patient and all their sessions
 * @param {Event} event 
 * @param {number} id 
 * @param {string} name 
 */
export async function deletePatient(event, id, name) {
    event.stopPropagation();
    if (!confirm(`¿Estás seguro de eliminar al paciente ${name} y TODAS sus sesiones? Esta acción es irreversible.`)) return;

    try {
        const res = await fetch(`${API_URL}/patients/${id}`, { method: 'DELETE' });
        if (res.ok) {
            if (AppState.selectedPatientId === id) {
                AppState.selectedPatientId = null;
                sessionStorage.removeItem('activePatientId');
                document.getElementById('patient-view').classList.add('hidden');
                document.getElementById('intro-view').classList.remove('hidden');
            }
            loadPatients();
        }
    } catch (e) {
        console.error("Error deleting patient:", e);
    }
}

/**
 * Create a new patient
 */
export async function createPatient() {
    const name = document.getElementById('patient-name-input').value.trim();
    if (!name) return;

    try {
        const res = await fetch(`${API_URL}/patients/?name=${encodeURIComponent(name)}`, { method: 'POST' });
        if (res.ok) {
            document.getElementById('patient-name-input').value = '';
            hideNewPatientModal();
            loadPatients();
        }
    } catch (e) {
        console.error("Error creating patient:", e);
    }
}

/**
 * Show new patient modal
 */
export function showNewPatientModal() {
    document.getElementById('new-patient-modal').classList.remove('hidden');
}

/**
 * Hide new patient modal
 */
export function hideNewPatientModal() {
    document.getElementById('new-patient-modal').classList.add('hidden');
}

/**
 * Navigate to home view (deselect patient)
 */
export function goToHome() {
    if (!AppState.authToken) return;

    AppState.selectedPatientId = null;
    sessionStorage.removeItem('activePatientId');
    sessionStorage.removeItem('activePatientName');

    document.getElementById('patient-view').classList.add('hidden');
    document.getElementById('intro-view').classList.remove('hidden');

    document.querySelectorAll('.patient-item').forEach(item => {
        item.classList.remove('selected');
    });
}
