// 管理者 ワークフロー / スキル管理画面 JavaScript

let skills = [];
let currentPage = 1;
const itemsPerPage = 10;
let totalItems = 0;

// ワークフロー一覧用
let workflows = [];
let wfCurrentPage = 1;
const wfItemsPerPage = 10;
let wfTotalItems = 0;

const AGENT_PROFILE_OPTIONS = ['explore', 'plan', 'implement', 'verification'];

function renderAgentProfileOptions(selected) {
    const none = `<option value="" ${!selected || selected === 'default' ? 'selected' : ''}>未指定</option>`;
    return none + AGENT_PROFILE_OPTIONS.map(v => `<option value="${v}" ${selected === v ? 'selected' : ''}>${v}</option>`).join('');
}

function validateParallelGroupProfiles(groups) {
    for (const grp of groups || []) {
        if ((grp.execution_type || 'serial') !== 'parallel') continue;
        const profiles = new Set((grp.skills || []).map(sk => sk.agent_profile || 'default'));
        if (profiles.size > 1) {
            throw new Error('parallel グループでは mixed agent_profile を許可していません。MVP では同一 profile に揃えてください。');
        }
    }
}

async function loadDashboardStats() {
    try {
        const stats = await apiRequest('/api/admin/dashboard');
        document.getElementById('total-accounts').textContent = stats.total_accounts;
        document.getElementById('total-skills').textContent = stats.total_skills;
        document.getElementById('total-workflows').textContent = stats.total_workflows || 0;
        document.getElementById('total-executions').textContent = stats.total_executions;
    } catch (error) {
        console.error('Dashboard stats error:', error);
    }
}

async function loadSkills(page = 1) {
    try {
        const skip = (page - 1) * itemsPerPage;
        const response = await apiRequest(`/api/admin/skills?skip=${skip}&limit=${itemsPerPage}`);

        skills = response.items || response;
        totalItems = response.total !== undefined ? response.total : (skills.length === itemsPerPage ? page * itemsPerPage + 1 : page * itemsPerPage);

        currentPage = page;
        renderSkills();
        renderPagination();
    } catch (error) {
        showAlert('スキルの読み込みに失敗しました', 'error');
        console.error('Load skills error:', error);
    }
}

function renderSkills() {
    const tbody = document.getElementById('skills-tbody');

    if (skills.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: rgba(255, 255, 255, 0.6);">スキルがまだ登録されていません</td></tr>';
        return;
    }

    tbody.innerHTML = skills.map(skill => {
        const modelDisplay = formatModelDisplay(skill.model_type, null, skill);
        return `
        <tr>
            <td>${skill.id}</td>
            <td>${escapeHtmlAdmin(skill.name)}</td>
            <td>${escapeHtmlAdmin(skill.description || '説明なし')}</td>
            <td>${modelDisplay}</td>
            <td>${statusBadgeHtml(skill.is_active)}</td>
            <td>
                <div style="display: flex; flex-direction: column; gap: 4px;">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        ${skill.allows_file_output ? ADMIN_ICONS.check : ADMIN_ICONS.cross}
                        <span style="color: ${skill.allows_file_output ? '#28a745' : '#dc3545'}; font-weight: ${skill.allows_file_output ? 'bold' : 'normal'};">ファイル出力: ${skill.allows_file_output ? '許可' : '不可'}</span>
                    </div>
                    <div style="display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: 11px; color: rgba(255,255,255,0.8);">
                    </div>
                </div>
            </td>
            <td>
                <div class="actions">
                    <button onclick="viewSkillContent(${skill.id})" title="スキルを表示" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #9c27b0; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m15.985 17.031c-1.479 1.238-3.384 1.985-5.461 1.985-4.697 0-8.509-3.812-8.509-8.508s3.812-8.508 8.509-8.508c4.695 0 8.508 3.812 8.508 8.508 0 2.078-.747 3.984-1.985 5.461l4.749 4.75c.146.146.219.338.219.531 0 .587-.537.75-.75.75-.192 0-.384-.073-.531-.22zm-5.461-13.53c-3.868 0-7.007 3.14-7.007 7.007s3.139 7.007 7.007 7.007c3.866 0 7.007-3.14 7.007-7.007s-3.141-7.007-7.007-7.007zm.741 8.499h-4.5c-.414 0-.75.336-.75.75s.336.75.75.75h4.5c.414 0 .75-.336.75-.75s-.336-.75-.75-.75zm3-2.5h-7.5c-.414 0-.75.336-.75.75s.336.75.75.75h7.5c.414 0 .75-.336.75-.75s-.336-.75-.75-.75zm0-2.5h-7.5c-.414 0-.75.336-.75.75s.336.75.75.75h7.5c.414 0 .75-.336.75-.75s-.336-.75-.75-.75z" fill-rule="nonzero"/></svg>
                    </button>
                    <button onclick="editSkill(${skill.id})" title="編集" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #28a745; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m11.239 15.533c-1.045 3.004-1.238 3.451-1.238 3.84 0 .441.385.627.627.627.272 0 1.108-.301 3.829-1.249zm.888-.888 3.22 3.22 6.408-6.401c.163-.163.245-.376.245-.591 0-.213-.082-.427-.245-.591-.58-.579-1.458-1.457-2.039-2.036-.163-.163-.377-.245-.591-.245-.213 0-.428.082-.592.245zm-3.127-.895c0-.402-.356-.75-.75-.75-2.561 0-2.939 0-5.5 0-.394 0-.75.348-.75.75s.356.75.75.75h5.5c.394 0 .75-.348.75-.75zm5-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75z" fill-rule="nonzero"/></svg>
                    </button>
                    <button onclick="deleteSkill(${skill.id})" title="削除" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #dc3545; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m20.015 6.506h-16v14.423c0 .591.448 1.071 1 1.071h14c.552 0 1-.48 1-1.071 0-3.905 0-14.423 0-14.423zm-5.75 2.494c.414 0 .75.336.75.75v8.5c0 .414-.336.75-.75.75s-.75-.336-.75-.75v-8.5c0-.414.336-.75.75-.75zm-4.5 0c.414 0 .75.336.75.75v8.5c0 .414-.336.75-.75.75s-.75-.336-.75-.75v-8.5c0-.414.336-.75.75-.75zm-.75-5v-1c0-.535.474-1 1-1h4c.526 0 1 .465 1 1v1h5.254c.412 0 .746.335.746.747s-.334.747-.746.747h-16.507c-.413 0-.747-.335-.747-.747s.334-.747.747-.747zm4.5 0v-.5h-3v.5z" fill-rule="nonzero"/></svg>
                    </button>
                    <button onclick="manageWorkflowsForSkill(${skill.id})" title="ワークフロー/Skillを編集" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <img src="../img/iconmonstr-apps-filled.svg" alt="WF" style="width: 20px; height: 20px; filter: invert(58%) sepia(86%) saturate(470%) hue-rotate(210deg) brightness(95%) contrast(90%);">
                    </button>
                </div>
            </td>
        </tr>
        `;
    }).join('');
}

function renderPagination() {
    renderAdminPagination('pagination-container', currentPage, totalItems, itemsPerPage, 'loadSkills');
}

// formatJSON は admin-common.js で定義済み

