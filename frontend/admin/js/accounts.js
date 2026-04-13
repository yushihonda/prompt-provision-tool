// 管理者 アカウント一覧画面 JavaScript

let accounts = [];
let allSkills = [];
let allWorkflows = [];

// 共通スタイル定数（skills.jsのWF_SWALと同じ）
const ACC_S = {
    lbl: 'style="display:block; font-weight:600; margin-bottom:5px; color:var(--content-text); font-size:13px;"',
    fld: 'style="text-align:left; margin-bottom:14px; width:100%; box-sizing:border-box;"',
    inp: 'class="swal2-input" style="width:100%; margin-top:0; box-sizing:border-box; max-width:100%;"',
    sel: 'class="swal2-select" style="width:100%; margin-top:0; box-sizing:border-box; max-width:100%;"',
    hint: 'style="color:var(--content-text-muted); display:block; margin-top:4px; font-size:12px;"',
    card: 'style="text-align:left; margin-bottom:15px; width:100%; box-sizing:border-box; padding:16px; background:var(--card-bg); border:1px solid rgba(0,0,0,0.06); border-radius:14px;"',
    secTitle: 'style="display:block; font-weight:700; margin-bottom:8px; color:var(--content-text); font-size:14px;"',
};

let currentPage = 1;
const itemsPerPage = 10;
let totalItems = 0;

async function loadAccounts(page = 1) {
    try {
        const skip = (page - 1) * itemsPerPage;
        const response = await apiRequest(`/api/admin/accounts?skip=${skip}&limit=${itemsPerPage}`);

        accounts = response.items || response;
        totalItems = response.total !== undefined ? response.total : (accounts.length === itemsPerPage ? page * itemsPerPage + 1 : page * itemsPerPage);

        currentPage = page;
        renderAccounts();
        renderPagination();
    } catch (error) {
        showAlert('アカウントの読み込みに失敗しました', 'error');
        console.error('Load accounts error:', error);
    }
}

function renderPagination() {
    renderAdminPagination('pagination-container', currentPage, totalItems, itemsPerPage, 'loadAccounts');
}

async function loadAllSkills() {
    try {
        const response = await apiRequest('/api/admin/skills?skip=0&limit=200');
        allSkills = response.items || response;
    } catch (error) {
        console.error('Load skills error:', error);
    }
}

async function loadAllWorkflows() {
    try {
        const response = await apiRequest('/api/admin/workflows?skip=0&limit=200');
        allWorkflows = response.items || response;
    } catch (error) {
        console.error('Load workflows error:', error);
    }
}

