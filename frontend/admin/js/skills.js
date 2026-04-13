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
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--content-text-muted);">スキルがまだ登録されていません</td></tr>';
        return;
    }

    tbody.innerHTML = skills.map(skill => {
        // CLI モード: API の model_type の代わりに設定済みの CLI モデル
        // （claude-sonnet-4-6 等）を表示 — これが CLI バイナリが実際に
        // 呼び出される際の値。
        const ctx = { skill: { config_json: skill.config_json } };
        const resolved = window.runtimeResolver
            ? window.runtimeResolver.resolveEffectiveRuntime(ctx)
            : { kind: 'api' };
        const modelDisplay = (resolved.kind === 'cli')
            ? escapeHtmlAdmin(window.runtimeResolver.effectiveModelLabel(ctx, ''))
            : formatModelDisplay(skill.model_type, null, skill);
        const runtimeChip = window.runtimeResolver
            ? window.runtimeResolver.renderResolvedRuntimeChip(ctx)
            : '';
        return `
        <tr>
            <td>${skill.id}</td>
            <td>${escapeHtmlAdmin(skill.name)}</td>
            <td>${escapeHtmlAdmin(skill.description || '説明なし')}</td>
            <td>${runtimeChip || '<span style="color:var(--content-text-muted); font-size:11px;">-</span>'}</td>
            <td>${modelDisplay}</td>
            <td>${statusBadgeHtml(skill.is_active)}</td>
            <td>
                <div style="display: flex; flex-direction: column; gap: 4px;">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        ${skill.allows_file_output ? ADMIN_ICONS.check : ADMIN_ICONS.cross}
                        <span style="color: ${skill.allows_file_output ? '#28a745' : '#dc3545'}; font-weight: ${skill.allows_file_output ? 'bold' : 'normal'};">ファイル出力: ${skill.allows_file_output ? '許可' : '不可'}</span>
                    </div>
                    <div style="display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: 11px; color: var(--content-text);">
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
                        <img src="../img/iconmonstr-apps-filled.svg" alt="WF" style="width: 20px; height: 20px; filter: invert(62%) sepia(85%) saturate(600%) hue-rotate(360deg) brightness(100%) contrast(95%);">
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
            <div style="text-align:left; width:100%; box-sizing:border-box;">
                <!-- スキル基本情報カード -->
                <div ${WF_SWAL.leaderCard}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <span ${WF_SWAL.secTitle} style="margin-bottom:0;">スキル情報</span>
                        <div style="display:flex; gap:12px;">
                            <label style="display:flex; align-items:center; cursor:pointer; gap:5px;">
                                <input type="checkbox" id="swal-skill-is-active" checked style="width:16px; height:16px; cursor:pointer; accent-color:var(--accent);">
                                <span style="font-size:12px; color:var(--accent); font-weight:600;">有効</span>
                            </label>
                            <label style="display:flex; align-items:center; cursor:pointer; gap:5px;">
                                <input type="checkbox" id="swal-skill-allows-file-output" style="width:16px; height:16px; cursor:pointer; accent-color:var(--accent);">
                                <span style="font-size:12px; color:var(--content-text-muted); font-weight:600;">ファイル出力</span>
                            </label>
                        </div>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
                        <div>
                            <label ${WF_SWAL.lbl}>スキル名 <span style="color:var(--accent);">*</span></label>
                            <input id="swal-skill-name" ${WF_SWAL.inp} placeholder="例: 記事要約スキル" required>
                        </div>
                        <div>
                            <label ${WF_SWAL.lbl}>説明</label>
                            <textarea id="swal-skill-description" ${WF_SWAL.txa(60)} placeholder="このスキルの用途"></textarea>
                        </div>
                    </div>
                    <!-- 実行方式の必須選択: API か CLI -->
                    <div style="margin-bottom:12px;">
                        <label ${WF_SWAL.lbl}>実行方式 <span style="color:var(--accent);">*</span></label>
                        <div style="display:flex; gap:8px;">
                            <label data-runtime-mode-label="api" style="flex:1; display:flex; align-items:center; gap:8px; padding:10px 12px; border:2px solid var(--accent); border-radius:8px; cursor:pointer; background:rgba(0,120,215,0.06);">
                                <input type="radio" name="swal-skill-runtime-mode" value="api" checked style="accent-color:var(--accent);">
                                <div>
                                    <div style="font-size:13px; font-weight:600;">API（HTTP provider）</div>
                                    <div style="font-size:11px; color:var(--content-text-muted);">OpenAI / Gemini / Claude など、クラウドAPIで実行</div>
                                </div>
                            </label>
                            <label data-runtime-mode-label="cli" style="flex:1; display:flex; align-items:center; gap:8px; padding:10px 12px; border:2px solid rgba(0,0,0,0.12); border-radius:8px; cursor:pointer;">
                                <input type="radio" name="swal-skill-runtime-mode" value="cli" style="accent-color:var(--accent);">
                                <div>
                                    <div style="font-size:13px; font-weight:600;">CLI（ローカル実行）</div>
                                    <div style="font-size:11px; color:var(--content-text-muted);">claude / codex などローカルにインストール済みのCLI</div>
                                </div>
                            </label>
                        </div>
                    </div>

                    <!-- Agent Profile は実行方式と独立: API/CLI どちらでも有効 -->
                    <div style="margin-bottom:12px;">
                        <label ${WF_SWAL.lbl}>Agent Profile</label>
                        <select id="swal-default-agent-profile" ${WF_SWAL.sel}>
                            ${renderAgentProfileOptions('default')}
                        </select>
                        <small ${WF_SWAL.hint}>Explore=調査 / Plan=設計 / Implement=実装 / Verification=検証（API/CLIどちらでも有効）</small>
                    </div>

                    <div data-runtime-api-section>
                        <label ${WF_SWAL.lbl}>AIモデル <span style="color:var(--accent);">*</span></label>
                        <select id="swal-skill-model" ${WF_SWAL.sel} required onchange="_updateModelBadge('swal-skill-model','swal-skill-model-badge')">
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

                    <div data-runtime-cli-section style="display:none; margin-top:4px;">
                        <small ${WF_SWAL.hint} style="display:block; margin-bottom:6px;">
                            CLI 実行では claude-code / codex などローカルにインストール済みの CLI を使用します。
                            ワークフローに組み込まれた際もこの設定が既定値になります。
                        </small>
                        <div id="swal-skill-execution-config-mount"></div>
                    </div>
                </div>

                <!-- スキル内容カード -->
                <div ${WF_SWAL.leaderCard}>
                    <span ${WF_SWAL.secTitle}>スキル内容</span>
                    <div ${WF_SWAL.fld}>
                        <label ${WF_SWAL.lbl}>プロンプト <span style="color:var(--accent);">*</span></label>
                        <textarea id="swal-skill-content" ${WF_SWAL.txa(180)} placeholder="スキル内容を入力してください。&#10;変数は {{variable_name}} の形式で記述できます。" required style="font-family:monospace;"></textarea>
                        <small ${WF_SWAL.hint}>変数の例: {{article_text}}, {{input}}, {{query}} など</small>
                    </div>
                    <div ${WF_SWAL.fld}>
                        <label ${WF_SWAL.lbl}>入力スキーマ（JSON形式、オプション）</label>
                        <textarea id="swal-skill-schema" ${WF_SWAL.txa(100)} placeholder='{"field_name": {"type": "string", "label": "ラベル", "required": true}}' style="font-family:monospace; font-size:12px;"></textarea>
                        <small ${WF_SWAL.hint}>ユーザー入力フィールドの定義（省略可能）</small>
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
        customClass: {
            popup: 'swal-scrollable-popup',
            htmlContainer: 'swal-scrollable-container'
        },
        didOpen: () => {
            const sel = document.getElementById('swal-skill-model');
            if (sel) {
                const badge = document.createElement('div');
                badge.id = 'swal-skill-model-badge';
                badge.style.cssText = 'margin-top:4px; font-size:11px;';
                sel.parentNode.appendChild(badge);
                _updateModelBadge('swal-skill-model', 'swal-skill-model-badge');
            }
            const mount = document.getElementById('swal-skill-execution-config-mount');
            if (mount && window.executionConfigForm) {
                // CLI フォームのデフォルトを execution_kind=external_cli で
                // 事前入力し、ユーザーが毎回再選択する手間を省く。
                const cliDefault = window.executionConfigForm.defaultConfig();
                cliDefault.execution.execution_kind = 'external_cli';
                mount.innerHTML = window.executionConfigForm.renderForm(cliDefault);
                window.executionConfigForm.attachDynamicWiring(mount);
            }
            _wireSkillRuntimeModeToggle();
        },
        preConfirm: () => _collectSkillFormValues()
    });

    if (formValues) {
        await saveSkill(null, formValues);
    }
}

// API/CLI ラジオを接続: 2つのセクションの表示を切り替え、
// モデルセレクトの `required` 属性もトグルして、ユーザーが CLI を
// 選択した際にブラウザが送信をブロックしないようにする。
function _wireSkillRuntimeModeToggle() {
    const radios = document.querySelectorAll('input[name="swal-skill-runtime-mode"]');
    const apiSec = document.querySelector('[data-runtime-api-section]');
    const cliSec = document.querySelector('[data-runtime-cli-section]');
    const modelSel = document.getElementById('swal-skill-model');
    const apiLabel = document.querySelector('[data-runtime-mode-label="api"]');
    const cliLabel = document.querySelector('[data-runtime-mode-label="cli"]');

    function apply() {
        const mode = (document.querySelector('input[name="swal-skill-runtime-mode"]:checked') || {}).value || 'api';
        if (mode === 'cli') {
            if (apiSec) apiSec.style.display = 'none';
            if (cliSec) cliSec.style.display = 'block';
            if (modelSel) modelSel.required = false;
            if (apiLabel) {
                apiLabel.style.borderColor = 'rgba(0,0,0,0.12)';
                apiLabel.style.background = 'transparent';
            }
            if (cliLabel) {
                cliLabel.style.borderColor = 'var(--accent)';
                cliLabel.style.background = 'rgba(0,120,215,0.06)';
            }
        } else {
            if (apiSec) apiSec.style.display = 'block';
            if (cliSec) cliSec.style.display = 'none';
            if (modelSel) modelSel.required = true;
            if (apiLabel) {
                apiLabel.style.borderColor = 'var(--accent)';
                apiLabel.style.background = 'rgba(0,120,215,0.06)';
            }
            if (cliLabel) {
                cliLabel.style.borderColor = 'rgba(0,0,0,0.12)';
                cliLabel.style.background = 'transparent';
            }
        }
    }
    radios.forEach(r => r.addEventListener('change', apply));
    apply();
}

// 作成/編集共通の preConfirm コレクター — saveSkill が使う formValues
// オブジェクトを返す。バリデーションエラー時は
// Swal.showValidationMessage を呼び出した後 false を返す。
function _collectSkillFormValues() {
    const name = document.getElementById('swal-skill-name').value.trim();
    const description = document.getElementById('swal-skill-description').value.trim();
    const model = document.getElementById('swal-skill-model').value;
    const content = document.getElementById('swal-skill-content').value.trim();
    const schemaText = document.getElementById('swal-skill-schema').value.trim();
    const isActive = document.getElementById('swal-skill-is-active').checked;
    const allowsFileOutput = document.getElementById('swal-skill-allows-file-output').checked;
    const defaultAgentProfile = document.getElementById('swal-default-agent-profile').value;
    const runtimeMode = (document.querySelector('input[name="swal-skill-runtime-mode"]:checked') || {}).value || 'api';

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

    // CLI モードが選択されている場合のみ execution_config を収集する。
    // API モードでは明示的に null を送信し、バックエンドが model_type にフォールバックする。
    let executionConfig = null;
    if (runtimeMode === 'cli') {
        try {
            const mount = document.getElementById('swal-skill-execution-config-mount');
            const root = mount && mount.querySelector('[data-exec-config-root]');
            if (root && window.executionConfigForm) {
                executionConfig = window.executionConfigForm.collectForm(root);
                // CLI モードでは execution_kind=external_cli を強制 — フォームでは
                // デフォルトだが、ユーザーが切り戻す可能性がある。
                executionConfig.execution.execution_kind = 'external_cli';
                if (!executionConfig.execution.preferred_adapter && !executionConfig.execution.cli_runtime_hint) {
                    Swal.showValidationMessage('CLI 実行では「推奨アダプター」を選択してください');
                    return false;
                }
                if (!executionConfig.execution.cwd_hint) {
                    Swal.showValidationMessage('CLI 実行では「cwd ヒント」（作業ディレクトリ）が必須です');
                    return false;
                }
            } else {
                Swal.showValidationMessage('実行ランタイム設定フォームを読み込めませんでした');
                return false;
            }
        } catch (_e) {
            Swal.showValidationMessage('実行ランタイム設定の読み込みに失敗しました');
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
        defaultAgentProfile,
        runtimeMode,
        executionConfig
    };
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

    const _esc = (t) => String(t || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    const _sel = (v, cur) => v === cur ? 'selected' : '';
    const _selDT = (model, dt, v) => {
        if (v.includes('deep-think')) return (model === v.replace('-deep-think','') && dt) || model === v ? 'selected' : '';
        return model === v && !dt ? 'selected' : '';
    };

    const { value: formValues } = await Swal.fire({
        title: 'スキルを編集',
        html: `
            <div style="text-align:left; width:100%; box-sizing:border-box;">
                <!-- スキル基本情報カード -->
                <div ${WF_SWAL.leaderCard}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <span ${WF_SWAL.secTitle} style="margin-bottom:0;">スキル情報</span>
                        <div style="display:flex; gap:12px;">
                            <label style="display:flex; align-items:center; cursor:pointer; gap:5px;">
                                <input type="checkbox" id="swal-skill-is-active" ${skill.is_active ? 'checked' : ''} style="width:16px; height:16px; cursor:pointer; accent-color:var(--accent);">
                                <span style="font-size:12px; color:var(--accent); font-weight:600;">有効</span>
                            </label>
                            <label style="display:flex; align-items:center; cursor:pointer; gap:5px;">
                                <input type="checkbox" id="swal-skill-allows-file-output" ${skill.allows_file_output ? 'checked' : ''} style="width:16px; height:16px; cursor:pointer; accent-color:var(--accent);">
                                <span style="font-size:12px; color:var(--content-text-muted); font-weight:600;">ファイル出力</span>
                            </label>
                        </div>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
                        <div>
                            <label ${WF_SWAL.lbl}>スキル名 <span style="color:var(--accent);">*</span></label>
                            <input id="swal-skill-name" ${WF_SWAL.inp} placeholder="例: 記事要約スキル" value="${_esc(skill.name)}" required>
                        </div>
                        <div>
                            <label ${WF_SWAL.lbl}>説明</label>
                            <textarea id="swal-skill-description" ${WF_SWAL.txa(60)} placeholder="このスキルの用途">${_esc(skill.description)}</textarea>
                        </div>
                    </div>
                    <!-- 実行方式の必須選択: API か CLI -->
                    <div style="margin-bottom:12px;">
                        <label ${WF_SWAL.lbl}>実行方式 <span style="color:var(--accent);">*</span></label>
                        <div style="display:flex; gap:8px;">
                            <label data-runtime-mode-label="api" style="flex:1; display:flex; align-items:center; gap:8px; padding:10px 12px; border:2px solid rgba(0,0,0,0.12); border-radius:8px; cursor:pointer;">
                                <input type="radio" name="swal-skill-runtime-mode" value="api" ${(!(skill.config_json && skill.config_json.execution_config && skill.config_json.execution_config.execution && skill.config_json.execution_config.execution.execution_kind === 'external_cli')) ? 'checked' : ''} style="accent-color:var(--accent);">
                                <div>
                                    <div style="font-size:13px; font-weight:600;">API（HTTP provider）</div>
                                    <div style="font-size:11px; color:var(--content-text-muted);">OpenAI / Gemini / Claude など、クラウドAPIで実行</div>
                                </div>
                            </label>
                            <label data-runtime-mode-label="cli" style="flex:1; display:flex; align-items:center; gap:8px; padding:10px 12px; border:2px solid rgba(0,0,0,0.12); border-radius:8px; cursor:pointer;">
                                <input type="radio" name="swal-skill-runtime-mode" value="cli" ${(skill.config_json && skill.config_json.execution_config && skill.config_json.execution_config.execution && skill.config_json.execution_config.execution.execution_kind === 'external_cli') ? 'checked' : ''} style="accent-color:var(--accent);">
                                <div>
                                    <div style="font-size:13px; font-weight:600;">CLI（ローカル実行）</div>
                                    <div style="font-size:11px; color:var(--content-text-muted);">claude / codex などローカルにインストール済みのCLI</div>
                                </div>
                            </label>
                        </div>
                    </div>

                    <!-- Agent Profile は実行方式と独立: API/CLI どちらでも有効 -->
                    <div style="margin-bottom:12px;">
                        <label ${WF_SWAL.lbl}>Agent Profile</label>
                        <select id="swal-default-agent-profile" ${WF_SWAL.sel}>
                            ${renderAgentProfileOptions(skill.default_agent_profile || 'default')}
                        </select>
                        <small ${WF_SWAL.hint}>Explore=調査 / Plan=設計 / Implement=実装 / Verification=検証（API/CLIどちらでも有効）</small>
                    </div>

                    <div data-runtime-api-section>
                        <label ${WF_SWAL.lbl}>AIモデル <span style="color:var(--accent);">*</span></label>
                        <select id="swal-skill-model" ${WF_SWAL.sel} required onchange="_updateModelBadge('swal-skill-model','swal-skill-model-badge')">
                            <optgroup label="OpenAI">
                                <option value="gpt-5.4" ${_sel(skill.model_type,'gpt-5.4')}>GPT-5.4 NEW</option>
                                    <option value="gpt-5.4-mini" ${_sel(skill.model_type,'gpt-5.4-mini')}>GPT-5.4 Mini NEW</option>
                                    <option value="gpt-5.4-pro" ${_sel(skill.model_type,'gpt-5.4-pro')}>GPT-5.4 Pro NEW</option>
                                    <option value="gpt-5.4-thinking" ${_sel(skill.model_type,'gpt-5.4-thinking')}>GPT-5.4 Thinking NEW</option>
                                    <option value="gpt-5.2" ${_sel(skill.model_type,'gpt-5.2')}>GPT-5.2</option>
                                    <option value="gpt-5.2-pro" ${_sel(skill.model_type,'gpt-5.2-pro')}>GPT-5.2 Pro</option>
                                    <option value="gpt-5.2-thinking" ${_sel(skill.model_type,'gpt-5.2-thinking')}>GPT-5.2 Thinking</option>
                                    <option value="o4-mini" ${_sel(skill.model_type,'o4-mini')}>o4-mini</option>
                                </optgroup>
                                <optgroup label="Gemini">
                                    <option value="gemini-3.1-pro-preview" ${_selDT(skill.model_type,skill.enable_deep_think,'gemini-3.1-pro-preview')}>Gemini 3.1 Pro NEW</option>
                                    <option value="gemini-3.1-pro-preview-deep-think" ${_selDT(skill.model_type,skill.enable_deep_think,'gemini-3.1-pro-preview-deep-think')}>Gemini 3.1 Pro Deep Think NEW</option>
                                    <option value="gemini-3-pro-preview" ${_selDT(skill.model_type,skill.enable_deep_think,'gemini-3-pro-preview')}>Gemini 3.0 Pro</option>
                                    <option value="gemini-3-pro-preview-deep-think" ${_selDT(skill.model_type,skill.enable_deep_think,'gemini-3-pro-preview-deep-think')}>Gemini 3.0 Pro Deep Think</option>
                                    <option value="gemini-2.5-pro" ${_sel(skill.model_type,'gemini-2.5-pro')}>Gemini 2.5 Pro</option>
                                    <option value="gemini-2.5-flash" ${_sel(skill.model_type,'gemini-2.5-flash')}>Gemini 2.5 Flash</option>
                                </optgroup>
                                <optgroup label="Claude">
                                    <option value="claude-sonnet-4-6" ${_sel(skill.model_type,'claude-sonnet-4-6')}>Claude Sonnet 4.6</option>
                                    <option value="claude-sonnet-4-6-thinking" ${_sel(skill.model_type,'claude-sonnet-4-6-thinking')}>Claude Sonnet 4.6 Thinking</option>
                                    <option value="claude-opus-4-6" ${_sel(skill.model_type,'claude-opus-4-6')}>Claude Opus 4.6</option>
                                    <option value="claude-opus-4-6-thinking" ${_sel(skill.model_type,'claude-opus-4-6-thinking')}>Claude Opus 4.6 Thinking</option>
                                    <option value="claude-haiku-4-5" ${_sel(skill.model_type,'claude-haiku-4-5')}>Claude Haiku 4.5</option>
                                </optgroup>
                        </select>
                    </div>

                    <div data-runtime-cli-section style="display:none; margin-top:4px;">
                        <small ${WF_SWAL.hint} style="display:block; margin-bottom:6px;">
                            CLI 実行では claude-code / codex などローカルにインストール済みの CLI を使用します。
                            ワークフローに組み込まれた際もこの設定が既定値になります。
                        </small>
                        <div id="swal-skill-execution-config-mount"></div>
                    </div>
                </div>

                <!-- スキル内容カード -->
                <div ${WF_SWAL.leaderCard}>
                    <span ${WF_SWAL.secTitle}>スキル内容</span>
                    <div ${WF_SWAL.fld}>
                        <label ${WF_SWAL.lbl}>プロンプト <span style="color:var(--accent);">*</span></label>
                        <textarea id="swal-skill-content" ${WF_SWAL.txa(180)} placeholder="スキル内容を入力してください。" required style="font-family:monospace;">${_esc(skillContent)}</textarea>
                        <small ${WF_SWAL.hint}>変数の例: {{article_text}}, {{input}}, {{query}} など</small>
                    </div>
                    <div ${WF_SWAL.fld}>
                        <label ${WF_SWAL.lbl}>入力スキーマ（JSON形式、オプション）</label>
                        <textarea id="swal-skill-schema" ${WF_SWAL.txa(100)} placeholder='{"field_name": {"type": "string"}}' style="font-family:monospace; font-size:12px;">${skill.input_schema ? formatJSON(skill.input_schema).replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''}</textarea>
                        <small ${WF_SWAL.hint}>ユーザー入力フィールドの定義（省略可能）</small>
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
        customClass: {
            popup: 'swal-scrollable-popup',
            htmlContainer: 'swal-scrollable-container'
        },
        didOpen: () => {
            const sel = document.getElementById('swal-skill-model');
            if (sel) {
                const badge = document.createElement('div');
                badge.id = 'swal-skill-model-badge';
                badge.style.cssText = 'margin-top:4px; font-size:11px;';
                sel.parentNode.appendChild(badge);
                _updateModelBadge('swal-skill-model', 'swal-skill-model-badge');
            }
            const mount = document.getElementById('swal-skill-execution-config-mount');
            if (mount && window.executionConfigForm) {
                // スキルに既存の execution_config がある場合はそれで事前入力し、
                // なければ external_cli をデフォルトとして開始して、
                // CLI に切り替えた際に種別を選択する追加クリックを不要にする。
                const existing = (skill.config_json && skill.config_json.execution_config) || null;
                let initial = existing;
                if (!initial) {
                    initial = window.executionConfigForm.defaultConfig();
                    initial.execution.execution_kind = 'external_cli';
                }
                mount.innerHTML = window.executionConfigForm.renderForm(initial);
                window.executionConfigForm.attachDynamicWiring(mount);
            }
            _wireSkillRuntimeModeToggle();
        },
        preConfirm: () => _collectSkillFormValues()
    });

    if (formValues) {
        await saveSkill(id, formValues);
    }
}

