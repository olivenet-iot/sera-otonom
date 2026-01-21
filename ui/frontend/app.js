/**
 * Sera Otonom - AI Brain Panel JavaScript
 */

// Configuration
const API_BASE = '/api';
const REFRESH_INTERVAL = 30000; // 30 seconds

// State
let currentPage = 1;
const pageSize = 10;
let refreshTimer = null;

// ===== API Helper =====
async function api(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const config = {
        headers: {
            'Content-Type': 'application/json',
        },
        ...options,
    };

    try {
        const response = await fetch(url, config);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'API request failed');
        }

        return data;
    } catch (error) {
        console.error(`API Error [${endpoint}]:`, error);
        throw error;
    }
}

// ===== Status Functions =====
async function refreshStatus() {
    try {
        const data = await api('/brain/status');
        updateStatusUI(data);
    } catch (error) {
        showToast('Durum bilgisi alinamadi', 'error');
    }
}

function updateStatusUI(data) {
    // Update running state
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');

    if (statusDot && statusText) {
        statusDot.className = `status-dot ${data.is_running ? 'running' : 'stopped'}`;
        statusText.textContent = data.is_running ? 'Calisiyor' : 'Durduruldu';
    }

    // Update mode selector
    const modeSelect = document.getElementById('mode-select');
    if (modeSelect && data.mode) {
        modeSelect.value = data.mode;
    }

    // Update AI status card
    updateAIStatusCard(data);

    // Update devices
    updateDevicesUI(data.devices || []);
}

function updateAIStatusCard(data) {
    // Last thought
    const lastThought = document.getElementById('last-thought');
    if (lastThought) {
        if (data.last_decision) {
            lastThought.textContent = data.last_decision.reason || 'Dusunce yok';
        } else {
            lastThought.textContent = 'Henuz karar verilmedi';
        }
    }

    // Confidence
    const confidenceValue = document.getElementById('confidence-value');
    const confidenceFill = document.getElementById('confidence-fill');

    if (confidenceValue && confidenceFill) {
        const confidence = data.last_decision?.confidence ?? 0;
        const percentage = Math.round(confidence * 100);

        confidenceValue.textContent = `%${percentage}`;
        confidenceFill.style.width = `${percentage}%`;

        // Update color class
        confidenceFill.className = 'confidence-fill';
        if (percentage >= 70) {
            confidenceFill.classList.add('high');
        } else if (percentage >= 40) {
            confidenceFill.classList.add('medium');
        } else {
            confidenceFill.classList.add('low');
        }
    }

    // Cycle count
    const cycleCount = document.getElementById('cycle-count');
    if (cycleCount) {
        cycleCount.textContent = data.cycle_count ?? 0;
    }

    // Last update time
    const lastUpdate = document.getElementById('last-update');
    if (lastUpdate && data.last_decision?.timestamp) {
        lastUpdate.textContent = timeAgo(data.last_decision.timestamp);
    }
}

// ===== Devices Functions =====
function updateDevicesUI(devices) {
    const container = document.getElementById('devices-container');
    if (!container) return;

    if (devices.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔌</div>
                <p class="empty-state-text">Cihaz bulunamadi</p>
            </div>
        `;
        return;
    }

    container.innerHTML = devices.map(device => `
        <div class="device-row" data-device-id="${device.id}">
            <div class="device-info">
                <div class="device-icon">${getDeviceIcon(device.type)}</div>
                <div>
                    <div class="device-name">${device.name}</div>
                    <div class="device-status">
                        <span class="status-badge ${device.state ? 'status-on' : 'status-off'}">
                            ${device.state ? 'Acik' : 'Kapali'}
                        </span>
                    </div>
                </div>
            </div>
            <div class="device-controls">
                <button class="btn btn-sm ${device.state ? 'btn-secondary' : 'btn-success'}"
                        onclick="controlDevice('${device.id}', 'on')"
                        ${device.state ? 'disabled' : ''}>
                    Ac
                </button>
                <button class="btn btn-sm ${!device.state ? 'btn-secondary' : 'btn-danger'}"
                        onclick="controlDevice('${device.id}', 'off')"
                        ${!device.state ? 'disabled' : ''}>
                    Kapat
                </button>
            </div>
        </div>
    `).join('');
}

function getDeviceIcon(type) {
    const icons = {
        'pump': '💧',
        'fan': '🌀',
        'heater': '🔥',
        'light': '💡',
        'valve': '🚿',
    };
    return icons[type] || '⚙️';
}

async function controlDevice(deviceId, action) {
    try {
        await api('/control/override', {
            method: 'POST',
            body: JSON.stringify({
                device_id: deviceId,
                action: action,
            }),
        });

        showToast(`Cihaz ${action === 'on' ? 'acildi' : 'kapatildi'}`, 'success');
        await refreshStatus();
    } catch (error) {
        showToast(`Cihaz kontrolu basarisiz: ${error.message}`, 'error');
    }
}

// ===== Decisions Functions =====
async function refreshDecisions() {
    try {
        const skip = (currentPage - 1) * pageSize;
        const data = await api(`/brain/decisions?limit=${pageSize}&skip=${skip}`);
        updateDecisionsUI(data);
    } catch (error) {
        showToast('Karar gecmisi alinamadi', 'error');
    }
}

function updateDecisionsUI(data) {
    const container = document.getElementById('decisions-container');
    const pagination = document.getElementById('decisions-pagination');

    if (!container) return;

    const decisions = data.decisions || [];
    const total = data.total || 0;
    const totalPages = Math.ceil(total / pageSize);

    if (decisions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📋</div>
                <p class="empty-state-text">Henuz karar yok</p>
            </div>
        `;
        if (pagination) pagination.innerHTML = '';
        return;
    }

    container.innerHTML = decisions.map(decision => `
        <div class="decision-item">
            <div class="decision-header">
                <div class="decision-action">
                    ${getActionIcon(decision.action)}
                    ${decision.action}
                </div>
                <div class="decision-time">${formatTime(decision.timestamp)}</div>
            </div>
            <div class="decision-reason">${decision.reason}</div>
            <div class="decision-confidence">
                <span class="decision-confidence-label">Guven: %${Math.round(decision.confidence * 100)}</span>
                <div class="confidence-bar" style="flex: 1;">
                    <div class="confidence-fill ${getConfidenceClass(decision.confidence)}"
                         style="width: ${decision.confidence * 100}%"></div>
                </div>
            </div>
        </div>
    `).join('');

    // Update pagination
    if (pagination && totalPages > 1) {
        pagination.innerHTML = `
            <button class="pagination-btn" onclick="changePage(${currentPage - 1})" ${currentPage <= 1 ? 'disabled' : ''}>
                &larr; Onceki
            </button>
            <span class="pagination-info">${currentPage} / ${totalPages}</span>
            <button class="pagination-btn" onclick="changePage(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>
                Sonraki &rarr;
            </button>
        `;
    } else if (pagination) {
        pagination.innerHTML = '';
    }
}

