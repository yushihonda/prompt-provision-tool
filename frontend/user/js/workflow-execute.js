// ユーザー ワークフロー実行画面 JavaScript

let workflowId = null;
let workflowDetail = null;
let workflowExecutionId = null;
let stepExecutions = new Map(); // skill_order -> { executionId, status, output, stepName, skillName }
let allExecutions = []; // 全ての実行履歴
let displayedHistoryCount = 3; // 表示する履歴の件数
let streamingWorkers = new Map(); // executionId -> worker
let _wfStageMeta = { currentStage: null, finalVerdict: null, handoffSummary: null, coordinatorView: null, synthesisEvents: [] };

async function loadWorkflowDetail() {
    workflowId = getQueryParam('id');
    if (!workflowId) {
        showAlert('ワークフローIDが指定されていません', 'error');
        return;
    }

    try {
        workflowDetail = await apiRequest(`/api/user/workflows/${workflowId}`);

        // ワークフロー情報を表示
        document.getElementById('workflow-name').textContent = workflowDetail.workflow.name;
        document.getElementById('workflow-description').textContent =
            workflowDetail.workflow.description || '説明なし';

        // 入力フィールドを生成（各Skillのinput_schemaを統合）
        await generateWorkflowInputFields(workflowDetail);

        // 実行履歴を読み込む
        await loadHistory();

        // 実行中のワークフローがあれば復元
        await restoreActiveWorkflowExecution();
    } catch (error) {
        showAlert('ワークフロー情報の読み込みに失敗しました', 'error');
        console.error('loadWorkflowDetail error:', error);
    }
}

async function restoreActiveWorkflowExecution() {
    // 1. URLパラメータ we_id があればそれを優先（詳細へ遷移時）
    // 2. なければ PersistentStatusBar から取得（実行中の復帰時）
    const urlWeId = getQueryParam('we_id');
    let weId = urlWeId ? parseInt(urlWeId) : null;

    if (!weId && PersistentStatusBar.executionId && PersistentStatusBar.workflowExecutionId) {
        weId = PersistentStatusBar.workflowExecutionId;
    }

    if (!weId) return;

    try {
        // 該当ワークフローの全実行を取得
        const response = await apiRequest(`/api/user/executions?limit=100`);
        const allExecs = response.items || response;
        const wfExecs = allExecs.filter(e => e.workflow_execution_id === weId);

        if (wfExecs.length === 0) return;

        workflowExecutionId = weId;
        wfExecs.sort((a, b) => (a.skill_order || 0) - (b.skill_order || 0));

        // ワークフロー全体が完了しているかチェック
        const allDone = wfExecs.every(e =>
            e.status === 'success' || e.status === 'error' || e.status === 'cancelled'
        );

        // 特殊ロールを除外
        const normalExecs = wfExecs.filter(e => !e.execution_role);
        const specialExecs = wfExecs.filter(e => e.execution_role);

        // 各ステップの状態を復元（最新のExecutionのみ）
        const latestByWsId = {};
        for (const exec of normalExecs) {
            if (!exec.workflow_skill_id) continue;
            const wsId = exec.workflow_skill_id;
            if (!latestByWsId[wsId] || exec.id > latestByWsId[wsId].id) {
                latestByWsId[wsId] = exec;
            }
        }

        for (const exec of Object.values(latestByWsId)) {
            const stepOrder = exec.skill_order;
            if (!stepOrder) continue;

            const skillInfo = workflowDetail?.skills?.find(s => s.skill_order == stepOrder);
            stepExecutions.set(stepOrder, {
                executionId: exec.id,
                workflowSkillId: exec.workflow_skill_id,
                executionRole: null,
                reflectionLoop: exec.reflection_loop || 0,
                status: exec.status,
                output: exec.output_data || '',
                stepName: skillInfo?.skill_name || `Step ${stepOrder}`,
                skillName: skillInfo?.skill_name || `Step ${stepOrder}`,
                errorMessage: exec.error_message || null,
                agentProfile: exec.agent_profile || null
            });

            // フロービューのステータス更新
            if (skillInfo) updateFlowStatus(stepOrder, skillInfo.skill_id, exec.status);

            // まだ実行中のステップがあればSSE再接続
            if (exec.status === 'pending' || exec.status === 'pending_local' || exec.status === 'processing') {
                startStepStreaming(exec.id, stepOrder, skillInfo?.skill_name || `Step ${stepOrder}`, skillInfo?.skill_name);
            }
        }

        // フロービューを初期化（詳細へ遷移時に必要）
        if (!_flowViewDetail && workflowDetail) {
            _flowViewDetail = workflowDetail;
            _flowStepStatuses = {};
            // 各スキルのステータスを設定（最新のExecutionのみ）
            for (const exec of Object.values(latestByWsId)) {
                const skillInfo = workflowDetail?.skills?.find(s => s.skill_order == exec.skill_order);
                if (skillInfo) {
                    _flowStepStatuses[skillInfo.skill_id] = exec.status === 'pending_local' ? 'pending' : exec.status;
                    _flowStepStatuses['ws_' + exec.workflow_skill_id] = exec.status === 'pending_local' ? 'pending' : exec.status;
                }
            }
            // リーダーステータス（特殊ロールでない、workflow_skill_id=null）
            const leaderExecForStatus = normalExecs.find(e => !e.workflow_skill_id);
            if (leaderExecForStatus) {
                _flowStepStatuses['leader'] = leaderExecForStatus.status;
            }
            // オーケストレーション状況を復元
            _orchestrationStatuses = specialExecs.map(e => ({
                role: e.execution_role,
                groupId: e.execution_group_id,
                status: e.status,
                action: '',
            }));
        }

        // 入力データを復元（全ステップから）
        restoreAllWorkflowInputData(wfExecs);

        // 全完了の場合
        if (allDone) {
            // PersistentStatusBarがまだこの実行を追跡中なら完了にする
            if (PersistentStatusBar.workflowExecutionId === weId) {
                const hasError = wfExecs.some(e => e.status === 'error');
                const hasCancelled = wfExecs.some(e => e.status === 'cancelled');
                const finalStatus = hasError ? 'error' : hasCancelled ? 'cancelled' : 'success';
                PersistentStatusBar.markAsCompleted(finalStatus);
            }

            // リーダーステップ（統合結果）を探す — 特殊ロールでない、workflow_skill_id=null
            const leaderExec = normalExecs.find(e => !e.workflow_skill_id);

            // 全ステップの結果を構築（最新のExecutionのみ、cancelledを除外）
            const allStepResults = Object.values(latestByWsId)
                .filter(exec => exec.status !== 'cancelled')
                .sort((a, b) => (a.skill_order || 0) - (b.skill_order || 0))
                .map(exec => {
                    const skillInfo = workflowDetail?.skills?.find(s => s.skill_order == exec.skill_order);
                    return {
                        stepOrder: exec.skill_order,
                        stepName: exec.skill_name || skillInfo?.skill_name || `Step ${exec.skill_order}`,
                        status: exec.status,
                        output: exec.output_data || '',
                        errorMessage: exec.error_message,
                        model: exec.model_used,
                        time: exec.execution_time,
                        tokens: exec.tokens_used
                    };
                });

            // リーダー出力をフロービュー用に保存（リーダーがなければ最後のステップ出力をフォールバック）
            const lastStepOutput = allStepResults.length > 0 ? allStepResults[allStepResults.length - 1].output : '';
            const finalOutput = leaderExec?.output_data || lastStepOutput || '';
            _flowLeaderOutput = finalOutput;
            if (!leaderExec && finalOutput) {
                _flowStepStatuses['leader'] = 'success';
            }

            // Blackboardキー復元
            try {
                const wfStatusRestore = await apiRequest(`/api/user/workflow-executions/${weId}/status`);
                if (wfStatusRestore?.blackboard_keys) _blackboardKeys = wfStatusRestore.blackboard_keys;
                _wfStageMeta = {
                    currentStage: wfStatusRestore?.current_stage || null,
                    finalVerdict: wfStatusRestore?.final_verdict || null,
                    handoffSummary: wfStatusRestore?.handoff_summary || null,
                    coordinatorView: wfStatusRestore?.coordinator_view || null,
                    synthesisEvents: wfStatusRestore?.synthesis_events || [],
                };
            } catch (e) {}

            // ワークフロー結果を表示（統合結果 + 各ステップ）
            const resultExec = leaderExec || (allStepResults.length > 0 ? allStepResults[allStepResults.length - 1] : null);
            if (resultExec) {
                displayWorkflowResult(finalOutput, allStepResults, resultExec);
            }
        } else {
            // 実行中: ステップごとの進捗を表示
            renderStepExecutions();

            // ボタン・入力フィールドを無効化（実行完了まで）
            const executeBtn = document.getElementById('workflow-execute-btn');
            if (executeBtn) executeBtn.disabled = true;
            const executeBtnText = document.getElementById('workflow-execute-btn-text');
            if (executeBtnText) executeBtnText.textContent = '実行中...';
            const executeBtnSpinner = document.getElementById('workflow-execute-btn-spinner');
            if (executeBtnSpinner) executeBtnSpinner.style.display = 'inline';
            const form = document.getElementById('workflow-execute-form');
            if (form) {
                form.querySelectorAll('input, textarea, select').forEach(el => { el.disabled = true; });
            }
        }
    } catch (error) {
        console.error('Failed to restore workflow execution:', error);
    }
}