function renderAccounts() {
    const tbody = document.getElementById('accounts-tbody');

    if (accounts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: var(--content-text-muted);">アカウントがまだ登録されていません</td></tr>';
        return;
    }

    tbody.innerHTML = accounts.map(account => `
        <tr>
            <td>${account.id}</td>
            <td>${escapeHtmlAdmin(account.username)}</td>
            <td>${escapeHtmlAdmin(account.email)}</td>
            <td>
                <span style="color: ${account.account_type === 'PARENT' ? 'var(--accent)' : 'var(--content-text)'}; font-weight: ${account.account_type === 'PARENT' ? 'bold' : 'normal'};">
                    ${account.account_type === 'PARENT' ? '管理者' : 'ユーザー'}
                </span>
            </td>
            <td>${statusBadgeHtml(account.is_active)}</td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">WF:</span>
                            <span style="color: var(--content-text);">${account.workflow_count || 0}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">スキル:</span>
                            <span style="color: var(--content-text);">${account.skill_count}</span>
                        </div>
                    </div>
                ` : `<span style="color: var(--content-text-muted);">-</span>`}
            </td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">今月:</span>
                            <span style="color: var(--content-text);">${account.executions_this_month || 0}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">全期間:</span>
                            <span style="color: var(--content-text);">${account.execution_count || 0}</span>
                        </div>
                    </div>
                ` : `<span style="color: var(--content-text-muted);">-</span>`}
            </td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">今月:</span>
                            <span style="color: var(--content-text);">${formatCompact(account.tokens_this_month)}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">全期間:</span>
                            <span style="color: var(--content-text);">${formatCompact(account.total_tokens)}</span>
                        </div>
                    </div>
                ` : `<span style="color: var(--content-text-muted);">-</span>`}
            </td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">今月:</span>
                            <span style="color: var(--content-text);">$${(account.cost_this_month || 0).toFixed(2)}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">全期間:</span>
                            <span style="color: var(--content-text);">$${(account.total_cost || 0).toFixed(2)}</span>
                        </div>
                    </div>
                ` : `<span style="color: var(--content-text-muted);">-</span>`}
            </td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: ${account.api_config && account.api_config.openai_api_key ? '#28a745' : 'var(--content-text-muted)'};">
                                OpenAI: ${account.api_config && account.api_config.openai_api_key ? '✓' : '✗'}
                            </span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: ${account.api_config && account.api_config.gemini_api_key ? '#28a745' : 'var(--content-text-muted)'};">
                                Gemini: ${account.api_config && account.api_config.gemini_api_key ? '✓' : '✗'}
                            </span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: ${account.api_config && account.api_config.anthropic_api_key ? '#28a745' : 'var(--content-text-muted)'};">
                                Claude: ${account.api_config && account.api_config.anthropic_api_key ? '✓' : '✗'}
                            </span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: var(--content-text-muted);">
                                制限: ${account.api_config ? (account.api_config.rate_limit_per_hour || 100) : 100}/時, ${account.api_config ? (account.api_config.rate_limit_per_day || 1000) : 1000}/日
                            </span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: ${account.api_config ? (account.api_config.is_enabled !== false ? '#28a745' : '#dc3545') : '#28a745'};">
                                状態: ${account.api_config ? (account.api_config.is_enabled !== false ? '有効' : '無効') : '有効'}
                            </span>
                        </div>
                    </div>
                ` : `
                    <span style="color: var(--content-text-muted);">-</span>
                `}
            </td>
            <td>
                <div class="actions">
                    <button ${account.account_type === 'PARENT' ? 'disabled' : `onclick="showAssignModal(${account.id})"`} title="${account.account_type === 'PARENT' ? '管理者はスキル割り当てできません' : 'スキル割り当て'}" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; ${account.account_type === 'PARENT' ? 'cursor: not-allowed; opacity: 0.5;' : 'cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;'}">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #ff9800; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m21 4c0-.478-.379-1-1-1h-16c-.62 0-1 .519-1 1v16c0 .621.52 1 1 1h16c.478 0 1-.379 1-1zm-16.5.5h15v15h-15zm6.75 9.25v3.25c0 .53-.47 1-1 1h-3.25c-.53 0-1-.47-1-1v-3.25c0-.53.47-1 1-1h3.25c.53 0 1 .47 1 1zm0-6.75v3.25c0 .53-.47 1-1 1h-3.25c-.53 0-1-.47-1-1v-3.25c0-.53.47-1 1-1h3.25c.53 0 1 .47 1 1zm6.75 0v3.25c0 .53-.47 1-1 1h-3.25c-.53 0-1-.47-1-1v-3.25c0-.53.47-1 1-1h3.25c.53 0 1 .47 1 1z" fill-rule="nonzero"/></svg>
                    </button>
                    <button onclick="editAccount(${account.id})" title="編集" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #28a745; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m11.239 15.533c-1.045 3.004-1.238 3.451-1.238 3.84 0 .441.385.627.627.627.272 0 1.108-.301 3.829-1.249zm.888-.888 3.22 3.22 6.408-6.401c.163-.163.245-.376.245-.591 0-.213-.082-.427-.245-.591-.58-.579-1.458-1.457-2.039-2.036-.163-.163-.377-.245-.591-.245-.213 0-.428.082-.592.245zm-3.127-.895c0-.402-.356-.75-.75-.75-2.561 0-2.939 0-5.5 0-.394 0-.75.348-.75.75s.356.75.75.75h5.5c.394 0 .75-.348.75-.75zm5-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75z" fill-rule="nonzero"/></svg>
                    </button>
                    <button ${account.account_type === 'PARENT' ? 'disabled' : `onclick="deleteAccount(${account.id})"`} title="${account.account_type === 'PARENT' ? '管理者は削除できません' : '削除'}" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; ${account.account_type === 'PARENT' ? 'cursor: not-allowed; opacity: 0.5;' : 'cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;'}">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #dc3545; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m20.015 6.506h-16v14.423c0 .591.448 1.071 1 1.071h14c.552 0 1-.48 1-1.071 0-3.905 0-14.423 0-14.423zm-5.75 2.494c.414 0 .75.336.75.75v8.5c0 .414-.336.75-.75.75s-.75-.336-.75-.75v-8.5c0-.414.336-.75.75-.75zm-4.5 0c.414 0 .75.336.75.75v8.5c0 .414-.336.75-.75.75s-.75-.336-.75-.75v-8.5c0-.414.336-.75.75-.75zm-.75-5v-1c0-.535.474-1 1-1h4c.526 0 1 .465 1 1v1h5.254c.412 0 .746.335.746.747s-.334.747-.746.747h-16.507c-.413 0-.747-.335-.747-.747s.334-.747.747-.747zm4.5 0v-.5h-3v.5z" fill-rule="nonzero"/></svg>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