async function showCreateModal() {
    const { value: formValues } = await Swal.fire({
        title: 'スキルを作成',
        html: `
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">スキル名 <span style="color: #ff6b6b;">*</span></label>
                <input id="swal-skill-name" class="swal2-input" placeholder="例: 記事要約スキル" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">説明</label>
                <textarea id="swal-skill-description" class="swal2-textarea" placeholder="このスキルの用途や説明を入力してください" style="min-height: 80px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;"></textarea>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">AIモデル <span style="color: #ff6b6b;">*</span></label>
                <select id="swal-skill-model" class="swal2-select" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <optgroup label="OpenAI">
                        <option value="gpt-5.4" selected>GPT-5.4 NEW</option>
                        <option value="gpt-5.4-mini">GPT-5.4 Mini NEW</option>
                        <option value="gpt-5.4-pro">GPT-5.4 Pro NEW</option>
                        <option value="gpt-5.4-thinking">GPT-5.4 Thinking NEW</option>
                        <option value="gpt-5.2">GPT-5.2</option>
                        <option value="gpt-5.2-pro">GPT-5.2 Pro</option>
                        <option value="gpt-5.2-thinking">GPT-5.2 Thinking</option>
                        <option value="o4-mini">o4-mini（推論コスパ）</option>
                    </optgroup>
                    <optgroup label="Gemini">
                        <option value="gemini-3.1-pro-preview">Gemini 3.1 Pro NEW</option>
                        <option value="gemini-3.1-pro-preview-deep-think">Gemini 3.1 Pro Deep Think NEW</option>
                        <option value="gemini-3-pro-preview">Gemini 3.0 Pro</option>
                        <option value="gemini-3-pro-preview-deep-think">Gemini 3.0 Pro Deep Think</option>
                        <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                        <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
                    </optgroup>
                    <optgroup label="Claude">
                        <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
                        <option value="claude-sonnet-4-6-thinking">Claude Sonnet 4.6 Thinking</option>
                        <option value="claude-opus-4-6">Claude Opus 4.6</option>
                        <option value="claude-opus-4-6-thinking">Claude Opus 4.6 Thinking</option>
                        <option value="claude-haiku-4-5">Claude Haiku 4.5</option>
                    </optgroup>
                </select>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">Agent Profile</label>
                <select id="swal-default-agent-profile" class="swal2-select" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    ${renderAgentProfileOptions('default')}
                </select>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">Explore=調査 / Plan=設計 / Implement=実装 / Verification=検証</small>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">スキル内容 <span style="color: #ff6b6b;">*</span></label>
                <textarea id="swal-skill-content" class="swal2-textarea" placeholder="スキル内容を入力してください。&#10;変数は {{variable_name}} の形式で記述できます。&#10;例: {{article_text}} を要約してください。" required style="min-height: 200px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;"></textarea>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">変数の例: {{article_text}}, {{input}}, {{query}} など</small>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">入力スキーマ（JSON形式、オプション）</label>
                <textarea id="swal-skill-schema" class="swal2-textarea" placeholder='{"field_name": {"type": "string", "label": "フィールドラベル", "required": true}}' style="min-height: 120px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%; font-family: monospace; font-size: 12px;"></textarea>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">ユーザー入力フィールドの定義をJSON形式で指定します（省略可能）</small>
            </div>
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-skill-is-active" checked style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">有効にする</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このスキルが有効になり、ユーザーが使用できるようになります</small>
            </div>
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-skill-allows-file-output" style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">ファイル出力を許可する</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このスキルの実行結果をCSV、PDF、DOCXなどの形式で出力できます</small>
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
        didOpen: () => {
            // チェックボックスロジックは削除されました
        },
        preConfirm: () => {
            const name = document.getElementById('swal-skill-name').value.trim();
            const description = document.getElementById('swal-skill-description').value.trim();
            const model = document.getElementById('swal-skill-model').value;
            const content = document.getElementById('swal-skill-content').value.trim();
            const schemaText = document.getElementById('swal-skill-schema').value.trim();
            const isActive = document.getElementById('swal-skill-is-active').checked;
            const allowsFileOutput = document.getElementById('swal-skill-allows-file-output').checked;
            const defaultAgentProfile = document.getElementById('swal-default-agent-profile').value;

            // モデル名からDeep Think設定を判定
            const enableDeepThink = model.includes('deep-think');

            if (!name) {
                Swal.showValidationMessage('スキル名は必須です');
                return false;
            }
            if (!content) {
                Swal.showValidationMessage('スキル内容は必須です');
                return false;
            }

            let inputSchema = null;
            if (schemaText) {
                try {
                    inputSchema = JSON.parse(schemaText);
                } catch {
                    Swal.showValidationMessage('入力スキーマのJSON形式が正しくありません');
                    return false;
                }
            }

            return {
                name,
                description,
                model,
                content,
                inputSchema,
                isActive,
                allowsFileOutput,
                enableDeepThink,
                defaultAgentProfile
            };
        }
    });

    if (formValues) {
        await saveSkill(null, formValues);
    }
}

async function editSkill(id) {
    const skill = skills.find(p => p.id === id);
    if (!skill) return;

    // スキル内容を取得
    let skillContent = '';
    try {
        const data = await apiRequest(`/api/admin/skills/${id}/content`);
        skillContent = data.content;
    } catch (error) {
        await showAlert('スキル内容の読み込みに失敗しました', 'error');
        return;
    }

    const { value: formValues } = await Swal.fire({
        title: 'スキルを編集',
        html: `
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">スキル名 <span style="color: #ff6b6b;">*</span></label>
                <input id="swal-skill-name" class="swal2-input" placeholder="例: 記事要約スキル" value="${skill.name.replace(/"/g, '&quot;')}" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">説明</label>
                <textarea id="swal-skill-description" class="swal2-textarea" placeholder="このスキルの用途や説明を入力してください" style="min-height: 80px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;">${(skill.description || '').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</textarea>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">AIモデル <span style="color: #ff6b6b;">*</span></label>
                <select id="swal-skill-model" class="swal2-select" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <optgroup label="OpenAI">
                        <option value="gpt-5.4" ${skill.model_type === 'gpt-5.4' ? 'selected' : ''}>GPT-5.4 NEW</option>
                        <option value="gpt-5.4-mini" ${skill.model_type === 'gpt-5.4-mini' ? 'selected' : ''}>GPT-5.4 Mini NEW</option>
                        <option value="gpt-5.4-pro" ${skill.model_type === 'gpt-5.4-pro' ? 'selected' : ''}>GPT-5.4 Pro NEW</option>
                        <option value="gpt-5.4-thinking" ${skill.model_type === 'gpt-5.4-thinking' ? 'selected' : ''}>GPT-5.4 Thinking NEW</option>
                        <option value="gpt-5.2" ${skill.model_type === 'gpt-5.2' ? 'selected' : ''}>GPT-5.2</option>
                        <option value="gpt-5.2-pro" ${skill.model_type === 'gpt-5.2-pro' ? 'selected' : ''}>GPT-5.2 Pro</option>
                        <option value="gpt-5.2-thinking" ${skill.model_type === 'gpt-5.2-thinking' ? 'selected' : ''}>GPT-5.2 Thinking</option>
                        <option value="o4-mini" ${skill.model_type === 'o4-mini' ? 'selected' : ''}>o4-mini（推論コスパ）</option>
                    </optgroup>
                    <optgroup label="Gemini">
                        <option value="gemini-3.1-pro-preview" ${skill.model_type === 'gemini-3.1-pro-preview' && !skill.enable_deep_think ? 'selected' : ''}>Gemini 3.1 Pro NEW</option>
                        <option value="gemini-3.1-pro-preview-deep-think" ${(skill.model_type === 'gemini-3.1-pro-preview' && skill.enable_deep_think) || (skill.model_type || '').includes('gemini-3.1') && (skill.model_type || '').includes('deep-think') ? 'selected' : ''}>Gemini 3.1 Pro Deep Think NEW</option>
                        <option value="gemini-3-pro-preview" ${skill.model_type === 'gemini-3-pro-preview' && !skill.enable_deep_think ? 'selected' : ''}>Gemini 3.0 Pro</option>
                        <option value="gemini-3-pro-preview-deep-think" ${(skill.model_type === 'gemini-3-pro-preview' && skill.enable_deep_think) || (skill.model_type || '').includes('gemini-3-pro') && (skill.model_type || '').includes('deep-think') ? 'selected' : ''}>Gemini 3.0 Pro Deep Think</option>
                        <option value="gemini-2.5-pro" ${skill.model_type === 'gemini-2.5-pro' ? 'selected' : ''}>Gemini 2.5 Pro</option>
                        <option value="gemini-2.5-flash" ${skill.model_type === 'gemini-2.5-flash' ? 'selected' : ''}>Gemini 2.5 Flash</option>
                    </optgroup>
                    <optgroup label="Claude">
                        <option value="claude-sonnet-4-6" ${skill.model_type === 'claude-sonnet-4-6' ? 'selected' : ''}>Claude Sonnet 4.6</option>
                        <option value="claude-sonnet-4-6-thinking" ${skill.model_type === 'claude-sonnet-4-6-thinking' ? 'selected' : ''}>Claude Sonnet 4.6 Thinking</option>
                        <option value="claude-opus-4-6" ${skill.model_type === 'claude-opus-4-6' ? 'selected' : ''}>Claude Opus 4.6</option>
                        <option value="claude-opus-4-6-thinking" ${skill.model_type === 'claude-opus-4-6-thinking' ? 'selected' : ''}>Claude Opus 4.6 Thinking</option>
                        <option value="claude-haiku-4-5" ${skill.model_type === 'claude-haiku-4-5' ? 'selected' : ''}>Claude Haiku 4.5</option>
                    </optgroup>
                </select>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">Agent Profile</label>
                <select id="swal-default-agent-profile" class="swal2-select" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    ${renderAgentProfileOptions(skill.default_agent_profile || 'default')}
                </select>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">Explore=調査 / Plan=設計 / Implement=実装 / Verification=検証</small>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">スキル内容 <span style="color: #ff6b6b;">*</span></label>
                <textarea id="swal-skill-content" class="swal2-textarea" placeholder="スキル内容を入力してください。&#10;変数は {{variable_name}} の形式で記述できます。&#10;例: {{article_text}} を要約してください。" required style="min-height: 200px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;">${skillContent.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</textarea>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">変数の例: {{article_text}}, {{input}}, {{query}} など</small>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">入力スキーマ（JSON形式、オプション）</label>
                <textarea id="swal-skill-schema" class="swal2-textarea" placeholder='{"field_name": {"type": "string", "label": "フィールドラベル", "required": true}}' style="min-height: 120px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%; font-family: monospace; font-size: 12px;">${skill.input_schema ? formatJSON(skill.input_schema).replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''}</textarea>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">ユーザー入力フィールドの定義をJSON形式で指定します（省略可能）</small>
            </div>
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-skill-is-active" ${skill.is_active ? 'checked' : ''} style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">有効にする</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このスキルが有効になり、ユーザーが使用できるようになります</small>
            </div>
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-skill-allows-file-output" style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;" ${skill.allows_file_output ? 'checked' : ''}>
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">ファイル出力を許可する</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このスキルの実行結果をCSV、PDF、DOCXなどの形式で出力できます</small>
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
        didOpen: () => {
            // チェックボックスロジックは削除されました
        },
        preConfirm: () => {
            const name = document.getElementById('swal-skill-name').value.trim();
            const description = document.getElementById('swal-skill-description').value.trim();
            const model = document.getElementById('swal-skill-model').value;
            const content = document.getElementById('swal-skill-content').value.trim();
            const schemaText = document.getElementById('swal-skill-schema').value.trim();
            const isActive = document.getElementById('swal-skill-is-active').checked;
            const allowsFileOutput = document.getElementById('swal-skill-allows-file-output').checked;
            const defaultAgentProfile = document.getElementById('swal-default-agent-profile').value;

            // モデル名からDeep Think設定を判定
            const enableDeepThink = model.includes('deep-think');

            if (!name) {
                Swal.showValidationMessage('スキル名は必須です');
                return false;
            }
            if (!content) {
                Swal.showValidationMessage('スキル内容は必須です');
                return false;
            }

            let inputSchema = null;
            if (schemaText) {
                try {
                    inputSchema = JSON.parse(schemaText);
                } catch {
                    Swal.showValidationMessage('入力スキーマのJSON形式が正しくありません');
                    return false;
                }
            }

            return {
                name,
                description,
                model,
                content,
                inputSchema,
                isActive,
                allowsFileOutput,
                enableDeepThink,
                defaultAgentProfile
            };
        }
    });

    if (formValues) {
        await saveSkill(id, formValues);
    }
}