async function saveSkill(id, formValues) {
    // config_json ペイロード。バックエンドは辞書を受け付け、未指定/空は
    // 「レガシーに戻す」を意味する。フォームがデフォルトから実際に
    // 変更された場合のみ execution_config を設定する。
    const configJson = formValues.executionConfig
        ? { execution_config: formValues.executionConfig }
        : {};

    const data = {
        name: formValues.name,
        description: formValues.description,
        model_type: formValues.model,
        content: formValues.content,
        input_schema: formValues.inputSchema,
        is_active: formValues.isActive,
        allows_file_output: formValues.allowsFileOutput,
        enable_deep_think: formValues.enableDeepThink,
        default_agent_profile: formValues.defaultAgentProfile || 'default',
        config_json: configJson
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
        await Swal.fire({
            title: 'スキル内容',
            html: `
                <div style="text-align:left;">
                    <div ${WF_SWAL.leaderCard}>
                        <div style="background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; padding:16px; white-space:pre-wrap; word-wrap:break-word; font-family:monospace; font-size:13px; line-height:1.6; color:var(--content-text); max-height:60vh; overflow-y:auto;">${data.content}</div>
                    </div>
                </div>
            `,
            width: '900px',
            showConfirmButton: false,
            customClass: { popup: 'swal-wide swal-scrollable-popup' }
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
        html: `
            <div style="text-align:center;">
                <div ${WF_SWAL.leaderCard} style="border-left:3px solid #dc3545;">
                    <p style="color:var(--content-text); font-size:14px; margin:0;">本当に「<strong>${skill.name}</strong>」を削除しますか？</p>
                    <p style="color:var(--content-text-muted); font-size:12px; margin:8px 0 0;">この操作は取り消せません。</p>
                </div>
            </div>
        `,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: '削除',
        cancelButtonText: ADMIN_SWAL.btnClose,
        cancelButtonColor: ADMIN_SWAL.secondary,
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
                <!-- 対象スキル情報 -->
                <div ${WF_SWAL.leaderCard}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                        <span ${WF_SWAL.secTitle} style="margin-bottom:0;">対象スキル</span>
                    </div>
                    <div style="background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; padding:12px 14px;">
                        <div style="font-size:14px; font-weight:600; color:var(--content-text);">${_wfbEsc(skill.name)}</div>
                        <div style="font-size:12px; color:var(--content-text-muted); margin-top:4px;">ID: ${skill.id} / ${_wfbEsc(skill.model_type || '')}</div>
                    </div>
                </div>

                <!-- ワークフロー所属 -->
                <div ${WF_SWAL.leaderCard}>
                    <span ${WF_SWAL.secTitle}>既存ワークフローへの所属</span>
                    <small ${WF_SWAL.hint}>含めるワークフローにチェックを付けます。外すとそのワークフローから除外されます（保存で反映）。</small>
                    <div id="wf-membership-container" style="margin-top:10px; border:1px solid rgba(0,0,0,0.06); border-radius:10px; padding:8px 10px; max-height:240px; overflow-y:auto; background:#fff;">
                        <div style="text-align:center; padding:14px; color:var(--content-text-muted); font-size:13px;">読み込み中...</div>
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
                    container.innerHTML = '<div style="text-align:center; padding:14px; color:var(--content-text-muted); font-size:13px;">ワークフローがまだ登録されていません</div>';
                    return;
                }

                container.innerHTML = details
                    .map(wf => {
                        const hasPrompt = (wf.skills || []).some(s => s.skill_id === skillId);
                        return `
                            <label class="wf-membership-row">
                                <input type="checkbox" class="wf-membership-checkbox" data-workflow-id="${wf.id}" ${hasPrompt ? 'checked' : ''} style="margin-top:2px; accent-color:var(--accent); width:16px; height:16px;">
                                <div style="flex:1; min-width:0;">
                                    <div style="font-size:13px; font-weight:bold; color:var(--content-text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${_wfbEsc(wf.name)}</div>
                                    <div style="font-size:12px; color:var(--content-text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                                        ID: ${wf.id} / ${wf.is_active ? '有効' : '無効'}
                                    </div>
                                </div>
                            </label>
                        `;
                    })
                    .join('');
            } catch (e) {
                console.error('Load workflows for skill error:', e);
                container.innerHTML = '<div style="text-align:center; padding:14px; color:var(--content-text-muted); font-size:13px;">ワークフローの取得に失敗しました</div>';
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
        <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; margin-bottom:4px;">
            <div style="width:24px; height:24px; border-radius:50%; background:var(--accent); display:flex; align-items:center; justify-content:center; font-size:12px; color:#fff; flex-shrink:0;">★</div>
            <div>
                <div style="font-size:12px; font-weight:600; color:var(--accent);">Leader: タスク振り分け</div>
                <div style="font-size:11px; color:var(--content-text);" id="wf-create-wf-subtitle">新規ワークフロー</div>
            </div>
        </div>`;
    const WF_LEADER_END = `
        <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; margin-top:4px;">
            <div style="width:24px; height:24px; border-radius:50%; background:var(--accent); display:flex; align-items:center; justify-content:center; font-size:12px; color:#fff; flex-shrink:0;">★</div>
            <div>
                <div style="font-size:12px; font-weight:600; color:var(--accent);">Leader: 結果統合</div>
                <div style="font-size:11px; color:var(--content-text);">全結果を統合して最終出力を生成</div>
            </div>
        </div>`;

    const { value: formValues } = await Swal.fire({
        title: 'ワークフローを作成',
        html: `
            <div class="swal-no-scroll" style="max-height: 75vh; overflow-y: auto; text-align: left; width: 100%; box-sizing: border-box;">
                <!-- ワークフロー基本情報カード -->
                <div ${WF_SWAL.leaderCard}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <span ${WF_SWAL.secTitle} style="margin-bottom:0;">ワークフロー情報</span>
                        <label style="display:flex; align-items:center; cursor:pointer; gap:6px;">
                            <input type="checkbox" id="swal-wf-is-active" checked style="width:16px; height:16px; cursor:pointer; accent-color:var(--accent);">
                            <span style="font-size:12px; color:var(--accent); font-weight:600;">有効</span>
                        </label>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                        <div>
                            <label ${WF_SWAL.lbl}>ワークフロー名 <span style="color: var(--accent);">*</span></label>
                            <input id="swal-wf-name" type="text" ${WF_SWAL.inp} placeholder="例: 記事作成ワークフロー">
                        </div>
                        <div>
                            <label ${WF_SWAL.lbl}>説明</label>
                            <textarea id="swal-wf-description" rows="2" ${WF_SWAL.txa(60)} placeholder="このワークフローの用途"></textarea>
                        </div>
                    </div>
                </div>

                <!-- 親スキル + 実行フロー（同じカード） -->
                <div ${WF_SWAL.leaderCard}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <span ${WF_SWAL.secTitle} style="margin-bottom:0;">親スキル & 実行フロー</span>
                        <button type="button" onclick="wfCreateAddGroup()" style="padding:5px 12px; background:var(--accent); border:none; border-radius:16px; color:#fff; cursor:pointer; font-size:12px; font-weight:600; white-space:nowrap;">+ グループ追加</button>
                    </div>

                    <!-- 親スキル設定 -->
                    <div style="background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; padding:14px; margin-bottom:12px;">
                        <div style="font-size:12px; font-weight:600; color:var(--content-text-muted); text-transform:uppercase; letter-spacing:0.3px; margin-bottom:10px;">親スキル（Leader）</div>
                        <input type="hidden" id="swal-parent-mode" value="required">
                        <input type="hidden" id="swal-supervisor-mode" value="disabled">

                        <!-- 実行方式の必須選択: API か CLI（スキル作成モーダルと同じ UI） -->
                        <div style="margin-bottom:12px;">
                            <label ${WF_SWAL.lbl}>実行方式 <span style="color:var(--accent);">*</span></label>
                            <div style="display:flex; gap:8px;">
                                <label data-wfcreate-parent-runtime-label="api" style="flex:1; display:flex; align-items:center; gap:8px; padding:10px 12px; border:2px solid var(--accent); border-radius:8px; cursor:pointer; background:rgba(0,120,215,0.06);">
                                    <input type="radio" name="swal-wfcreate-parent-runtime-mode" value="api" checked style="accent-color:var(--accent);">
                                    <div>
                                        <div style="font-size:13px; font-weight:600;">API（HTTP provider）</div>
                                        <div style="font-size:11px; color:var(--content-text-muted);">OpenAI / Gemini / Claude など、クラウドAPIで実行</div>
                                    </div>
                                </label>
                                <label data-wfcreate-parent-runtime-label="cli" style="flex:1; display:flex; align-items:center; gap:8px; padding:10px 12px; border:2px solid rgba(0,0,0,0.12); border-radius:8px; cursor:pointer;">
                                    <input type="radio" name="swal-wfcreate-parent-runtime-mode" value="cli" style="accent-color:var(--accent);">
                                    <div>
                                        <div style="font-size:13px; font-weight:600;">CLI（ローカル実行）</div>
                                        <div style="font-size:11px; color:var(--content-text-muted);">claude / codex などローカルにインストール済みのCLI</div>
                                    </div>
                                </label>
                            </div>
                        </div>

                        <!-- CLI 詳細フォーム（API モードでは非表示） -->
                        <div data-wfcreate-parent-cli-section style="display:none; margin-bottom:12px;">
                            <small style="display:block; color:var(--content-text-muted); font-size:11px; margin-bottom:6px;">
                                CLI 実行では claude-code / codex などローカル CLI を使用します。adapter と cwd ヒントが必須です。
                            </small>
                            <div id="swal-wfcreate-parent-exec-config-mount"></div>
                        </div>

                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                            <div>
                                <label ${WF_SWAL.lbl}>スキル名 <span style="color: var(--accent);">*</span></label>
                                <input id="swal-leader-name" type="text" ${WF_SWAL.inp} placeholder="例: 記事統合スキル">
                            </div>
                            <div data-wfcreate-parent-api-section>
                                <label ${WF_SWAL.lbl}>AIモデル <span style="color: var(--accent);">*</span></label>
                                <select id="swal-leader-model" ${WF_SWAL.sel} onchange="_updateModelBadge('swal-leader-model','swal-leader-model-badge')">
                                    <optgroup label="OpenAI">
                                        <option value="gpt-5.4" selected>GPT-5.4 NEW</option>
                                        <option value="gpt-5.4-pro">GPT-5.4 Pro NEW</option>
                                        <option value="gpt-5.2">GPT-5.2</option>
                                        <option value="gpt-5.2-pro">GPT-5.2 Pro</option>
                                        <option value="gpt-5.1">GPT-5.1</option>
                                    </optgroup>
                                    <optgroup label="Gemini">
                                        <option value="gemini-3.1-pro-preview">Gemini 3.1 Pro NEW</option>
                                        <option value="gemini-3.1-pro-preview-deep-think">Gemini 3.1 Pro Deep Think NEW</option>
                                        <option value="gemini-3-pro-preview">Gemini 3.0 Pro</option>
                                    </optgroup>
                                    <optgroup label="Claude">
                                        <option value="claude-sonnet-4-6">Claude Sonnet 4.6</option>
                                        <option value="claude-opus-4-6">Claude Opus 4.6</option>
                                        <option value="claude-haiku-4-5">Claude Haiku 4.5</option>
                                    </optgroup>
                                </select>
                                <div id="swal-leader-model-badge" style="margin-top:4px; font-size:11px;"></div>
                            </div>
                        </div>
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px;">
                            <div>
                                <label ${WF_SWAL.lbl}>説明</label>
                                <textarea id="swal-leader-description" rows="2" ${WF_SWAL.txa(50)} placeholder="親スキルの説明"></textarea>
                            </div>
                            <div style="display:flex; flex-direction:column; justify-content:flex-end;">
                                <input type="hidden" id="swal-leader-content" value="(自動生成)">
                                <small style="color:var(--content-text-muted); font-size:11px; margin-bottom:8px;">スキル内容は自動生成されます</small>
                                <label style="display: flex; align-items: center; cursor: pointer;">
                                    <input type="checkbox" id="swal-leader-deep-think" checked style="margin-right: 6px; width: 16px; height: 16px; cursor: pointer;">
                                    <span style="font-size: 12px; color: var(--content-text);">Deep Think</span>
                                </label>
                            </div>
                        </div>
                    </div>

                    <!-- 実行フロー -->
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
            _wfCreateParentExecConfig = null;

            // CLI 詳細フォームを事前マウント（隠れているが DOM には存在）。
            // execution-config-form は adapter / runtime_hint / cwd /
            // workspace_policy / approval_policy など CLI 固有の詳細を
            // すべて一括で表示するので、ここに入れるだけで claude / codex
            // 選択もユーザーに見える。
            const cliMount = document.getElementById('swal-wfcreate-parent-exec-config-mount');
            if (cliMount && window.executionConfigForm) {
                const seed = window.executionConfigForm.defaultConfig();
                seed.execution = seed.execution || {};
                seed.execution.execution_kind = 'external_cli';
                cliMount.innerHTML = window.executionConfigForm.renderForm(seed);
                window.executionConfigForm.attachDynamicWiring(cliMount);
            }

            // API / CLI ラジオ切替配線
            const radios = document.querySelectorAll('input[name="swal-wfcreate-parent-runtime-mode"]');
            const apiSec = document.querySelector('[data-wfcreate-parent-api-section]');
            const cliSec = document.querySelector('[data-wfcreate-parent-cli-section]');
            const modelSel = document.getElementById('swal-leader-model');
            const apiLabel = document.querySelector('[data-wfcreate-parent-runtime-label="api"]');
            const cliLabel = document.querySelector('[data-wfcreate-parent-runtime-label="cli"]');
            function applyParentRuntimeToggle() {
                const mode = (document.querySelector('input[name="swal-wfcreate-parent-runtime-mode"]:checked') || {}).value || 'api';
                if (mode === 'cli') {
                    if (apiSec) apiSec.style.display = 'none';
                    if (cliSec) cliSec.style.display = 'block';
                    if (modelSel) modelSel.required = false;
                    if (apiLabel) { apiLabel.style.borderColor = 'rgba(0,0,0,0.12)'; apiLabel.style.background = 'transparent'; }
                    if (cliLabel) { cliLabel.style.borderColor = 'var(--accent)'; cliLabel.style.background = 'rgba(0,120,215,0.06)'; }
                } else {
                    if (apiSec) apiSec.style.display = 'block';
                    if (cliSec) cliSec.style.display = 'none';
                    if (modelSel) modelSel.required = true;
                    if (apiLabel) { apiLabel.style.borderColor = 'var(--accent)'; apiLabel.style.background = 'rgba(0,120,215,0.06)'; }
                    if (cliLabel) { cliLabel.style.borderColor = 'rgba(0,0,0,0.12)'; cliLabel.style.background = 'transparent'; }
                }
            }
            radios.forEach(r => r.addEventListener('change', applyParentRuntimeToggle));
            applyParentRuntimeToggle();

            // バッジ初期表示
            _updateModelBadge('swal-leader-model', 'swal-leader-model-badge');
            const dtCheck = document.getElementById('swal-leader-deep-think');
            if (dtCheck) dtCheck.addEventListener('change', () => _updateModelBadge('swal-leader-model', 'swal-leader-model-badge'));

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

            // 親スキル実行方式（API / CLI）を解決してバリデーション
            const parentRuntimeMode = (document.querySelector('input[name="swal-wfcreate-parent-runtime-mode"]:checked') || {}).value || 'api';
            let parentConfigJson = null;
            if (parentRuntimeMode === 'cli') {
                const mount = document.getElementById('swal-wfcreate-parent-exec-config-mount');
                const root = mount && mount.querySelector('[data-exec-config-root]');
                if (!root || !window.executionConfigForm) {
                    Swal.showValidationMessage('CLI 設定フォームを読み込めませんでした');
                    return false;
                }
                const execCfg = window.executionConfigForm.collectForm(root);
                execCfg.execution = execCfg.execution || {};
                execCfg.execution.execution_kind = 'external_cli';
                if (!execCfg.execution.preferred_adapter && !execCfg.execution.cli_runtime_hint) {
                    Swal.showValidationMessage('CLI 実行では adapter を選択してください');
                    return false;
                }
                if (!execCfg.execution.cwd_hint) {
                    Swal.showValidationMessage('CLI 実行では cwd ヒント（作業ディレクトリ）が必須です');
                    return false;
                }
                parentConfigJson = { execution_config: execCfg };
                _wfCreateParentExecConfig = execCfg;
            } else {
                // API モード: モデル必須チェック
                if (!leaderModel) {
                    Swal.showValidationMessage('API 実行では AI モデルを選択してください');
                    return false;
                }
                _wfCreateParentExecConfig = null;
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
                config_json: g.config_json || null,
                skills: g.skills.map((sk, si) => ({
                    skill_id: sk.skill_id,
                    order_in_group: si + 1,
                    skill_name: sk.skill_name || `Step ${si + 1}`,
                    model_type: sk.model_type || null,
                    on_error: sk.on_error || 'stop',
                    max_retries: parseInt(sk.max_retries) || 0,
                    retry_delay_seconds: parseInt(sk.retry_delay_seconds) || 5,
                    depends_on: sk.depends_on || null,
                    output_key: sk.output_key || null,
                    input_mapping: sk.input_mapping || null,
                    quality_gate_type: sk.quality_gate_type || 'disabled',
                    quality_gate_prompt: sk.quality_gate_prompt || '',
                    quality_gate_model: sk.quality_gate_model || null,
                    max_reflection_loops: parseInt(sk.max_reflection_loops) || 0,
                    agent_profile: sk.agent_profile || 'default',
                    // enable_deep_think は親 Skill 由来の read-only 表示
                    // 専用 (WorkflowSkill 列なし)。送信しない。
                    config_json: sk.config_json || null,
                })),
            }));

            const supervisorMode = document.getElementById('swal-supervisor-mode')?.value || 'disabled';
            return {
                name,
                description,
                isActive,
                groups,
                supervisor_mode: supervisorMode,
                // ワークフローレベルの config_json（継承チェーンの最上位）。
                // 親が API 経由で実行される場合は null、または詳細フォームから
                // 収集された CLI 実行設定ブロック。
                config_json: parentConfigJson,
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
                config_json: formValues.config_json || null,
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
        container.innerHTML = '<div style="text-align:center; padding:24px 12px; color:var(--content-text-muted); font-size:13px;">グループがありません。右上の「+ グループ追加」から追加してください。</div>';
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
            // ステップごとのランタイムチップ — 共有リゾルバーを使い、
            // アプリ内の他のすべてのバッジと一致させる（ピル型、パレット）。
            const stepChipHtml = window.runtimeResolver
                ? window.runtimeResolver.renderResolvedRuntimeChip({ step: { config_json: sk.config_json } })
                : '';
            const advHtml = `
                <div style="margin-top:6px; padding:6px 8px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:8px; font-size:11px;">
                    <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                        <label style="color:var(--content-text-muted);">Profile:</label>
                        <select onchange="_wfbUpdateSkillField(${gi},${si},'agent_profile',this.value)" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px;">
                            ${renderAgentProfileOptions(sk.agent_profile || 'default')}
                        </select>
                        <button type="button" onclick="wfCreateEditStepExecutionConfig(${gi},${si})" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px; cursor:pointer; display:inline-flex; align-items:center; gap:4px;" title="このステップの実行ランタイムを上書き">
                            ⚙ ランタイム
                            ${stepChipHtml}
                        </button>
                        <span style="color:var(--content-text-muted); font-size:10px; margin-left:4px;">エラー時・品質ゲート・出力キーは自動設定</span>
                    </div>
                </div>`;
            if (useParallelLayout) {
                skillsHtml += `
                <div class="wf-create-skill" data-gi="${gi}" data-si="${si}" style="flex:1; min-width:180px; display:flex; flex-direction:column; gap:4px; padding:10px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; border-left:3px solid ${gColor}; cursor:grab;">
                    <div style="display:flex; align-items:flex-start; gap:6px;">
                        <span class="wf-create-skill-drag" style="cursor:grab; opacity:0.45; flex-shrink:0; padding-top:2px;">&#x2261;</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:13px; font-weight:bold; color:var(--content-text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${sName}${errBadge}</div>
                            <div style="font-size:12px; color:var(--content-text-muted);">${sModel}</div>
                        </div>
                        <button type="button" onclick="wfCreateRemoveSkill(${sk._uid})" style="background:none; border:none; color:var(--accent); cursor:pointer; font-size:14px; flex-shrink:0;" title="削除">&times;</button>
                    </div>
                    ${advHtml}
                </div>`;
            } else {
                const connector = si > 0
                    ? '<div style="display:flex; justify-content:flex-start; padding:2px 0 2px 20px;"><div style="width:1px; height:10px; background:rgba(0,0,0,0.06);"></div></div>'
                    : '';
                skillsHtml += `${connector}
                <div class="wf-create-skill" data-gi="${gi}" data-si="${si}" style="padding:8px 10px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; border-left:3px solid ${gColor}; cursor:grab; ${si > 0 ? 'margin-top:6px;' : ''}">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span class="wf-create-skill-drag" style="cursor:grab; opacity:0.45; flex-shrink:0;">&#x2261;</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:13px; font-weight:bold; color:var(--content-text);">${sName}${errBadge}</div>
                            <div style="font-size:12px; color:var(--content-text-muted);">${sModel}</div>
                        </div>
                        <button type="button" onclick="wfCreateRemoveSkill(${sk._uid})" style="background:none; border:none; color:var(--accent); cursor:pointer; font-size:14px; flex-shrink:0;" title="削除">&times;</button>
                    </div>
                    ${advHtml}
                </div>`;
            }
        });

        const skillsEmpty = useParallelLayout
            ? '<div style="flex:1; text-align:center; padding:14px; color:var(--content-text-muted); font-size:13px;">スキルを下のメニューから追加</div>'
            : '<div style="text-align:center; padding:14px; color:var(--content-text-muted); font-size:13px;">スキルを下のメニューから追加</div>';

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
                        <input type="text" id="wf-create-gname-${gi}" value="${_wfbEsc(grp.group_name)}" onchange="wfCreateUpdateGroup(${gi},'name',this.value)" placeholder="グループ名" class="swal2-input" style="flex:1; min-width:140px; margin-top:0; max-width:none; background:#fff; font-size:13px;">
                        <button type="button" onclick="wfCreateRemoveGroup(${gi})" style="background:none; border:none; color:var(--accent); cursor:pointer; font-size:16px; flex-shrink:0;" title="グループ削除">&times;</button>
                    </div>
                    ${grp.condition_expression ? `<div style="padding:4px 14px; background:rgba(255,193,7,0.08); font-size:11px; color:#ffc107;">条件: ${_wfbEsc(JSON.stringify(grp.condition_expression))}</div>` : ''}
                    <div style="padding:6px 14px; background:rgba(0,0,0,0.02); border-top:1px solid rgba(0,0,0,0.06); font-size:11px;">
                        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                            <label style="color:var(--content-text-muted);">動的:</label>
                            <select onchange="wfCreateUpdateGroup(${gi},'dynamic_mode',this.value)" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px;">
                                <option value="static" ${grp.dynamic_mode === 'static' ? 'selected' : ''}>静的</option>
                                <option value="dynamic" ${grp.dynamic_mode === 'dynamic' ? 'selected' : ''}>動的(プランナー)</option>
                            </select>
                            <span style="color:var(--content-text-muted); font-size:10px; margin-left:4px;">ジャッジ・SVは自動適用</span>
                        </div>
                    </div>
                    <div id="wf-create-skills-${gi}" style="${skillsWrapStyle}">
                        ${skillsHtml || skillsEmpty}
                    </div>
                    <div style="padding:8px 14px 12px; border-top:1px solid rgba(0,0,0,0.06);">
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
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--content-text-muted);">ワークフローがまだ登録されていません</td></tr>';
        return;
    }

    tbody.innerHTML = workflows.map(wf => {
        const wfCtx = { workflow: { config_json: wf.config_json } };
        const wfResolved = window.runtimeResolver
            ? window.runtimeResolver.resolveEffectiveRuntime(wfCtx)
            : { kind: 'api' };
        const wfModelDisplay = (wfResolved.kind === 'cli')
            ? window.runtimeResolver.effectiveModelLabel(wfCtx, '')
            : (typeof formatModelDisplay === 'function' ? formatModelDisplay(wf.parent_model_type || '', null, {}) : (wf.parent_model_type || '-'));
        const wfRuntimeChip = window.runtimeResolver
            ? window.runtimeResolver.renderResolvedRuntimeChip(wfCtx)
            : '';
        return `
        <tr>
            <td>${wf.id}</td>
            <td>${wf.name}</td>
            <td>${wf.description || '説明なし'}</td>
            <td>${wfRuntimeChip || '<span style="color:var(--content-text-muted); font-size:11px;">-</span>'}</td>
            <td>${wfModelDisplay}</td>
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
                    <button onclick="deleteWorkflow(${wf.id})" title="削除" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 22px; height: 22px; fill: #dc3545;"><path d="M9 3v1H4v2h1v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6h1V4h-5V3H9zm2 4h2v11h-2V7zm-4 0h2v11H7V7zm8 0h2v11h-2V7z"/></svg>
                    </button>
                </div>
            </td>
        </tr>
    `;
    }).join('');
}