async function showCreateModal() {
    const { value: formValues } = await Swal.fire({
        title: '新しいアカウント',
        html: `
            <div style="text-align:left; width:100%; box-sizing:border-box;">
                <!-- アカウント情報カード -->
                <div ${ACC_S.card}>
                    <span ${ACC_S.secTitle}>アカウント情報</span>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
                        <div>
                            <label ${ACC_S.lbl}>ユーザー名 <span style="color:var(--accent);">*</span></label>
                            <input id="swal-account-username" ${ACC_S.inp} type="text" placeholder="例: user01" required>
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>メールアドレス <span style="color:var(--accent);">*</span></label>
                            <input id="swal-account-email" ${ACC_S.inp} type="email" placeholder="例: user@example.com" required>
                        </div>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                        <div>
                            <label ${ACC_S.lbl}>パスワード <span style="color:var(--accent);">*</span></label>
                            <input id="swal-account-password" ${ACC_S.inp} type="password" placeholder="パスワード" required>
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>アカウントタイプ <span style="color:var(--accent);">*</span></label>
                            <select id="swal-account-type" ${ACC_S.sel} required onchange="toggleApiConfigSection()">
                                <option value="CHILD" selected>子アカウント（ユーザー）</option>
                                <option value="PARENT">親アカウント（管理者）</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- API設定カード -->
                <div id="swal-api-config-section" ${ACC_S.card}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <span ${ACC_S.secTitle} style="margin-bottom:0;">API設定（オプション）</span>
                        <label style="display:flex; align-items:center; cursor:pointer; gap:5px;">
                            <input type="checkbox" id="swal-account-api-enabled" checked style="width:16px; height:16px; cursor:pointer; accent-color:var(--accent);">
                            <span style="font-size:12px; color:var(--accent); font-weight:600;">有効</span>
                        </label>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:12px;">
                        <div>
                            <label ${ACC_S.lbl}>OpenAI API Key</label>
                            <input id="swal-account-openai-key" ${ACC_S.inp} type="password" placeholder="sk-...">
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>Gemini API Key</label>
                            <input id="swal-account-gemini-key" ${ACC_S.inp} type="password" placeholder="AIza...">
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>Anthropic API Key</label>
                            <input id="swal-account-anthropic-key" ${ACC_S.inp} type="password" placeholder="sk-ant-...">
                        </div>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                        <div>
                            <label ${ACC_S.lbl}>レート制限（1時間）</label>
                            <input id="swal-account-rate-limit-hour" ${ACC_S.inp} type="number" min="1" value="100">
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>レート制限（1日）</label>
                            <input id="swal-account-rate-limit-day" ${ACC_S.inp} type="number" min="1" value="1000">
                        </div>
                    </div>
                </div>
            </div>
        `,
        focusConfirm: false,
        showCancelButton: true,
        confirmButtonText: '作成',
        cancelButtonText: ADMIN_SWAL.btnClose,
        confirmButtonColor: ADMIN_SWAL.primary,
        cancelButtonColor: ADMIN_SWAL.secondary,
        width: '800px',
        customClass: {
            popup: 'swal-scrollable-popup',
            htmlContainer: 'swal-scrollable-container'
        },
        preConfirm: () => {
            const username = document.getElementById('swal-account-username').value.trim();
            const email = document.getElementById('swal-account-email').value.trim();
            const password = document.getElementById('swal-account-password').value.trim();
            const accountType = document.getElementById('swal-account-type').value;

            const result = {
                username,
                email,
                password,
                accountType
            };

            // 子アカウントの場合のみAPI設定を取得
            if (accountType === 'CHILD') {
                const openaiKeyEl = document.getElementById('swal-account-openai-key');
                const geminiKeyEl = document.getElementById('swal-account-gemini-key');
                const anthropicKeyEl = document.getElementById('swal-account-anthropic-key');
                const rateLimitHourEl = document.getElementById('swal-account-rate-limit-hour');
                const rateLimitDayEl = document.getElementById('swal-account-rate-limit-day');
                const apiEnabledEl = document.getElementById('swal-account-api-enabled');

                if (openaiKeyEl) result.openaiKey = openaiKeyEl.value.trim();
                if (geminiKeyEl) result.geminiKey = geminiKeyEl.value.trim();
                if (anthropicKeyEl) result.anthropicKey = anthropicKeyEl.value.trim();
                if (rateLimitHourEl) result.rateLimitHour = parseInt(rateLimitHourEl.value) || 100;
                if (rateLimitDayEl) result.rateLimitDay = parseInt(rateLimitDayEl.value) || 1000;
                if (apiEnabledEl) result.apiEnabled = apiEnabledEl.checked;
            }

            if (!username) {
                Swal.showValidationMessage('ユーザー名は必須です');
                return false;
            }
            if (!email) {
                Swal.showValidationMessage('メールアドレスは必須です');
                return false;
            }
            // メールアドレスの基本的なバリデーション
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailRegex.test(email)) {
                Swal.showValidationMessage('有効なメールアドレスを入力してください（例: user@example.com）');
                return false;
            }
            if (!password) {
                Swal.showValidationMessage('パスワードは必須です');
                return false;
            }

            return result;
        },
        didOpen: () => {
            // アカウントタイプの変更を監視
            const typeSelect = document.getElementById('swal-account-type');
            if (typeSelect) {
                typeSelect.addEventListener('change', toggleApiConfigSection);
                toggleApiConfigSection(); // 初期状態を設定
            }
        }
    });

    if (formValues) {
        await saveAccount(null, formValues);
    }
}

