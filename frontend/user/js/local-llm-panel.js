// Local LLM (Ollama) adapter panel — shared between settings.html and
// cli-terminal.html. Depends on DOM ids: local-llm-health-badge,
// local-llm-latency, local-llm-base-url, local-llm-model-select,
// local-llm-refresh-btn, local-llm-error.

const HEALTH_BADGE_STYLES = {
    healthy:     { bg: '#dcfce7', fg: '#166534', label: 'healthy' },
    degraded:    { bg: '#fef3c7', fg: '#92400e', label: 'degraded' },
    unreachable: { bg: '#fee2e2', fg: '#991b1b', label: 'unreachable' },
    unknown:     { bg: '#e5e7eb', fg: '#374151', label: 'unknown' },
};

function setHealthBadge(status) {
    const badge = document.getElementById('local-llm-health-badge');
    if (!badge) return;
    const style = HEALTH_BADGE_STYLES[status] || HEALTH_BADGE_STYLES.unknown;
    badge.textContent = style.label;
    badge.style.background = style.bg;
    badge.style.color = style.fg;
}

function setLocalLlmError(msg) {
    const el = document.getElementById('local-llm-error');
    if (!el) return;
    if (msg) {
        el.textContent = msg;
        el.style.display = 'block';
    } else {
        el.textContent = '';
        el.style.display = 'none';
    }
}

async function refreshLocalLlm() {
    const baseUrlEl = document.getElementById('local-llm-base-url');
    const baseUrl = (baseUrlEl?.value || 'http://localhost:11434/v1').trim();
    const latencyEl = document.getElementById('local-llm-latency');
    setLocalLlmError(null);
    setHealthBadge('unknown');
    if (latencyEl) latencyEl.textContent = '...';

    const tauriInvoke = window.__TAURI__?.core?.invoke;
    if (!tauriInvoke) {
        setLocalLlmError('Tauri ランタイムが利用できません（デスクトップ版で実行してください）');
        return;
    }

    try {
        const result = await tauriInvoke('local_llm_list_models', {
            req: { base_url: baseUrl },
        });
        if (latencyEl) {
            latencyEl.textContent = result.latency_ms != null ? `${result.latency_ms} ms` : '';
        }
        if (!result.reachable) {
            setHealthBadge('unreachable');
            setLocalLlmError(result.error || 'unreachable');
            populateModelOptions([]);
            return;
        }
        if (!result.models || result.models.length === 0) {
            setHealthBadge('degraded');
            setLocalLlmError(result.error || 'モデルが見つかりません');
            populateModelOptions([]);
            return;
        }
        setHealthBadge('healthy');
        populateModelOptions(result.models);
    } catch (e) {
        setHealthBadge('unreachable');
        setLocalLlmError(String(e));
        if (latencyEl) latencyEl.textContent = '';
    }
}

function populateModelOptions(models) {
    const select = document.getElementById('local-llm-model-select');
    if (!select) return;
    if (!models || models.length === 0) {
        select.innerHTML = '<option value="">（モデルなし）</option>';
        return;
    }
    select.innerHTML = models
        .map((m) => `<option value="${m}">${m}</option>`)
        .join('');
    const preferred = models.find((m) => m === 'qwen2.5-coder:14b');
    if (preferred) select.value = preferred;
}

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('local-llm-refresh-btn');
    if (btn) {
        btn.addEventListener('click', refreshLocalLlm);
    }
});