async function deleteWorkflow(id) {
    const wf = workflows.find(w => w.id === id);
    if (!wf) return;
    const result = await Swal.fire({
        title: '削除の確認',
        html: `
            <div style="text-align:center;">
                <div ${WF_SWAL.leaderCard} style="border-left:3px solid #dc3545;">
                    <p style="color:var(--content-text); font-size:14px; margin:0;">本当に「<strong>${_wfbEsc(wf.name)}</strong>」を削除しますか？</p>
                    <p style="color:var(--content-text-muted); font-size:12px; margin:8px 0 0;">このワークフロー内で参照しているスキルは削除されません。</p>
                </div>
            </div>
        `,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: '削除',
        cancelButtonText: ADMIN_SWAL.btnClose,
        cancelButtonColor: ADMIN_SWAL.secondary,
    });
    if (!result.isConfirmed) return;
    try {
        await apiRequest(`/api/admin/workflows/${id}`, { method: 'DELETE' });
        await Swal.fire({
            title: '削除完了',
            text: 'ワークフローを削除しました',
            icon: 'success',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary,
        });
        loadWorkflows(wfCurrentPage);
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'ワークフローの削除に失敗しました: ' + (error.message || ''),
            icon: 'error',
            confirmButtonText: ADMIN_SWAL.btnClose,
            confirmButtonColor: ADMIN_SWAL.primary,
        });
        console.error('Delete workflow error:', error);
    }
}
window.deleteWorkflow = deleteWorkflow;

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
/** モデルセレクト変更時にバッジを更新 */
function _updateModelBadge(selectId, badgeId) {
    const sel = document.getElementById(selectId);
    const badge = document.getElementById(badgeId);
    if (!sel || !badge) return;
    const val = sel.value;
    // Deep Thinkチェックボックスがあれば取得
    const dtCheck = document.getElementById(selectId.replace('-model', '-deep-think'));
    const edt = dtCheck ? dtCheck.checked : val.includes('deep-think');
    badge.innerHTML = typeof formatModelDisplay === 'function'
        ? formatModelDisplay(val, null, { enable_deep_think: edt })
        : val;
}