async function editAccount(id) {
    const account = accounts.find(a => a.id === id);
    if (!account) return;

    const _apiStatus = (key) => account.api_config && account.api_config[key] ? '設定済み' : '未設定';
    const _apiPh = (key) => account.api_config && account.api_config[key] ? '変更する場合は新しいキーを入力' : '未設定（キーを入力）';

    const { value: formValues } = await Swal.fire({
        title: 'アカウントを編集',
        html: `
            <div style="text-align:left; width:100%; box-sizing:border-box;">
                <!-- アカウント情報カード -->
                <div ${ACC_S.card}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <span ${ACC_S.secTitle} style="margin-bottom:0;">アカウント情報</span>
                        <label style="display:flex; align-items:center; cursor:pointer; gap:5px;">
                            <input type="checkbox" id="swal-account-is-active" ${account.is_active ? 'checked' : ''} style="width:16px; height:16px; cursor:pointer; accent-color:var(--accent);">
                            <span style="font-size:12px; color:var(--accent); font-weight:600;">有効</span>
                        </label>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                        <div>
                            <label ${ACC_S.lbl}>ユーザー名</label>
                            <input id="swal-account-username" ${ACC_S.inp} type="text" value="${account.username}" disabled style="background:var(--card-bg) !important; opacity:0.7;">
                            <small ${ACC_S.hint}>変更不可</small>
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>メールアドレス <span style="color:var(--accent);">*</span></label>
                            <input id="swal-account-email" ${ACC_S.inp} type="email" value="${account.email}" required>
                        </div>
                    </div>
                    <div ${ACC_S.fld} style="margin-top:12px;">
                        <label ${ACC_S.lbl}>パスワード（変更する場合のみ）</label>
                        <input id="swal-account-password" ${ACC_S.inp} type="password" placeholder="変更しない場合は空欄">
                    </div>
                </div>

                ${account.account_type === 'CHILD' ? `
                <!-- API設定カード -->
                <div ${ACC_S.card}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <span ${ACC_S.secTitle} style="margin-bottom:0;">API設定</span>
                        <label style="display:flex; align-items:center; cursor:pointer; gap:5px;">
                            <input type="checkbox" id="swal-account-edit-api-enabled" ${account.api_config ? (account.api_config.is_enabled !== false ? 'checked' : '') : 'checked'} style="width:16px; height:16px; cursor:pointer; accent-color:var(--accent);">
                            <span style="font-size:12px; color:var(--accent); font-weight:600;">有効</span>
                        </label>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:12px;">
                        <div>
                            <label ${ACC_S.lbl}>OpenAI <span style="font-size:10px; color:var(--content-text-muted);">(${_apiStatus('openai_api_key')})</span></label>
                            <input id="swal-account-edit-openai-key" ${ACC_S.inp} type="password" placeholder="${_apiPh('openai_api_key')}">
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>Gemini <span style="font-size:10px; color:var(--content-text-muted);">(${_apiStatus('gemini_api_key')})</span></label>
                            <input id="swal-account-edit-gemini-key" ${ACC_S.inp} type="password" placeholder="${_apiPh('gemini_api_key')}">
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>Anthropic <span style="font-size:10px; color:var(--content-text-muted);">(${_apiStatus('anthropic_api_key')})</span></label>
                            <input id="swal-account-edit-anthropic-key" ${ACC_S.inp} type="password" placeholder="${_apiPh('anthropic_api_key')}">
                        </div>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                        <div>
                            <label ${ACC_S.lbl}>レート制限（1時間）</label>
                            <input id="swal-account-edit-rate-limit-hour" ${ACC_S.inp} type="number" min="1" value="${account.api_config ? (account.api_config.rate_limit_per_hour || 100) : 100}">
                        </div>
                        <div>
                            <label ${ACC_S.lbl}>レート制限（1日）</label>
                            <input id="swal-account-edit-rate-limit-day" ${ACC_S.inp} type="number" min="1" value="${account.api_config ? (account.api_config.rate_limit_per_day || 1000) : 1000}">
                        </div>
                    </div>
                </div>
                ` : ''}
            </div>
        `,
        focusConfirm: false,
        showCancelButton: true,
        confirmButtonText: '保存',
        cancelButtonText: ADMIN_SWAL.btnClose,
        confirmButtonColor: ADMIN_SWAL.primary,
        cancelButtonColor: ADMIN_SWAL.secondary,
        width: '800px',
        customClass: {
            popup: 'swal-scrollable-popup',
            htmlContainer: 'swal-scrollable-container'
        },
        preConfirm: () => {
            const email = document.getElementById('swal-account-email').value.trim();
            const password = document.getElementById('swal-account-password').value.trim();
            const isActive = document.getElementById('swal-account-is-active').checked;

            const result = {
                email,
                password,
                isActive
            };

            // 子アカウントの場合のみAPI設定を取得
            if (account.account_type === 'CHILD') {
                const openaiKeyEl = document.getElementById('swal-account-edit-openai-key');
                const geminiKeyEl = document.getElementById('swal-account-edit-gemini-key');
                const anthropicKeyEl = document.getElementById('swal-account-edit-anthropic-key');
                const rateLimitHourEl = document.getElementById('swal-account-edit-rate-limit-hour');
                const rateLimitDayEl = document.getElementById('swal-account-edit-rate-limit-day');
                const apiEnabledEl = document.getElementById('swal-account-edit-api-enabled');

                if (openaiKeyEl) result.openaiKey = openaiKeyEl.value.trim();
                if (geminiKeyEl) result.geminiKey = geminiKeyEl.value.trim();
                if (anthropicKeyEl) result.anthropicKey = anthropicKeyEl.value.trim();
                if (rateLimitHourEl) result.rateLimitHour = parseInt(rateLimitHourEl.value) || 100;
                if (rateLimitDayEl) result.rateLimitDay = parseInt(rateLimitDayEl.value) || 1000;
                if (apiEnabledEl) result.apiEnabled = apiEnabledEl.checked;
            }

            if (!email) {
                Swal.showValidationMessage('メールアドレスは必須です');
                return false;
            }

            return result;
        }
    });

    if (formValues) {
        await saveAccount(id, formValues);
    }
}

