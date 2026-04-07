// ユーザー API設定画面 JavaScript

document.addEventListener('DOMContentLoaded', async () => {
    await checkAuth();
    initUserLayout('settings.html');
    await loadApiConfig();
});

async function loadApiConfig() {
    try {
        const config = await apiRequest('/api/user/settings/api-config');
        renderStatus(config);
        renderRateLimits(config);

        // マスク値をplaceholderに設定
        document.getElementById('input-openai').placeholder = config.openai_api_key || 'sk-...（未設定）';
        document.getElementById('input-gemini').placeholder = config.gemini_api_key || 'AIza...（未設定）';
        document.getElementById('input-anthropic').placeholder = config.anthropic_api_key || 'sk-ant-...（未設定）';
    } catch (e) {
        console.error('Load API config error:', e);
    }
}

function renderStatus(config) {
    const el = document.getElementById('api-status');
    const providers = [
        { key: 'openai_api_key', label: 'OpenAI', color: '#10a37f' },
        { key: 'gemini_api_key', label: 'Gemini', color: '#4285f4' },
        { key: 'anthropic_api_key', label: 'Anthropic', color: '#d97757' },
    ];
    el.innerHTML = providers.map(p => {
        const configured = !!config[p.key];
        return `
            <div style="background: var(--card-bg, #fff); border-radius: 12px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); text-align: center;">
                <div style="font-size: 13px; font-weight: 600; color: ${p.color}; margin-bottom: 8px;">${p.label}</div>
                <div style="font-size: 22px;">${configured ? '<span style="color:#28a745;">&#10003;</span>' : '<span style="color:#ccc;">&#10007;</span>'}</div>
                <div style="font-size: 10px; color: var(--content-text-muted); margin-top: 4px;">${configured ? config[p.key] : '未設定'}</div>
            </div>
        `;
    }).join('');
}

function renderRateLimits(config) {
    const el = document.getElementById('rate-limit-info');
    el.innerHTML = `
        <span style="font-weight: 600;">レート制限（管理者設定）:</span>
        <span style="margin-left: 8px;">${config.rate_limit_per_hour || 100} 回/時間</span>
        <span style="margin-left: 12px;">${config.rate_limit_per_day || 1000} 回/日</span>
        ${config.is_enabled === false ? '<span style="margin-left: 12px; color: #dc3545; font-weight: 600;">API無効</span>' : ''}
    `;
}

async function saveApiConfig() {
    const openai = document.getElementById('input-openai').value;
    const gemini = document.getElementById('input-gemini').value;
    const anthropic = document.getElementById('input-anthropic').value;

    // 入力があるフィールドのみ送信
    const body = {};
    if (openai) body.openai_api_key = openai;
    if (gemini) body.gemini_api_key = gemini;
    if (anthropic) body.anthropic_api_key = anthropic;

    if (Object.keys(body).length === 0) {
        showAlert('変更するキーを入力してください', 'warning');
        return;
    }

    try {
        await apiRequest('/api/user/settings/api-config', {
            method: 'PATCH',
            body: JSON.stringify(body),
        });
        showAlert('APIキーを保存しました', 'success');
        // 入力フィールドをクリア＆再読み込み
        document.getElementById('input-openai').value = '';
        document.getElementById('input-gemini').value = '';
        document.getElementById('input-anthropic').value = '';
        await loadApiConfig();
    } catch (e) {
        showAlert('保存に失敗しました: ' + e.message, 'error');
    }
}

// ───────────────────────────────────────────────
// Local LLM (Ollama) adapter — read-only health probe + model list.
// Tauri command for instant local feedback; backend endpoint for
// persistent health state.
// ───────────────────────────────────────────────
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
    // Pre-select qwen2.5-coder:14b if present.
    const preferred = models.find((m) => m === 'qwen2.5-coder:14b');
    if (preferred) select.value = preferred;
}

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('local-llm-refresh-btn');
    if (btn) {
        btn.addEventListener('click', refreshLocalLlm);
    }
});