const WF_SWAL = {
    lbl: 'style="display: block; font-weight: 600; margin-bottom: 5px; color: var(--content-text); font-size: 13px;"',
    fld: 'style="text-align: left; margin-bottom: 14px; width: 100%; box-sizing: border-box;"',
    inp: 'class="swal2-input" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;"',
    txa(minH) {
        return `class="swal2-textarea" style="min-height: ${minH}px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;"`;
    },
    sel: 'class="swal2-select" style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;"',
    hint: 'style="color: var(--content-text-muted); display: block; margin-top: 4px; font-size: 12px;"',
    secTitle: 'style="display: block; font-weight: 700; margin-bottom: 8px; color: var(--content-text); font-size: 14px;"',
    flowWrap: 'style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box; padding: 16px; background: var(--card-bg); border: 1px solid rgba(0,0,0,0.06); border-radius: 14px;"',
    leaderCard: 'style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box; padding: 16px; background: var(--card-bg); border: 1px solid rgba(0,0,0,0.06); border-radius: 14px;"',
    col: 'style="flex: 1; min-width: 220px; text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;"',
};

let _wfCreateStepUid = 0;
let _wfCreateGroups = [];
let _wfCreateUsableSkills = [];
// ワークフロー作成モーダルの親ランタイム状態（編集モーダルで使う
// _wfBuilderState とは別）。null = API モード、
// それ以外は完全な StepExecutionConfig オブジェクト。
let _wfCreateParentExecConfig = null;