async function generateWorkflowInputFields(detail) {
    const container = document.getElementById('workflow-input-fields-container');
    if (!container) return;

    // 1. このワークフローに含まれる全Promptの詳細(input_schema)を取得
    const skillsById = {};
    for (const step of detail.skills || []) {
        const pid = step.skill_id;
        if (!skillsById[pid]) {
            try {
                const p = await apiRequest(`/api/user/skills/${pid}`);
                skillsById[pid] = p;
            } catch (e) {
                console.error('Failed to load prompt for workflow step', pid, e);
            }
        }
    }

    const parts = [];

    // 2. ワークフロー全体の入力セクション（input_schemaがある場合）
    const workflowInputSchema = detail.input_schema || detail.workflow?.input_schema;
    const hasWorkflowGlobalSchema =
        workflowInputSchema &&
        typeof workflowInputSchema === 'object' &&
        Object.keys(workflowInputSchema).length > 0;
    if (hasWorkflowGlobalSchema) {
        parts.push(`
            <div class="workflow-global-section" style="margin-bottom: 24px; padding-bottom: 24px; border-bottom: 2px solid rgba(255,255,255,0.2);">
                <h3 style="margin-top: 0; margin-bottom: 12px; color: rgba(255,255,255,0.9);">
                    ワークフロー共通入力
                </h3>
                <p style="font-size: 12px; color: rgba(255,255,255,0.7); margin-bottom: 12px;">
                    すべてのステップで共通して使用される入力データ
                </p>
                <div data-workflow-global-input="true">
                    ${renderInputFieldsForWorkflowGlobal(workflowInputSchema)}
                </div>
            </div>
        `);
    }

    // 3. 各ステップごとに入力セクションを生成（同じスキルでもステップが異なれば別の入力欄）
    // ワークフロー共通入力に含まれるフィールドは各ステップから除外
    const globalFieldNames = new Set();
    if (hasWorkflowGlobalSchema) {
        const gProps = workflowInputSchema.properties || workflowInputSchema;
        for (const name of Object.keys(gProps)) {
            globalFieldNames.add(name);
        }
    }

    // input_mapping が設定されているフィールドはユーザー入力不要（自動注入される）
    const mappedFieldsByWsId = {};
    for (const grp of (detail.groups || detail.workflow?.groups || [])) {
        for (const gs of (grp.skills || [])) {
            const wsId = gs.workflow_skill_id || gs.id;
            if (gs.input_mapping && typeof gs.input_mapping === 'object') {
                mappedFieldsByWsId[wsId] = Object.keys(gs.input_mapping);
            }
        }
    }

    const stepSections = [];
    let hasAnyInput = false;

    for (const step of detail.skills || []) {
        const prompt = skillsById[step.skill_id];
        const inputSchema = prompt ? prompt.input_schema : null;

        // input_schemaがないStepはスキップ（前ステップ出力を自動受け渡し）
        if (!inputSchema || typeof inputSchema !== 'object') continue;

        let properties = {};
        let requiredFields = [];

        if (inputSchema.properties) {
            properties = inputSchema.properties;
            requiredFields = inputSchema.required || [];
        } else {
            properties = inputSchema;
            requiredFields = Object.entries(properties)
                .filter(([_, cfg]) => cfg && cfg.required === true)
                .map(([name]) => name);
        }

        // 自動注入・内部メタフィールドを除外
        const wsId = step.workflow_skill_id;
        const mappedFields = mappedFieldsByWsId[wsId] || [];
        const autoInjectedFields = new Set([
            ...mappedFields,
            // ワークフローエンジンが自動注入するフィールド
            'previous_output', 'previous_step_result', 'all_step_results',
            'global_input_data', 'steps', 'blackboard',
        ]);
        const filteredProperties = {};
        for (const [name, cfg] of Object.entries(properties)) {
            // _ppt_ プレフィックス（内部メタデータ）を除外
            if (name.startsWith('_ppt_')) continue;
            // 自動注入フィールドを除外
            if (autoInjectedFields.has(name)) continue;
            // ワークフロー共通入力と重複するフィールドを除外
            if (globalFieldNames.has(name)) continue;
            filteredProperties[name] = cfg;
        }
        properties = filteredProperties;

        if (Object.keys(properties).length === 0) continue;

        const stepLabel = step.skill_name || prompt?.name || `Step ${step.skill_order}`;

        const fieldsHTML = Object.entries(properties).map(([fieldName, cfg]) => {
            const label = cfg.title || cfg.label || fieldName;
            const description = cfg.description || '';
            const required = requiredFields.includes(fieldName) || cfg.required === true;
            const type = cfg.type || 'string';
            const placeholder = cfg.placeholder || cfg.description || '';
            const rows = cfg.rows || (type === 'code' ? 12 : 6);
            const requiredAttr = required ? 'required' : '';
            const placeholderAttr = placeholder ? `placeholder="${placeholder}"` : '';
            const fullName = `${wsId}__${fieldName}`;

            if (type === 'number' || type === 'integer') {
                return `<div class="form-group">
                    <label for="${fullName}">${label}</label>
                    ${description ? `<small style="color: rgba(255,255,255,0.6);">${description}</small>` : ''}
                    <input type="number" id="${fullName}" name="${fullName}" ${requiredAttr} ${placeholderAttr}>
                </div>`;
            }
            return `<div class="form-group">
                <label for="${fullName}">${label}</label>
                ${description ? `<small style="color: rgba(255,255,255,0.6);">${description}</small>` : ''}
                <textarea id="${fullName}" name="${fullName}" rows="${rows}" ${requiredAttr} ${placeholderAttr}></textarea>
            </div>`;
        }).join('');

        stepSections.push({ wsId, stepLabel, fieldsHTML });
        hasAnyInput = true;
    }

    // 4. 入力欄が1つも無い場合のフォールバック
    if (!hasWorkflowGlobalSchema && !hasAnyInput) {
        const firstStep = (detail.skills || [])[0];
        if (firstStep) {
            const wsId = firstStep.workflow_skill_id;
            const fullName = `${wsId}__input`;
            stepSections.push({
                wsId,
                stepLabel: firstStep.skill_name || 'Step 1',
                fieldsHTML: `<div class="form-group">
                    <label for="${fullName}">入力</label>
                    <textarea id="${fullName}" name="${fullName}" rows="6" required></textarea>
                </div>`
            });
        }
    }

    // 5. ステップごとの入力セクションを表示
    if (stepSections.length > 0) {
        // 1ステップだけなら見出し不要、複数ならステップ名で区別
        if (stepSections.length === 1) {
            parts.push(`
                <div class="workflow-step-input-section" style="margin-top: 24px;">
                    <h3 style="margin-top: 0; margin-bottom: 12px; color: rgba(255,255,255,0.9);">入力データ</h3>
                    <div>${stepSections[0].fieldsHTML}</div>
                </div>
            `);
        } else {
            parts.push(`
                <div class="workflow-step-input-section" style="margin-top: 24px;">
                    <h3 style="margin-top: 0; margin-bottom: 12px; color: rgba(255,255,255,0.9);">各ステップの入力データ</h3>
                    <p style="font-size: 12px; color: rgba(255,255,255,0.7); margin-bottom: 12px;">
                        各ステップに個別の入力を設定できます
                    </p>
                    ${stepSections.map(sec => `
                        <div style="margin-bottom: 16px; padding: 12px; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; border-left: 3px solid #7c3aed;">
                            <div style="font-size: 12px; font-weight: 600; color: #c4b5fd; margin-bottom: 8px;">${sec.stepLabel}</div>
                            ${sec.fieldsHTML}
                        </div>
                    `).join('')}
                </div>
            `);
        }
    }

    if (!parts.length) {
        container.innerHTML =
            '<p style="text-align:center; color: rgba(255,255,255,0.6);">このワークフローに有効なステップがありません</p>';
    } else {
        container.innerHTML = parts.join('');
    }
}

// ワークフロー共通入力のinput_schemaから入力フィールドHTMLを生成
function renderInputFieldsForWorkflowGlobal(inputSchema) {
    if (!inputSchema || typeof inputSchema !== 'object') {
        return '<p style="color: rgba(255,255,255,0.6);">入力スキーマが定義されていません</p>';
    }

    let properties = {};
    let requiredFields = [];

    if (inputSchema.properties) {
        properties = inputSchema.properties;
        requiredFields = inputSchema.required || [];
    } else {
        properties = inputSchema;
        requiredFields = Object.entries(properties)
            .filter(([_, cfg]) => cfg && cfg.required === true)
            .map(([name]) => name);
    }

    if (Object.keys(properties).length === 0) {
        return '<p style="color: rgba(255,255,255,0.6);">入力フィールドが定義されていません</p>';
    }

    const fieldsHTML = Object.entries(properties)
        .map(([fieldName, cfg]) => {
            const label = cfg.title || cfg.label || fieldName;
            const description = cfg.description || '';
            const required =
                requiredFields.includes(fieldName) || cfg.required === true ? 'required' : '';
            const type = cfg.type || 'string';
            const placeholder = cfg.placeholder || description || '';
            const placeholderAttr = placeholder ? `placeholder="${placeholder}"` : '';
            const rows = cfg.rows || (type === 'code' ? 12 : 6);

            // ワークフロー共通入力は "wf_global__" プレフィックスを付ける
            const fullName = `wf_global__${fieldName}`;

            if (type === 'number' || type === 'integer') {
                return `
                    <div class="form-group">
                        <label for="${fullName}">${label}</label>
                        ${description ? `<small style="color: rgba(255,255,255,0.6);">${description}</small>` : ''}
                        <input type="number" id="${fullName}" name="${fullName}" ${required} ${placeholderAttr}>
                    </div>
                `;
            }

            // 文字列はtextareaで統一
            return `
                <div class="form-group">
                    <label for="${fullName}">${label}</label>
                    ${description ? `<small style="color: rgba(255,255,255,0.6);">${description}</small>` : ''}
                    <textarea id="${fullName}" name="${fullName}" rows="${rows}" ${required} ${placeholderAttr}></textarea>
                </div>
            `;
        })
        .join('');

    return fieldsHTML;
}

// Promptのinput_schemaから入力フィールドHTMLを生成（execute.jsのgenerateInputFieldsと同等のロジックを縮小版で利用）
function renderInputFieldsForSchema(step, inputSchema) {
    // inputSchemaがnull/不正ならシンプルなテキストエリアを1つ用意
    if (!inputSchema || typeof inputSchema !== 'object') {
        // フィールド名にworkflow_skill_idのプレフィックスを付けておく
        const fieldName = `${step.workflow_skill_id}__input`;
        return `
            <div class="form-group">
                <label for="${fieldName}">入力</label>
                <textarea id="${fieldName}" name="${fieldName}" rows="6" required></textarea>
            </div>
        `;
    }

    let properties = {};
    let requiredFields = [];

    if (inputSchema.properties) {
        properties = inputSchema.properties;
        requiredFields = inputSchema.required || [];
    } else {
        properties = inputSchema;
        requiredFields = Object.entries(properties)
            .filter(([_, cfg]) => cfg && cfg.required === true)
            .map(([name]) => name);
    }

    if (Object.keys(properties).length === 0) {
        const fieldName = `${step.workflow_skill_id}__input`;
        return `
            <div class="form-group">
                <label for="${fieldName}">入力</label>
                <textarea id="${fieldName}" name="${fieldName}" rows="6" required></textarea>
            </div>
        `;
    }

    const fieldsHTML = Object.entries(properties)
        .map(([fieldName, cfg]) => {
            const label = cfg.title || cfg.label || fieldName;
            const description = cfg.description || '';
            const required =
                requiredFields.includes(fieldName) || cfg.required === true ? 'required' : '';
            const type = cfg.type || 'string';
            const placeholder = cfg.placeholder || description || '';
            const placeholderAttr = placeholder ? `placeholder="${placeholder}"` : '';
            const rows = cfg.rows || (type === 'code' ? 12 : 6);

            // フィールド名にstep IDのプレフィックスを付けることで衝突を避ける
            const fullName = `${step.workflow_skill_id}__${fieldName}`;

            if (type === 'number' || type === 'integer') {
                return `
                    <div class="form-group">
                        <label for="${fullName}">${label}</label>
                        ${description ? `<small style="color: rgba(255,255,255,0.6);">${description}</small>` : ''}
                        <input type="number" id="${fullName}" name="${fullName}" ${required} ${placeholderAttr}>
                    </div>
                `;
            }

            // 文字列はtextareaで統一
            return `
                <div class="form-group">
                    <label for="${fullName}">${label}</label>
                    ${description ? `<small style="color: rgba(255,255,255,0.6);">${description}</small>` : ''}
                    <textarea id="${fullName}" name="${fullName}" rows="${rows}" ${required} ${placeholderAttr}></textarea>
                </div>
            `;
        })
        .join('');

    return fieldsHTML;
}

