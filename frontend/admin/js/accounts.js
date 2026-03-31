// 管理者 アカウント一覧画面 JavaScript

let accounts = [];
let allSkills = [];
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
        const response = await apiRequest('/api/admin/skills?skip=0&limit=1000');
        allSkills = response.items || response;
    } catch (error) {
        console.error('Load skills error:', error);
    }
}

function renderAccounts() {
    const tbody = document.getElementById('accounts-tbody');

    if (accounts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: rgba(255, 255, 255, 0.6);">アカウントがまだ登録されていません</td></tr>';
        return;
    }

    tbody.innerHTML = accounts.map(account => `
        <tr>
            <td>${account.id}</td>
            <td>${escapeHtmlAdmin(account.username)}</td>
            <td>${escapeHtmlAdmin(account.email)}</td>
            <td>
                <span style="color: ${account.account_type === 'PARENT' ? '#9c27b0' : 'rgba(255, 255, 255, 0.9)'}; font-weight: ${account.account_type === 'PARENT' ? 'bold' : 'normal'};">
                    ${account.account_type === 'PARENT' ? '管理者' : 'ユーザー'}
                </span>
            </td>
            <td>${statusBadgeHtml(account.is_active)}</td>
            <td>
                ${account.account_type === 'CHILD' ? account.skill_count : `<span style="color: rgba(255, 255, 255, 0.5);">-</span>`}
            </td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: rgba(255, 255, 255, 0.7);">今月:</span>
                            <span style="color: rgba(255, 255, 255, 0.9);">${account.executions_this_month || 0}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: rgba(255, 255, 255, 0.7);">全期間:</span>
                            <span style="color: rgba(255, 255, 255, 0.9);">${account.execution_count || 0}</span>
                        </div>
                    </div>
                ` : `<span style="color: rgba(255, 255, 255, 0.5);">-</span>`}
            </td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: rgba(255, 255, 255, 0.7);">今月:</span>
                            <span style="color: rgba(255, 255, 255, 0.9);">${(account.tokens_this_month || 0).toLocaleString()}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: rgba(255, 255, 255, 0.7);">全期間:</span>
                            <span style="color: rgba(255, 255, 255, 0.9);">${(account.total_tokens || 0).toLocaleString()}</span>
                        </div>
                    </div>
                ` : `<span style="color: rgba(255, 255, 255, 0.5);">-</span>`}
            </td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: rgba(255, 255, 255, 0.7);">今月:</span>
                            <span style="color: rgba(255, 255, 255, 0.9);">$${(account.cost_this_month || 0).toFixed(2)}</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: rgba(255, 255, 255, 0.7);">全期間:</span>
                            <span style="color: rgba(255, 255, 255, 0.9);">$${(account.total_cost || 0).toFixed(2)}</span>
                        </div>
                    </div>
                ` : `<span style="color: rgba(255, 255, 255, 0.5);">-</span>`}
            </td>
            <td>
                ${account.account_type === 'CHILD' ? `
                    <div style="display: flex; flex-direction: column; gap: 4px; font-size: 0.85em;">
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: ${account.api_config && account.api_config.openai_api_key ? '#28a745' : 'rgba(255, 255, 255, 0.5)'};">
                                OpenAI: ${account.api_config && account.api_config.openai_api_key ? '✓' : '✗'}
                            </span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: ${account.api_config && account.api_config.gemini_api_key ? '#28a745' : 'rgba(255, 255, 255, 0.5)'};">
                                Gemini: ${account.api_config && account.api_config.gemini_api_key ? '✓' : '✗'}
                            </span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: ${account.api_config && account.api_config.anthropic_api_key ? '#28a745' : 'rgba(255, 255, 255, 0.5)'};">
                                Claude: ${account.api_config && account.api_config.anthropic_api_key ? '✓' : '✗'}
                            </span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <span style="color: rgba(255, 255, 255, 0.7);">
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
                    <span style="color: rgba(255, 255, 255, 0.5);">-</span>
                `}
            </td>
            <td>
                <div class="actions">
                    <button ${account.account_type === 'PARENT' ? 'disabled' : `onclick="showAssignModal(${account.id})"`} title="${account.account_type === 'PARENT' ? '管理者はスキル割り当てできません' : 'スキル割り当て'}" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; ${account.account_type === 'PARENT' ? 'cursor: not-allowed; opacity: 0.5;' : 'cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;'}">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #9c27b0; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m21 4c0-.478-.379-1-1-1h-16c-.62 0-1 .519-1 1v16c0 .621.52 1 1 1h16c.478 0 1-.379 1-1zm-16.5.5h15v15h-15zm6.75 9.25v3.25c0 .53-.47 1-1 1h-3.25c-.53 0-1-.47-1-1v-3.25c0-.53.47-1 1-1h3.25c.53 0 1 .47 1 1zm0-6.75v3.25c0 .53-.47 1-1 1h-3.25c-.53 0-1-.47-1-1v-3.25c0-.53.47-1 1-1h3.25c.53 0 1 .47 1 1zm6.75 0v3.25c0 .53-.47 1-1 1h-3.25c-.53 0-1-.47-1-1v-3.25c0-.53.47-1 1-1h3.25c.53 0 1 .47 1 1z" fill-rule="nonzero"/></svg>
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
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">ユーザー名 <span style="color: #ff6b6b;">*</span></label>
                <input id="swal-account-username" class="swal2-input" type="text" placeholder="例: user01" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">メールアドレス <span style="color: #ff6b6b;">*</span></label>
                <input id="swal-account-email" class="swal2-input" type="email" placeholder="例: user@example.com" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">パスワード <span style="color: #ff6b6b;">*</span></label>
                <input id="swal-account-password" class="swal2-input" type="password" placeholder="パスワードを入力してください" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">アカウントタイプ <span style="color: #ff6b6b;">*</span></label>
                <select id="swal-account-type" class="swal2-select" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;" onchange="toggleApiConfigSection()">
                    <option value="CHILD" selected>子アカウント（ユーザー）</option>
                    <option value="PARENT">親アカウント（管理者）</option>
                </select>
            </div>
            <div id="swal-api-config-section" style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box; padding: 15px; background: rgba(255, 255, 255, 0.05); border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.1);">
                <h4 style="color: rgba(255, 255, 255, 0.9); margin-bottom: 15px; font-size: 16px; border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding-bottom: 8px;">API設定（オプション）</h4>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">OpenAI API Key</label>
                    <input id="swal-account-openai-key" class="swal2-input" type="password" placeholder="sk-..." style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">子アカウント用のOpenAI API Key（オプション）</small>
                </div>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">Gemini API Key</label>
                    <input id="swal-account-gemini-key" class="swal2-input" type="password" placeholder="AIza..." style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">子アカウント用のGemini API Key（オプション）</small>
                </div>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">Anthropic API Key</label>
                    <input id="swal-account-anthropic-key" class="swal2-input" type="password" placeholder="sk-ant-..." style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">子アカウント用のAnthropic API Key（オプション）</small>
                </div>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">レート制限（1時間あたり）</label>
                    <input id="swal-account-rate-limit-hour" class="swal2-input" type="number" min="1" value="100" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">1時間あたりの実行制限回数（デフォルト: 100）</small>
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">レート制限（1日あたり）</label>
                    <input id="swal-account-rate-limit-day" class="swal2-input" type="number" min="1" value="1000" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">1日あたりの実行制限回数（デフォルト: 1000）</small>
                </div>
                <div>
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="checkbox" id="swal-account-api-enabled" checked style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                        <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">API設定を有効にする</span>
                    </label>
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このAPI設定が有効になります</small>
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

    const { value: formValues } = await Swal.fire({
        title: 'アカウントを編集',
        html: `
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">ユーザー名</label>
                <input id="swal-account-username" class="swal2-input" type="text" value="${account.username}" disabled style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%; background: rgba(255, 255, 255, 0.1);">
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">ユーザー名は変更できません</small>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">メールアドレス <span style="color: #ff6b6b;">*</span></label>
                <input id="swal-account-email" class="swal2-input" type="email" placeholder="例: user@example.com" value="${account.email}" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">パスワード（変更する場合のみ入力）</label>
                <input id="swal-account-password" class="swal2-input" type="password" placeholder="変更しない場合は空欄のまま" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">パスワードを変更しない場合は空欄のままにしてください</small>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-account-is-active" ${account.is_active ? 'checked' : ''} style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">有効にする</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このアカウントが有効になります</small>
            </div>
            ${account.account_type === 'CHILD' ? `
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box; padding: 15px; background: rgba(255, 255, 255, 0.05); border-radius: 8px; border: 1px solid rgba(255, 255, 255, 0.1);">
                <h4 style="color: rgba(255, 255, 255, 0.9); margin-bottom: 15px; font-size: 16px; border-bottom: 1px solid rgba(255, 255, 255, 0.1); padding-bottom: 8px;">API設定</h4>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">OpenAI API Key</label>
                    <input id="swal-account-edit-openai-key" class="swal2-input" type="password" placeholder="${account.api_config && account.api_config.openai_api_key ? '設定済み（変更する場合は新しいキーを入力）' : '未設定（設定する場合はキーを入力）'}" value="" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">${account.api_config && account.api_config.openai_api_key ? '現在設定済みです。変更する場合は新しいキーを入力してください。' : '未設定（設定する場合はキーを入力）'}</small>
                </div>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">Gemini API Key</label>
                    <input id="swal-account-edit-gemini-key" class="swal2-input" type="password" placeholder="${account.api_config && account.api_config.gemini_api_key ? '設定済み（変更する場合は新しいキーを入力）' : '未設定（設定する場合はキーを入力）'}" value="" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">${account.api_config && account.api_config.gemini_api_key ? '現在設定済みです。変更する場合は新しいキーを入力してください。' : '未設定（設定する場合はキーを入力）'}</small>
                </div>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">Anthropic API Key</label>
                    <input id="swal-account-edit-anthropic-key" class="swal2-input" type="password" placeholder="${account.api_config && account.api_config.anthropic_api_key ? '設定済み（変更する場合は新しいキーを入力）' : '未設定（設定する場合はキーを入力）'}" value="" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">${account.api_config && account.api_config.anthropic_api_key ? '現在設定済みです。変更する場合は新しいキーを入力してください。' : '未設定（設定する場合はキーを入力）'}</small>
                </div>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">レート制限（1時間あたり）</label>
                    <input id="swal-account-edit-rate-limit-hour" class="swal2-input" type="number" min="1" value="${account.api_config ? (account.api_config.rate_limit_per_hour || 100) : 100}" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">1時間あたりの実行制限回数</small>
                </div>
                <div style="margin-bottom: 15px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">レート制限（1日あたり）</label>
                    <input id="swal-account-edit-rate-limit-day" class="swal2-input" type="number" min="1" value="${account.api_config ? (account.api_config.rate_limit_per_day || 1000) : 1000}" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">1日あたりの実行制限回数</small>
                </div>
                <div>
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="checkbox" id="swal-account-edit-api-enabled" ${account.api_config ? (account.api_config.is_enabled !== false ? 'checked' : '') : 'checked'} style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                        <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">API設定を有効にする</span>
                    </label>
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このAPI設定が有効になります</small>
                </div>
            </div>
            ` : ''}
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
        html: `本当に「<strong>${account.username}</strong>」を削除しますか？<br>この操作は取り消せません。`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: ADMIN_SWAL.danger,
        cancelButtonColor: ADMIN_SWAL.secondary,
        confirmButtonText: '削除',
        cancelButtonText: ADMIN_SWAL.btnClose
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

        // 割り当て可能なスキル（有効なスキルのみ）
        const availableSkills = allSkills.filter(p => !assignedIds.includes(p.id) && p.is_active);

        // 割り当て可能なスキルのHTML
        const availableSkillsHTML = availableSkills.length > 0
            ? availableSkills.map(p => `
                <div class="card" style="padding: 10px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px;">
                    <div style="flex: 1;">
                        <strong style="color: rgba(255, 255, 255, 0.9);">${p.name}</strong>
                        ${p.description ? `<div style="color: rgba(255, 255, 255, 0.6); font-size: 0.9em; margin-top: 4px;">${p.description}</div>` : ''}
                    </div>
                    <button class="btn btn-sm btn-success" onclick="Swal.close(); assignSkill(${accountId}, ${p.id})" style="margin-left: 10px; white-space: nowrap;">割り当て</button>
                </div>
            `).join('')
            : '<p style="text-align: center; color: rgba(255, 255, 255, 0.6); padding: 20px;">割り当て可能なスキルがありません</p>';

        // 割り当て済みスキルのHTML
        const assignedSkillsHTML = assignedSkills.length > 0
            ? assignedSkills.map(p => `
                <div class="card" style="padding: 10px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 8px; ${!p.is_active ? 'opacity: 0.7;' : ''}">
                    <div style="flex: 1;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <strong style="color: rgba(255, 255, 255, 0.9);">${p.name}</strong>
                            ${!p.is_active ? `
                                <span style="display: flex; align-items: center; gap: 4px; color: #dc3545; font-size: 0.85em;">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="#dc3545">
                                        <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                                    </svg>
                                    無効
                                </span>
                            ` : ''}
                        </div>
                        ${p.description ? `<div style="color: rgba(255, 255, 255, 0.6); font-size: 0.9em; margin-top: 4px;">${p.description}</div>` : ''}
                    </div>
                    <button class="btn btn-sm btn-danger" onclick="Swal.close(); unassignSkill(${p.assignment_id}, ${accountId})" style="margin-left: 10px; white-space: nowrap;">解除</button>
                </div>
            `).join('')
            : '<p style="text-align: center; color: rgba(255, 255, 255, 0.6); padding: 20px;">割り当てられているスキルがありません</p>';

        await Swal.fire({
            title: 'スキル割り当て',
            html: `
                <div style="text-align: left; margin-bottom: 20px;">
                    <strong style="color: rgba(255, 255, 255, 0.9);">${account.username} (${account.email})</strong>
                </div>
                <div style="margin-bottom: 20px;">
                    <h4 style="color: rgba(255, 255, 255, 0.9); margin-bottom: 10px; font-size: 16px;">割り当て可能なスキル</h4>
                    <div style="max-height: 300px; overflow-y: auto; padding: 10px; background: rgba(0, 0, 0, 0.2); border-radius: 8px;">
                        ${availableSkillsHTML}
                    </div>
                </div>
                <div>
                    <h4 style="color: rgba(255, 255, 255, 0.9); margin-bottom: 10px; font-size: 16px;">割り当て済みスキル</h4>
                    <div style="max-height: 300px; overflow-y: auto; padding: 10px; background: rgba(0, 0, 0, 0.2); border-radius: 8px;">
                        ${assignedSkillsHTML}
                    </div>
                </div>
            `,
            width: '900px',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary,
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
            title: '割り当て完了',
            text: 'スキルを割り当てました',
            icon: 'success',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
        showAssignModal(accountId); // リロード
        loadAccounts(currentPage); // アカウント一覧も更新
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'スキルの割り当てに失敗しました',
            icon: 'error',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
        console.error('Assign skill error:', error);
    }
}

async function unassignSkill(assignmentId, accountId) {
    const result = await Swal.fire({
        title: '解除の確認',
        text: 'このスキルの割り当てを解除しますか？',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: ADMIN_SWAL.danger,
        cancelButtonColor: ADMIN_SWAL.secondary,
        confirmButtonText: '解除',
        cancelButtonText: ADMIN_SWAL.btnClose
    });

    if (result.isConfirmed) {
        try {
            await apiRequest(`/api/admin/assign-skill/${assignmentId}`, {
                method: 'DELETE'
            });
            await Swal.fire({
                title: '解除完了',
                text: 'スキルの割り当てを解除しました',
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            showAssignModal(accountId); // リロード
            loadAccounts(currentPage); // アカウント一覧も更新
        } catch (error) {
            await Swal.fire({
                title: 'エラー',
                text: '割り当て解除に失敗しました',
                icon: 'error',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            console.error('Unassign skill error:', error);
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
})();