async function saveAccount(id, formValues) {
    const data = {};

    if (id) {
        // 更新
        if (formValues.email) {
            data.email = formValues.email;
        }
        if (formValues.password) {
            data.password = formValues.password;
        }
        if (formValues.isActive !== undefined) {
            data.is_active = formValues.isActive;
        }

        // API設定の更新（子アカウントの場合のみ）
        const account = accounts.find(a => a.id === id);
        if (account && account.account_type === 'CHILD') {
            // APIキーが入力されている場合のみ更新（空文字列の場合は更新しない）
            if (formValues.openaiKey && formValues.openaiKey.trim() !== '') {
                data.openai_api_key = formValues.openaiKey.trim();
            }

            if (formValues.geminiKey && formValues.geminiKey.trim() !== '') {
                data.gemini_api_key = formValues.geminiKey.trim();
            }

            if (formValues.anthropicKey && formValues.anthropicKey.trim() !== '') {
                data.anthropic_api_key = formValues.anthropicKey.trim();
            }

            if (formValues.rateLimitHour !== undefined) {
                data.rate_limit_per_hour = formValues.rateLimitHour;
            }
            if (formValues.rateLimitDay !== undefined) {
                data.rate_limit_per_day = formValues.rateLimitDay;
            }
            if (formValues.apiEnabled !== undefined) {
                data.api_config_enabled = formValues.apiEnabled;
            }
        }

        try {
            await apiRequest(`/api/admin/accounts/${id}`, {
                method: 'PATCH',
                body: JSON.stringify(data)
            });
            await Swal.fire({
                title: '更新完了',
                text: 'アカウントを更新しました',
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            loadAccounts(currentPage);
        } catch (error) {
            await Swal.fire({
                title: 'エラー',
                text: 'アカウントの更新に失敗しました',
                icon: 'error',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            console.error('Update account error:', error);
        }
    } else {
        // 作成
        data.username = formValues.username;
        data.email = formValues.email;
        data.password = formValues.password;
        data.account_type = formValues.accountType;

        // API設定（子アカウントの場合のみ）
        if (formValues.accountType === 'CHILD') {
            if (formValues.openaiKey) {
                data.openai_api_key = formValues.openaiKey;
            }
            if (formValues.geminiKey) {
                data.gemini_api_key = formValues.geminiKey;
            }
            if (formValues.anthropicKey) {
                data.anthropic_api_key = formValues.anthropicKey;
            }
            if (formValues.rateLimitHour !== undefined) {
                data.rate_limit_per_hour = formValues.rateLimitHour;
            }
            if (formValues.rateLimitDay !== undefined) {
                data.rate_limit_per_day = formValues.rateLimitDay;
            }
            if (formValues.apiEnabled !== undefined) {
                data.api_config_enabled = formValues.apiEnabled;
            }
        }

        try {
            await apiRequest('/api/admin/accounts', {
                method: 'POST',
                body: JSON.stringify(data)
            });
            await Swal.fire({
                title: '作成完了',
                text: 'アカウントを作成しました',
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            loadAccounts(1);
        } catch (error) {
            const errorMessage = error.message || 'アカウントの作成に失敗しました';
            await Swal.fire({
                title: 'エラー',
                text: errorMessage,
                icon: 'error',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            console.error('Create account error:', error);
            console.error('Error message:', errorMessage);
        }
    }
}

async function deleteAccount(id) {
    const account = accounts.find(a => a.id === id);
    if (!account) return;

    const result = await Swal.fire({
        title: '削除の確認',
        html: `
            <div style="text-align:center;">
                <div ${ACC_S.card} style="border-left:3px solid #dc3545; text-align:left;">
                    <p style="color:var(--content-text); font-size:14px; margin:0;">本当に「<strong>${account.username}</strong>」を削除しますか？</p>
                    <p style="color:var(--content-text-muted); font-size:12px; margin:8px 0 0;">この操作は取り消せません。</p>
                </div>
            </div>
        `,
        icon: 'warning',
        confirmButtonColor: '#dc3545',
        confirmButtonText: '削除'
    });

    if (result.isConfirmed) {
        try {
            await apiRequest(`/api/admin/accounts/${id}`, {
                method: 'DELETE'
            });
            await Swal.fire({
                title: '削除完了',
                text: 'アカウントを削除しました',
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            loadAccounts(currentPage);
        } catch (error) {
            const errorMessage = error.message || 'アカウントの削除に失敗しました';
            await Swal.fire({
                title: 'エラー',
                text: errorMessage,
                icon: 'error',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            console.error('Delete account error:', error);
        }
    }
}

async function showAssignModal(accountId) {
    const account = accounts.find(a => a.id === accountId);
    if (!account) return;

    // 割り当て済みスキルを取得
    try {
        const assignedSkills = await apiRequest(`/api/admin/accounts/${accountId}/skills`);
        const assignedIds = assignedSkills.map(p => p.id);

        // ワークフロー親子構造を構築
        // 各ワークフローに含まれるスキルIDを収集
        const wfSkillMap = {}; // skillId → [wfName, ...]
        const wfList = [];
        for (const wf of allWorkflows) {
            if (!wf.is_active) continue;
            const wfSkillIds = (wf.groups || []).flatMap(g => (g.skills || []).map(s => s.skill_id));
            const allAssigned = wfSkillIds.length > 0 && wfSkillIds.every(sid => assignedIds.includes(sid));
            wfList.push({ ...wf, wfSkillIds, allAssigned });
            for (const sid of wfSkillIds) {
                if (!wfSkillMap[sid]) wfSkillMap[sid] = [];
                wfSkillMap[sid].push(wf.name);
            }
        }

        // スキル割り当てバッジ生成
        function skillBadge(skillId) {
            const assigned = assignedIds.includes(skillId);
            const asg = assignedSkills.find(s => s.id === skillId);
            if (assigned) {
                return `<span style="color:#28a745; font-size:10px; padding:2px 8px; background:rgba(40,167,69,0.1); border-radius:20px; font-weight:600;">有効</span>
                    <button onclick="Swal.close(); unassignSkill(${asg?.assignment_id}, ${accountId})" style="font-size:10px; padding:2px 8px; background:#fff; border:1px solid rgba(220,53,69,0.3); border-radius:20px; color:#dc3545; cursor:pointer; margin-left:4px; font-weight:600; transition:all 0.2s;" onmouseover="this.style.background='#dc3545';this.style.color='#fff';" onmouseout="this.style.background='#fff';this.style.color='#dc3545';">無効にする</button>`;
            }
            return `<button onclick="Swal.close(); assignSkill(${accountId}, ${skillId})" style="font-size:10px; padding:2px 8px; background:#fff; border:1px solid rgba(220,53,69,0.3); border-radius:20px; color:#dc3545; cursor:pointer; font-weight:600; transition:all 0.2s;" onmouseover="this.style.background='#dc3545';this.style.color='#fff';" onmouseout="this.style.background='#fff';this.style.color='#dc3545';">有効にする</button>`;
        }

        // ワークフロー親子HTML
        let wfSectionHTML = '';
        for (const wf of wfList) {
            const skillsInWf = wf.wfSkillIds.map(sid => {
                const sk = allSkills.find(s => s.id === sid);
                return sk ? sk : { id: sid, name: `Skill #${sid}` };
            });
            const assignedCount = wf.wfSkillIds.filter(sid => assignedIds.includes(sid)).length;
            const totalCount = wf.wfSkillIds.length;
            const statusLabel = wf.allAssigned ? '<span style="color:#28a745; font-size:10px;">全て有効</span>' : `<span style="color:var(--content-text-muted); font-size:10px;">${assignedCount}/${totalCount}</span>`;

            wfSectionHTML += `
                <div style="margin-bottom:10px; border:1px solid rgba(0,0,0,0.06); border-radius:10px; overflow:hidden;">
                    <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; background:rgba(0,0,0,0.02);">
                        <strong style="color:var(--content-text); font-size:13px; flex:1;">${wf.name}</strong>
                        ${statusLabel}
                        ${wf.allAssigned
                            ? `<button onclick="Swal.close(); unassignWorkflow(${wf.id}, ${accountId})" style="font-size:10px; padding:2px 10px; background:#fff; border:1px solid rgba(220,53,69,0.3); border-radius:20px; color:#dc3545; cursor:pointer; font-weight:600; transition:all 0.2s;" onmouseover="this.style.background='#dc3545';this.style.color='#fff';" onmouseout="this.style.background='#fff';this.style.color='#dc3545';">一括無効</button>`
                            : `<button onclick="Swal.close(); assignWorkflow(${accountId}, ${wf.id})" style="font-size:10px; padding:2px 10px; background:#fff; border:1px solid rgba(220,53,69,0.3); border-radius:20px; color:#dc3545; cursor:pointer; font-weight:600; transition:all 0.2s;" onmouseover="this.style.background='#dc3545';this.style.color='#fff';" onmouseout="this.style.background='#fff';this.style.color='#dc3545';">一括有効</button>`
                        }
                    </div>
                    <div style="padding:8px 14px;">
                        ${skillsInWf.map(sk => `
                            <div style="display:flex; align-items:center; gap:8px; padding:5px 0; border-bottom:1px solid rgba(0,0,0,0.04);">
                                <span style="color:var(--content-text-muted); font-size:10px; width:14px; text-align:center;">└</span>
                                <span style="font-size:12px; color:var(--content-text); flex:1;">${sk.name}</span>
                                ${skillBadge(sk.id)}
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        if (!wfSectionHTML) {
            wfSectionHTML = '<p style="text-align:center; color:var(--content-text-muted); padding:10px; font-size:12px;">ワークフローがありません</p>';
        }

        // ワークフローに属さないスキル
        const wfSkillIdSet = new Set(Object.keys(wfSkillMap).map(Number));
        const standaloneAssigned = assignedSkills.filter(s => !wfSkillIdSet.has(s.id));
        const standaloneAvailable = allSkills.filter(s => !assignedIds.includes(s.id) && s.is_active && !wfSkillIdSet.has(s.id));

        let standaloneSectionHTML = '';
        if (standaloneAssigned.length > 0 || standaloneAvailable.length > 0) {
            standaloneSectionHTML = [...standaloneAvailable.map(s => `
                <div style="display:flex; align-items:center; gap:8px; padding:6px 10px; margin-bottom:4px; border-radius:8px;">
                    <span style="font-size:12px; color:var(--content-text); flex:1;">${s.name}</span>
                    <button onclick="Swal.close(); assignSkill(${accountId}, ${s.id})" style="font-size:10px; padding:2px 8px; background:#fff; border:1px solid rgba(220,53,69,0.3); border-radius:20px; color:#dc3545; cursor:pointer; font-weight:600; transition:all 0.2s;" onmouseover="this.style.background='#dc3545';this.style.color='#fff';" onmouseout="this.style.background='#fff';this.style.color='#dc3545';">有効にする</button>
                </div>
            `), ...standaloneAssigned.map(s => `
                <div style="display:flex; align-items:center; gap:8px; padding:6px 10px; margin-bottom:4px; border-radius:8px;">
                    <span style="font-size:12px; color:var(--content-text); flex:1;">${s.name}</span>
                    <span style="color:#28a745; font-size:10px; padding:2px 8px; background:rgba(40,167,69,0.1); border-radius:20px; font-weight:600;">有効</span>
                    <button onclick="Swal.close(); unassignSkill(${s.assignment_id}, ${accountId})" style="font-size:10px; padding:2px 8px; background:#fff; border:1px solid rgba(220,53,69,0.3); border-radius:20px; color:#dc3545; cursor:pointer; font-weight:600; transition:all 0.2s;" onmouseover="this.style.background='#dc3545';this.style.color='#fff';" onmouseout="this.style.background='#fff';this.style.color='#dc3545';">無効にする</button>
                </div>
            `)].join('');
        }

        await Swal.fire({
            title: 'ワークフロー / スキル管理',
            html: `
                <div style="text-align:left;">
                    <!-- ユーザー情報 -->
                    <div ${ACC_S.card}>
                        <span ${ACC_S.secTitle}>${account.username}</span>
                        <span style="color:var(--content-text-muted); font-size:12px;">${account.email}</span>
                    </div>

                    <!-- ワークフロー -->
                    <div ${ACC_S.card}>
                        <span ${ACC_S.secTitle}>ワークフロー（関連スキル付き）</span>
                        <div style="max-height:400px; overflow-y:auto; padding:10px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px;">
                            ${wfSectionHTML}
                        </div>
                    </div>

                    ${standaloneSectionHTML ? `
                    <!-- その他のスキル -->
                    <div ${ACC_S.card}>
                        <span ${ACC_S.secTitle}>その他のスキル</span>
                        <div style="max-height:200px; overflow-y:auto; padding:10px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px;">
                            ${standaloneSectionHTML}
                        </div>
                    </div>
                    ` : ''}
                </div>
            `,
            width: '900px',
            showConfirmButton: false,
            customClass: {
                popup: 'swal-wide swal-scrollable-popup',
                htmlContainer: 'swal-scrollable-container'
            },
            didOpen: () => {
                // ボタンのスタイルを調整
                const buttons = document.querySelectorAll('.swal2-popup .btn');
                buttons.forEach(btn => {
                    btn.style.cursor = 'pointer';
                });
            }
        });
    } catch (error) {
        await showAlert('スキル情報の読み込みに失敗しました', 'error');
        console.error('Load assigned skills error:', error);
    }
}

async function assignSkill(accountId, skillId) {
    try {
        await apiRequest('/api/admin/assign-skill', {
            method: 'POST',
            body: JSON.stringify({
                account_id: accountId,
                skill_id: skillId
            })
        });
        await Swal.fire({
            title: '有効化完了',
            text: 'スキルを有効にしました',
            icon: 'success',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
        showAssignModal(accountId); // リロード
        loadAccounts(currentPage); // アカウント一覧も更新
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'スキルの有効化に失敗しました',
            icon: 'error',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
        console.error('Assign skill error:', error);
    }
}

async function unassignSkill(assignmentId, accountId) {
    const result = await Swal.fire({
        title: '無効化の確認',
        text: 'このスキルを無効にしますか？',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: ADMIN_SWAL.danger,
        cancelButtonColor: ADMIN_SWAL.secondary,
        confirmButtonText: '無効',
        cancelButtonText: ADMIN_SWAL.btnClose
    });

    if (result.isConfirmed) {
        try {
            await apiRequest(`/api/admin/assign-skill/${assignmentId}`, {
                method: 'DELETE'
            });
            await Swal.fire({
                title: '無効化完了',
                text: 'スキルを無効にしました',
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            showAssignModal(accountId); // リロード
            loadAccounts(currentPage); // アカウント一覧も更新
        } catch (error) {
            await Swal.fire({
                title: 'エラー',
                text: '無効化に失敗しました',
                icon: 'error',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            console.error('Unassign skill error:', error);
        }
    }
}


async function assignWorkflow(accountId, workflowId) {
    try {
        const resp = await apiRequest('/api/admin/assign-workflow', {
            method: 'POST',
            body: JSON.stringify({ account_id: accountId, workflow_id: workflowId })
        });
        await Swal.fire({
            title: '有効化完了',
            text: `ワークフローの関連スキル ${resp.assigned_skills}件 を有効にしました`,
            icon: 'success',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
        showAssignModal(accountId);
        loadAccounts(currentPage);
    } catch (error) {
        await Swal.fire({ title: 'エラー', text: 'ワークフローの有効化に失敗しました', icon: 'error', confirmButtonText: ADMIN_SWAL.btnClose, confirmButtonColor: ADMIN_SWAL.primary });
        console.error('Assign workflow error:', error);
    }
}

async function unassignWorkflow(workflowId, accountId) {
    const result = await Swal.fire({
        title: '一括無効化の確認',
        text: 'このワークフローの関連スキルをまとめて無効にしますか？',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: ADMIN_SWAL.danger,
        cancelButtonColor: ADMIN_SWAL.secondary,
        confirmButtonText: '一括無効',
        cancelButtonText: ADMIN_SWAL.btnClose
    });
    if (result.isConfirmed) {
        try {
            const resp = await apiRequest(`/api/admin/assign-workflow/${workflowId}/account/${accountId}`, { method: 'DELETE' });
            await Swal.fire({
                title: '無効化完了',
                text: `関連スキル ${resp.removed_skills}件 を無効にしました`,
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            showAssignModal(accountId);
            loadAccounts(currentPage);
        } catch (error) {
            await Swal.fire({ title: 'エラー', text: '無効に失敗しました', icon: 'error', confirmButtonText: ADMIN_SWAL.btnClose, confirmButtonColor: ADMIN_SWAL.primary });
            console.error('Unassign workflow error:', error);
        }
    }
}

// API設定セクションの表示/非表示を切り替える
function toggleApiConfigSection() {
    const typeSelect = document.getElementById('swal-account-type');
    const apiConfigSection = document.getElementById('swal-api-config-section');
    if (typeSelect && apiConfigSection) {
        if (typeSelect.value === 'PARENT') {
            apiConfigSection.style.display = 'none';
        } else {
            apiConfigSection.style.display = 'block';
        }
    }
}

// ページ読み込み時に実行
(async () => {
    initAdminLayout('accounts.html');
    await checkAuth();
    loadAccounts(1);
    loadAllSkills();
    loadAllWorkflows();
})();