// 常時ステータスバーを更新
function updateStatusBar() {
    const bar = document.getElementById('wf-status-bar');
    if (!bar) return;
    const cv = _wfStageMeta.coordinatorView;
    const esc = typeof escapeHtml === 'function' ? escapeHtml : (t => t);
    if (!cv && !_wfStageMeta.currentStage) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'block';
    const stage = _wfStageMeta.currentStage || '-';
    const verdict = _wfStageMeta.finalVerdict;
    const summary = cv?.latest_summary || '';
    const completedCount = cv?.completed_count || 0;
    const totalExecs = cv?.total_executions || 0;
    const nextAction = cv?.next_expected_action || '';
    const stageColor = _profileColor(stage);
    const verdictColor = verdict === 'PASS' ? '#28a745' : verdict === 'FAIL' ? '#dc3545' : verdict === 'PARTIAL' ? '#ffc107' : null;

    let html = `<div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">`;
    html += `<span style="font-size:12px; font-weight:bold; color:${stageColor}; background:${stageColor}22; padding:2px 10px; border-radius:10px;">${esc(formatStageLabel(stage))}</span>`;
    if (verdict) {
        html += `<span style="font-size:11px; font-weight:bold; color:${verdictColor};">${esc(verdict)}</span>`;
    }
    if (totalExecs > 0) {
        html += `<span style="font-size:10px; color:rgba(255,255,255,0.4);">${completedCount}/${totalExecs}</span>`;
    }
    if (summary) {
        html += `<span style="font-size:11px; color:rgba(255,255,255,0.7); flex:1;">${esc(summary)}</span>`;
    }
    html += `</div>`;
    bar.innerHTML = html;
}

// ステップの実行進捗を表示（フロービューが全て担当、下の出力パネルは非表示）
function renderStepExecutions() {
    updateStatusBar();
    // 下の結果コンテナは非表示（フロービューが各スキル出力を担当）
    const resultContainer = document.getElementById('workflow-result-container');
    if (resultContainer) resultContainer.style.display = 'none';

    // フロービューを更新（スキル出力を反映）
    if (_flowViewDetail) {
        renderFlowView(_flowViewDetail, _flowStepStatuses);
    }
}

// ---------------------------------------------------------------------------
// 実行フロービュー（リーダー付き縦フロー表示）
// ---------------------------------------------------------------------------

function formatStageLabel(stage) {
    if (!stage) return '-';
    const map = { default: 'Default', explore: 'Explore', plan: 'Plan', implement: 'Implement', verification: 'Verification' };
    return map[stage] || stage;
}

// profile / stage の固定色（全画面で統一）
function _profileColor(profile) {
    const colors = {
        default: '#9e9e9e',
        explore: '#2196f3',
        plan: '#ff9800',
        implement: '#4caf50',
        verification: '#e91e63',
    };
    return colors[(profile || '').toLowerCase()] || '#9e9e9e';
}

function renderWorkflowStageSummary(esc) {
    const cv = _wfStageMeta.coordinatorView;
    const events = _wfStageMeta.synthesisEvents || [];
    const stage = formatStageLabel(_wfStageMeta.currentStage);
    const verdict = _wfStageMeta.finalVerdict || '-';
    const refs = Array.isArray(_wfStageMeta.handoffSummary?.blackboard_refs) ? _wfStageMeta.handoffSummary.blackboard_refs : [];
    const failedStep = Array.from(stepExecutions.values()).find(step => step.status === 'error');
    const failedStage = failedStep?.agentProfile ? formatStageLabel(failedStep.agentProfile) : null;

    // coordinator view: 現在のステータスバー
    const latestSummary = cv?.latest_summary || '';
    const nextAction = cv?.next_expected_action || '';
    const completedCount = cv?.completed_count || 0;
    const totalExecs = cv?.total_executions || 0;

    // ステータスアイコン
    const actionIcon = {
        'completed': '✓', 'failed': '✗', 'executing_steps': '⟳',
        'waiting_for_judge': '⚖', 'waiting_for_quality_gate': '🔍',
        'waiting_for_supervisor': '👁', 'waiting_for_leader': '⟳',
        'awaiting_continuation': '→',
    }[nextAction] || '→';
    const actionColor = nextAction === 'completed' ? '#28a745' : nextAction === 'failed' ? '#dc3545' : '#64b5f6';

    let html = `<div style="padding:10px 14px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.12); border-radius:8px; margin-bottom:10px;">`;

    // 1行目: Stage + Verdict + 進捗
    html += `<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:${latestSummary || events.length ? '8px' : '0'};">`;
    html += `<span style="font-size:11px; color:rgba(255,255,255,0.55);">Stage</span>`;
    html += `<span style="font-size:12px; font-weight:bold; color:#fff;">${esc(stage)}</span>`;
    if (verdict !== '-') {
        html += `<span style="font-size:11px; color:rgba(255,255,255,0.55); margin-left:8px;">Verdict</span>`;
        html += `<span style="font-size:12px; font-weight:bold; color:${verdict === 'PASS' ? '#28a745' : verdict === 'FAIL' ? '#dc3545' : verdict === 'PARTIAL' ? '#ffc107' : 'rgba(255,255,255,0.7)'};">${esc(verdict)}</span>`;
    }
    if (totalExecs > 0) {
        html += `<span style="font-size:10px; color:rgba(255,255,255,0.4); margin-left:auto;">${completedCount}/${totalExecs} steps</span>`;
    }
    if (failedStage) {
        html += `<span style="font-size:12px; font-weight:bold; color:#ff8a80; margin-left:8px;">${esc(failedStage)} failed</span>`;
    }
    html += `</div>`;

    // 2行目: coordinator latest_summary
    if (latestSummary) {
        html += `<div style="display:flex; align-items:center; gap:6px; margin-bottom:${events.length > 0 ? '8px' : '0'};">`;
        html += `<span style="color:${actionColor}; font-size:12px;">${actionIcon}</span>`;
        html += `<span style="font-size:11px; color:rgba(255,255,255,0.8);">${esc(latestSummary)}</span>`;
        html += `</div>`;
    }

    // 3行目: synthesis events タイムライン（最新5件）
    if (events.length > 0) {
        const recentEvents = events.slice(-5);
        html += `<div style="display:flex; flex-wrap:wrap; gap:4px;">`;
        for (const ev of recentEvents) {
            const evIcon = {
                'workflow_start': '▶', 'group_complete': '◆', 'leader_start': '⟳',
                'step_complete': '✓', 'judge_complete': '⚖', 'supervisor_decision': '👁',
                'quality_gate_pass': '🔍', 'leader_complete': '★',
                'step_error': '✗', 'debate_judge_error': '⚖✗',
            }[ev.event_type] || '•';
            const evColor = ev.event_type.includes('error') ? '#dc3545' : '#28a745';
            html += `<span style="font-size:10px; padding:2px 8px; background:rgba(255,255,255,0.06); border-radius:10px; color:rgba(255,255,255,0.65); display:inline-flex; align-items:center; gap:3px;">`;
            html += `<span style="color:${evColor};">${evIcon}</span>${esc(ev.summary || ev.step_name || '')}`;
            html += `</span>`;
        }
        html += `</div>`;
    }

    // key_points
    const cvKeyPoints = cv?.key_points || [];
    if (cvKeyPoints.length > 0) {
        html += `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-top:4px;">`;
        cvKeyPoints.forEach(kp => { html += `<span style="font-size:10px; padding:2px 8px; background:rgba(76,175,80,0.12); border-radius:10px; color:rgba(255,255,255,0.7);">${esc(kp)}</span>`; });
        html += `</div>`;
    }

    // Blackboard refs
    if (refs.length) {
        html += `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-top:6px;">${refs.map(ref => `<span style="font-size:10px; padding:2px 8px; background:rgba(33,150,243,0.15); border-radius:10px; color:rgba(255,255,255,0.7);">${esc(ref)}</span>`).join('')}</div>`;
    }

    html += `</div>`;
    return html;
}

