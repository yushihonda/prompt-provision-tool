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