async function saveSkill(id, formValues) {
    const data = {
        name: formValues.name,
        description: formValues.description,
        model_type: formValues.model,
        content: formValues.content,
        input_schema: formValues.inputSchema,
        is_active: formValues.isActive,
        allows_file_output: formValues.allowsFileOutput,
        enable_deep_think: formValues.enableDeepThink,
        default_agent_profile: formValues.defaultAgentProfile
    };

    try {
        if (id) {
            // 更新
            await apiRequest(`/api/admin/skills/${id}`, {
                method: 'PATCH',
                body: JSON.stringify(data)
            });
            await Swal.fire({
                title: '更新完了',
                text: 'スキルを更新しました',
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            loadSkills(currentPage);
        } else {
            // 作成
            await apiRequest('/api/admin/skills', {
                method: 'POST',
                body: JSON.stringify(data)
            });
            await Swal.fire({
                title: '作成完了',
                text: 'スキルを作成しました',
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            loadSkills(1);
        }
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'スキルの保存に失敗しました',
            icon: 'error',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
        console.error('Save skill error:', error);
    }
}

async function viewSkillContent(id) {
    try {
        const data = await apiRequest(`/api/admin/skills/${id}/content`);
        const contentHTML = `
            <div style="text-align: left; max-height: 70vh; overflow-y: auto;">
                <div style="background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.1); padding: 15px; border-radius: 8px; white-space: pre-wrap; word-wrap: break-word; font-family: monospace; font-size: 13px; line-height: 1.6; color: rgba(255, 255, 255, 0.9);">${data.content}</div>
            </div>
        `;

        await Swal.fire({
            title: 'スキル内容',
            html: contentHTML,
            width: '900px',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary,
            customClass: {
                popup: 'swal-wide swal-scrollable-popup',
                htmlContainer: 'swal-scrollable-container'
            }
        });
    } catch (error) {
        await showAlert('スキル内容の読み込みに失敗しました', 'error');
    }
}

async function deleteSkill(id) {
    const skill = skills.find(p => p.id === id);
    if (!skill) return;

    const result = await Swal.fire({
        title: '削除の確認',
        html: `本当に「<strong>${skill.name}</strong>」を削除しますか？<br>この操作は取り消せません。`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: ADMIN_SWAL.danger,
        cancelButtonColor: ADMIN_SWAL.secondary,
        confirmButtonText: '削除',
        cancelButtonText: ADMIN_SWAL.btnClose
    });

    if (result.isConfirmed) {
        try {
            await apiRequest(`/api/admin/skills/${id}`, {
                method: 'DELETE'
            });
            await Swal.fire({
                title: '削除完了',
                text: 'スキルを削除しました',
                icon: 'success',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            loadSkills(currentPage);
        } catch (error) {
            await Swal.fire({
                title: 'エラー',
                text: 'スキルの削除に失敗しました',
                icon: 'error',
                confirmButtonText: ADMIN_SWAL.btnClose,
                confirmButtonColor: ADMIN_SWAL.primary
            });
            console.error('Delete skill error:', error);
        }
    }
}

async function toggleSkillStatus(id, isActive) {
    try {
        await apiRequest(`/api/admin/skills/${id}`, {
            method: 'PATCH',
            body: JSON.stringify({ is_active: isActive })
        });
        await showAlert(`スキルを${isActive ? '有効' : '無効'}にしました`, 'success');
        loadSkills(currentPage);
    } catch (error) {
        await showAlert('ステータスの更新に失敗しました', 'error');
        console.error('Toggle skill status error:', error);
        // エラー時は元に戻すために再読み込み
        loadSkills(currentPage);
    }
}

async function manageWorkflowsForSkill(skillId) {
    const skill = skills.find(p => p.id === skillId);
    if (!skill) return;

    let workflowsForPrompt = [];
    let allWorkflows = [];

    const { value: formValues } = await Swal.fire({
        title: 'ワークフロー / Skill を編集',
        html: `
            <div class="swal-no-scroll" style="max-height:75vh; overflow-y:auto; text-align:left; width:100%; box-sizing:border-box;">
                <div ${WF_SWAL.fld}>
                    <label ${WF_SWAL.lbl}>対象スキル</label>
                    <div style="padding:12px 14px; border-radius:8px; background:rgba(156,39,176,0.08); border:1px solid rgba(156,39,176,0.25);">
                        <div style="font-size:14px; font-weight:bold; color:rgba(255,255,255,0.95);">${_wfbEsc(skill.name)}</div>
                        <div style="font-size:13px; color:rgba(255,255,255,0.55); margin-top:4px;">ID: ${skill.id} / ${_wfbEsc(skill.model_type || '')}</div>
                    </div>
                </div>

                <div ${WF_SWAL.flowWrap}>
                    <span ${WF_SWAL.secTitle}>既存ワークフローへの所属</span>
                    <small ${WF_SWAL.hint}>含めるワークフローにチェックを付けます。外すとそのワークフローから除外されます（保存で反映）。</small>
                    <div id="wf-membership-container" style="margin-top:10px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:8px 10px; max-height:240px; overflow-y:auto; background:rgba(0,0,0,0.12);">
                        <div style="text-align:center; padding:14px; color:rgba(255,255,255,0.55); font-size:13px;">読み込み中...</div>
                    </div>
                </div>
            </div>
        `,
        focusConfirm: false,
        showCancelButton: true,
        confirmButtonText: '保存',
        cancelButtonText: ADMIN_SWAL.btnClose,
        confirmButtonColor: ADMIN_SWAL.primary,
        cancelButtonColor: ADMIN_SWAL.secondary,
        width: '800px',
        didOpen: async () => {
            const container = document.getElementById('wf-membership-container');
            try {
                const resp = await apiRequest('/api/admin/workflows?skip=0&limit=1000');
                allWorkflows = resp.items || [];

                // それぞれのWorkflowの詳細を取得して、このスキルが含まれているか判定
                const details = [];
                for (const wf of allWorkflows) {
                    try {
                        const d = await apiRequest(`/api/admin/workflows/${wf.id}`);
                        details.push(d);
                    } catch (e) {
                        console.error('Failed to load workflow detail', wf.id, e);
                    }
                }

                workflowsForPrompt = details;

                if (!details.length) {
                    container.innerHTML = '<div style="text-align:center; padding:14px; color:rgba(255,255,255,0.55); font-size:13px;">ワークフローがまだ登録されていません</div>';
                    return;
                }

                container.innerHTML = details
                    .map(wf => {
                        const hasPrompt = (wf.skills || []).some(s => s.skill_id === skillId);
                        return `
                            <label class="wf-membership-row">
                                <input type="checkbox" class="wf-membership-checkbox" data-workflow-id="${wf.id}" ${hasPrompt ? 'checked' : ''} style="margin-top:2px;">
                                <div style="flex:1; min-width:0;">
                                    <div style="font-size:13px; font-weight:bold; color:rgba(255,255,255,0.9); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${_wfbEsc(wf.name)}</div>
                                    <div style="font-size:12px; color:rgba(255,255,255,0.55); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                                        ID: ${wf.id} / ${wf.is_active ? '有効' : '無効'}
                                    </div>
                                </div>
                            </label>
                        `;
                    })
                    .join('');
            } catch (e) {
                console.error('Load workflows for skill error:', e);
                container.innerHTML = '<div style="text-align:center; padding:14px; color:rgba(255,255,255,0.55); font-size:13px;">ワークフローの取得に失敗しました</div>';
            }
        },
        preConfirm: () => {
            // 既存ワークフローでの所属変更
            const membershipChanges = [];
            const checkboxes = document.querySelectorAll('.wf-membership-checkbox');
            for (const cb of checkboxes) {
                const wfId = parseInt(cb.dataset.workflowId, 10);
                const wfDetail = workflowsForPrompt.find(w => w.id === wfId);
                if (!wfDetail) continue;
                const currentlyHas = (wfDetail.skills || []).some(s => s.skill_id === skillId);
                const wantHas = cb.checked;
                if (currentlyHas === wantHas) continue; // 変更なし

                // 新しいskills配列を作る
                let newSkills = (wfDetail.skills || []).filter(s => s.skill_id !== skillId);
                if (wantHas) {
                    // 末尾に追加
                    const newOrder = newSkills.length + 1;
                    newSkills.push({
                        skill_id: skillId,
                        skill_order: newOrder,
                        skill_name: `Step ${newOrder}: ${skill.name}`
                    });
                }
                // skill_order を振り直す
                newSkills = newSkills
                    .sort((a, b) => a.skill_order - b.skill_order)
                    .map((s, idx) => ({
                        skill_id: s.skill_id,
                        skill_order: idx + 1,
                        skill_name: s.skill_name || `Step ${idx + 1}`
                    }));

                membershipChanges.push({
                    workflow_id: wfId,
                    skills: newSkills
                });
            }

            return {
                membershipChanges,
                newWorkflow: null
            };
        }
    });

    if (!formValues) return;

    try {
        // 所属更新を反映
        for (const ch of formValues.membershipChanges || []) {
            await apiRequest(`/api/admin/workflows/${ch.workflow_id}/skills`, {
                method: 'PUT',
                body: JSON.stringify({ skills: ch.skills })
            });
        }

        // 新規ワークフロー作成
        if (formValues.newWorkflow) {
            const created = await apiRequest('/api/admin/workflows', {
                method: 'POST',
                body: JSON.stringify({
                    name: formValues.newWorkflow.name,
                    description: formValues.newWorkflow.description,
                    is_active: formValues.newWorkflow.is_active
                })
            });

            // このスキルだけをStep1として紐付け
            await apiRequest(`/api/admin/workflows/${created.id}/skills`, {
                method: 'PUT',
                body: JSON.stringify({
                    skills: [
                        {
                            skill_id: skillId,
                            skill_order: 1,
                            skill_name: `Step 1: ${skill.name}`
                        }
                    ]
                })
            });
        }

        await Swal.fire({
            title: '更新完了',
            text: 'ワークフロー/Skill設定を更新しました',
            icon: 'success',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'ワークフロー/Skill設定の更新に失敗しました',
            icon: 'error',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
        console.error('manageWorkflowsForSkill error:', error);
    }
}

async function showCreateWorkflowFromSkills() {
    const WF_CONN = _wfFlowConnectorHtml();
    const WF_LEADER_START = `
        <div style="display:flex; align-items:center; gap:10px; padding:12px 16px; background:rgba(156,39,176,0.12); border:1px solid rgba(156,39,176,0.3); border-radius:8px; margin-bottom:4px;">
            <div style="width:28px; height:28px; border-radius:50%; background:rgba(255,255,255,0.2); display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">&#9711;</div>
            <div>
                <div style="font-size:13px; font-weight:bold; color:#ce93d8;">Leader: タスク振り分け</div>
                <div style="font-size:13px; color:rgba(255,255,255,0.6);" id="wf-create-wf-subtitle">新規ワークフロー</div>
            </div>
        </div>`;
    const WF_LEADER_END = `
        <div style="display:flex; align-items:center; gap:10px; padding:12px 16px; background:rgba(156,39,176,0.12); border:1px solid rgba(156,39,176,0.3); border-radius:8px; margin-top:4px;">
            <div style="width:28px; height:28px; border-radius:50%; background:rgba(255,255,255,0.2); display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">&#9711;</div>
            <div>
                <div style="font-size:13px; font-weight:bold; color:#ce93d8;">Leader: 結果統合</div>
                <div style="font-size:13px; color:rgba(255,255,255,0.6);">全結果を統合して最終出力を生成</div>
            </div>
        </div>`;

    const { value: formValues } = await Swal.fire({
        title: 'ワークフローを作成',
        html: `
            <div class="swal-no-scroll" style="max-height: 75vh; overflow-y: auto; text-align: left; width: 100%; box-sizing: border-box;">
                <div ${WF_SWAL.fld}>
                    <label ${WF_SWAL.lbl}>ワークフロー名 <span style="color: #ff6b6b;">*</span></label>
                    <input id="swal-wf-name" type="text" ${WF_SWAL.inp} placeholder="例: 記事作成ワークフロー">
                </div>
                <div ${WF_SWAL.fld}>
                    <label ${WF_SWAL.lbl}>説明</label>
                    <textarea id="swal-wf-description" rows="4" ${WF_SWAL.txa(100)} placeholder="このワークフローの用途や流れを説明してください"></textarea>
                </div>
                <div ${WF_SWAL.fld}>
                    <label style="display: flex; align-items: center; cursor: pointer;">
                        <input type="checkbox" id="swal-wf-is-active" checked style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                        <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">有効なワークフローとして作成する</span>
                    </label>
                    <small ${WF_SWAL.hint}>チェックすると一覧で有効として表示されます。</small>
                </div>

                <div ${WF_SWAL.leaderCard}>
                    <span ${WF_SWAL.secTitle}>親スキル（Parent Skill）</span>
                    <small style="color: rgba(255, 255, 255, 0.6); display: block; margin: 0 0 12px 0; font-size: 13px;">全ステップ完了後に結果を統合し、最終出力を生成するスキルです。</small>
                    <input type="hidden" id="swal-parent-mode" value="required">
                    <input type="hidden" id="swal-supervisor-mode" value="disabled">
                    <div ${WF_SWAL.fld}>
                        <label ${WF_SWAL.lbl}>リーダー用スキル名 <span style="color: #ff6b6b;">*</span></label>
                        <input id="swal-leader-name" type="text" ${WF_SWAL.inp} placeholder="例: 記事統合スキル">
                    </div>
                    <div ${WF_SWAL.fld}>
                        <label ${WF_SWAL.lbl}>説明</label>
                        <textarea id="swal-leader-description" rows="4" ${WF_SWAL.txa(100)} placeholder="親スキルの説明"></textarea>
                    </div>
                    <div ${WF_SWAL.fld}>
                        <label ${WF_SWAL.lbl}>AIモデル <span style="color: #ff6b6b;">*</span></label>
                        <select id="swal-leader-model" ${WF_SWAL.sel}>
                            <optgroup label="OpenAI">
                                <option value="gpt-5.4" selected>GPT-5.4 NEW</option>
                                <option value="gpt-5.4-pro">GPT-5.4 Pro NEW</option>
                                        <option value="gpt-5.2">GPT-5.2</option>
                                <option value="gpt-5.2-pro">GPT-5.2 Pro</option>
                                <option value="gpt-5.1">GPT-5.1</option>
                                <option value="gpt-5-pro">GPT-5 Pro</option>
                            </optgroup>
                            <optgroup label="Gemini">
                                <option value="gemini-3.1-pro-preview">Gemini 3.1 Pro NEW</option>
                                <option value="gemini-3.1-pro-preview-deep-think">Gemini 3.1 Pro Deep Think NEW</option>
                                <option value="gemini-3-pro-preview">Gemini 3.0 Pro</option>
                            </optgroup>
                            <optgroup label="Claude">
                                <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
                                <option value="claude-sonnet-4-6-thinking">Claude Sonnet 4.6 Thinking</option>
                                <option value="claude-opus-4-6">Claude Opus 4.6</option>
                                <option value="claude-opus-4-6-thinking">Claude Opus 4.6 Thinking</option>
                                <option value="claude-haiku-4-5">Claude Haiku 4.5</option>
                            </optgroup>
                        </select>
                    </div>
                    <input type="hidden" id="swal-leader-content" value="(自動生成)">
                    <small style="color: rgba(255,255,255,0.5); display:block; margin: 0 0 8px; font-size:11px;">リーダースキル内容はワークフロー名・説明から自動生成されます</small>
                    <div style="display: flex; gap: 8px; text-align: left; margin-bottom: 0;">
                        <label style="display: flex; align-items: center; cursor: pointer;">
                            <input type="checkbox" id="swal-leader-deep-think" checked style="margin-right: 6px; width: 16px; height: 16px; cursor: pointer;">
                            <span style="font-size: 13px; color: rgba(255, 255, 255, 0.9);">Deep Think</span>
                        </label>
                    </div>
                </div>

                <div ${WF_SWAL.flowWrap}>
                    <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:12px; flex-wrap:wrap;">
                        <div style="flex:1; min-width:200px;">
                            <span ${WF_SWAL.secTitle}>実行フロー（作成）</span>
                            <small ${WF_SWAL.hint}>編集の「実行フロー（編集）」と同じです。右上の「+ グループ追加」でグループを増やし、各グループに Skill を追加します。グループ・Skill は ≡ で並べ替えできます。</small>
                        </div>
                        <button type="button" onclick="wfCreateAddGroup()" style="padding:8px 16px; background:rgba(40,167,69,0.9); border:1px solid rgba(72,180,97,0.65); border-radius:8px; color:#fff; cursor:pointer; font-size:13px; font-weight:600; flex-shrink:0; white-space:nowrap; align-self:flex-start;">+ グループ追加</button>
                    </div>
                    <div style="display:flex; flex-direction:column; gap:0;">
                        ${WF_LEADER_START}
                        ${WF_CONN}
                        <div id="wf-create-groups-container"></div>
                        ${WF_CONN}
                        ${WF_LEADER_END}
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
        didOpen: async () => {
            _wfCreateStepUid = 0;
            _wfCreateGroups = [];
            _wfCreateUsableSkills = [];

            const nameInput = document.getElementById('swal-wf-name');
            const subEl = document.getElementById('wf-create-wf-subtitle');
            if (nameInput && subEl) {
                const syncSub = () => { subEl.textContent = nameInput.value.trim() || '新規ワークフロー'; };
                nameInput.addEventListener('input', syncSub);
                syncSub();
            }

            try {
                const resp = await apiRequest('/api/admin/skills?skip=0&limit=1000');
                const allSkills = resp.items || [];
                _wfCreateUsableSkills = allSkills.filter((p) => p.is_active !== false && !p.deleted_at);
            } catch (e) {
                console.error('Load skills for workflow create error:', e);
            }

            wfCreateRenderGroups();
        },
        preConfirm: () => {
            const name = document.getElementById('swal-wf-name').value.trim();
            const description = document.getElementById('swal-wf-description').value.trim();
            const isActive = document.getElementById('swal-wf-is-active').checked;

            // 親スキル情報
            const leaderName = document.getElementById('swal-leader-name').value.trim();
            const leaderDescription = document.getElementById('swal-leader-description').value.trim();
            const leaderModel = document.getElementById('swal-leader-model').value;
            const leaderContent = document.getElementById('swal-leader-content').value.trim();
            const leaderDeepThink = document.getElementById('swal-leader-deep-think').checked;

            if (!name) {
                Swal.showValidationMessage('ワークフロー名は必須です');
                return false;
            }

            if (!leaderName) {
                Swal.showValidationMessage('リーダー用スキル名は必須です');
                return false;
            }

            // リーダースキル内容は自動生成のため検証不要

            wfCreateSyncGroupFieldsFromDom();
            if (!_wfCreateGroups.length) {
                Swal.showValidationMessage('右上の「+ グループ追加」で少なくとも1つのグループを追加してください');
                return false;
            }
            const totalSkills = _wfCreateGroups.reduce((n, g) => n + g.skills.length, 0);
            if (!totalSkills) {
                Swal.showValidationMessage('いずれかのグループに Skill を1つ以上追加してください');
                return false;
            }

            const groups = _wfCreateGroups.map((g, gi) => ({
                group_order: gi + 1,
                group_name: g.group_name,
                execution_type: g.execution_type || 'serial',
                condition_expression: g.condition_expression || null,
                skip_on_condition_fail: g.skip_on_condition_fail !== false,
                supervisor_prompt: g.supervisor_prompt || '',
                supervisor_model: g.supervisor_model || '',
                dynamic_mode: g.dynamic_mode || 'static',
                judge_prompt: g.judge_prompt || '',
                judge_model: g.judge_model || '',
                skills: g.skills.map((sk, si) => ({
                    skill_id: sk.skill_id,
                    order_in_group: si + 1,
                    skill_name: sk.skill_name || `Step ${si + 1}`,
                    on_error: sk.on_error || 'stop',
                    max_retries: parseInt(sk.max_retries) || 0,
                    retry_delay_seconds: parseInt(sk.retry_delay_seconds) || 5,
                    output_key: sk.output_key || null,
                    input_mapping: sk.input_mapping || null,
                    quality_gate_type: sk.quality_gate_type || 'disabled',
                    quality_gate_prompt: sk.quality_gate_prompt || '',
                    max_reflection_loops: parseInt(sk.max_reflection_loops) || 0,
                })),
            }));

            const supervisorMode = document.getElementById('swal-supervisor-mode')?.value || 'disabled';
            return {
                name,
                description,
                isActive,
                groups,
                supervisor_mode: supervisorMode,
                leaderPrompt: {
                    name: leaderName,
                    description: leaderDescription,
                    model_type: leaderModel,
                    content: leaderContent,
                    enable_deep_think: leaderDeepThink,
                }
            };
        }
    });

    if (!formValues) return;

    try {
        // 新しいAPI（親スキル＋子スキルを一括作成）を使用
        const created = await apiRequest('/api/admin/workflows/with-parent-skill', {
            method: 'POST',
            body: JSON.stringify({
                name: formValues.name,
                description: formValues.description,
                is_active: formValues.isActive,
                parent_skill: formValues.leaderPrompt,
                supervisor_mode: formValues.supervisor_mode || 'disabled',
                groups: formValues.groups
            })
        });

        await Swal.fire({
            title: '作成完了',
            text: `ワークフロー「${formValues.name}」を作成しました`,
            icon: 'success',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });

        // ワークフロー一覧を再読み込み
        await loadWorkflows(wfCurrentPage);
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'ワークフローの作成に失敗しました',
            icon: 'error',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary
        });
        console.error('showCreateWorkflowFromSkills error:', error);
    }
}

function wfCreateSyncGroupFieldsFromDom() {
    _wfCreateGroups.forEach((g, gi) => {
        const n = document.getElementById(`wf-create-gname-${gi}`);
        if (n) g.group_name = n.value;
        const t = document.getElementById(`wf-create-gtype-${gi}`);
        if (t) g.execution_type = t.value;
    });
}

function wfCreateDestroySortables() {
    const gc = document.getElementById('wf-create-groups-container');
    if (gc && gc._wfSortable) {
        gc._wfSortable.destroy();
        gc._wfSortable = null;
    }
    document.querySelectorAll('[id^="wf-create-skills-"]').forEach((el) => {
        if (el._wfSortable) {
            el._wfSortable.destroy();
            el._wfSortable = null;
        }
    });
}

function wfCreateRenderGroups() {
    const container = document.getElementById('wf-create-groups-container');
    if (!container) return;

    wfCreateDestroySortables();

    const conn = _wfFlowConnectorHtml();
    const opts = !_wfCreateUsableSkills.length
        ? '<option value="">スキルがありません</option>'
        : '<option value="">+ スキル追加...</option>' + _wfCreateUsableSkills.map((p) =>
            `<option value="${p.id}">${_wfbEsc(p.name)} (${_wfbEsc(p.model_type || '')})</option>`
        ).join('');

    if (!_wfCreateGroups.length) {
        container.innerHTML = '<div style="text-align:center; padding:24px 12px; color:rgba(255,255,255,0.55); font-size:13px;">グループがありません。右上の「+ グループ追加」から追加してください。</div>';
        return;
    }

    let html = '';
    _wfCreateGroups.forEach((grp, gi) => {
        const gColor = grp.execution_type === 'parallel' ? '#2196f3' : '#ff9800';
        const useParallelLayout = grp.execution_type === 'parallel' && grp.skills.length > 1;

        let skillsHtml = '';
        grp.skills.forEach((sk, si) => {
            const sName = _wfbEsc(sk.skill_name || '');
            const sModel = _wfbEsc(sk.model_type || '');
            const onErr = sk.on_error || 'stop';
            const errBadge = onErr === 'retry' ? '<span style="font-size:10px; color:#ffc107; margin-left:4px;">⟳retry</span>'
                           : onErr === 'skip' ? '<span style="font-size:10px; color:#17a2b8; margin-left:4px;">▷skip</span>' : '';
            const advHtml = `
                <div style="margin-top:6px; padding:6px 8px; background:rgba(0,0,0,0.15); border-radius:4px; font-size:11px;">
                    <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                        <label style="color:rgba(255,255,255,0.7);">Profile:</label>
                        <select onchange="_wfbUpdateSkillField(${gi},${si},'agent_profile',this.value)" style="font-size:11px; padding:2px 4px; background:rgba(0,0,0,0.3); color:#fff; border:1px solid rgba(255,255,255,0.2); border-radius:4px;">
                            ${renderAgentProfileOptions(sk.agent_profile || 'default')}
                        </select>
                        <span style="color:rgba(255,255,255,0.4); font-size:10px; margin-left:4px;">エラー時・品質ゲート・出力キーは自動設定</span>
                    </div>
                </div>`;
            if (useParallelLayout) {
                skillsHtml += `
                <div class="wf-create-skill" data-gi="${gi}" data-si="${si}" style="flex:1; min-width:180px; display:flex; flex-direction:column; gap:4px; padding:10px; background:rgba(0,0,0,0.2); border-radius:6px; border-left:3px solid ${gColor}; cursor:grab;">
                    <div style="display:flex; align-items:flex-start; gap:6px;">
                        <span class="wf-create-skill-drag" style="cursor:grab; opacity:0.45; flex-shrink:0; padding-top:2px;">&#x2261;</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:13px; font-weight:bold; color:rgba(255,255,255,0.9); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${sName}${errBadge}</div>
                            <div style="font-size:12px; color:rgba(255,255,255,0.55);">${sModel}</div>
                        </div>
                        <button type="button" onclick="wfCreateRemoveSkill(${sk._uid})" style="background:none; border:none; color:#ff6b6b; cursor:pointer; font-size:14px; flex-shrink:0;" title="削除">&times;</button>
                    </div>
                    ${advHtml}
                </div>`;
            } else {
                const connector = si > 0
                    ? '<div style="display:flex; justify-content:flex-start; padding:2px 0 2px 20px;"><div style="width:1px; height:10px; background:rgba(255,255,255,0.1);"></div></div>'
                    : '';
                skillsHtml += `${connector}
                <div class="wf-create-skill" data-gi="${gi}" data-si="${si}" style="padding:8px 10px; background:rgba(0,0,0,0.15); border-radius:6px; border-left:3px solid ${gColor}; cursor:grab; ${si > 0 ? 'margin-top:6px;' : ''}">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span class="wf-create-skill-drag" style="cursor:grab; opacity:0.45; flex-shrink:0;">&#x2261;</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:13px; font-weight:bold; color:rgba(255,255,255,0.9);">${sName}${errBadge}</div>
                            <div style="font-size:12px; color:rgba(255,255,255,0.55);">${sModel}</div>
                        </div>
                        <button type="button" onclick="wfCreateRemoveSkill(${sk._uid})" style="background:none; border:none; color:#ff6b6b; cursor:pointer; font-size:14px; flex-shrink:0;" title="削除">&times;</button>
                    </div>
                    ${advHtml}
                </div>`;
            }
        });

        const skillsEmpty = useParallelLayout
            ? '<div style="flex:1; text-align:center; padding:14px; color:rgba(255,255,255,0.55); font-size:13px;">スキルを下のメニューから追加</div>'
            : '<div style="text-align:center; padding:14px; color:rgba(255,255,255,0.55); font-size:13px;">スキルを下のメニューから追加</div>';

        const skillsWrapStyle = useParallelLayout
            ? 'display:flex; flex-wrap:wrap; gap:6px; padding:10px 14px; min-height:52px; align-items:stretch; max-height:280px; overflow-y:auto;'
            : 'padding:8px 14px; min-height:52px; max-height:280px; overflow-y:auto;';

        html += `
            <div class="wf-create-group-slot" data-gi="${gi}">
                <div class="wf-create-group" style="margin:4px 0; border:1px solid ${gColor}33; border-radius:8px; overflow:hidden;">
                    <div style="padding:8px 14px; background:${gColor}15; display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                        <span class="wf-create-group-handle" style="cursor:grab; opacity:0.5; font-size:16px; flex-shrink:0;" title="グループの並べ替え">&#x2261;</span>
                        <select id="wf-create-gtype-${gi}" onchange="wfCreateUpdateGroup(${gi},'type',this.value)" class="swal2-select" style="font-size:13px; font-weight:bold; color:${gColor}; background:${gColor}22; border:1px solid ${gColor}44; padding:4px 10px; border-radius:8px; cursor:pointer; width:auto; max-width:none; margin-top:0; flex-shrink:0;">
                            <option value="serial" ${grp.execution_type === 'serial' ? 'selected' : ''}>直列</option>
                            <option value="parallel" ${grp.execution_type === 'parallel' ? 'selected' : ''}>並列</option>
                        </select>
                        <input type="text" id="wf-create-gname-${gi}" value="${_wfbEsc(grp.group_name)}" onchange="wfCreateUpdateGroup(${gi},'name',this.value)" placeholder="グループ名" class="swal2-input" style="flex:1; min-width:140px; margin-top:0; max-width:none; background:rgba(0,0,0,0.2); font-size:13px;">
                        <button type="button" onclick="wfCreateRemoveGroup(${gi})" style="background:none; border:none; color:#ff6b6b; cursor:pointer; font-size:16px; flex-shrink:0;" title="グループ削除">&times;</button>
                    </div>
                    ${grp.condition_expression ? `<div style="padding:4px 14px; background:rgba(255,193,7,0.08); font-size:11px; color:#ffc107;">条件: ${_wfbEsc(JSON.stringify(grp.condition_expression))}</div>` : ''}
                    <div style="padding:6px 14px; background:rgba(0,0,0,0.08); border-top:1px solid rgba(255,255,255,0.06); font-size:11px;">
                        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                            <label style="color:rgba(255,255,255,0.7);">動的:</label>
                            <select onchange="wfCreateUpdateGroup(${gi},'dynamic_mode',this.value)" style="font-size:11px; padding:2px 4px; background:rgba(0,0,0,0.3); color:#fff; border:1px solid rgba(255,255,255,0.2); border-radius:4px;">
                                <option value="static" ${grp.dynamic_mode === 'static' ? 'selected' : ''}>静的</option>
                                <option value="dynamic" ${grp.dynamic_mode === 'dynamic' ? 'selected' : ''}>動的(プランナー)</option>
                            </select>
                            <span style="color:rgba(255,255,255,0.4); font-size:10px; margin-left:4px;">ジャッジ・SVは自動適用</span>
                        </div>
                    </div>
                    <div id="wf-create-skills-${gi}" style="${skillsWrapStyle}">
                        ${skillsHtml || skillsEmpty}
                    </div>
                    <div style="padding:8px 14px 12px; border-top:1px solid rgba(255,255,255,0.08);">
                        <select id="wf-create-add-skill-${gi}" data-gi="${gi}" onchange="wfCreatePickSkill(this)" class="swal2-select" style="width:100%; margin-top:0; box-sizing:border-box; max-width:100%; font-size:13px;">
                            ${opts}
                        </select>
                    </div>
                </div>
                ${gi < _wfCreateGroups.length - 1 ? conn : ''}
            </div>`;
    });

    container.innerHTML = html;

    if (typeof Sortable === 'undefined') return;

    if (container.querySelector('.wf-create-group-slot')) {
        container._wfSortable = Sortable.create(container, {
            handle: '.wf-create-group-handle',
            animation: 150,
            draggable: '.wf-create-group-slot',
            onEnd: (evt) => {
                const [moved] = _wfCreateGroups.splice(evt.oldIndex, 1);
                _wfCreateGroups.splice(evt.newIndex, 0, moved);
                _wfCreateGroups.forEach((g, i) => { g.group_order = i + 1; });
                wfCreateRenderGroups();
            },
        });
    }

    _wfCreateGroups.forEach((grp, gi) => {
        const el = document.getElementById(`wf-create-skills-${gi}`);
        if (!el || !el.querySelector('.wf-create-skill')) return;
        el._wfSortable = Sortable.create(el, {
            group: 'wfcreate-skills',
            handle: '.wf-create-skill-drag',
            filter: 'button',
            preventOnFilter: false,
            animation: 150,
            onEnd: (evt) => {
                const fromGi = parseInt(evt.from.id.replace('wf-create-skills-', ''), 10);
                const toGi = parseInt(evt.to.id.replace('wf-create-skills-', ''), 10);
                const [moved] = _wfCreateGroups[fromGi].skills.splice(evt.oldIndex, 1);
                _wfCreateGroups[toGi].skills.splice(evt.newIndex, 0, moved);
                _wfCreateGroups.forEach((g) => g.skills.forEach((s, i) => { s.order_in_group = i + 1; }));
                wfCreateRenderGroups();
            },
        });
    });
}

function wfCreateAddGroup() {
    wfCreateSyncGroupFieldsFromDom();
    _wfCreateGroups.push({
        group_order: _wfCreateGroups.length + 1,
        group_name: `グループ ${_wfCreateGroups.length + 1}`,
        execution_type: 'serial',
        condition_expression: null,
        skip_on_condition_fail: true,
        supervisor_prompt: '',
        supervisor_model: '',
        dynamic_mode: 'static',
        judge_prompt: '',
        judge_model: '',
        skills: [],
    });
    wfCreateRenderGroups();
}

function wfCreateRemoveGroup(gi) {
    wfCreateSyncGroupFieldsFromDom();
    _wfCreateGroups.splice(gi, 1);
    _wfCreateGroups.forEach((g, i) => { g.group_order = i + 1; });
    wfCreateRenderGroups();
}

function wfCreateUpdateGroup(gi, field, value) {
    wfCreateSyncGroupFieldsFromDom();
    if (field === 'name') _wfCreateGroups[gi].group_name = value;
    if (field === 'type') _wfCreateGroups[gi].execution_type = value;
    if (field === 'skip_on_condition_fail') _wfCreateGroups[gi].skip_on_condition_fail = value;
    if (field === 'supervisor_prompt') _wfCreateGroups[gi].supervisor_prompt = value;
    if (field === 'supervisor_model') _wfCreateGroups[gi].supervisor_model = value;
    if (field === 'dynamic_mode') _wfCreateGroups[gi].dynamic_mode = value;
    if (field === 'judge_prompt') _wfCreateGroups[gi].judge_prompt = value;
    if (field === 'judge_model') _wfCreateGroups[gi].judge_model = value;
    wfCreateRenderGroups();
}

function wfCreateUpdateSkillField(uid, field, value) {
    for (const g of _wfCreateGroups) {
        const sk = g.skills.find(s => s._uid === uid);
        if (sk) { sk[field] = value; break; }
    }
}

function wfCreatePickSkill(sel) {
    const gi = parseInt(sel.getAttribute('data-gi'), 10);
    const v = parseInt(sel.value, 10);
    if (!v || Number.isNaN(gi)) return;
    const p = _wfCreateUsableSkills.find((x) => x.id === v);
    if (!p) return;
    wfCreateSyncGroupFieldsFromDom();
    _wfCreateGroups[gi].skills.push({
        _uid: ++_wfCreateStepUid,
        skill_id: p.id,
        skill_name: p.name,
        model_type: p.model_type || '',
        order_in_group: _wfCreateGroups[gi].skills.length + 1,
        on_error: 'stop',
        max_retries: 0,
        retry_delay_seconds: 5,
        output_key: '',
        input_mapping: null,
        quality_gate_type: 'disabled',
        quality_gate_prompt: '',
        max_reflection_loops: 0,
    });
    sel.value = '';
    wfCreateRenderGroups();
}

function wfCreateRemoveSkill(uid) {
    wfCreateSyncGroupFieldsFromDom();
    for (const g of _wfCreateGroups) {
        const ix = g.skills.findIndex((s) => s._uid === uid);
        if (ix >= 0) {
            g.skills.splice(ix, 1);
            g.skills.forEach((s, i) => { s.order_in_group = i + 1; });
            break;
        }
    }
    wfCreateRenderGroups();
}

// ==================== ワークフロー一覧 ====================

async function loadWorkflows(page = 1) {
    try {
        const skip = (page - 1) * wfItemsPerPage;
        const response = await apiRequest(`/api/admin/workflows?skip=${skip}&limit=${wfItemsPerPage}`);

        workflows = response.items || [];
        wfTotalItems = response.total || workflows.length;
        wfCurrentPage = page;

        renderWorkflows();
        renderWorkflowsPagination();
    } catch (error) {
        showAlert('ワークフローの読み込みに失敗しました', 'error');
        console.error('Load workflows error:', error);
    }
}

function renderWorkflows() {
    const tbody = document.getElementById('workflows-tbody');
    if (!tbody) return;

    if (!workflows || workflows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: rgba(255, 255, 255, 0.6);">ワークフローがまだ登録されていません</td></tr>';
        return;
    }

    tbody.innerHTML = workflows.map(wf => `
        <tr>
            <td>${wf.id}</td>
            <td>${wf.name}</td>
            <td>${wf.description || '説明なし'}</td>
            <td>${typeof formatModelDisplay === 'function' ? formatModelDisplay(wf.parent_model_type || '', null, {}) : (wf.parent_model_type || '-')}</td>
            <td>
                <div style="display: flex; align-items: center; gap: 6px;">
                    ${wf.is_active ? `
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#28a745" style="flex-shrink: 0;">
                            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                        </svg>
                    ` : `
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#dc3545" style="flex-shrink: 0;">
                            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                        </svg>
                    `}
                    <span style="color: ${wf.is_active ? '#28a745' : '#dc3545'}; font-weight: ${wf.is_active ? 'bold' : 'normal'};">
                        ${wf.is_active ? '有効' : '無効'}
                    </span>
                </div>
            </td>
            <td>
                <div class="actions">
                    <button onclick="openWorkflowDetail(${wf.id})" title="編集" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #28a745; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m11.239 15.533c-1.045 3.004-1.238 3.451-1.238 3.84 0 .441.385.627.627.627.272 0 1.108-.301 3.829-1.249zm.888-.888 3.22 3.22 6.408-6.401c.163-.163.245-.376.245-.591 0-.213-.082-.427-.245-.591-.58-.579-1.458-1.457-2.039-2.036-.163-.163-.377-.245-.591-.245-.213 0-.428.082-.592.245zm-3.127-.895c0-.402-.356-.75-.75-.75-2.561 0-2.939 0-5.5 0-.394 0-.75.348-.75.75s.356.75.75.75h5.5c.394 0 .75-.348.75-.75zm5-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75z" fill-rule="nonzero"/></svg>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

function renderWorkflowsPagination() {
    const container = document.getElementById('workflows-pagination-container');
    if (!container) return;

    const totalPages = Math.ceil(wfTotalItems / wfItemsPerPage);
    if (totalPages <= 1) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';

    let html = `
        <button onclick="loadWorkflows(${wfCurrentPage - 1})" ${wfCurrentPage === 1 ? 'disabled' : ''}>前へ</button>
    `;

    const startPage = Math.max(1, wfCurrentPage - 2);
    const endPage = Math.min(totalPages, startPage + 4);

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="page-number ${i === wfCurrentPage ? 'active' : ''}" onclick="loadWorkflows(${i})">${i}</button>`;
    }

    html += `
        <span class="page-info">${wfCurrentPage} / ${totalPages}</span>
        <button onclick="loadWorkflows(${wfCurrentPage + 1})" ${wfCurrentPage >= totalPages ? 'disabled' : ''}>次へ</button>
    `;

    container.innerHTML = html;
}

// ============================================================================
// ワークフロー編集（モーダル）
// ============================================================================

function _wfbEsc(text) {
    if (text == null || text === '') return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/** ワークフロー親スキル用・スキル編集と同じ選択肢の value 一覧（一覧外モデル用フォールバック判定） */
const _WFB_PARENT_MODEL_OPTION_VALUES = new Set([
    'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-pro', 'gpt-5.4-thinking', 'gpt-5.2', 'gpt-5.2-pro', 'gpt-5.2-thinking', 'o4-mini',
    'gemini-3.1-pro-preview', 'gemini-3.1-pro-preview-deep-think', 'gemini-3-pro-preview', 'gemini-3-pro-preview-deep-think',
    'gemini-2.5-pro', 'gemini-2.5-flash',
    'claude-sonnet-4-6', 'claude-sonnet-4-6-thinking', 'claude-opus-4-6', 'claude-opus-4-6-thinking', 'claude-haiku-4-5',
]);

/** DB の parent_model_type + parent_enable_deep_think を select の value に合わせる */
function _wfbParentModelCurrentSelectValue(s) {
    const pm = s.parent_model_type || '';
    const dt = !!s.parent_enable_deep_think;
    if (pm.includes('deep-think')) return pm;
    if (pm === 'gemini-3.1-pro-preview' && dt) return 'gemini-3.1-pro-preview-deep-think';
    if (pm === 'gemini-3-pro-preview' && dt) return 'gemini-3-pro-preview-deep-think';
    return pm;
}

/** select の値 → API 用にベース model と deep_think フラグへ（スキル保存の deep-think 判定と同趣旨） */
function _wfbNormalizeParentModelFromSelect(raw) {
    const v = raw || '';
    const parent_enable_deep_think = v.includes('deep-think');
    const parent_model_type = v.endsWith('-deep-think') ? v.slice(0, -'-deep-think'.length) : v;
    return { parent_model_type, parent_enable_deep_think };
}

/** ワークフロー編集モーダル用 AIモデル select の内側 HTML（OpenAI / Gemini / Claude の optgroup） */
function _wfbParentModelSelectInnerHtml(s) {
    const cur = _wfbParentModelCurrentSelectValue(s);
    const sel = (v) => (v === cur ? ' selected' : '');
    let html = `
                    <optgroup label="OpenAI">
                        <option value="gpt-5.4"${sel('gpt-5.4')}>GPT-5.4 NEW</option>
                        <option value="gpt-5.4-mini"${sel('gpt-5.4-mini')}>GPT-5.4 Mini NEW</option>
                        <option value="gpt-5.4-pro"${sel('gpt-5.4-pro')}>GPT-5.4 Pro NEW</option>
                        <option value="gpt-5.4-thinking"${sel('gpt-5.4-thinking')}>GPT-5.4 Thinking NEW</option>
                        <option value="gpt-5.2"${sel('gpt-5.2')}>GPT-5.2</option>
                        <option value="gpt-5.2-pro"${sel('gpt-5.2-pro')}>GPT-5.2 Pro</option>
                        <option value="gpt-5.2-thinking"${sel('gpt-5.2-thinking')}>GPT-5.2 Thinking</option>
                        <option value="o4-mini"${sel('o4-mini')}>o4-mini（推論コスパ）</option>
                    </optgroup>
                    <optgroup label="Gemini">
                        <option value="gemini-3.1-pro-preview"${sel('gemini-3.1-pro-preview')}>Gemini 3.1 Pro NEW</option>
                        <option value="gemini-3.1-pro-preview-deep-think"${sel('gemini-3.1-pro-preview-deep-think')}>Gemini 3.1 Pro Deep Think NEW</option>
                        <option value="gemini-3-pro-preview"${sel('gemini-3-pro-preview')}>Gemini 3.0 Pro</option>
                        <option value="gemini-3-pro-preview-deep-think"${sel('gemini-3-pro-preview-deep-think')}>Gemini 3.0 Pro Deep Think</option>
                        <option value="gemini-2.5-pro"${sel('gemini-2.5-pro')}>Gemini 2.5 Pro</option>
                        <option value="gemini-2.5-flash"${sel('gemini-2.5-flash')}>Gemini 2.5 Flash</option>
                    </optgroup>
                    <optgroup label="Claude">
                        <option value="claude-sonnet-4-6"${sel('claude-sonnet-4-6')}>Claude Sonnet 4.6</option>
                        <option value="claude-sonnet-4-6-thinking"${sel('claude-sonnet-4-6-thinking')}>Claude Sonnet 4.6 Thinking</option>
                        <option value="claude-opus-4-6"${sel('claude-opus-4-6')}>Claude Opus 4.6</option>
                        <option value="claude-opus-4-6-thinking"${sel('claude-opus-4-6-thinking')}>Claude Opus 4.6 Thinking</option>
                        <option value="claude-haiku-4-5"${sel('claude-haiku-4-5')}>Claude Haiku 4.5</option>
                    </optgroup>`;
    if (cur && !_WFB_PARENT_MODEL_OPTION_VALUES.has(cur)) {
        html += `
                    <optgroup label="現在の値（一覧外）">
                        <option value="${_wfbEsc(cur)}" selected>${_wfbEsc(cur)}</option>
                    </optgroup>`;
    }
    return html;
}

let _wfBuilderState = null;
let _availableSkills = [];

/** ワークフロー作成 / 編集 SweetAlert 共通のラベル・入力スタイル（スキル編集ダイアログと同系） */
const WF_SWAL = {
    lbl: 'style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);"',
    fld: 'style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;"',
    inp: 'class="swal2-input" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;"',
    txa(minH) {
        return `class="swal2-textarea" style="min-height: ${minH}px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;"`;
    },
    sel: 'class="swal2-select" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;"',
    hint: 'style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; font-size: 13px;"',
    secTitle: 'style="display: block; font-weight: bold; margin-bottom: 10px; color: rgba(255, 255, 255, 0.9);"',
    flowWrap: 'style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box; padding: 12px 14px; background: rgba(0,0,0,0.12); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px;"',
    leaderCard: 'style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box; padding: 12px; background: rgba(156,39,176,0.08); border: 1px solid rgba(156,39,176,0.25); border-radius: 8px;"',
    col: 'style="flex: 1; min-width: 220px; text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;"',
};

let _wfCreateStepUid = 0;
let _wfCreateGroups = [];
let _wfCreateUsableSkills = [];

function _wfFlowConnectorHtml() {
    return '<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>';
}

async function openWorkflowDetail(id) {
    try {
        const wf = await apiRequest(`/api/admin/workflows/${id}`);
        _wfBuilderState = {
            id: wf.id,
            name: wf.name,
            description: wf.description || '',
            is_active: wf.is_active,
            parent_prompt_content: wf.parent_prompt_content || '',
            parent_model_type: wf.parent_model_type || 'gpt-5.1',
            parent_enable_deep_think: wf.parent_enable_deep_think ?? true,
            supervisor_mode: wf.supervisor_mode || 'disabled',
            groups: (wf.groups || []).map(g => ({
                group_order: g.group_order,
                group_name: g.group_name || '',
                execution_type: g.execution_type || 'serial',
                condition_expression: g.condition_expression || null,
                skip_on_condition_fail: g.skip_on_condition_fail !== false,
                supervisor_prompt: g.supervisor_prompt || '',
                supervisor_model: g.supervisor_model || '',
                dynamic_mode: g.dynamic_mode || 'static',
                judge_prompt: g.judge_prompt || '',
                judge_model: g.judge_model || '',
                skills: (g.skills || []).map(s => ({
                    skill_id: s.skill_id,
                    skill_name: s.skill_name || '',
                    model_type: s.model_type || '',
                    order_in_group: s.order_in_group || 1,
                    on_error: s.on_error || 'stop',
                    max_retries: s.max_retries || 0,
                    retry_delay_seconds: s.retry_delay_seconds || 5,
                    output_key: s.output_key || '',
                    input_mapping: s.input_mapping || null,
                    quality_gate_type: s.quality_gate_type || 'disabled',
                    quality_gate_prompt: s.quality_gate_prompt || '',
                    max_reflection_loops: s.max_reflection_loops || 0,
                    agent_profile: s.agent_profile || 'default',
                })),
            })),
        };

        // 利用可能スキル取得
        try {
            _availableSkills = await apiRequest('/api/admin/skills?skip=0&limit=1000');
            if (_availableSkills.items) _availableSkills = _availableSkills.items;
        } catch (e) { _availableSkills = []; }

        _renderWorkflowBuilder();
    } catch (error) {
        await showAlert('ワークフローの取得に失敗しました', 'error');
    }
}

function _renderWorkflowBuilder() {
    const s = _wfBuilderState;
    const MODEL_OPTIONS = _wfbParentModelSelectInnerHtml(s);

    const scPending = 'rgba(255,255,255,0.2)';
    const siPending = '&#9711;';
    const flowConnector = `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>`;

    // 実行フローと同じ見た目で編集（リーダー → グループ → リーダー）
    let groupsHtml = '';
    s.groups.forEach((grp, gi) => {
        const gColor = grp.execution_type === 'parallel' ? '#2196f3' : '#ff9800';
        const useParallelLayout = grp.execution_type === 'parallel' && grp.skills.length > 1;

        let skillsHtml = '';
        grp.skills.forEach((sk, si) => {
            const sName = _wfbEsc(sk.skill_name || '');
            const sModel = _wfbEsc(sk.model_type || '');
            const onErr = sk.on_error || 'stop';
            const errBadge = onErr === 'retry' ? '<span style="font-size:10px; color:#ffc107; margin-left:4px;">⟳retry</span>'
                           : onErr === 'skip' ? '<span style="font-size:10px; color:#17a2b8; margin-left:4px;">▷skip</span>' : '';
            const advHtml = `
                <div style="margin-top:6px; padding:6px 8px; background:rgba(0,0,0,0.15); border-radius:4px; font-size:11px;">
                    <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                        <label style="color:rgba(255,255,255,0.7);">Profile:</label>
                        <select onchange="_wfbUpdateSkillField(${gi},${si},'agent_profile',this.value)" style="font-size:11px; padding:2px 4px; background:rgba(0,0,0,0.3); color:#fff; border:1px solid rgba(255,255,255,0.2); border-radius:4px;">
                            ${renderAgentProfileOptions(sk.agent_profile || 'default')}
                        </select>
                        <span style="color:rgba(255,255,255,0.4); font-size:10px; margin-left:4px;">エラー時・品質ゲート・出力キーは自動設定</span>
                    </div>
                </div>`;
            if (useParallelLayout) {
                skillsHtml += `
                <div class="wfb-skill" data-gi="${gi}" data-si="${si}" style="flex:1; min-width:180px; display:flex; flex-direction:column; gap:4px; padding:10px; background:rgba(0,0,0,0.2); border-radius:6px; border-left:3px solid ${gColor}; cursor:grab;">
                    <div style="display:flex; align-items:flex-start; gap:6px;">
                        <span class="wfb-skill-drag" style="cursor:grab; opacity:0.45; flex-shrink:0; padding-top:2px;">&#x2261;</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:13px; font-weight:bold; color:rgba(255,255,255,0.9); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${sName}${errBadge}</div>
                            <div style="font-size:12px; color:rgba(255,255,255,0.55);">${sModel}</div>
                        </div>
                        <button type="button" onclick="_wfbRemoveSkill(${gi},${si})" style="background:none; border:none; color:#ff6b6b; cursor:pointer; font-size:14px; flex-shrink:0;" title="削除">&times;</button>
                    </div>
                    ${advHtml}
                </div>`;
            } else {
                const connector = si > 0
                    ? `<div style="display:flex; justify-content:flex-start; padding:2px 0 2px 20px;"><div style="width:1px; height:10px; background:rgba(255,255,255,0.1);"></div></div>`
                    : '';
                skillsHtml += `${connector}
                <div class="wfb-skill" data-gi="${gi}" data-si="${si}" style="padding:8px 10px; background:rgba(0,0,0,0.15); border-radius:6px; border-left:3px solid ${gColor}; cursor:grab; ${si > 0 ? 'margin-top:6px;' : ''}">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span class="wfb-skill-drag" style="cursor:grab; opacity:0.45; flex-shrink:0;">&#x2261;</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:13px; font-weight:bold; color:rgba(255,255,255,0.9);">${sName}${errBadge}</div>
                            <div style="font-size:12px; color:rgba(255,255,255,0.55);">${sModel}</div>
                        </div>
                        <button type="button" onclick="_wfbRemoveSkill(${gi},${si})" style="background:none; border:none; color:#ff6b6b; cursor:pointer; font-size:14px; flex-shrink:0;" title="削除">&times;</button>
                    </div>
                    ${advHtml}
                </div>`;
            }
        });

        const skillsEmpty = useParallelLayout
            ? '<div style="flex:1; text-align:center; padding:14px; color:rgba(255,255,255,0.55); font-size:13px;">スキルをドラッグまたは下のメニューから追加</div>'
            : '<div style="text-align:center; padding:14px; color:rgba(255,255,255,0.55); font-size:13px;">スキルをドラッグまたは下のメニューから追加</div>';

        const skillsWrapStyle = useParallelLayout
            ? 'display:flex; flex-wrap:wrap; gap:6px; padding:10px 14px; min-height:52px; align-items:stretch;'
            : 'padding:8px 14px; min-height:52px;';

        groupsHtml += `
            <div class="wfb-group-slot" data-gi="${gi}">
                <div class="wfb-group" data-gi="${gi}" style="margin:4px 0; border:1px solid ${gColor}33; border-radius:8px; overflow:hidden;">
                    <div style="padding:8px 14px; background:${gColor}15; display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                        <span class="wfb-group-handle" style="cursor:grab; opacity:0.5; font-size:16px; flex-shrink:0;" title="グループの並べ替え">&#x2261;</span>
                        <select onchange="_wfbUpdateGroup(${gi},'type',this.value)" class="swal2-select" style="font-size:13px; font-weight:bold; color:${gColor}; background:${gColor}22; border:1px solid ${gColor}44; padding:4px 10px; border-radius:8px; cursor:pointer; width:auto; max-width:none; margin-top:0; flex-shrink:0;" title="このグループ内の実行方式">
                            <option value="serial" ${grp.execution_type === 'serial' ? 'selected' : ''}>直列</option>
                            <option value="parallel" ${grp.execution_type === 'parallel' ? 'selected' : ''}>並列</option>
                        </select>
                        <input type="text" value="${_wfbEsc(grp.group_name)}" onchange="_wfbUpdateGroup(${gi},'name',this.value)" placeholder="グループ名" class="swal2-input" style="flex:1; min-width:140px; margin-top:0; max-width:none; background:rgba(0,0,0,0.2); font-size:13px;">
                        <button type="button" onclick="_wfbRemoveGroup(${gi})" style="background:none; border:none; color:#ff6b6b; cursor:pointer; font-size:16px; flex-shrink:0;" title="グループ削除">&times;</button>
                    </div>
                    ${grp.condition_expression ? `<div style="padding:4px 14px; background:rgba(255,193,7,0.08); font-size:11px; color:#ffc107;">条件: ${_wfbEsc(JSON.stringify(grp.condition_expression))}</div>` : ''}
                    <div style="padding:6px 14px; background:rgba(0,0,0,0.08); border-top:1px solid rgba(255,255,255,0.06); font-size:11px;">
                        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                            <label style="color:rgba(255,255,255,0.7);">動的:</label>
                            <select onchange="_wfbUpdateGroup(${gi},'dynamic_mode',this.value)" style="font-size:11px; padding:2px 4px; background:rgba(0,0,0,0.3); color:#fff; border:1px solid rgba(255,255,255,0.2); border-radius:4px;">
                                <option value="static" ${grp.dynamic_mode === 'static' ? 'selected' : ''}>静的</option>
                                <option value="dynamic" ${grp.dynamic_mode === 'dynamic' ? 'selected' : ''}>動的(プランナー)</option>
                            </select>
                            <span style="color:rgba(255,255,255,0.4); font-size:10px; margin-left:4px;">ジャッジ・SVは自動適用</span>
                        </div>
                    </div>
                    <div id="wfb-skills-${gi}" style="${skillsWrapStyle}">
                        ${skillsHtml || skillsEmpty}
                    </div>
                    <div style="padding:8px 14px 12px; border-top:1px solid rgba(255,255,255,0.08);">
                        <select id="wfb-add-skill-${gi}" class="swal2-select" style="width:100%; margin-top:0; box-sizing:border-box; max-width:100%; font-size:13px;">
                            <option value="">+ スキル追加...</option>
                            ${_availableSkills.filter(p => p.is_active !== false && !p.deleted_at).map(p =>
                                `<option value="${p.id}">${_wfbEsc(p.name)} (${_wfbEsc(p.model_type)})</option>`
                            ).join('')}
                        </select>
                    </div>
                </div>
                ${gi < s.groups.length - 1 ? flowConnector : ''}
            </div>`;
    });

    const leaderStart = `
        <div style="display:flex; align-items:center; gap:10px; padding:12px 16px; background:rgba(156,39,176,0.12); border:1px solid rgba(156,39,176,0.3); border-radius:8px; margin-bottom:4px;">
            <div style="width:28px; height:28px; border-radius:50%; background:${scPending}; display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">${siPending}</div>
            <div>
                <div style="font-size:13px; font-weight:bold; color:#ce93d8;">Leader: タスク振り分け</div>
                <div style="font-size:13px; color:rgba(255,255,255,0.6);">${_wfbEsc(s.name || 'ワークフロー')}</div>
            </div>
        </div>`;

    const leaderEnd = `
        <div style="display:flex; align-items:center; gap:10px; padding:12px 16px; background:rgba(156,39,176,0.12); border:1px solid rgba(156,39,176,0.3); border-radius:8px; margin-top:4px;">
            <div style="width:28px; height:28px; border-radius:50%; background:${scPending}; display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">${siPending}</div>
            <div>
                <div style="font-size:13px; font-weight:bold; color:#ce93d8;">Leader: 結果統合</div>
                <div style="font-size:13px; color:rgba(255,255,255,0.6);">全結果を統合して最終出力を生成</div>
            </div>
        </div>`;

    const flowColumn = `
        <div ${WF_SWAL.flowWrap}>
            <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:12px; flex-wrap:wrap;">
                <div style="flex:1; min-width:200px;">
                    <span ${WF_SWAL.secTitle}>実行フロー（編集）</span>
                    <small ${WF_SWAL.hint}>グループとスキルは ≡ をドラッグして並べ替えできます。右上の「+ グループ追加」でグループを追加できます。</small>
                </div>
                <button type="button" onclick="_wfbAddGroup()" style="padding:8px 16px; background:rgba(40,167,69,0.9); border:1px solid rgba(72,180,97,0.65); border-radius:8px; color:#fff; cursor:pointer; font-size:13px; font-weight:600; flex-shrink:0; white-space:nowrap; align-self:flex-start;">+ グループ追加</button>
            </div>
            <div style="display:flex; flex-direction:column; gap:0;">
                ${leaderStart}
                ${flowConnector}
                <div id="wfb-groups-container">
                    ${groupsHtml || `<div style="text-align:center; padding:24px 12px; color:rgba(255,255,255,0.55); font-size:13px;">グループがありません。右上の「+ グループ追加」から追加してください。</div>`}
                </div>
                ${flowConnector}
                ${leaderEnd}
            </div>
        </div>`;

    Swal.fire({
        title: 'ワークフローを編集',
        html: `
            <div class="swal-no-scroll" style="max-height:75vh; overflow-y:auto; text-align:left; width:100%; box-sizing:border-box;">
                <div ${WF_SWAL.fld}>
                    <label ${WF_SWAL.lbl}>ワークフロー名 <span style="color: #ff6b6b;">*</span></label>
                    <input type="text" id="wfb-name" ${WF_SWAL.inp} value="${_wfbEsc(s.name)}" placeholder="例: 記事制作パイプライン">
                </div>
                <div ${WF_SWAL.fld}>
                    <label ${WF_SWAL.lbl}>説明</label>
                    <textarea id="wfb-desc" rows="4" ${WF_SWAL.txa(100)} placeholder="このワークフローの用途や流れを入力">${_wfbEsc(s.description)}</textarea>
                </div>

                <div ${WF_SWAL.leaderCard}>
                    <span ${WF_SWAL.secTitle}>親スキル（Parent Skill）</span>
                    <input type="hidden" id="wfb-parent-mode" value="required">
                    <input type="hidden" id="wfb-supervisor-mode" value="disabled">
                    <div ${WF_SWAL.fld}>
                        <label ${WF_SWAL.lbl}>AIモデル <span style="color: #ff6b6b;">*</span></label>
                        <select id="wfb-parent-model" ${WF_SWAL.sel}>
                            ${MODEL_OPTIONS}
                        </select>
                    </div>
                    <input type="hidden" id="wfb-parent-content" value="${s.parent_prompt_content || '(自動生成)'}">
                    <small style="color: rgba(255,255,255,0.5); display:block; margin: 0 0 8px; font-size:11px;">リーダースキル内容はワークフロー名・説明から自動生成されます</small>
                </div>

                ${flowColumn}
            </div>
        `,
        width: '800px',
        showCancelButton: true,
        confirmButtonText: '保存',
        cancelButtonText: ADMIN_SWAL.btnClose,
        confirmButtonColor: ADMIN_SWAL.primary,
        cancelButtonColor: ADMIN_SWAL.secondary,
        didOpen: () => {
            _wfbInitSortables();
            _wfbInitAddSkillSelects();
        },
        preConfirm: () => _wfbSave(),
    });
}

function _wfbInitSortables() {
    // グループの並べ替え（スロット単位・実行フロー矢印は各スロット内で維持）
    const container = document.getElementById('wfb-groups-container');
    if (container && container.querySelector('.wfb-group-slot')) {
        Sortable.create(container, {
            handle: '.wfb-group-handle',
            animation: 150,
            draggable: '.wfb-group-slot',
            onEnd: (evt) => {
                const groups = _wfBuilderState.groups;
                const [moved] = groups.splice(evt.oldIndex, 1);
                groups.splice(evt.newIndex, 0, moved);
                groups.forEach((g, i) => g.group_order = i + 1);
                _renderWorkflowBuilder();
            }
        });
    }

    // 各グループ内のスキル並べ替え
    _wfBuilderState.groups.forEach((grp, gi) => {
        const el = document.getElementById(`wfb-skills-${gi}`);
        if (el) {
            Sortable.create(el, {
                group: 'skills',
                handle: '.wfb-skill-drag',
                filter: 'button',
                preventOnFilter: false,
                animation: 150,
                onEnd: (evt) => {
                    const fromGi = parseInt(evt.from.id.split('-')[2]);
                    const toGi = parseInt(evt.to.id.split('-')[2]);
                    const [moved] = _wfBuilderState.groups[fromGi].skills.splice(evt.oldIndex, 1);
                    _wfBuilderState.groups[toGi].skills.splice(evt.newIndex, 0, moved);
                    // order_in_group 再計算
                    _wfBuilderState.groups.forEach(g => g.skills.forEach((s, i) => s.order_in_group = i + 1));
                    _renderWorkflowBuilder();
                }
            });
        }
    });
}

function _wfbInitAddSkillSelects() {
    _wfBuilderState.groups.forEach((grp, gi) => {
        const sel = document.getElementById(`wfb-add-skill-${gi}`);
        if (sel) {
            sel.addEventListener('change', () => {
                const pid = parseInt(sel.value);
                if (!pid) return;
                const p = _availableSkills.find(x => x.id === pid);
                if (!p) return;
                _wfBuilderState.groups[gi].skills.push({
                    skill_id: pid,
                    skill_name: p.name,
                    model_type: p.model_type,
                    order_in_group: grp.skills.length + 1,
                    on_error: 'stop',
                    max_retries: 0,
                    retry_delay_seconds: 5,
                    output_key: '',
                    input_mapping: null,
                    quality_gate_type: 'disabled',
                    quality_gate_prompt: '',
                    max_reflection_loops: 0,
                    agent_profile: p.default_agent_profile || 'default',
                });
                _renderWorkflowBuilder();
            });
        }
    });
}

function _wfbUpdateSkillField(gi, si, field, value) {
    if (_wfBuilderState.groups[gi] && _wfBuilderState.groups[gi].skills[si]) {
        _wfBuilderState.groups[gi].skills[si][field] = value;
        if (field === 'on_error') _renderWorkflowBuilder(); // re-render to show/hide retry count
    }
}

function _wfbAddGroup() {
    _wfBuilderState.groups.push({
        group_order: _wfBuilderState.groups.length + 1,
        group_name: `グループ ${_wfBuilderState.groups.length + 1}`,
        execution_type: 'serial',
        condition_expression: null,
        skip_on_condition_fail: true,
        supervisor_prompt: '',
        supervisor_model: '',
        dynamic_mode: 'static',
        judge_prompt: '',
        judge_model: '',
        skills: [],
    });
    _renderWorkflowBuilder();
}

function _wfbRemoveGroup(gi) {
    _wfBuilderState.groups.splice(gi, 1);
    _wfBuilderState.groups.forEach((g, i) => g.group_order = i + 1);
    _renderWorkflowBuilder();
}

function _wfbRemoveSkill(gi, si) {
    _wfBuilderState.groups[gi].skills.splice(si, 1);
    _wfBuilderState.groups[gi].skills.forEach((s, i) => s.order_in_group = i + 1);
    _renderWorkflowBuilder();
}

function _wfbUpdateGroup(gi, field, value) {
    if (field === 'name') _wfBuilderState.groups[gi].group_name = value;
    if (field === 'type') _wfBuilderState.groups[gi].execution_type = value;
    if (field === 'skip_on_condition_fail') _wfBuilderState.groups[gi].skip_on_condition_fail = value;
    if (field === 'supervisor_prompt') _wfBuilderState.groups[gi].supervisor_prompt = value;
    if (field === 'supervisor_model') _wfBuilderState.groups[gi].supervisor_model = value;
    if (field === 'dynamic_mode') _wfBuilderState.groups[gi].dynamic_mode = value;
    if (field === 'judge_prompt') _wfBuilderState.groups[gi].judge_prompt = value;
    if (field === 'judge_model') _wfBuilderState.groups[gi].judge_model = value;
    // Re-render to update flow view & colors
    _renderWorkflowBuilder();
}

async function _wfbSave() {
    const s = _wfBuilderState;
    // 入力値を反映
    s.name = document.getElementById('wfb-name')?.value || s.name;
    s.description = document.getElementById('wfb-desc')?.value || s.description;
    s.parent_prompt_content = document.getElementById('wfb-parent-content')?.value || s.parent_prompt_content;
    const rawModel = document.getElementById('wfb-parent-model')?.value;
    if (rawModel != null && rawModel !== '') {
        const norm = _wfbNormalizeParentModelFromSelect(rawModel);
        s.parent_model_type = norm.parent_model_type;
        s.parent_enable_deep_think = norm.parent_enable_deep_think;
    }
    const supervisorModeEl = document.getElementById('wfb-supervisor-mode');
    if (supervisorModeEl) s.supervisor_mode = supervisorModeEl.value;

    validateParallelGroupProfiles(s.groups);

    const payload = {
        name: s.name,
        description: s.description,
        parent_prompt_content: s.parent_prompt_content,
        parent_model_type: s.parent_model_type,
        parent_enable_deep_think: s.parent_enable_deep_think,
        supervisor_mode: s.supervisor_mode || 'disabled',
        groups: s.groups.map((g, gi) => ({
            group_order: gi + 1,
            group_name: g.group_name,
            execution_type: g.execution_type,
            condition_expression: g.condition_expression || null,
            skip_on_condition_fail: g.skip_on_condition_fail !== false,
            supervisor_prompt: g.supervisor_prompt || '',
            supervisor_model: g.supervisor_model || '',
            dynamic_mode: g.dynamic_mode || 'static',
            judge_prompt: g.judge_prompt || '',
            judge_model: g.judge_model || '',
            skills: g.skills.map((sk, si) => ({
                skill_id: sk.skill_id,
                order_in_group: si + 1,
                skill_name: sk.skill_name || '',
                on_error: sk.on_error || 'stop',
                max_retries: parseInt(sk.max_retries) || 0,
                retry_delay_seconds: parseInt(sk.retry_delay_seconds) || 5,
                output_key: sk.output_key || null,
                input_mapping: sk.input_mapping || null,
                quality_gate_type: sk.quality_gate_type || 'disabled',
                quality_gate_prompt: sk.quality_gate_prompt || '',
                max_reflection_loops: parseInt(sk.max_reflection_loops) || 0,
                agent_profile: sk.agent_profile || 'default',
            })),
        })),
    };

    try {
        await apiRequest(`/api/admin/workflows/${s.id}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
        });
        await showAlert('ワークフローを保存しました', 'success');
        loadWorkflows();
        return true;
    } catch (e) {
        await showAlert('保存に失敗しました: ' + e.message, 'error');
        return false;
    }
}

// ページ読み込み時に実行
(async () => {
    initAdminLayout('dashboard.html');
    await checkAuth();
    loadDashboardStats();
    loadSkills(1);
    loadWorkflows(1);
})();