function renderFlowView(wfDetail, allStepStatuses) {
    const flowEl = document.getElementById('workflow-flow-view');
    if (!flowEl) return;

    const wf = wfDetail.workflow || wfDetail;
    const groups = wf.groups || [];
    const wfName = wf.name || 'ワークフロー';

    if (groups.length === 0) {
        flowEl.style.display = 'none';
        return;
    }
    flowEl.style.display = 'block';

    const esc = typeof escapeHtml === 'function' ? escapeHtml : (t => t);

    // ステータスカラー・アイコン
    const sc = (s) => s === 'success' ? '#28a745' : s === 'processing' ? '#7c3aed' : s === 'error' ? '#dc3545' : 'rgba(255,255,255,0.2)';
    const si = (s) => s === 'success' ? '&#10003;' : s === 'processing' ? '&#9679;' : s === 'error' ? '&#10007;' : '&#9711;';

    // stepExecutions からワークフロースキルID→出力データのマップを作成
    // executionId → stepData のマップも作成（executionIdベースで引けるように）
    const skillOutputByWsId = {};   // workflow_skill_id -> { output, errorMessage, status }
    const skillOutputByExecId = {}; // execution_id -> { output, errorMessage, status }
    if (stepExecutions && stepExecutions.size > 0) {
        for (const [stepOrder, data] of stepExecutions.entries()) {
            if (data.executionId) {
                skillOutputByExecId[data.executionId] = data;
            }
            // workflowSkillId が stepData に含まれていればそれを使う（数値・文字列の両方でセット）
            if (data.workflowSkillId) {
                skillOutputByWsId[data.workflowSkillId] = data;
                skillOutputByWsId[String(data.workflowSkillId)] = data;
            }
        }
    }

    // スキルノードの出力HTML（折りたたみ）— workflow_skill_id で引く
    function skillOutputHtml(wsId) {
        const data = skillOutputByWsId[wsId] || skillOutputByWsId[String(wsId)] || skillOutputByWsId[Number(wsId)];
        if (!data) return '';
        // Reflectionバッジ
        const refLoop = data.reflectionLoop || 0;
        const refBadge = refLoop > 0 ? `<span style="font-size:9px; color:#ffc107; background:rgba(255,193,7,0.15); padding:1px 6px; border-radius:8px; margin-left:4px;">再実行 ${refLoop}回目</span>` : '';
        if (data.status === 'processing') {
            const chunkLen = data.output ? data.output.length : 0;
            const chunkInfo = chunkLen > 0 ? `${chunkLen}文字受信中` : '実行中';
            return `<div style="margin-top:6px; padding:6px 8px; background:rgba(124,58,237,0.1); border-radius:4px; font-size:11px; color:rgba(255,255,255,0.6); display:flex; align-items:center; gap:6px;"><div style="width:12px; height:12px; border:2px solid rgba(255,255,255,0.1); border-top:2px solid #7c3aed; border-radius:50%; animation:spin 1s linear infinite; flex-shrink:0;"></div><span>${chunkInfo}...${refBadge}</span></div>`;
        }
        if (data.status === 'success' && data.output) {
            return `<details data-ws-id="${wsId}" style="margin-top:6px;"><summary style="font-size:10px; color:rgba(255,255,255,0.5); cursor:pointer; user-select:none;">出力を表示${refBadge}</summary><div style="margin-top:4px; padding:8px; background:rgba(0,0,0,0.3); border-radius:4px; max-height:150px; overflow-y:auto;"><div style="color:rgba(255,255,255,0.8); white-space:pre-wrap; word-wrap:break-word; font-size:11px; line-height:1.5;">${esc(data.output)}</div></div></details>`;
        }
        if (data.status === 'error' && data.errorMessage) {
            return `<div style="margin-top:6px; padding:6px 8px; background:rgba(220,53,69,0.15); border-radius:4px; font-size:11px; color:#dc3545;">${esc(data.errorMessage)}${refBadge}</div>`;
        }
        return '';
    }

    // オーケストレーション状況ノードHTML (ジャッジ/SV/BB)
    function orchestrationNodesHtml(grpId) {
        if (!_orchestrationStatuses) return '';
        const items = _orchestrationStatuses.filter(o => o.groupId === grpId);
        if (!items.length) return '';
        let html = '';
        for (const item of items) {
            const roleLabel = item.role === 'debate_judge' ? 'Judge 合議' : item.role === 'supervisor' ? 'Supervisor 判定' : item.role === 'quality_gate' ? '品質ゲート' : item.role;
            const roleColor = item.role === 'debate_judge' ? '#e91e63' : item.role === 'supervisor' ? '#ff9800' : '#9c27b0';
            const statusColor = sc(item.status);
            const statusIcon = si(item.status);
            html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:10px; background:rgba(255,255,255,0.1);"></div></div>`;
            html += `
                <div style="display:flex; align-items:center; gap:8px; padding:8px 14px; background:${roleColor}10; border:1px solid ${roleColor}30; border-radius:6px; margin:2px 0;">
                    <span style="color:${statusColor}; font-size:12px;">${statusIcon}</span>
                    <span style="font-size:11px; font-weight:bold; color:${roleColor};">${roleLabel}</span>
                    ${item.status === 'processing' ? '<div class="spinner" style="display:inline-block; width:10px; height:10px; border-width:1.5px;"></div>' : ''}
                    ${item.action ? `<span style="font-size:10px; color:rgba(255,255,255,0.5); margin-left:auto;">${esc(item.action)}</span>` : ''}
                </div>`;
        }
        return html;
    }

    // リーダーステータス判定
    // リーダー以外のスキルステータスで判定
    const skillStatuses = allStepStatuses ? Object.entries(allStepStatuses).filter(([k]) => k !== 'leader') : [];
    const anyStarted = skillStatuses.length > 0;
    const allSkillsDone = skillStatuses.length > 0 && skillStatuses.every(([, s]) => s === 'success');
    const leaderStartStatus = anyStarted ? 'success' : 'pending';
    const leaderEndStatus = allStepStatuses?.['leader'] || (allSkillsDone ? 'pending' : 'pending');

    // リーダー（結果統合）の出力
    const leaderOutput = _flowLeaderOutput || '';

    let html = renderWorkflowStageSummary(esc);

    // --- リーダー開始 ---
    html += `
        <div style="display:flex; align-items:center; gap:10px; padding:12px 16px; background:rgba(156,39,176,0.12); border:1px solid rgba(156,39,176,0.3); border-radius:8px; margin-bottom:4px;">
            <div style="width:28px; height:28px; border-radius:50%; background:${sc(leaderStartStatus)}; display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">${si(leaderStartStatus)}</div>
            <div>
                <div style="font-size:13px; font-weight:bold; color:#ce93d8;">親スキル: タスク振り分け</div>
                <div style="font-size:11px; color:rgba(255,255,255,0.5);">${wfName}</div>
            </div>
        </div>
    `;

    // --- 矢印 ---
    html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>`;

    // --- グループ ---
    groups.forEach((grp, gi) => {
        const isParallel = grp.execution_type === 'parallel';
        const skills = grp.skills || [];
        const gColor = isParallel ? '#2196f3' : '#ff9800';
        const gLabel = isParallel ? '並列' : '直列';
        const gName = grp.group_name || ('Group ' + (gi + 1));

        html += `<div style="margin:4px 0; border:1px solid ${gColor}33; border-radius:8px; overflow:hidden;">`;

        // グループヘッダー
        html += `
            <div style="padding:8px 14px; background:${gColor}15; display:flex; align-items:center; gap:8px;">
                <span style="font-size:10px; font-weight:bold; color:${gColor}; background:${gColor}22; padding:2px 8px; border-radius:10px;">${gLabel}</span>
                <span style="font-size:12px; font-weight:bold; color:rgba(255,255,255,0.8);">${gName}</span>
            </div>
        `;

        // スキル
        if (isParallel && skills.length > 1) {
            html += `<div style="display:flex; gap:6px; padding:10px 14px;">`;
            skills.forEach((sk) => {
                const sName = sk.skill_name || '?';
                const sModel = typeof formatModelDisplay === 'function' ? formatModelDisplay(sk.model_type || '', null, {}) : (sk.model_type || '');
                const sStatus = (allStepStatuses && (allStepStatuses['ws_' + sk.workflow_skill_id] || allStepStatuses[sk.skill_id])) || 'pending';
                html += `
                    <div style="flex:1; padding:10px; background:rgba(0,0,0,0.2); border-radius:6px; border-left:3px solid ${sc(sStatus)}; min-width:0;">
                        <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                            <span style="color:${sc(sStatus)}; font-size:12px;">${si(sStatus)}</span>
                            <span style="font-size:12px; font-weight:bold; color:rgba(255,255,255,0.9); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${sName}</span>
                        </div>
                        <div style="font-size:10px; color:rgba(255,255,255,0.4);">${sModel}</div>
                        <div style="margin-top:4px;"><span style="font-size:10px; padding:2px 8px; background:${_profileColor(sk.agent_profile || 'default')}22; border-radius:10px; color:${_profileColor(sk.agent_profile || 'default')};">${esc(formatStageLabel(sk.agent_profile || 'default'))}</span></div>
                        ${skillOutputHtml(sk.workflow_skill_id)}
                    </div>
                `;
            });
            html += `</div>`;
        } else {
            html += `<div style="padding:8px 14px;">`;
            skills.forEach((sk, si_idx) => {
                const sName = sk.skill_name || '?';
                const sModel = typeof formatModelDisplay === 'function' ? formatModelDisplay(sk.model_type || '', null, {}) : (sk.model_type || '');
                const sStatus = (allStepStatuses && (allStepStatuses['ws_' + sk.workflow_skill_id] || allStepStatuses[sk.skill_id])) || 'pending';
                html += `
                    <div style="padding:8px 10px; background:rgba(0,0,0,0.15); border-radius:6px; border-left:3px solid ${sc(sStatus)}; ${si_idx > 0 ? 'margin-top:6px;' : ''}">
                        <div style="display:flex; align-items:center; gap:10px;">
                            <span style="color:${sc(sStatus)}; font-size:12px;">${si(sStatus)}</span>
                            <div style="flex:1; min-width:0;">
                                <div style="font-size:12px; font-weight:bold; color:rgba(255,255,255,0.9);">${sName}</div>
                                <div style="font-size:10px; color:rgba(255,255,255,0.4);">${sModel}</div>
                                <div style="margin-top:4px;"><span style="font-size:10px; padding:2px 8px; background:${_profileColor(sk.agent_profile || 'default')}22; border-radius:10px; color:${_profileColor(sk.agent_profile || 'default')};">${esc(formatStageLabel(sk.agent_profile || 'default'))}</span></div>
                            </div>
                        </div>
                        ${skillOutputHtml(sk.workflow_skill_id)}
                    </div>
                `;
                if (si_idx < skills.length - 1 && !isParallel) {
                    html += `<div style="display:flex; justify-content:flex-start; padding:2px 0 2px 20px;"><div style="width:1px; height:10px; background:rgba(255,255,255,0.1);"></div></div>`;
                }
            });
            html += `</div>`;
        }

        html += `</div>`;

        // オーケストレーション状況 (ジャッジ/SV) をグループ後に表示
        html += orchestrationNodesHtml(grp.id);

        // グループ間矢印
        if (gi < groups.length - 1) {
            html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>`;
        }
    });

    // --- Blackboard パネル（キーがあれば表示） ---
    if (_blackboardKeys.length > 0) {
        html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:10px; background:rgba(255,255,255,0.1);"></div></div>`;
        html += `<div style="padding:8px 14px; background:rgba(33,150,243,0.08); border:1px solid rgba(33,150,243,0.2); border-radius:6px; margin:2px 0;">`;
        html += `<div style="font-size:10px; font-weight:bold; color:#64b5f6; margin-bottom:4px;">Blackboard (共有メモリ)</div>`;
        html += `<div style="display:flex; flex-wrap:wrap; gap:4px;">`;
        for (const key of _blackboardKeys) {
            html += `<span style="font-size:10px; padding:2px 8px; background:rgba(33,150,243,0.15); border-radius:10px; color:rgba(255,255,255,0.7);">${esc(key)}</span>`;
        }
        html += `</div></div>`;
    }

    // --- 矢印 ---
    html += `<div style="display:flex; justify-content:center; padding:2px 0;"><div style="width:2px; height:16px; background:rgba(255,255,255,0.15);"></div></div>`;

    // --- 親スキル統合（最終結果を表示） ---
    html += `<div id="leader-result-section" style="background:rgba(156,39,176,0.12); border:1px solid rgba(156,39,176,0.3); border-radius:8px; margin-top:4px; overflow:hidden; display:flex; flex-direction:column;">`;
    html += `<div style="display:flex; align-items:center; gap:10px; padding:12px 16px;">`;
    html += `<div style="width:28px; height:28px; border-radius:50%; background:${sc(leaderEndStatus)}; display:flex; align-items:center; justify-content:center; font-size:14px; color:white; flex-shrink:0;">${si(leaderEndStatus)}</div>`;
    html += `<div style="flex:1;"><div style="font-size:13px; font-weight:bold; color:#ce93d8;">親スキル: 結果統合</div><div style="font-size:11px; color:rgba(255,255,255,0.5);">全結果を統合して最終出力を生成</div></div>`;
    if (leaderOutput) {
        html += `<button onclick="copyLeaderOutput()" title="出力をコピー" style="display:flex; align-items:center; justify-content:center; padding:6px; background:none; border:none; cursor:pointer; opacity:0.5; transition:opacity 0.2s;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.5'"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" style="fill:rgba(255,255,255,0.7);"><path d="M16 10c3.469 0 2 4 2 4s4-1.594 4 2v6h-10v-12h4zm.827-2h-6.827v16h14v-8.842c0-2.392-4.011-7.158-7.173-7.158zm-8.827 12h-6v-16h4l2.102 2h3.898l2-2h4v2.145c.656.143 1.327.391 2 .754v-4.899h-3c-1.229 0-2.18-1.084-3-2h-8c-.82.916-1.771 2-3 2h-3v20h8v-2zm2-18c.553 0 1 .448 1 1s-.447 1-1 1-1-.448-1-1 .447-1 1-1zm4 18h6v-1h-6v1zm0-2h6v-1h-6v1zm0-2h6v-1h-6v1z"/></svg></button>`;
    }
    html += `</div>`;
    if (leaderOutput) {
        html += `<div style="padding:0 16px 12px 16px;"><div id="leader-output-content" style="padding:12px; background:rgba(0,0,0,0.3); border-radius:6px; max-height:60vh; overflow-y:auto;"><div style="color:rgba(255,255,255,0.9); white-space:pre-wrap; word-wrap:break-word; font-size:12px; line-height:1.6;">${esc(leaderOutput)}</div></div></div>`;
    }
    html += `</div>`;

    // 再描画前に開いている <details> の data-ws-id を保存
    const openDetails = new Set();
    flowEl.querySelectorAll('details[open][data-ws-id]').forEach(d => {
        openDetails.add(d.getAttribute('data-ws-id'));
    });

    flowEl.innerHTML = html;

    // 開閉状態を復元
    if (openDetails.size > 0) {
        flowEl.querySelectorAll('details[data-ws-id]').forEach(d => {
            if (openDetails.has(d.getAttribute('data-ws-id'))) {
                d.open = true;
            }
        });
    }
}