function changePage(page) {
    currentPage = page;
    refreshDecisions();
}

function getActionIcon(action) {
    if (!action) return '❓';

    const actionLower = action.toLowerCase();
    if (actionLower.includes('pump') || actionLower.includes('sulama')) return '💧';
    if (actionLower.includes('fan') || actionLower.includes('havalandirma')) return '🌀';
    if (actionLower.includes('heater') || actionLower.includes('isitici')) return '🔥';
    if (actionLower.includes('light') || actionLower.includes('isik')) return '💡';
    if (actionLower.includes('wait') || actionLower.includes('bekle')) return '⏳';
    return '⚡';
}

function getConfidenceClass(confidence) {
    if (confidence >= 0.7) return 'high';
    if (confidence >= 0.4) return 'medium';
    return 'low';
}

// ===== Mode Functions =====
async function handleModeChange(event) {
    const mode = event.target.value;

    try {
        await api('/control/mode', {
            method: 'POST',
            body: JSON.stringify({ mode: mode }),
        });

        showToast(`Mod degistirildi: ${getModeText(mode)}`, 'success');
        await refreshStatus();
    } catch (error) {
        showToast(`Mod degistirilemedi: ${error.message}`, 'error');
        // Revert select
        await refreshStatus();
    }
}

function getModeText(mode) {
    const modes = {
        'auto': 'Otomatik',
        'manual': 'Manuel',
        'paused': 'Duraklatildi',
    };
    return modes[mode] || mode;
}

// ===== Ask AI Functions =====
async function askAI() {
    const input = document.getElementById('ai-question');
    const responseContainer = document.getElementById('ai-response');
    const askBtn = document.getElementById('ask-btn');

    if (!input || !responseContainer) return;

    const question = input.value.trim();
    if (!question) {
        showToast('Lutfen bir soru girin', 'warning');
        return;
    }

    // Show loading
    askBtn.disabled = true;
    askBtn.innerHTML = '<span class="spinner"></span> Dusunuyor...';
    responseContainer.innerHTML = '<div class="text-muted">AI dusunuyor...</div>';

    try {
        const data = await api('/brain/ask', {
            method: 'POST',
            body: JSON.stringify({ question: question }),
        });

        responseContainer.innerHTML = `
            <div class="decision-item" style="border-left-color: #8b5cf6;">
                <div class="decision-header">
                    <div class="decision-action">🤖 AI Yaniti</div>
                </div>
                <div class="decision-reason">${data.response || data.answer || 'Yanit alinamadi'}</div>
            </div>
        `;

        input.value = '';
    } catch (error) {
        responseContainer.innerHTML = `
            <div class="text-error">Hata: ${error.message}</div>
        `;
    } finally {
        askBtn.disabled = false;
        askBtn.innerHTML = 'Sor';
    }
}

// ===== Toast Notifications =====
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
        'success': '✓',
        'error': '✕',
        'warning': '⚠',
        'info': 'ℹ',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${icons[type] || ''}</span> ${message}`;

    container.appendChild(toast);

    // Auto remove after 4 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ===== Utility Functions =====
function formatTime(timestamp) {
    if (!timestamp) return '-';

    const date = new Date(timestamp);
    return date.toLocaleString('tr-TR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

function timeAgo(timestamp) {
    if (!timestamp) return '-';

    const date = new Date(timestamp);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'Az once';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} dakika once`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} saat once`;
    return `${Math.floor(seconds / 86400)} gun once`;
}

// ===== Initialization =====
function startAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }

    refreshTimer = setInterval(() => {
        refreshStatus();
    }, REFRESH_INTERVAL);
}

function stopAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
    }
}

async function init() {
    console.log('AI Brain Panel initializing...');

    // Initial data load
    await Promise.all([
        refreshStatus(),
        refreshDecisions(),
    ]);

    // Start auto-refresh
    startAutoRefresh();

    // Handle enter key for AI question
    const aiInput = document.getElementById('ai-question');
    if (aiInput) {
        aiInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                askAI();
            }
        });
    }

    console.log('AI Brain Panel initialized');
}

// Start when DOM is ready
document.addEventListener('DOMContentLoaded', init);

// Handle page visibility for auto-refresh
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopAutoRefresh();
    } else {
        refreshStatus();
        startAutoRefresh();
    }
});