function _wfFlowConnectorHtml() {
    return '<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(0,0,0,0.08);"></div></div>';
}

async function openWorkflowDetail(id) {
    try {
        const wf = await apiRequest(`/api/admin/workflows/${id}`);
        _wfBuilderState = {
            id: wf.id,
            name: wf.name,
            description: wf.description || '',
            is_active: wf.is_active,
            parent_skill_content: wf.parent_skill_content || '',
            parent_model_type: wf.parent_model_type || 'gpt-5.1',
            parent_enable_deep_think: wf.parent_enable_deep_think ?? true,
            supervisor_mode: wf.supervisor_mode || 'disabled',
            // ワークフローレベルの execution_config（継承チェーンの最上位）。
            // null = レガシー/デフォルトを使用。それ以外は execution_config を
            // ラップする辞書（skill/step と同じ形状）。
            config_json: wf.config_json || null,
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
                // グループレベルの execution_config（ワークフローとスキルの間に位置する）。
                config_json: g.config_json || null,
                skills: (g.skills || []).map(s => ({
                    skill_id: s.skill_id,
                    skill_name: s.skill_name || '',
                    model_type: s.model_type || '',
                    order_in_group: s.order_in_group || 1,
                    on_error: s.on_error || 'stop',
                    max_retries: s.max_retries || 0,
                    retry_delay_seconds: s.retry_delay_seconds || 5,
                    depends_on: s.depends_on || null,
                    output_key: s.output_key || '',
                    input_mapping: s.input_mapping || null,
                    quality_gate_type: s.quality_gate_type || 'disabled',
                    quality_gate_prompt: s.quality_gate_prompt || '',
                    quality_gate_model: s.quality_gate_model || null,
                    max_reflection_loops: s.max_reflection_loops || 0,
                    agent_profile: s.agent_profile || 'default',
                    enable_deep_think: s.enable_deep_think ?? null,
                    // ステップごとの execution_config 上書き（config_json 内に格納）。
                    // null = 親スキルの execution_config を継承する。
                    config_json: s.config_json || null,
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

    const flowConnector = _wfFlowConnectorHtml();

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
            // ステップごとのランタイムチップ — 共有リゾルバー、
            // アプリ内の他のすべてのバッジと一致。
            const stepChipHtml = window.runtimeResolver
                ? window.runtimeResolver.renderResolvedRuntimeChip({ step: { config_json: sk.config_json } })
                : '';
            const advHtml = `
                <div style="margin-top:6px; padding:6px 8px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:8px; font-size:11px;">
                    <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                        <label style="color:var(--content-text-muted);">Profile:</label>
                        <select onchange="_wfbUpdateSkillField(${gi},${si},'agent_profile',this.value)" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px;">
                            ${renderAgentProfileOptions(sk.agent_profile || 'default')}
                        </select>
                        <button type="button" onclick="_wfbEditStepExecutionConfig(${gi},${si})" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px; cursor:pointer; display:inline-flex; align-items:center; gap:4px;" title="このステップの実行ランタイムを上書き">
                            ⚙ ランタイム
                            ${stepChipHtml}
                        </button>
                        <span style="color:var(--content-text-muted); font-size:10px; margin-left:4px;">エラー時・品質ゲート・出力キーは自動設定</span>
                    </div>
                </div>`;
            if (useParallelLayout) {
                skillsHtml += `
                <div class="wfb-skill" data-gi="${gi}" data-si="${si}" style="flex:1; min-width:180px; display:flex; flex-direction:column; gap:4px; padding:10px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; border-left:3px solid ${gColor}; cursor:grab;">
                    <div style="display:flex; align-items:flex-start; gap:6px;">
                        <span class="wfb-skill-drag" style="cursor:grab; opacity:0.45; flex-shrink:0; padding-top:2px;">&#x2261;</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:13px; font-weight:bold; color:var(--content-text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${sName}${errBadge}</div>
                            <div style="font-size:12px; color:var(--content-text-muted);">${sModel}</div>
                        </div>
                        <button type="button" onclick="_wfbRemoveSkill(${gi},${si})" style="background:none; border:none; color:var(--accent); cursor:pointer; font-size:14px; flex-shrink:0;" title="削除">&times;</button>
                    </div>
                    ${advHtml}
                </div>`;
            } else {
                const connector = si > 0
                    ? `<div style="display:flex; justify-content:flex-start; padding:2px 0 2px 20px;"><div style="width:1px; height:10px; background:rgba(0,0,0,0.06);"></div></div>`
                    : '';
                skillsHtml += `${connector}
                <div class="wfb-skill" data-gi="${gi}" data-si="${si}" style="padding:8px 10px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; border-left:3px solid ${gColor}; cursor:grab; ${si > 0 ? 'margin-top:6px;' : ''}">
                    <div style="display:flex; align-items:center; gap:10px;">
                        <span class="wfb-skill-drag" style="cursor:grab; opacity:0.45; flex-shrink:0;">&#x2261;</span>
                        <div style="flex:1; min-width:0;">
                            <div style="font-size:13px; font-weight:bold; color:var(--content-text);">${sName}${errBadge}</div>
                            <div style="font-size:12px; color:var(--content-text-muted);">${sModel}</div>
                        </div>
                        <button type="button" onclick="_wfbRemoveSkill(${gi},${si})" style="background:none; border:none; color:var(--accent); cursor:pointer; font-size:14px; flex-shrink:0;" title="削除">&times;</button>
                    </div>
                    ${advHtml}
                </div>`;
            }
        });

        const skillsEmpty = useParallelLayout
            ? '<div style="flex:1; text-align:center; padding:14px; color:var(--content-text-muted); font-size:13px;">スキルをドラッグまたは下のメニューから追加</div>'
            : '<div style="text-align:center; padding:14px; color:var(--content-text-muted); font-size:13px;">スキルをドラッグまたは下のメニューから追加</div>';

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
                        <input type="text" value="${_wfbEsc(grp.group_name)}" onchange="_wfbUpdateGroup(${gi},'name',this.value)" placeholder="グループ名" class="swal2-input" style="flex:1; min-width:140px; margin-top:0; max-width:none; background:#fff; font-size:13px;">
                        <button type="button" onclick="_wfbEditGroupExecutionConfig(${gi})" title="グループ既定の実行ランタイム (CLI / ローカルLLM 等)" style="background:${grp.config_json && grp.config_json.execution_config ? 'var(--accent)' : '#fff'}; color:${grp.config_json && grp.config_json.execution_config ? '#fff' : 'var(--content-text-muted)'}; border:1px solid rgba(0,0,0,0.12); border-radius:14px; padding:3px 10px; font-size:11px; cursor:pointer; flex-shrink:0;">⚙ ランタイム${grp.config_json && grp.config_json.execution_config ? '✓' : ''}</button>
                        <button type="button" onclick="_wfbRemoveGroup(${gi})" style="background:none; border:none; color:var(--accent); cursor:pointer; font-size:16px; flex-shrink:0;" title="グループ削除">&times;</button>
                    </div>
                    ${grp.condition_expression ? `<div style="padding:4px 14px; background:rgba(255,193,7,0.08); font-size:11px; color:#ffc107;">条件: ${_wfbEsc(JSON.stringify(grp.condition_expression))}</div>` : ''}
                    <div style="padding:6px 14px; background:rgba(0,0,0,0.02); border-top:1px solid rgba(0,0,0,0.06); font-size:11px;">
                        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                            <label style="color:var(--content-text-muted);">動的:</label>
                            <select onchange="_wfbUpdateGroup(${gi},'dynamic_mode',this.value)" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px;">
                                <option value="static" ${grp.dynamic_mode === 'static' ? 'selected' : ''}>静的</option>
                                <option value="dynamic" ${grp.dynamic_mode === 'dynamic' ? 'selected' : ''}>動的(プランナー)</option>
                            </select>
                            ${grp.execution_type === 'parallel' ? (() => {
                                const jExec = (grp.config_json && grp.config_json.judge_execution_config && grp.config_json.judge_execution_config.execution) || {};
                                const jKind = jExec.execution_kind === 'external_cli' ? 'cli' : 'api';
                                const jAdapter = jExec.preferred_adapter || '';
                                return `
                                <label style="color:var(--content-text-muted); margin-left:8px;">判定:</label>
                                <select onchange="_wfbSetJudgeKind(${gi},this.value)" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px;" title="判定の実行方式 (APIプロバイダ or CLIサブプロセス)">
                                    <option value="api" ${jKind === 'api' ? 'selected' : ''}>API</option>
                                    <option value="cli" ${jKind === 'cli' ? 'selected' : ''}>CLI</option>
                                </select>
                                ${jKind === 'api' ? `
                                <select onchange="_wfbUpdateGroup(${gi},'judge_model',this.value)" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px;" title="判定に使うモデル。空欄なら親モデル">
                                    <option value="" ${!grp.judge_model ? 'selected' : ''}>(親モデル)</option>
                                    <optgroup label="OpenAI">
                                        <option value="gpt-5.4" ${grp.judge_model === 'gpt-5.4' ? 'selected' : ''}>GPT-5.4</option>
                                        <option value="gpt-5.4-mini" ${grp.judge_model === 'gpt-5.4-mini' ? 'selected' : ''}>GPT-5.4 Mini</option>
                                        <option value="o4-mini" ${grp.judge_model === 'o4-mini' ? 'selected' : ''}>o4-mini</option>
                                    </optgroup>
                                    <optgroup label="Anthropic">
                                        <option value="claude-sonnet-4-6" ${grp.judge_model === 'claude-sonnet-4-6' ? 'selected' : ''}>Claude Sonnet 4.6</option>
                                        <option value="claude-opus-4-6" ${grp.judge_model === 'claude-opus-4-6' ? 'selected' : ''}>Claude Opus 4.6</option>
                                        <option value="claude-haiku-4-5" ${grp.judge_model === 'claude-haiku-4-5' ? 'selected' : ''}>Claude Haiku 4.5</option>
                                    </optgroup>
                                    <optgroup label="Gemini">
                                        <option value="gemini-3.1-pro-preview" ${grp.judge_model === 'gemini-3.1-pro-preview' ? 'selected' : ''}>Gemini 3.1 Pro</option>
                                        <option value="gemini-2.5-flash" ${grp.judge_model === 'gemini-2.5-flash' ? 'selected' : ''}>Gemini 2.5 Flash</option>
                                    </optgroup>
                                </select>
                                ` : `
                                <select onchange="_wfbSetJudgeAdapter(${gi},this.value)" style="font-size:11px; padding:4px 8px; background:#fff; color:var(--content-text); border:1px solid rgba(0,0,0,0.1); border-radius:8px;" title="判定に使うCLIアダプタ">
                                    <option value="claude-code-local" ${jAdapter === 'claude-code-local' ? 'selected' : ''}>Claude Code</option>
                                    <option value="codex-local" ${jAdapter === 'codex-local' ? 'selected' : ''}>Codex</option>
                                </select>
                                `}
                                `;
                            })() : ''}
                            <span style="color:var(--content-text-muted); font-size:10px; margin-left:4px;">ジャッジ・SVは自動適用</span>
                        </div>
                    </div>
                    <div id="wfb-skills-${gi}" style="${skillsWrapStyle}">
                        ${skillsHtml || skillsEmpty}
                    </div>
                    <div style="padding:8px 14px 12px; border-top:1px solid rgba(0,0,0,0.06);">
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
        <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; margin-bottom:4px;">
            <div style="width:24px; height:24px; border-radius:50%; background:var(--accent); display:flex; align-items:center; justify-content:center; font-size:12px; color:#fff; flex-shrink:0;">★</div>
            <div>
                <div style="font-size:12px; font-weight:600; color:var(--accent);">Leader: タスク振り分け</div>
                <div style="font-size:11px; color:var(--content-text);">${_wfbEsc(s.name || 'ワークフロー')}</div>
            </div>
        </div>`;

    const leaderEnd = `
        <div style="display:flex; align-items:center; gap:10px; padding:10px 14px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; margin-top:4px;">
            <div style="width:24px; height:24px; border-radius:50%; background:var(--accent); display:flex; align-items:center; justify-content:center; font-size:12px; color:#fff; flex-shrink:0;">★</div>
            <div>
                <div style="font-size:12px; font-weight:600; color:var(--accent);">Leader: 結果統合</div>
                <div style="font-size:11px; color:var(--content-text);">全結果を統合して最終出力を生成</div>
            </div>
        </div>`;

    const parentRuntimeMode = _wfbParentRuntimeMode(s);
    const existingWfExecCfg = (s.config_json && s.config_json.execution_config) || null;

    const flowColumn = `
        <div ${WF_SWAL.leaderCard}>
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; gap:8px; flex-wrap:wrap;">
                <span ${WF_SWAL.secTitle} style="margin-bottom:0;">親スキル & 実行フロー</span>
                <div style="display:flex; gap:8px;">
                    <button type="button" onclick="_wfbAddGroup()" style="padding:5px 12px; background:var(--accent); border:none; border-radius:16px; color:#fff; cursor:pointer; font-size:12px; font-weight:600; white-space:nowrap;">+ グループ追加</button>
                </div>
            </div>

            <!-- 親スキル設定 -->
            <div style="background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:10px; padding:14px; margin-bottom:12px;">
                <div style="font-size:12px; font-weight:600; color:var(--content-text-muted); text-transform:uppercase; letter-spacing:0.3px; margin-bottom:10px;">親スキル（Leader）</div>
                <input type="hidden" id="wfb-parent-mode" value="required">
                <input type="hidden" id="wfb-supervisor-mode" value="disabled">

                <!-- 実行方式の必須選択: API か CLI（スキル作成モーダルと同じ UI） -->
                <div style="margin-bottom:12px;">
                    <label ${WF_SWAL.lbl}>実行方式 <span style="color:var(--accent);">*</span></label>
                    <div style="display:flex; gap:8px;">
                        <label data-wfb-parent-runtime-label="api" style="flex:1; display:flex; align-items:center; gap:8px; padding:10px 12px; border:2px solid ${parentRuntimeMode === 'api' ? 'var(--accent)' : 'rgba(0,0,0,0.12)'}; border-radius:8px; cursor:pointer; background:${parentRuntimeMode === 'api' ? 'rgba(0,120,215,0.06)' : 'transparent'};">
                            <input type="radio" name="wfb-parent-runtime-mode" value="api" ${parentRuntimeMode === 'api' ? 'checked' : ''} style="accent-color:var(--accent);">
                            <div>
                                <div style="font-size:13px; font-weight:600;">API（HTTP provider）</div>
                                <div style="font-size:11px; color:var(--content-text-muted);">OpenAI / Gemini / Claude など、クラウドAPIで実行</div>
                            </div>
                        </label>
                        <label data-wfb-parent-runtime-label="cli" style="flex:1; display:flex; align-items:center; gap:8px; padding:10px 12px; border:2px solid ${parentRuntimeMode === 'cli' ? 'var(--accent)' : 'rgba(0,0,0,0.12)'}; border-radius:8px; cursor:pointer; background:${parentRuntimeMode === 'cli' ? 'rgba(0,120,215,0.06)' : 'transparent'};">
                            <input type="radio" name="wfb-parent-runtime-mode" value="cli" ${parentRuntimeMode === 'cli' ? 'checked' : ''} style="accent-color:var(--accent);">
                            <div>
                                <div style="font-size:13px; font-weight:600;">CLI（ローカル実行）</div>
                                <div style="font-size:11px; color:var(--content-text-muted);">claude / codex などローカルにインストール済みのCLI</div>
                            </div>
                        </label>
                    </div>
                </div>

                <!-- CLI 詳細フォーム（API モードでは非表示） -->
                <div data-wfb-parent-cli-section style="display:${parentRuntimeMode === 'cli' ? 'block' : 'none'}; margin-bottom:12px;">
                    <small style="display:block; color:var(--content-text-muted); font-size:11px; margin-bottom:6px;">
                        CLI 実行では claude-code / codex などローカル CLI を使用します。adapter と cwd ヒントが必須です。
                    </small>
                    <div id="wfb-parent-exec-config-mount"></div>
                </div>

                <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                    <div data-wfb-parent-api-section style="${parentRuntimeMode === 'cli' ? 'display:none;' : ''}">
                        <label ${WF_SWAL.lbl}>AIモデル <span style="color: var(--accent);">*</span></label>
                        <select id="wfb-parent-model" ${WF_SWAL.sel} onchange="_updateModelBadge('wfb-parent-model','wfb-parent-model-badge')">
                            ${MODEL_OPTIONS}
                        </select>
                        <div id="wfb-parent-model-badge" style="margin-top:4px; font-size:11px;"></div>
                    </div>
                    <div style="display:flex; flex-direction:column; justify-content:flex-end;">
                        <input type="hidden" id="wfb-parent-content" value="${s.parent_skill_content || '(自動生成)'}">
                        <small style="color:var(--content-text-muted); font-size:11px;">スキル内容は自動生成されます</small>
                    </div>
                </div>
            </div>

            <!-- 実行フロー -->
            <div style="font-size:12px; font-weight:600; color:var(--content-text-muted); text-transform:uppercase; letter-spacing:0.3px; margin-bottom:8px;">実行フロー</div>
            <div style="display:flex; flex-direction:column; gap:0;">
                ${leaderStart}
                ${flowConnector}
                <div id="wfb-groups-container">
                    ${groupsHtml || `<div style="text-align:center; padding:24px 12px; color:var(--content-text-muted); font-size:13px;">グループがありません。右上の「+ グループ追加」から追加してください。</div>`}
                </div>
                ${flowConnector}
                ${leaderEnd}
            </div>
        </div>`;

    Swal.fire({
        title: 'ワークフローを編集',
        html: `
            <div class="swal-no-scroll" style="max-height:75vh; overflow-y:auto; text-align:left; width:100%; box-sizing:border-box;">
                <!-- ワークフロー基本情報カード -->
                <div ${WF_SWAL.leaderCard}>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
                        <span ${WF_SWAL.secTitle} style="margin-bottom:0;">ワークフロー情報</span>
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                        <div>
                            <label ${WF_SWAL.lbl}>ワークフロー名 <span style="color: var(--accent);">*</span></label>
                            <input type="text" id="wfb-name" ${WF_SWAL.inp} value="${_wfbEsc(s.name)}" placeholder="例: 記事制作パイプライン">
                        </div>
                        <div>
                            <label ${WF_SWAL.lbl}>説明</label>
                            <textarea id="wfb-desc" rows="2" ${WF_SWAL.txa(60)} placeholder="このワークフローの用途">${_wfbEsc(s.description)}</textarea>
                        </div>
                    </div>
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
            _updateModelBadge('wfb-parent-model', 'wfb-parent-model-badge');

            // CLI 詳細フォームをマウント（既存の workflow.config_json を
            // 初期値として読み込む）。execution-config-form は adapter /
            // cli_runtime_hint / cwd_hint / workspace_policy /
            // approval_policy など CLI 固有項目を1つのフォームで扱う。
            const mount = document.getElementById('wfb-parent-exec-config-mount');
            if (mount && window.executionConfigForm) {
                let seed;
                if (existingWfExecCfg) {
                    seed = existingWfExecCfg;
                } else {
                    seed = window.executionConfigForm.defaultConfig();
                    seed.execution = seed.execution || {};
                    seed.execution.execution_kind = 'external_cli';
                }
                mount.innerHTML = window.executionConfigForm.renderForm(seed);
                window.executionConfigForm.attachDynamicWiring(mount);
            }

            // API / CLI ラジオ切替配線（作成モーダルと同じロジック）
            const radios = document.querySelectorAll('input[name="wfb-parent-runtime-mode"]');
            const apiSec = document.querySelector('[data-wfb-parent-api-section]');
            const cliSec = document.querySelector('[data-wfb-parent-cli-section]');
            const modelSel = document.getElementById('wfb-parent-model');
            const apiLabel = document.querySelector('[data-wfb-parent-runtime-label="api"]');
            const cliLabel = document.querySelector('[data-wfb-parent-runtime-label="cli"]');
            function applyToggle() {
                const mode = (document.querySelector('input[name="wfb-parent-runtime-mode"]:checked') || {}).value || 'api';
                if (mode === 'cli') {
                    if (apiSec) apiSec.style.display = 'none';
                    if (cliSec) cliSec.style.display = 'block';
                    if (modelSel) modelSel.required = false;
                    if (apiLabel) { apiLabel.style.borderColor = 'rgba(0,0,0,0.12)'; apiLabel.style.background = 'transparent'; }
                    if (cliLabel) { cliLabel.style.borderColor = 'var(--accent)'; cliLabel.style.background = 'rgba(0,120,215,0.06)'; }
                } else {
                    if (apiSec) apiSec.style.display = 'block';
                    if (cliSec) cliSec.style.display = 'none';
                    if (modelSel) modelSel.required = true;
                    if (apiLabel) { apiLabel.style.borderColor = 'var(--accent)'; apiLabel.style.background = 'rgba(0,120,215,0.06)'; }
                    if (cliLabel) { cliLabel.style.borderColor = 'rgba(0,0,0,0.12)'; cliLabel.style.background = 'transparent'; }
                }
            }
            radios.forEach(r => r.addEventListener('change', applyToggle));
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

// ワークフロービルダー内からステップごとの execution_config 上書きを編集する。
// SweetAlert2 は一度に1つのモーダルしか許可せず、外側のワークフロー
// ビルダーを閉じてしまうため、ここでは Swal.fire を使えない。代わりに
// Swal コンテナの上に高い z-index でプレーンなオーバーレイ div を配置し、
// 保存/キャンセル時に削除することで、ワークフロービルダーモーダルを
// そのまま維持する。
function _wfbEditStepExecutionConfig(gi, si) {
    if (!window.executionConfigForm) {
        showAlert('execution-config-form helper not loaded', 'error');
        return;
    }
    const sk = _wfBuilderState.groups[gi] && _wfBuilderState.groups[gi].skills[si];
    if (!sk) return;

    // 既存のオーバーレイを削除（防御的 — ユーザーが連打した場合に備えて）。
    const prior = document.getElementById('wfb-step-runtime-overlay');
    if (prior) prior.remove();

    const existing = (sk.config_json && sk.config_json.execution_config) || null;
    const formHtml = window.executionConfigForm.renderForm(existing);

    const overlay = document.createElement('div');
    overlay.id = 'wfb-step-runtime-overlay';
    // SweetAlert2 のデフォルト z-index (1060) より高く設定。外側の Swal
    // バックドロップはそのまま残り、ワークフロービルダーモーダルが
    // 表示されたまま閉じないようにする。
    overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:20000',
        'background:rgba(0,0,0,0.45)',
        'display:flex', 'align-items:center', 'justify-content:center',
    ].join(';');

    const stepLabel = (sk.skill_name || `Step ${si + 1}`);
    overlay.innerHTML = `
        <div style="background:#fff; border-radius:14px; width:min(720px,92vw); max-height:88vh; display:flex; flex-direction:column; box-shadow:0 24px 60px rgba(0,0,0,0.32);">
            <div style="padding:16px 20px; border-bottom:1px solid rgba(0,0,0,0.08); display:flex; align-items:center; justify-content:space-between;">
                <div>
                    <div style="font-size:15px; font-weight:700;">ステップ実行ランタイム上書き</div>
                    <div style="font-size:12px; color:#6b7280; margin-top:2px;">${_wfbEsc(stepLabel)}</div>
                </div>
                <button type="button" data-overlay-close style="background:none; border:none; font-size:22px; line-height:1; cursor:pointer; color:#6b7280;" title="閉じる">&times;</button>
            </div>
            <div style="padding:14px 20px; overflow-y:auto; flex:1;">
                <p style="font-size:12px; color:#6b7280; margin:0 0 10px;">
                    このステップだけの実行ランタイム上書きです。
                    空欄のままなら親スキルの既定設定が継承されます。
                    「継承に戻す」を押すと上書きを削除します。
                </p>
                ${formHtml}
            </div>
            <div style="padding:12px 20px; border-top:1px solid rgba(0,0,0,0.08); display:flex; gap:8px; justify-content:flex-end;">
                <button type="button" data-overlay-revert style="padding:8px 14px; border:1px solid rgba(0,0,0,0.12); background:#fff; border-radius:8px; cursor:pointer; font-size:13px;">継承に戻す</button>
                <button type="button" data-overlay-cancel style="padding:8px 14px; border:1px solid rgba(0,0,0,0.12); background:#fff; border-radius:8px; cursor:pointer; font-size:13px;">キャンセル</button>
                <button type="button" data-overlay-save style="padding:8px 16px; background:var(--accent); color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600;">保存</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    if (window.executionConfigForm && window.executionConfigForm.attachDynamicWiring) {
        window.executionConfigForm.attachDynamicWiring(overlay.querySelector('[data-exec-config-root]'));
    }

    function close() {
        overlay.remove();
    }
    overlay.querySelector('[data-overlay-close]').addEventListener('click', close);
    overlay.querySelector('[data-overlay-cancel]').addEventListener('click', close);
    // 暗転したバックドロップ（内側のカードではなく）をクリックしても閉じる。
    overlay.addEventListener('click', (ev) => {
        if (ev.target === overlay) close();
    });
    overlay.querySelector('[data-overlay-revert]').addEventListener('click', () => {
        sk.config_json = null;
        close();
        _renderWorkflowBuilder();
    });
    overlay.querySelector('[data-overlay-save]').addEventListener('click', () => {
        const root = overlay.querySelector('[data-exec-config-root]');
        if (!root) { close(); return; }
        const newCfg = window.executionConfigForm.collectForm(root);
        const baseConfigJson = (sk.config_json && typeof sk.config_json === 'object') ? { ...sk.config_json } : {};
        baseConfigJson.execution_config = newCfg;
        sk.config_json = baseConfigJson;
        close();
        _renderWorkflowBuilder();
    });
}
window._wfbEditStepExecutionConfig = _wfbEditStepExecutionConfig;

// ワークフロー作成バリアント — 同じオーバーレイ UX だが、_wfBuilderState の
// 代わりに _wfCreateGroups を変更し、wfCreateRenderGroups で再レンダリング。
function wfCreateEditStepExecutionConfig(gi, si) {
    if (!window.executionConfigForm) {
        showAlert('execution-config-form helper not loaded', 'error');
        return;
    }
    const sk = _wfCreateGroups[gi] && _wfCreateGroups[gi].skills[si];
    if (!sk) return;
    _openStepExecutionConfigOverlay({
        sk,
        stepLabel: sk.skill_name || `Step ${si + 1}`,
        onChange: () => wfCreateRenderGroups(),
    });
}
window.wfCreateEditStepExecutionConfig = wfCreateEditStepExecutionConfig;

// 作成・編集両方のワークフロービルダーで使用される共有オーバーレイ実装。
// 渡された `sk` 参照をその場で変更する — 両方の呼び出し元がそれぞれの
// 状態配列へのライブ参照を保持している。
// `config_json` フィールドを持つ任意のコンテナ（ワークフロー / グループ /
// ステップ）の execution_config を編集する汎用オーバーレイ。コンテナを
// その場で変更する。`title` と `subLabel` で階層を説明する。以下の
// ワークフロー + グループエディターで直接使用。ステップごとのバリアント
// `_openStepExecutionConfigOverlay` は後方互換性のための薄いラッパー。
function _openExecutionConfigOverlay({ container, title, subLabel, onChange }) {
    if (!window.executionConfigForm) {
        showAlert('execution-config-form helper not loaded', 'error');
        return;
    }
    const prior = document.getElementById('wfb-step-runtime-overlay');
    if (prior) prior.remove();

    const existing = (container.config_json && container.config_json.execution_config) || null;
    const formHtml = window.executionConfigForm.renderForm(existing);

    const overlay = document.createElement('div');
    overlay.id = 'wfb-step-runtime-overlay';
    overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:20000',
        'background:rgba(0,0,0,0.45)',
        'display:flex', 'align-items:center', 'justify-content:center',
    ].join(';');

    overlay.innerHTML = `
        <div style="background:#fff; border-radius:14px; width:min(720px,92vw); max-height:88vh; display:flex; flex-direction:column; box-shadow:0 24px 60px rgba(0,0,0,0.32);">
            <div style="padding:16px 20px; border-bottom:1px solid rgba(0,0,0,0.08); display:flex; align-items:center; justify-content:space-between;">
                <div>
                    <div style="font-size:15px; font-weight:700;">${_wfbEsc(title)}</div>
                    <div style="font-size:12px; color:#6b7280; margin-top:2px;">${_wfbEsc(subLabel || '')}</div>
                </div>
                <button type="button" data-overlay-close style="background:none; border:none; font-size:22px; line-height:1; cursor:pointer; color:#6b7280;" title="閉じる">&times;</button>
            </div>
            <div style="padding:14px 20px; overflow-y:auto; flex:1;">
                <p style="font-size:12px; color:#6b7280; margin:0 0 10px;">
                    この階層の既定実行ランタイムです。下位階層 (グループ / スキル / ステップ) で
                    指定がある場合はそちらが優先されます。「継承に戻す」で削除できます。
                </p>
                ${formHtml}
            </div>
            <div style="padding:12px 20px; border-top:1px solid rgba(0,0,0,0.08); display:flex; gap:8px; justify-content:flex-end;">
                <button type="button" data-overlay-revert style="padding:8px 14px; border:1px solid rgba(0,0,0,0.12); background:#fff; border-radius:8px; cursor:pointer; font-size:13px;">継承に戻す</button>
                <button type="button" data-overlay-cancel style="padding:8px 14px; border:1px solid rgba(0,0,0,0.12); background:#fff; border-radius:8px; cursor:pointer; font-size:13px;">キャンセル</button>
                <button type="button" data-overlay-save style="padding:8px 16px; background:var(--accent); color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600;">保存</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    if (window.executionConfigForm && window.executionConfigForm.attachDynamicWiring) {
        window.executionConfigForm.attachDynamicWiring(overlay.querySelector('[data-exec-config-root]'));
    }

    function close() { overlay.remove(); }
    overlay.querySelector('[data-overlay-close]').addEventListener('click', close);
    overlay.querySelector('[data-overlay-cancel]').addEventListener('click', close);
    overlay.addEventListener('click', (ev) => {
        if (ev.target === overlay) close();
    });
    overlay.querySelector('[data-overlay-revert]').addEventListener('click', () => {
        container.config_json = null;
        close();
        if (typeof onChange === 'function') onChange();
    });
    overlay.querySelector('[data-overlay-save]').addEventListener('click', () => {
        const root = overlay.querySelector('[data-exec-config-root]');
        if (!root) { close(); return; }
        const newCfg = window.executionConfigForm.collectForm(root);
        const baseConfigJson = (container.config_json && typeof container.config_json === 'object') ? { ...container.config_json } : {};
        baseConfigJson.execution_config = newCfg;
        container.config_json = baseConfigJson;
        close();
        if (typeof onChange === 'function') onChange();
    });
}

// ビルダー状態の workflow.config_json から親ランタイムモード
// ("api" | "cli") を導出する。まだ execution_config が設定されて
// いない場合は "api" をデフォルトにし、ラジオが API から開始する
// （従来の動作）。
function _wfbParentRuntimeMode(s) {
    const exec = s && s.config_json && s.config_json.execution_config && s.config_json.execution_config.execution;
    return (exec && exec.execution_kind === 'external_cli') ? 'cli' : 'api';
}
window._wfbParentRuntimeMode = _wfbParentRuntimeMode;

// ラジオ onchange ハンドラー: ビルダー状態の config_json を
// API (= null / provider) と CLI (= external_cli スタブ) の間で切り替え、
// 再レンダリングする。CLI の詳細（adapter / cwd / workspace policy）は
// 引き続き「⚙ ランタイム」オーバーレイで編集する。
function _wfbSetParentRuntimeMode(mode) {
    if (!_wfBuilderState) return;
    if (mode === 'cli') {
        const existing = (_wfBuilderState.config_json && _wfBuilderState.config_json.execution_config) || null;
        if (!(existing && existing.execution && existing.execution.execution_kind === 'external_cli')) {
            const seed = (window.executionConfigForm && window.executionConfigForm.defaultConfig)
                ? window.executionConfigForm.defaultConfig()
                : { execution: {}, workspace: {}, approval: {}, artifact_contract: {} };
            seed.execution = seed.execution || {};
            seed.execution.execution_kind = 'external_cli';
            _wfBuilderState.config_json = { ...(_wfBuilderState.config_json || {}), execution_config: seed };
        }
    } else {
        // API モード: ワークフローレベルの execution_config を削除し、
        // ステップ/グループレベルが引き続きオーバーライドできるようにする。
        // null = デフォルトを継承（= HTTP プロバイダー）。
        if (_wfBuilderState.config_json && _wfBuilderState.config_json.execution_config) {
            const rest = { ..._wfBuilderState.config_json };
            delete rest.execution_config;
            _wfBuilderState.config_json = Object.keys(rest).length ? rest : null;
        }
    }
    _renderWorkflowBuilder();
}
window._wfbSetParentRuntimeMode = _wfbSetParentRuntimeMode;

// 編集ビルダー用のワークフローレベル（継承チェーンの最上位）エディター。
function _wfbEditWorkflowExecutionConfig() {
    if (!_wfBuilderState) return;
    _openExecutionConfigOverlay({
        container: _wfBuilderState,
        title: 'ワークフロー既定の実行ランタイム',
        subLabel: _wfBuilderState.name || '',
        onChange: () => _renderWorkflowBuilder(),
    });
}
window._wfbEditWorkflowExecutionConfig = _wfbEditWorkflowExecutionConfig;

// 編集ビルダー用のグループレベルエディター。
function _wfbEditGroupExecutionConfig(gi) {
    const grp = _wfBuilderState && _wfBuilderState.groups[gi];
    if (!grp) return;
    _openExecutionConfigOverlay({
        container: grp,
        title: 'グループ既定の実行ランタイム',
        subLabel: grp.group_name || `グループ ${gi + 1}`,
        onChange: () => _renderWorkflowBuilder(),
    });
}
window._wfbEditGroupExecutionConfig = _wfbEditGroupExecutionConfig;

function _openStepExecutionConfigOverlay({ sk, stepLabel, onChange }) {
    const prior = document.getElementById('wfb-step-runtime-overlay');
    if (prior) prior.remove();

    const existing = (sk.config_json && sk.config_json.execution_config) || null;
    const formHtml = window.executionConfigForm.renderForm(existing);

    const overlay = document.createElement('div');
    overlay.id = 'wfb-step-runtime-overlay';
    overlay.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:20000',
        'background:rgba(0,0,0,0.45)',
        'display:flex', 'align-items:center', 'justify-content:center',
    ].join(';');

    overlay.innerHTML = `
        <div style="background:#fff; border-radius:14px; width:min(720px,92vw); max-height:88vh; display:flex; flex-direction:column; box-shadow:0 24px 60px rgba(0,0,0,0.32);">
            <div style="padding:16px 20px; border-bottom:1px solid rgba(0,0,0,0.08); display:flex; align-items:center; justify-content:space-between;">
                <div>
                    <div style="font-size:15px; font-weight:700;">ステップ実行ランタイム上書き</div>
                    <div style="font-size:12px; color:#6b7280; margin-top:2px;">${_wfbEsc(stepLabel)}</div>
                </div>
                <button type="button" data-overlay-close style="background:none; border:none; font-size:22px; line-height:1; cursor:pointer; color:#6b7280;" title="閉じる">&times;</button>
            </div>
            <div style="padding:14px 20px; overflow-y:auto; flex:1;">
                <p style="font-size:12px; color:#6b7280; margin:0 0 10px;">
                    このステップだけの実行ランタイム上書きです。
                    空欄のままなら親スキルの既定設定が継承されます。
                    「継承に戻す」を押すと上書きを削除します。
                </p>
                ${formHtml}
            </div>
            <div style="padding:12px 20px; border-top:1px solid rgba(0,0,0,0.08); display:flex; gap:8px; justify-content:flex-end;">
                <button type="button" data-overlay-revert style="padding:8px 14px; border:1px solid rgba(0,0,0,0.12); background:#fff; border-radius:8px; cursor:pointer; font-size:13px;">継承に戻す</button>
                <button type="button" data-overlay-cancel style="padding:8px 14px; border:1px solid rgba(0,0,0,0.12); background:#fff; border-radius:8px; cursor:pointer; font-size:13px;">キャンセル</button>
                <button type="button" data-overlay-save style="padding:8px 16px; background:var(--accent); color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600;">保存</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    if (window.executionConfigForm && window.executionConfigForm.attachDynamicWiring) {
        window.executionConfigForm.attachDynamicWiring(overlay.querySelector('[data-exec-config-root]'));
    }

    function close() { overlay.remove(); }
    overlay.querySelector('[data-overlay-close]').addEventListener('click', close);
    overlay.querySelector('[data-overlay-cancel]').addEventListener('click', close);
    overlay.addEventListener('click', (ev) => {
        if (ev.target === overlay) close();
    });
    overlay.querySelector('[data-overlay-revert]').addEventListener('click', () => {
        sk.config_json = null;
        close();
        if (typeof onChange === 'function') onChange();
    });
    overlay.querySelector('[data-overlay-save]').addEventListener('click', () => {
        const root = overlay.querySelector('[data-exec-config-root]');
        if (!root) { close(); return; }
        const newCfg = window.executionConfigForm.collectForm(root);
        const baseConfigJson = (sk.config_json && typeof sk.config_json === 'object') ? { ...sk.config_json } : {};
        baseConfigJson.execution_config = newCfg;
        sk.config_json = baseConfigJson;
        close();
        if (typeof onChange === 'function') onChange();
    });
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
    // フロービュー & 色を更新するために再レンダリング
    _renderWorkflowBuilder();
}

// group.config_json.judge_execution_config を設定/クリアして、
// ディベートジャッジステップを API (HTTP プロバイダー) と CLI (external_cli)
// の間で切り替える。通常のステップごとの継承チェーン
// (config_json.execution_config) に影響しないよう judge_execution_config に格納。
function _wfbSetJudgeKind(gi, kind) {
    const grp = _wfBuilderState.groups[gi];
    if (!grp) return;
    if (kind === 'cli') {
        const existing = grp.config_json && grp.config_json.judge_execution_config && grp.config_json.judge_execution_config.execution || {};
        const adapter = existing.preferred_adapter || 'claude-code-local';
        grp.config_json = { ...(grp.config_json || {}), judge_execution_config: {
            schema_version: '1.0',
            execution: {
                execution_kind: 'external_cli',
                preferred_adapter: adapter,
                cli_runtime_hint: adapter === 'codex-local' ? 'codex' : 'claude_code',
                cli_model: existing.cli_model || null,
            },
        }};
    } else {
        if (grp.config_json && grp.config_json.judge_execution_config) {
            const rest = { ...grp.config_json };
            delete rest.judge_execution_config;
            grp.config_json = Object.keys(rest).length ? rest : null;
        }
    }
    _renderWorkflowBuilder();
}
window._wfbSetJudgeKind = _wfbSetJudgeKind;

function _wfbSetJudgeAdapter(gi, adapter) {
    const grp = _wfBuilderState.groups[gi];
    if (!grp || !grp.config_json || !grp.config_json.judge_execution_config) return;
    const exec = grp.config_json.judge_execution_config.execution || {};
    exec.preferred_adapter = adapter;
    exec.cli_runtime_hint = adapter === 'codex-local' ? 'codex' : 'claude_code';
    grp.config_json.judge_execution_config.execution = exec;
    _renderWorkflowBuilder();
}
window._wfbSetJudgeAdapter = _wfbSetJudgeAdapter;

async function _wfbSave() {
    const s = _wfBuilderState;
    // 入力値を反映
    s.name = document.getElementById('wfb-name')?.value || s.name;
    s.description = document.getElementById('wfb-desc')?.value || s.description;
    s.parent_skill_content = document.getElementById('wfb-parent-content')?.value || s.parent_skill_content;
    const rawModel = document.getElementById('wfb-parent-model')?.value;
    if (rawModel != null && rawModel !== '') {
        const norm = _wfbNormalizeParentModelFromSelect(rawModel);
        s.parent_model_type = norm.parent_model_type;
        s.parent_enable_deep_think = norm.parent_enable_deep_think;
    }
    const supervisorModeEl = document.getElementById('wfb-supervisor-mode');
    if (supervisorModeEl) s.supervisor_mode = supervisorModeEl.value;

    validateParallelGroupProfiles(s.groups);

    // 親ランタイムモードは必須 — ラジオを直接読み取り、CLI が選択された場合は
    // CLI 詳細フォームを収集する。API モードではワークフローレベルの
    // execution_config を削除し、クリーンに継承されるようにする。
    const parentMode = (document.querySelector('input[name="wfb-parent-runtime-mode"]:checked') || {}).value || 'api';
    if (parentMode === 'cli') {
        const mount = document.getElementById('wfb-parent-exec-config-mount');
        const root = mount && mount.querySelector('[data-exec-config-root]');
        if (!root || !window.executionConfigForm) {
            Swal.showValidationMessage('CLI 設定フォームを読み込めませんでした');
            return false;
        }
        const execCfg = window.executionConfigForm.collectForm(root);
        execCfg.execution = execCfg.execution || {};
        execCfg.execution.execution_kind = 'external_cli';
        if (!execCfg.execution.preferred_adapter && !execCfg.execution.cli_runtime_hint) {
            Swal.showValidationMessage('CLI 実行では adapter を選択してください');
            return false;
        }
        if (!execCfg.execution.cwd_hint) {
            Swal.showValidationMessage('CLI 実行では cwd ヒント（作業ディレクトリ）が必須です');
            return false;
        }
        s.config_json = { ...(s.config_json || {}), execution_config: execCfg };
    } else {
        if (!s.parent_model_type) {
            Swal.showValidationMessage('親スキルがAPI実行の場合、AIモデルを選択してください');
            return false;
        }
        // ワークフローレベルの execution_config を削除し、グループ/ステップの
        // オーバーライドが引き続き機能し、親が HTTP プロバイダーパスをデフォルトにする。
        if (s.config_json && s.config_json.execution_config) {
            const rest = { ...s.config_json };
            delete rest.execution_config;
            s.config_json = Object.keys(rest).length ? rest : null;
        }
    }

    const payload = {
        name: s.name,
        description: s.description,
        is_active: s.is_active,
        parent_skill_content: s.parent_skill_content,
        parent_model_type: s.parent_model_type,
        parent_enable_deep_think: s.parent_enable_deep_think,
        supervisor_mode: s.supervisor_mode || 'disabled',
        config_json: s.config_json || null,
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
            config_json: g.config_json || null,
            skills: g.skills.map((sk, si) => ({
                skill_id: sk.skill_id,
                order_in_group: si + 1,
                skill_name: sk.skill_name || '',
                model_type: sk.model_type || null,
                on_error: sk.on_error || 'stop',
                max_retries: parseInt(sk.max_retries) || 0,
                retry_delay_seconds: parseInt(sk.retry_delay_seconds) || 5,
                depends_on: sk.depends_on || null,
                output_key: sk.output_key || null,
                input_mapping: sk.input_mapping || null,
                quality_gate_type: sk.quality_gate_type || 'disabled',
                quality_gate_prompt: sk.quality_gate_prompt || '',
                quality_gate_model: sk.quality_gate_model || null,
                max_reflection_loops: parseInt(sk.max_reflection_loops) || 0,
                agent_profile: sk.agent_profile || 'default',
                // 注意: enable_deep_think はここでは読み取り専用。WorkflowSkill
                // ではなく親の Skill 行に存在する — admin.py の
                // _build_workflow_response を参照。返送しないこと。
                // バックエンドにはステップごとの格納先がない。
                config_json: sk.config_json || null,
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