async function copyLeaderOutput() {
    const text = _flowLeaderOutput || '';
    if (!text) {
        showAlert('コピーする内容がありません', 'warning');
        return;
    }
    try {
        await navigator.clipboard.writeText(text);
        showAlert('クリップボードにコピーしました', 'success');
    } catch (e) {
        showAlert('コピーに失敗しました', 'error');
    }
}

// フロービュー用のステータス更新
let _flowViewDetail = null;

function updateFlowStatus(stepOrder, skillIdOrWsId, status) {
    if (!_flowStepStatuses) return;
    if (skillIdOrWsId) _flowStepStatuses[skillIdOrWsId] = status;
    // workflow_skill_id でもセット（同じスキルが複数回使われる場合の対応）
    const stepData = stepExecutions.get(stepOrder);
    if (stepData?.workflowSkillId) {
        _flowStepStatuses['ws_' + stepData.workflowSkillId] = status;
    }
    if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);
}
let _flowStepStatuses = {};
let _flowLeaderOutput = '';  // リーダーステップ（結果統合）の出力
let _orchestrationStatuses = [];  // [{role, groupId, status, action}]
let _blackboardKeys = [];  // Blackboardのキー一覧

// escapeHtml, formatJSON, getQueryParam は user-common.js で定義済み

// ステップのストリーミングを開始
function startStepStreaming(executionId, stepOrder, stepName, skillName) {
    // 既にストリーミング中の場合はスキップ
    if (streamingWorkers.has(executionId)) {
        return;
    }

    // ステップ実行情報を初期化
    // workflow_skill_id を取得（フロービューのマッピング用）— 型揺れ対策で == 比較
    const matchedSkill = workflowDetail?.skills?.find(s => s.skill_order == stepOrder);
    stepExecutions.set(stepOrder, {
        executionId,
        workflowSkillId: matchedSkill?.workflow_skill_id || null,
        status: 'processing',
        output: '',
        stepName,
        skillName,
        errorMessage: null
    });
    renderStepExecutions();

    // フロービューのステータス更新
    // skillId を取得するためにスキル情報を検索
    const skills = workflowDetail?.skills || [];
    const matchSkill = skills.find(s => s.skill_order == stepOrder);
    if (matchSkill) updateFlowStatus(stepOrder, matchSkill.skill_id, 'processing');

    // Web Workerを作成してストリーミングを開始（execute.htmlと同じWorkerを再利用）
    const worker = new Worker('/user/js/execution-worker.js');
    streamingWorkers.set(executionId, worker);

    worker.postMessage({
        type: 'start',
        executionId: executionId,
        token: sessionStorage.getItem('token')
    });

    let accumulatedOutput = '';

    worker.onmessage = (event) => {
        const { type, data } = event.data;

        console.log('Worker message received:', { type, data, stepOrder, executionId });

        // workflow_next_stepイベントの処理（専用イベントタイプ）
        if (type === 'workflow_next_step') {
            let stepData = null;
            
            // dataがオブジェクトの場合
            if (data && typeof data === 'object') {
                stepData = data;
            } 
            // dataが文字列（JSON）の場合
            else if (typeof data === 'string') {
                try {
                    stepData = JSON.parse(data);
                } catch (e) {
                    console.error('Failed to parse workflow_next_step data:', e);
                    return;
                }
            }

            if (stepData && stepData.next_execution_id) {
                // ワークフロー実行の次のステップが起動された
                const nextExecutionId = stepData.next_execution_id;
                const nextStepOrder = stepData.next_skill_order;
                const nextStepName = stepData.skill_name || `Step ${nextStepOrder}`;
                const nextPromptName = stepData.skill_name || nextStepName;
                const workflowName = stepData.workflow_name || workflowDetail?.workflow?.name || 'ワークフロー';

                console.log('Workflow next step detected:', { 
                    nextExecutionId, 
                    nextStepOrder, 
                    nextStepName, 
                    workflowName,
                    currentStepOrder: stepOrder,
                    currentExecutionId: executionId
                });

                // バックグラウンドパネルに次のステップを追加
                if (typeof PersistentStatusBar !== 'undefined') {
                    PersistentStatusBar.handleWorkflowNextStep(
                        nextExecutionId,
                        nextStepOrder,
                        nextStepName,
                        workflowName
                    );
                }

                // 次のステップのストリーミングを開始
                setTimeout(() => {
                    startStepStreaming(nextExecutionId, nextStepOrder, nextStepName, nextPromptName);
                }, 500);
                return; // チャンクとして表示しない
            }
        }

        if (type === 'chunk') {
            // チャンクデータの処理
            let chunkText = data.text || (typeof data === 'string' ? data : '');

            // チャンクを累積
            accumulatedOutput += chunkText;
            const stepData = stepExecutions.get(stepOrder);
            if (stepData) {
                stepData.output = accumulatedOutput;
                // リーダーステップ（workflowSkillIdなし かつ 特殊ロールでない）ならフロービューにリアルタイム反映
                if (!stepData.workflowSkillId && !stepData.executionRole) {
                    _flowLeaderOutput = accumulatedOutput;
                    _flowStepStatuses['leader'] = 'processing';
                }
                renderStepExecutions();
            }
        } else if (type === 'complete') {
            // 完了時は実行結果を取得して表示
            console.log('Step complete event received:', { executionId, stepOrder });
            handleStepComplete(executionId, stepOrder, 'success');
        } else if (type === 'error') {
            console.log('Step error event received:', { executionId, stepOrder, error: data.message });
            handleStepComplete(executionId, stepOrder, 'error', data.message || 'エラーが発生しました');
        } else if (type === 'cancel') {
            console.log('Step cancel event received:', { executionId, stepOrder });
            handleStepComplete(executionId, stepOrder, 'cancelled');
        }
    };

    worker.onerror = (error) => {
        console.error('Stream worker error:', error);
        handleStepComplete(executionId, stepOrder, 'error', 'ストリーミングエラーが発生しました');
    };
}

// ステップの完了処理
async function handleStepComplete(executionId, stepOrder, status, errorMessage = null) {
    console.log('handleStepComplete called:', { executionId, stepOrder, status, errorMessage });

    // Workerを停止
    const worker = streamingWorkers.get(executionId);
    if (worker) {
        worker.terminate();
        streamingWorkers.delete(executionId);
    }

    try {
        const execution = await apiRequest(`/api/user/executions/${executionId}`);
        const execRole = execution.execution_role;
        console.log('Execution data retrieved:', {
            executionId,
            stepOrder,
            status: execution.status,
            execution_role: execRole,
            workflow_execution_id: execution.workflow_execution_id,
            workflow_skill_id: execution.workflow_skill_id,
            output_length: execution.output_data ? execution.output_data.length : 0
        });

        // 特殊ロール（品質ゲート/ジャッジ/スーパーバイザー）はフロービュー更新して次ステップチェック
        if (execRole === 'quality_gate' || execRole === 'debate_judge' || execRole === 'supervisor') {
            console.log('Special role execution completed:', { execRole, executionId, status: execution.status });
            // オーケストレーション状況を更新
            const existing = _orchestrationStatuses.find(o => o.role === execRole && o.groupId === execution.execution_group_id);
            if (existing) {
                existing.status = execution.status;
            } else {
                _orchestrationStatuses.push({
                    role: execRole,
                    groupId: execution.execution_group_id,
                    status: execution.status,
                    action: '',
                });
            }
            if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);

            if (execution.workflow_execution_id && workflowExecutionId === execution.workflow_execution_id) {
                setTimeout(async () => {
                    await checkAndStartNextStep(execution.workflow_execution_id, stepOrder);
                }, 2000);
            }
            return;
        }

        // ステップ実行情報を更新
        const stepData = stepExecutions.get(stepOrder);
        if (stepData) {
            stepData.status = execution.status || status;
            stepData.output = execution.output_data || stepData.output || '';
            stepData.errorMessage = execution.error_message || errorMessage;
            stepData.executionRole = execRole || null;
            renderStepExecutions();

            // フロービューのステータス更新
            const skillId = execution.skill_id;
            if (skillId) updateFlowStatus(stepOrder, skillId, stepData.status);
            // リーダーステップ検出（workflow_skill_id=null かつ 特殊ロールでない）
            if (!execution.workflow_skill_id && !execRole && execution.workflow_execution_id) {
                _flowStepStatuses['leader'] = stepData.status;
                _flowLeaderOutput = execution.output_data || stepData.output || '';
                if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);
            }
        } else {
            // stepDataが存在しない場合は新規作成
            const stepInfo = workflowDetail?.skills?.find(s => s.skill_order == stepOrder);
            stepExecutions.set(stepOrder, {
                executionId,
                workflowSkillId: execution.workflow_skill_id || stepInfo?.workflow_skill_id || null,
                executionRole: execRole || null,
                status: execution.status || status,
                output: execution.output_data || '',
                stepName: execution.skill_name || stepInfo?.skill_name || `Step ${stepOrder}`,
                skillName: stepInfo?.skill_name || `Step ${stepOrder}`,
                errorMessage: execution.error_message || errorMessage
            });
            renderStepExecutions();
        }

        // リーダーステップ（workflow_skill_idがNone かつ 特殊ロールでない）の場合はワークフロー全体が完了
        const isLeaderStep = (execution.workflow_skill_id === null || execution.workflow_skill_id === undefined) && !execRole;
        if (isLeaderStep && execution.workflow_execution_id && workflowExecutionId === execution.workflow_execution_id) {
            console.log('Leader step completed, handling workflow complete');
            // ワークフロー全体が完了したので、スキル実行と同様の処理を実行
            await handleWorkflowComplete(execution.workflow_execution_id, execution);
            return;
        }

        // 通常のステップ（workflow_skill_idがnullでない）の場合は、次のステップが開始されているか確認
        // リーダーステップでない場合のみ次のステップをチェック
        if (!isLeaderStep && execution.workflow_execution_id && status === 'success' && workflowExecutionId === execution.workflow_execution_id) {
            console.log('Regular step completed, checking for next step');
            // 少し待ってから次のステップをチェック（オーケストレーションが完了するまで待つ）
            setTimeout(async () => {
                await checkAndStartNextStep(execution.workflow_execution_id, stepOrder);
            }, 2000);
        }
    } catch (error) {
        console.error('Failed to get execution result:', error);
        const stepData = stepExecutions.get(stepOrder);
        if (stepData) {
            stepData.status = status;
            stepData.errorMessage = errorMessage;
            renderStepExecutions();
        }
    }

    // 履歴を再読み込み
    await loadHistory();
}

// ワークフロー全体の完了処理（スキル実行と同様の挙動）
async function handleWorkflowComplete(workflowExecutionId, leaderExecution) {
    console.log('handleWorkflowComplete called:', { workflowExecutionId, leaderExecutionId: leaderExecution?.id });
    
    try {
        // ワークフロー実行の全実行を取得して統合結果を表示
        const response = await apiRequest(`/api/user/executions?limit=100`);
        const responseExecutions = response.items || response;
        const workflowExecutions = responseExecutions.filter(exec => exec.workflow_execution_id === workflowExecutionId);
        
        console.log('Workflow executions found:', { 
            count: workflowExecutions.length,
            executionIds: workflowExecutions.map(e => e.id),
            stepOrders: workflowExecutions.map(e => e.skill_order)
        });
        
        // 特殊ロールを除外し、最新のExecutionのみ使用
        const normalWfExecs = workflowExecutions.filter(e => !e.execution_role);
        const latestByWs = {};
        for (const exec of normalWfExecs) {
            if (!exec.workflow_skill_id) continue;
            if (!latestByWs[exec.workflow_skill_id] || exec.id > latestByWs[exec.workflow_skill_id].id) {
                latestByWs[exec.workflow_skill_id] = exec;
            }
        }

        const allStepResults = Object.values(latestByWs)
            .filter(exec => exec.status !== 'cancelled')
            .sort((a, b) => (a.skill_order || 0) - (b.skill_order || 0))
            .map(exec => {
                const stepInfo = workflowDetail?.skills?.find(s => s.skill_order == exec.skill_order);
                const stepData = stepExecutions.get(exec.skill_order);
                return {
                    stepOrder: exec.skill_order,
                    stepName: exec.skill_name || stepInfo?.skill_name || `Step ${exec.skill_order}`,
                    status: exec.status,
                    output: stepData?.output || exec.output_data || '',
                    errorMessage: exec.error_message,
                    model: exec.model_used,
                    time: exec.execution_time,
                    tokens: exec.tokens_used
                };
            });
        
        console.log('All step results:', allStepResults.map(s => ({ 
            stepOrder: s.stepOrder, 
            stepName: s.stepName, 
            status: s.status, 
            outputLength: s.output.length 
        })));

        // ステータスバーを更新（確実に成功状態で表示）
        if (typeof PersistentStatusBar !== 'undefined') {
            // ワークフロー実行IDが一致する場合のみ更新
            if (PersistentStatusBar.workflowExecutionId === workflowExecutionId) {
                const allStepsSuccess = allStepResults.every(s => s.status === 'success');
                const finalStatus = (leaderExecution?.status === 'success' || (!leaderExecution && allStepsSuccess)) ? 'success' : 'error';
                PersistentStatusBar.markAsCompleted(finalStatus);
                console.log('Workflow completed, PersistentStatusBar updated:', finalStatus);
            }
        }

        // リーダー出力をフロービュー用に保存（リーダーがなければ最後のステップ出力をフォールバック）
        const lastStepResult = allStepResults.length > 0 ? allStepResults[allStepResults.length - 1].output : '';
        _flowLeaderOutput = leaderExecution?.output_data || lastStepResult || '';
        if (!leaderExecution?.output_data && _flowLeaderOutput) {
            _flowStepStatuses['leader'] = 'success';
        }

        // Blackboardキー・オーケストレーション状況を復元
        try {
            const wfStatusFinal = await apiRequest(`/api/user/workflow-executions/${workflowExecutionId}/status`);
            if (wfStatusFinal?.blackboard_keys) _blackboardKeys = wfStatusFinal.blackboard_keys;
        } catch (e) {}
        const specialWfExecs = workflowExecutions.filter(e => e.execution_role);
        _orchestrationStatuses = specialWfExecs.map(e => ({
            role: e.execution_role,
            groupId: e.execution_group_id,
            status: e.status,
            action: '',
        }));
        if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);

        // 入力データを復元（全ステップから）
        restoreAllWorkflowInputData(workflowExecutions);

        // 実行ボタンを再有効化
        const executeBtn = document.getElementById('workflow-execute-btn');
        const executeBtnText = document.getElementById('workflow-execute-btn-text');
        const executeBtnSpinner = document.getElementById('workflow-execute-btn-spinner');
        const form = document.getElementById('workflow-execute-form');
        
        if (executeBtn) {
            executeBtn.disabled = false;
        }
        if (executeBtnText) {
            executeBtnText.textContent = 'ワークフロー実行';
        }
        if (executeBtnSpinner) {
            executeBtnSpinner.style.display = 'none';
        }
        if (form) {
            const inputs = form.querySelectorAll('input, textarea, select, button');
            inputs.forEach((el) => {
                if (el !== executeBtn) {
                    el.disabled = false;
                }
            });
        }

        // 全ステップの結果を統合して表示
        const finalOutput = _flowLeaderOutput;
        const effectiveLeader = leaderExecution || (allStepResults.length > 0 ? allStepResults[allStepResults.length - 1] : null);
        displayWorkflowResult(finalOutput, allStepResults, effectiveLeader);

        // 出力パネルを確実に表示（スキル実行と同様）
        const outputContent = document.getElementById('workflow-output-content');
        if (outputContent) {
            // 出力パネルが表示されるようにスクロール
            outputContent.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        // 完了ポップアップを表示（スキル実行と同様）
        const allSuccess = allStepResults.every(s => s.status === 'success');
        await Swal.fire({
            title: 'ワークフロー実行完了',
            text: 'ワークフロー実行が完了しました',
            icon: (leaderExecution?.status === 'success' || (!leaderExecution && allSuccess)) ? 'success' : 'error',
            confirmButtonText: USER_SWAL.btnClose,
            confirmButtonColor: USER_SWAL.primary
        });

        // 履歴を再読み込み
        await loadHistory();
    } catch (error) {
        console.error('Failed to handle workflow complete:', error);
        await showAlert('ワークフロー完了処理に失敗しました', 'error');
    }
}


// ワークフロー結果を出力パネルに表示
function displayWorkflowResult(finalOutput, allStepResults, leaderExecution) {
    // フロービューが全て担当（各スキル出力 + 結果統合）するので、下の出力パネルは非表示
    const resultContainer = document.getElementById('workflow-result-container');
    if (resultContainer) {
        resultContainer.style.display = 'none';
    }

    // フロービューを更新（スキルの出力 + リーダー最終結果をフローに反映）
    if (_flowViewDetail) {
        renderFlowView(_flowViewDetail, _flowStepStatuses);
    }

    // 結果統合セクションまで自動スクロール
    setTimeout(() => {
        const leaderSection = document.getElementById('leader-result-section');
        if (leaderSection) {
            leaderSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }, 200);
}

// ワークフロー入力データを復元（単一Executionから）
function restoreWorkflowInputData(execution) {
    if (!execution.input_data) return;

    try {
        let inputData;
        if (typeof execution.input_data === 'string') {
            inputData = JSON.parse(execution.input_data);
        } else {
            inputData = execution.input_data;
        }

        const form = document.getElementById('workflow-execute-form');
        if (!form) return;

        Object.entries(inputData).forEach(([key, value]) => {
            // ワークフロー共通入力（wf_global__ プレフィックス）
            if (key.startsWith('wf_global__') || !key.includes('__')) {
                const fieldName = key.startsWith('wf_global__') ? `wf_global__${key.replace('wf_global__', '')}` : `wf_global__${key}`;
                const inputElement = form.querySelector(`#${fieldName}, [name="${fieldName}"]`);
                if (inputElement) {
                    inputElement.value = value || '';
                }
            } else {
                // Skill個別入力（workflow_skill_id__fieldName 形式）
                const inputElement = form.querySelector(`#${key}, [name="${key}"]`);
                if (inputElement) {
                    inputElement.value = value || '';
                }
            }
        });
    } catch (e) {
        console.error('Failed to restore workflow input data:', e);
    }
}

// 全ステップの入力データからフォームを復元（複数Executionから）
function restoreAllWorkflowInputData(executions) {
    const form = document.getElementById('workflow-execute-form');
    if (!form) return;

    // フォーム内の全入力フィールドを取得してマップ化
    // name属性 -> element のマップを作成
    const fieldMap = {};
    form.querySelectorAll('input[name], textarea[name], select[name]').forEach(el => {
        fieldMap[el.name] = el;
    });

    for (const exec of executions) {
        if (!exec.input_data) continue;

        try {
            const inputData = typeof exec.input_data === 'string'
                ? JSON.parse(exec.input_data)
                : exec.input_data;

            const wsId = exec.workflow_skill_id;

            Object.entries(inputData).forEach(([key, value]) => {
                if (value === null || value === undefined) return;
                // オブジェクト・配列は復元対象外（previous_output, all_step_results等の内部データ）
                if (typeof value === 'object') return;

                // 1. wf_global__key で一致するフィールドを探す
                const globalName = `wf_global__${key}`;
                if (fieldMap[globalName]) {
                    fieldMap[globalName].value = value;
                }

                // 2. workflow_skill_id__key で一致するフィールドを探す
                if (wsId) {
                    const skillFieldName = `${wsId}__${key}`;
                    if (fieldMap[skillFieldName]) {
                        fieldMap[skillFieldName].value = value;
                    }
                }

                // 3. 全ての wsId__key パターンで一致するフィールドを探す（フォールバック）
                //    異なるスキルでも同名フィールドがある場合に対応
                for (const fname in fieldMap) {
                    if (fname.endsWith(`__${key}`) && !fieldMap[fname].value) {
                        fieldMap[fname].value = value;
                    }
                }
            });
        } catch (e) {
            console.error('Failed to restore input data for execution:', exec.id, e);
        }
    }
}

// 次のステップが開始されているか確認し、開始されていなければ開始する
let _checkNextStepRetryCount = 0;
const _MAX_CHECK_RETRIES = 20;  // 最大20回（約60秒）
async function checkAndStartNextStep(wfExecId, completedStepOrder) {
    try {
        console.log('checkAndStartNextStep called:', { wfExecId, completedStepOrder });

        // まずWF全体のステータスを確認 → error/successなら即停止
        let wfStatus = null;
        try {
            wfStatus = await apiRequest(`/api/user/workflow-executions/${wfExecId}/status`);
            if (wfStatus && (wfStatus.status === 'success' || wfStatus.status === 'error' || wfStatus.status === 'cancelled')) {
                console.log('Workflow finished:', wfStatus.status);
                _checkNextStepRetryCount = 0;
                if (wfStatus.status === 'error') {
                    showAlert(`ワークフローがエラーで停止しました: ${wfStatus.error_message || ''}`, 'error');
                    if (typeof PersistentStatusBar !== 'undefined') PersistentStatusBar.markAsCompleted('error');
                }
                if (wfStatus.status === 'success') {
                    if (typeof PersistentStatusBar !== 'undefined') PersistentStatusBar.markAsCompleted('success');
                }
                streamingWorkers.forEach((w) => { w.terminate(); });
                streamingWorkers.clear();
                return;
            }
        } catch (e) {
            console.log('WF status check failed, falling back:', e.message);
        }

        // ワークフロー実行の全実行を取得
        const response = await apiRequest(`/api/user/executions?limit=100`);
        const responseExecutions = response.items || response;
        const workflowExecutions = responseExecutions.filter(exec => exec.workflow_execution_id === wfExecId);

        // 特殊ロール(品質ゲート/ジャッジ/スーパーバイザー)を除外した通常スキルのみ
        const normalExecutions = workflowExecutions.filter(exec => !exec.execution_role);
        const specialExecutions = workflowExecutions.filter(exec => exec.execution_role);

        // オーケストレーション状況を更新してフロービューに反映
        _orchestrationStatuses = specialExecutions.map(exec => ({
            role: exec.execution_role,
            groupId: exec.execution_group_id,
            status: exec.status,
            action: '',
        }));

        // Blackboardキーを取得
        if (wfStatus && wfStatus.blackboard_keys) {
            _blackboardKeys = wfStatus.blackboard_keys;
        }
        _wfStageMeta = {
            currentStage: wfStatus?.current_stage || null,
            finalVerdict: wfStatus?.final_verdict || null,
            handoffSummary: wfStatus?.handoff_summary || null,
            coordinatorView: wfStatus?.coordinator_view || null,
            synthesisEvents: wfStatus?.synthesis_events || [],
        };

        // 最新の通常スキルのステータスをフロービューに反映
        // (SVのrepeat後はcancelledの古いものではなく最新のExecution を使う)
        const latestByWsId = {};
        for (const exec of normalExecutions) {
            const wsId = exec.workflow_skill_id;
            if (!wsId) continue;
            const existing = latestByWsId[wsId];
            if (!existing || exec.id > existing.id) {
                latestByWsId[wsId] = exec;
            }
        }
        for (const [wsId, exec] of Object.entries(latestByWsId)) {
            // フローステータスを更新
            _flowStepStatuses['ws_' + wsId] = exec.status === 'pending_local' ? 'pending' : exec.status;
            if (exec.skill_id) _flowStepStatuses[exec.skill_id] = exec.status === 'pending_local' ? 'pending' : exec.status;

            // stepExecutionsも最新に更新
            const stepData = stepExecutions.get(exec.skill_order);
            if (stepData) {
                stepData.status = exec.status;
                stepData.reflectionLoop = exec.reflection_loop || 0;
                if (exec.output_data) stepData.output = exec.output_data;
            }
        }

        // フロービューを再描画
        if (_flowViewDetail) {
            renderFlowView(_flowViewDetail, _flowStepStatuses);
        }

        // ストリーミング未開始のprocessing中スキルがあれば開始
        for (const exec of normalExecutions) {
            if (exec.status === 'processing' && !streamingWorkers.has(exec.id) && exec.workflow_skill_id) {
                const stepInfo = workflowDetail?.skills?.find(s => s.workflow_skill_id == exec.workflow_skill_id);
                const name = stepInfo?.skill_name || exec.skill_name || `Step ${exec.skill_order}`;
                console.log('Starting streaming for untracked execution:', { id: exec.id, name });
                startStepStreaming(exec.id, exec.skill_order, name, name);
            }
        }

        console.log('Workflow executions found:', {
            total: workflowExecutions.length,
            normal: normalExecutions.length,
            special: specialExecutions.length,
            orchestration: _orchestrationStatuses.map(o => `${o.role}:${o.status}`),
            bb: _blackboardKeys,
        });

        // WFステータスを再取得（ジャッジ/SV等が進行して状態が変わっている可能性）
        try {
            wfStatus = await apiRequest(`/api/user/workflow-executions/${wfExecId}/status`);
        } catch (e) {
            console.log('WF status re-check failed:', e.message);
        }

        // WFが完了/エラーなら即停止
        if (wfStatus && (wfStatus.status === 'success' || wfStatus.status === 'error' || wfStatus.status === 'cancelled')) {
            console.log('Workflow finished:', wfStatus.status, wfStatus.error_message);
            _checkNextStepRetryCount = 0;
            if (wfStatus.status === 'error') {
                showAlert(`ワークフローがエラーで停止しました: ${wfStatus.error_message || ''}`, 'error');
            }
            if (typeof PersistentStatusBar !== 'undefined') {
                PersistentStatusBar.markAsCompleted(wfStatus.status === 'success' ? 'success' : 'error');
            }
            streamingWorkers.forEach((w) => w.terminate());
            streamingWorkers.clear();
            return;
        }

        // 次のステップを探す:
        // 1. pending/processing中の通常スキル（SVのrepeat後の再実行、品質ゲート後の再実行など）
        // 2. なければcompleted以降のskill_orderで未ストリーミングのもの
        let nextExecution = normalExecutions
            .filter(exec => ['pending_local', 'pending', 'processing'].includes(exec.status) && !streamingWorkers.has(exec.id))
            .sort((a, b) => a.id - b.id)[0];  // IDが新しいものを優先

        if (!nextExecution) {
            nextExecution = normalExecutions
                .filter(exec => exec.skill_order > completedStepOrder && !streamingWorkers.has(exec.id) && exec.status !== 'cancelled')
                .sort((a, b) => a.skill_order - b.skill_order)[0];
        }

        if (nextExecution) {
            _checkNextStepRetryCount = 0;
            const nextStepOrder = nextExecution.skill_order;
            console.log('Next step execution found:', {
                nextExecutionId: nextExecution.id,
                nextStepOrder,
                status: nextExecution.status,
            });

            const nextStepInfo = workflowDetail?.skills?.find(s => s.skill_order == nextStepOrder);
            const nextStepName = nextStepInfo?.skill_name || nextExecution.skill_name || `Step ${nextStepOrder}`;
            const nextPromptName = nextStepInfo?.skill_name || nextStepName;
            const workflowName = workflowDetail?.workflow?.name || 'ワークフロー';

            if (typeof PersistentStatusBar !== 'undefined') {
                PersistentStatusBar.handleWorkflowNextStep(nextExecution.id, nextStepOrder, nextStepName, workflowName);
            }

            console.log('Starting next step streaming:', { nextExecutionId: nextExecution.id, nextStepOrder, nextStepName });
            startStepStreaming(nextExecution.id, nextStepOrder, nextStepName, nextPromptName);
        } else if (wfStatus && wfStatus.status === 'processing') {
            // WFはまだ処理中（ジャッジ/SV/Reflectionがバックエンドで進行中）→ リトライ
            _checkNextStepRetryCount++;
            if (_checkNextStepRetryCount >= _MAX_CHECK_RETRIES) {
                console.log('Max retries but WF still processing, continuing to poll...');
                _checkNextStepRetryCount = 0;  // リセットして継続
            }
            console.log('WF processing, waiting for backend orchestration...', { retry: _checkNextStepRetryCount });
            setTimeout(async () => {
                await checkAndStartNextStep(wfExecId, completedStepOrder);
            }, 3000);
        } else {
            _checkNextStepRetryCount++;
            if (_checkNextStepRetryCount >= _MAX_CHECK_RETRIES) {
                console.error('Max retries reached and WF status unknown');
                showAlert('次のステップの起動がタイムアウトしました。履歴から詳細を確認してください。', 'error');
                return;
            }
            console.log('Next step not found yet, will retry...', { retry: _checkNextStepRetryCount });
            setTimeout(async () => {
                await checkAndStartNextStep(wfExecId, completedStepOrder);
            }, 3000);
        }
    } catch (error) {
        console.error('Failed to check next step:', error);
    }
}

// 実行履歴を読み込む
async function loadHistory() {
    try {
        const response = await apiRequest(`/api/user/executions?skip=0&limit=500`);
        const responseExecutions = response.items || response;

        // このワークフローに関連する実行をフィルタリング
        const workflowPromptIds = workflowDetail?.skills?.map(s => s.skill_id) || [];
        const relevantExecs = responseExecutions.filter(exec =>
            exec.workflow_execution_id && (
                (workflowExecutionId && exec.workflow_execution_id === workflowExecutionId) ||
                workflowPromptIds.includes(exec.skill_id)
            )
        );

        // ワークフロー実行ID単位でグルーピング
        const grouped = {};
        for (const exec of relevantExecs) {
            const weId = exec.workflow_execution_id;
            if (!grouped[weId]) {
                grouped[weId] = [];
            }
            grouped[weId].push(exec);
        }

        // 各グループ内をステップ順序でソート
        for (const weId in grouped) {
            grouped[weId].sort((a, b) => (a.skill_order || 0) - (b.skill_order || 0));
        }

        // ワークフロー実行単位でまとめた配列（最新順）
        allExecutions = Object.entries(grouped)
            .map(([weId, execs]) => ({
                workflowExecutionId: parseInt(weId),
                executions: execs,
                latestAt: execs.reduce((max, e) => {
                    const t = e.executed_at ? new Date(e.executed_at).getTime() : 0;
                    return t > max ? t : max;
                }, 0),
            }))
            .sort((a, b) => b.latestAt - a.latestAt);

        displayedHistoryCount = 5;
        renderHistory();
    } catch (error) {
        console.error('Load history error:', error);
    }
}

function _wfStatusColor(status) {
    if (status === 'success') return '#28a745';
    if (status === 'error') return '#dc3545';
    if (status === 'cancelled') return '#ffc107';
    if (status === 'pending' || status === 'pending_local' || status === 'processing') return '#7c3aed';
    return 'rgba(255, 255, 255, 0.6)';
}

function _wfOverallStatus(execs) {
    if (execs.some(e => e.status === 'error')) return 'error';
    if (execs.some(e => e.status === 'cancelled')) return 'cancelled';
    if (execs.some(e => e.status === 'pending' || e.status === 'pending_local' || e.status === 'processing')) return 'processing';
    if (execs.every(e => e.status === 'success')) return 'success';
    return 'pending';
}

// 実行履歴を表示（テーブル形式 — history.html と同じ見た目）
function renderHistory() {
    const tbody = document.getElementById('history-tbody');
    if (!tbody) return;

    if (allExecutions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: rgba(255, 255, 255, 0.6);">このワークフローの実行履歴がありません</td></tr>';
        return;
    }

    const displayed = allExecutions.slice(0, displayedHistoryCount);
    const hasMore = allExecutions.length > displayedHistoryCount;

    tbody.innerHTML = displayed.map((group) => {
        const execs = group.executions;
        const firstAt = execs.reduce((min, e) => {
            if (!e.executed_at) return min;
            return !min || e.executed_at < min ? e.executed_at : min;
        }, null);
        const normalExecsHist = execs.filter(e => !e.execution_role);
        const totalTime = normalExecsHist.reduce((sum, e) => sum + (e.execution_time || 0), 0);
        const totalTokens = normalExecsHist.reduce((sum, e) => sum + (e.tokens_used || 0), 0);
        const overallStatus = _wfOverallStatus(execs);
        const statusColor = _wfStatusColor(overallStatus);
        const stepExecs = normalExecsHist.filter(e => e.skill_order && e.workflow_skill_id);

        // 各スキルの小さなバー（history.html と同じ形式）
        const skillBars = stepExecs.map(e => {
            const sc = _wfStatusColor(e.status);
            const name = escapeHtmlCommon(e.skill_name || `Step ${e.skill_order}`);
            return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:4px;font-size:10px;background:rgba(0,0,0,0.2);border-left:2px solid ${sc};color:rgba(255,255,255,0.8);">${name}</span>`;
        }).join(' ');

        return `
        <tr>
            <td>${firstAt ? formatDate(firstAt) : '-'}</td>
            <td>
                <div style="margin-bottom:4px;">
                    <span style="color: rgba(255,255,255,0.4); font-size: 11px;">${stepExecs.length} steps</span>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:4px;">${skillBars}</div>
            </td>
            <td>${totalTime ? totalTime + 'ms' : '-'}</td>
            <td>${totalTokens || '-'}</td>
            <td><span style="color: ${statusColor}">${overallStatus}</span></td>
            <td style="white-space: nowrap;">
                <button onclick="editWorkflowExecution(${group.workflowExecutionId})" title="入力データを復元" class="icon-btn" style="display: inline-flex; align-items: center; justify-content: center; padding: 6px; background: none; border: none; cursor: pointer;">
                    <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 20px; height: 20px; fill: #28a745;"><path d="m11.239 15.533c-1.045 3.004-1.238 3.451-1.238 3.84 0 .441.385.627.627.627.272 0 1.108-.301 3.829-1.249zm.888-.888 3.22 3.22 6.408-6.401c.163-.163.245-.376.245-.591 0-.213-.082-.427-.245-.591-.58-.579-1.458-1.457-2.039-2.036-.163-.163-.377-.245-.591-.245-.213 0-.428.082-.592.245zm-3.127-.895c0-.402-.356-.75-.75-.75-2.561 0-2.939 0-5.5 0-.394 0-.75.348-.75.75s.356.75.75.75h5.5c.394 0 .75-.348.75-.75zm5-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75z" fill-rule="nonzero"/></svg>
                </button>
                <button onclick="showWorkflowHistoryDetail(${group.workflowExecutionId})" title="詳細" class="icon-btn" style="display: inline-flex; align-items: center; justify-content: center; padding: 6px; background: none; border: none; cursor: pointer;">
                    <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 20px; height: 20px; fill: #17a2b8;"><path d="m15 17.75c0-.414-.336-.75-.75-.75h-11.5c-.414 0-.75.336-.75.75s.336.75.75.75h11.5c.414 0 .75-.336.75-.75zm7-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75z" fill-rule="nonzero"/></svg>
                </button>
            </td>
        </tr>
        `;
    }).join('') + (hasMore ? `
        <tr><td colspan="6" style="text-align: center; padding: 15px;">
            <button class="btn btn-secondary" onclick="loadMoreHistory()">もっと見る</button>
        </td></tr>
    ` : '');
}

function loadMoreHistory() {
    displayedHistoryCount += 5;
    renderHistory();
}

// ワークフロー実行の入力データを復元
async function editWorkflowExecution(weId) {
    try {
        // 該当ワークフロー実行の全ステップを取得
        const response = await apiRequest(`/api/user/executions?limit=100`);
        const allExecs = (response.items || response).filter(e => e.workflow_execution_id === weId);
        if (allExecs.length === 0) {
            showAlert('実行データが見つかりません', 'error');
            return;
        }

        allExecs.sort((a, b) => (a.skill_order || 0) - (b.skill_order || 0));

        // 全ステップの入力データからフォームを復元
        restoreAllWorkflowInputData(allExecs);

        // 入力パネルにスクロール
        const inputPanel = document.querySelector('.workflow-input-panel') || document.getElementById('workflow-input-fields-container');
        if (inputPanel) {
            inputPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        showAlert('入力データを読み込みました。必要に応じて編集してから実行ボタンを押してください。', 'success');
    } catch (error) {
        showAlert('実行データの読み込みに失敗しました', 'error');
        console.error('editWorkflowExecution error:', error);
    }
}

// ワークフロー実行の詳細をまとめて表示
async function showWorkflowHistoryDetail(weId) {
    try {
        const response = await apiRequest(`/api/user/executions?skip=0&limit=500`);
        const execs = (response.items || response)
            .filter(e => e.workflow_execution_id === weId)
            .sort((a, b) => (a.skill_order || 0) - (b.skill_order || 0));

        if (execs.length === 0) {
            showAlert('実行データが見つかりません', 'error');
            return;
        }

        const esc = execDetailModal.escapeHtml;
        const workflowName = execs[0]?.workflow_name || workflowDetail?.workflow?.name || 'ワークフロー';
        const wfStatus = await apiRequest(`/api/user/workflow-executions/${weId}/status`);

        const normalExecs = execs.filter(e => !e.execution_role);
        const leaderExec = normalExecs.find(e => !e.workflow_skill_id || e.workflow_skill_id === null);
        const stepExecs = normalExecs.filter(e => e.skill_order && e.workflow_skill_id);
        const totalTime = normalExecs.reduce((sum, e) => sum + (e.execution_time || 0), 0);
        const totalTokens = normalExecs.reduce((sum, e) => sum + (e.tokens_used || 0), 0);

        // グループ情報（このページでは workflowDetail が既にある）
        const groups = workflowDetail?.workflow?.groups || null;

        const allStepResults = stepExecs.map(exec => ({
            stepOrder: exec.skill_order,
            stepName: exec.skill_name || `Step ${exec.skill_order}`,
            status: exec.status,
            output: exec.output_data || '',
            errorMessage: exec.error_message,
            model: exec.model_used,
            time: exec.execution_time,
            tokens: exec.tokens_used,
            workflowSkillId: exec.workflow_skill_id,
            skillId: exec.skill_id,
            agentProfile: exec.agent_profile || null,
            inputData: exec.input_data || null,
        }));
        const finalOutput = leaderExec?.output_data || '';
        const resultHtml = execDetailModal.buildWorkflowFlowHTML({
            finalOutput, allStepResults, workflowName, groups,
            stageMeta: {
                currentStage: wfStatus?.current_stage || null,
                finalVerdict: wfStatus?.final_verdict || null,
                handoffSummary: wfStatus?.handoff_summary || null,
                coordinatorView: wfStatus?.coordinator_view || null,
                synthesisEvents: wfStatus?.synthesis_events || [],
            },
        });

        const detailHTML = `
            <div style="text-align: left;">
                <div style="margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1);">
                    <div style="color: #c4b5fd; font-weight: 600; font-size: 16px; margin-bottom: 6px;">${esc(workflowName)}</div>
                    <div style="display: flex; gap: 16px; color: #888; font-size: 12px;">
                        <span>${stepExecs.length} ステップ</span>
                        <span>合計 ${totalTime}ms</span>
                        <span>${totalTokens} tokens</span>
                    </div>
                </div>
                ${resultHtml}
            </div>
        `;

        await Swal.fire({
            title: 'ワークフロー実行詳細',
            html: detailHTML,
            width: '880px',
            confirmButtonText: USER_SWAL.btnClose,
            confirmButtonColor: USER_SWAL.primary,
            customClass: { popup: 'swal-wide swal-exec-detail' },
        });
    } catch (error) {
        await showAlert('詳細情報の読み込みに失敗しました', 'error');
        console.error('showWorkflowHistoryDetail error:', error);
    }
}

// 後方互換（個別ステップ詳細が呼ばれた場合のフォールバック）
async function showHistoryDetail(id) {
    try {
        const execution = await apiRequest(`/api/user/executions/${id}`);
        if (execution.workflow_execution_id) {
            await showWorkflowHistoryDetail(execution.workflow_execution_id);
        } else {
            const { escapeHtml, buildHtml } = execDetailModal;
            const detailHTML = buildHtml(execution, {
                formatJSON,
                summaryChips: [
                    { label: '実行日時', valueHtml: escapeHtml(formatDate(execution.executed_at)) },
                    { label: 'モデル', valueHtml: escapeHtml(execution.model_used || '-') },
                ],
                showOutputFormat: true,
                outputCopyId: String(execution.id),
            });
            await Swal.fire({
                title: '実行詳細',
                html: detailHTML,
                width: '880px',
                confirmButtonText: USER_SWAL.btnClose,
                confirmButtonColor: USER_SWAL.primary,
                customClass: { popup: 'swal-wide swal-exec-detail' },
            });
        }
    } catch (error) {
        await showAlert('詳細情報の読み込みに失敗しました', 'error');
    }
}

document.getElementById('workflow-execute-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const executeBtn = document.getElementById('workflow-execute-btn');
    const executeBtnText = document.getElementById('workflow-execute-btn-text');
    const executeBtnSpinner = document.getElementById('workflow-execute-btn-spinner');
    const form = e.target;
    // finally でも参照するためここで取得しておく（未定義防止）
    const inputs = form.querySelectorAll('input, textarea, select, button');

    try {
        // 入力値を集約
        // 注意: disabled な入力は FormData に含まれないため、無効化は「取得後」に行う
        const formData = new FormData(form);
        const globalInputData = {};
        const perSkillInput = {};

        for (const [key, value] of formData.entries()) {
            if (key === 'workflow-output-format') continue;

            // ワークフロー共通入力（wf_global__ プレフィックス）
            if (key.startsWith('wf_global__')) {
                const fieldName = key.replace('wf_global__', '');
                globalInputData[fieldName] = value;
                continue;
            }

            // Skill個別入力（workflow_skill_id__fieldName 形式）
            const parts = key.split('__');
            if (parts.length !== 2) continue;
            const wsId = parseInt(parts[0], 10);
            const fieldName = parts[1];
            if (!wsId || !fieldName) continue;
            if (!perSkillInput[wsId]) {
                perSkillInput[wsId] = {};
            }
            perSkillInput[wsId][fieldName] = value;
        }

        const outputFormatSelect = document.getElementById('workflow-output-format');
        const outputFormat = outputFormatSelect ? outputFormatSelect.value || 'txt' : 'txt';

        const body = {
            workflow_id: parseInt(workflowId),
            global_input_data: globalInputData,
            per_skill_input: perSkillInput,
            output_format: outputFormat,
        };

        // ボタン無効化
        executeBtn.disabled = true;
        executeBtnText.textContent = '実行中...';
        if (executeBtnSpinner) executeBtnSpinner.style.display = 'inline';
        inputs.forEach((el) => { if (el !== executeBtn) el.disabled = true; });

        const resp = await apiRequest('/api/execute/workflow', {
            method: 'POST',
            body: JSON.stringify(body)
        });

        // workflow_execution_idを保存
        workflowExecutionId = resp.workflow_execution_id;
        stepExecutions.clear();
        _checkNextStepRetryCount = 0;

        // 結果コンテナを再表示（前回非表示にした場合）
        const resultContainer = document.getElementById('workflow-result-container');
        if (resultContainer) resultContainer.style.display = '';

        // フロービュー表示（リーダー + グループ構造）
        _flowStepStatuses = {};
        _flowLeaderOutput = '';
        _orchestrationStatuses = [];
        _blackboardKeys = [];
        _flowViewDetail = workflowDetail;
        if (workflowDetail) {
            renderFlowView(workflowDetail, _flowStepStatuses);
        }

        // 全ての初期ステップのストリーミングを開始（並列実行対応）
        const executionIds = resp.execution_ids || [];
        const allSkills = workflowDetail?.skills || [];

        if (executionIds.length > 0) {
            // バックグラウンドパネルに最初のステップを登録
            const firstStep = allSkills[0];
            const firstStepName = firstStep?.skill_name || 'Step 1';
            if (typeof PersistentStatusBar !== 'undefined') {
                const workflowName = workflowDetail?.workflow?.name || 'ワークフロー';
                PersistentStatusBar.start(
                    executionIds[0],
                    null,
                    firstStepName,
                    workflowExecutionId,
                    workflowName,
                    firstStep?.skill_order || 1,
                    firstStepName,
                    parseInt(workflowId)
                );
            }

            // 全ての初期ステップのストリーミングを開始
            for (let i = 0; i < executionIds.length; i++) {
                const stepSkill = allSkills[i] || allSkills[0];
                const stepName = stepSkill?.skill_name || `Step ${i + 1}`;
                const stepOrder = stepSkill?.skill_order || (i + 1);
                startStepStreaming(executionIds[i], stepOrder, stepName, stepName);
            }
        }

        // 履歴を再読み込み
        await loadHistory();
        // 実行成功 — ボタンは完了まで非活性のまま維持
        return;
    } catch (error) {
        await showAlert('ワークフロー実行に失敗しました', 'error');
        console.error('execute workflow error:', error);
        // エラー時のみボタンを再有効化
        executeBtn.disabled = false;
        executeBtnText.textContent = 'ワークフロー実行';
        if (executeBtnSpinner) executeBtnSpinner.style.display = 'none';
        inputs.forEach((el) => {
            if (el !== executeBtn) el.disabled = false;
        });
    }
});

// ページ読み込み時に実行
(async () => {
    initUserLayout('');  // workflow-execute.html はナビでactive無し
    await checkAuth();
    await loadWorkflowDetail();
})();
