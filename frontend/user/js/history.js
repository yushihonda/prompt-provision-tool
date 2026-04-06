// ユーザー 実行履歴画面 JavaScript

let groupedRows = []; // { type: 'skill' | 'workflow', ... }
let currentPage = 1;
const itemsPerPage = 10;
let totalItems = 0;

async function loadHistory(page = 1) {
    try {
        // ワークフロー実行をまとめるため、多めに取得してグルーピング
        const response = await apiRequest(`/api/user/executions?skip=0&limit=500`);
        const allExecs = response.items || response;

        // ワークフロー実行IDでグルーピング / スキル単体はそのまま
        const wfGroups = {};
        const skillRows = [];

        for (const exec of allExecs) {
            if (exec.workflow_execution_id) {
                const weId = exec.workflow_execution_id;
                if (!wfGroups[weId]) {
                    wfGroups[weId] = {
                        type: 'workflow',
                        workflowExecutionId: weId,
                        workflowName: exec.workflow_name || 'ワークフロー',
                        executions: [],
                    };
                }
                wfGroups[weId].executions.push(exec);
            } else {
                skillRows.push({ type: 'skill', execution: exec });
            }
        }

        // ワークフローグループ内をステップ順でソート、代表日時を算出
        const wfRows = Object.values(wfGroups).map(g => {
            g.executions.sort((a, b) => (a.skill_order || 0) - (b.skill_order || 0));
            g.executedAt = g.executions.reduce((earliest, e) => {
                if (!e.executed_at) return earliest;
                return !earliest || e.executed_at < earliest ? e.executed_at : earliest;
            }, null);
            return g;
        });

        // スキル行とワークフロー行を統合して日時降順ソート
        const merged = [...skillRows, ...wfRows];
        merged.sort((a, b) => {
            const tA = a.type === 'skill' ? a.execution.executed_at : a.executedAt;
            const tB = b.type === 'skill' ? b.execution.executed_at : b.executedAt;
            if (!tA) return 1;
            if (!tB) return -1;
            return tB > tA ? 1 : tB < tA ? -1 : 0;
        });

        groupedRows = merged;
        totalItems = merged.length;
        currentPage = page;
        renderHistory();
        renderPagination();
    } catch (error) {
        showAlert('実行履歴の読み込みに失敗しました', 'error');
        console.error('Load history error:', error);
    }
}

function renderHistory() {
    const tbody = document.getElementById('history-tbody');
    const start = (currentPage - 1) * itemsPerPage;
    const pageRows = groupedRows.slice(start, start + itemsPerPage);

    if (pageRows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: #a0a0a0;">実行履歴がありません</td></tr>';
        return;
    }

    tbody.innerHTML = pageRows.map(row => {
        if (row.type === 'skill') {
            return renderSkillRow(row.execution);
        } else {
            return renderWorkflowRow(row);
        }
    }).join('');
}

function renderSkillRow(execution) {
    const modelDisplay = formatModelDisplay(execution.model_used, execution);
    const statusColor = getStatusColor(execution.status);

    return `
    <tr>
        <td>${formatDate(execution.executed_at)}</td>
        <td>${escapeHtmlCommon(execution.skill_name || '-')}</td>
        <td>${modelDisplay}</td>
        <td>${execution.output_format ? execution.output_format.toUpperCase() : 'TXT'}</td>
        <td>${execution.execution_time || '-'}${execution.execution_time ? 'ms' : ''}</td>
        <td>${execution.tokens_used || '-'}</td>
        <td><span style="color: ${statusColor}">${execution.status}</span></td>
        <td>
            <button onclick="showDetail(${execution.id})" title="詳細" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer;">
                <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #17a2b8;"><path d="m15 17.75c0-.414-.336-.75-.75-.75h-11.5c-.414 0-.75.336-.75.75s.336.75.75.75h11.5c.414 0 .75-.336.75-.75zm7-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75z" fill-rule="nonzero"/></svg>
            </button>
        </td>
    </tr>
    `;
}

function renderWorkflowRow(group) {
    const execs = group.executions;
    const normalExecs = execs.filter(e => !e.execution_role);
    const totalTime = normalExecs.reduce((s, e) => s + (e.execution_time || 0), 0);
    const totalTokens = normalExecs.reduce((s, e) => s + (e.tokens_used || 0), 0);
    const overallStatus = getOverallStatus(execs);
    const statusColor = getStatusColor(overallStatus);
    const stepExecs = normalExecs.filter(e => e.skill_order && e.workflow_skill_id);
    const leaderExec = normalExecs.find(e => !e.workflow_skill_id);
    const parentModel = leaderExec?.model_used || normalExecs[0]?.model_used || '-';
    const modelDisplay = typeof formatModelDisplay === 'function' ? formatModelDisplay(parentModel, null, {}) : parentModel;
    const weId = group.workflowExecutionId;

    // 各スキルのミニキューブ
    let skillBars = stepExecs.map((e, i) => {
        const sc = getStatusColor(e.status);
        const cube = renderMiniCube(e.agent_profile || 'default', { size: 22, borderColor: sc, showLabel: false });
        return (i > 0 ? '<span style="color:#ccc; font-size:10px; vertical-align:middle;">→</span>' : '') + cube;
    }).join('');
    // リーダーキューブを追加
    const leaderSc = getStatusColor(overallStatus);
    skillBars += '<span style="color:#ccc; font-size:10px; vertical-align:middle;">→</span>' + renderMiniCube('default', { size: 22, borderColor: leaderSc, showLabel: false });

    return `
    <tr>
        <td>${group.executedAt ? formatDate(group.executedAt) : '-'}</td>
        <td>
            <div style="margin-bottom:4px;">
                <span style="color: #7c3aed; font-weight: 600; font-size: 13px;">${escapeHtmlCommon(group.workflowName)}</span>
                <span style="color: #a0a0a0; font-size: 11px; margin-left: 6px;">${stepExecs.length} steps</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:12px;perspective:300px;align-items:center;">${skillBars}</div>
        </td>
        <td>${modelDisplay}</td>
        <td>-</td>
        <td>${totalTime ? totalTime + 'ms' : '-'}</td>
        <td>${totalTokens || '-'}</td>
        <td><span style="color: ${statusColor}">${overallStatus}</span></td>
        <td>
            <button onclick="showWorkflowDetail(${weId})" title="詳細" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer;">
                <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #17a2b8;"><path d="m15 17.75c0-.414-.336-.75-.75-.75h-11.5c-.414 0-.75.336-.75.75s.336.75.75.75h11.5c.414 0 .75-.336.75-.75zm7-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75z" fill-rule="nonzero"/></svg>
            </button>
        </td>
    </tr>
    `;
}

function getStatusColor(status) {
    if (status === 'success') return '#28a745';
    if (status === 'error') return '#dc3545';
    if (status === 'cancelled') return '#ffc107';
    if (status === 'pending' || status === 'pending_local' || status === 'processing') return '#7c3aed';
    return '#a0a0a0';
}

function getOverallStatus(execs) {
    // 特殊ロール（quality_gate, supervisor等）のエラーはWF全体のエラーとしない
    const normalExecs = execs.filter(e => !e.execution_role);
    if (normalExecs.some(e => e.status === 'error')) return 'error';
    if (normalExecs.some(e => e.status === 'cancelled')) return 'cancelled';
    if (normalExecs.some(e => e.status === 'pending' || e.status === 'pending_local' || e.status === 'processing')) return 'processing';
    if (normalExecs.every(e => e.status === 'success')) return 'success';
    return 'pending';
}

function renderPagination() {
    renderUserPagination('pagination-container', currentPage, totalItems, itemsPerPage, 'loadHistory');
}

async function showDetail(id) {
    try {
        const execution = await apiRequest(`/api/user/executions/${id}`);

        // ワークフロー実行の場合はワークフロー詳細に切り替え
        if (execution.workflow_execution_id) {
            await showWorkflowDetail(execution.workflow_execution_id);
            return;
        }

        const modelHtml = formatModelDisplay(execution.model_used, execution);
        const { escapeHtml, buildHtml } = execDetailModal;

        const summaryChips = [
            { label: '実行日時', valueHtml: escapeHtml(formatDate(execution.executed_at)) },
            { label: 'スキル', valueHtml: escapeHtml(execution.skill_name || '-') },
            { label: 'モデル', valueHtml: modelHtml },
        ];

        const detailHTML = buildHtml(execution, {
            formatJSON,
            summaryChips,
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
    } catch (error) {
        await showAlert('詳細情報の読み込みに失敗しました', 'error');
        console.error('Load detail error:', error);
    }
}

async function showWorkflowDetail(weId) {
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
        const workflowName = execs[0]?.workflow_name || 'ワークフロー';
        const normalExecs = execs.filter(e => !e.execution_role);
        const leaderExec = normalExecs.find(e => !e.workflow_skill_id || e.workflow_skill_id === null);
        const stepExecs = normalExecs.filter(e => e.skill_order && e.workflow_skill_id);
        const totalTime = normalExecs.reduce((s, e) => s + (e.execution_time || 0), 0);
        const totalTokens = normalExecs.reduce((s, e) => s + (e.tokens_used || 0), 0);

        // グループ情報を取得
        let groups = null;
        const wfId = execs.find(e => e.workflow_id)?.workflow_id;
        if (wfId) {
            try {
                const wfDetail = await apiRequest(`/api/user/workflows/${wfId}`);
                groups = wfDetail?.workflow?.groups || null;
            } catch (e) { /* グループ取得失敗時はフラット表示 */ }
        }

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
            inputData: exec.input_data || null,
            agentProfile: exec.agent_profile || null,
        }));
        const finalOutput = leaderExec?.output_data || '';
        // coordinator view / synthesis events を取得
        let wfStatus = null;
        try {
            wfStatus = await apiRequest(`/api/user/workflow-executions/${weId}/status`);
        } catch (e) { /* ignore */ }
        await execDetailModal.showWorkflowDetailPopup({
            workflowName, allStepResults, leaderExec, groups,
            leaderModel: leaderExec?.model_used || '',
            stageMeta: {
                currentStage: wfStatus?.current_stage || null,
                finalVerdict: wfStatus?.final_verdict || null,
                handoffSummary: wfStatus?.handoff_summary || null,
                coordinatorView: wfStatus?.coordinator_view || null,
                synthesisEvents: wfStatus?.synthesis_events || [],
            },
            stepCount: stepExecs.length,
            totalTime,
            totalTokens,
        });
    } catch (error) {
        await showAlert('詳細情報の読み込みに失敗しました', 'error');
        console.error('showWorkflowDetail error:', error);
    }
}

// formatJSON は user-common.js で定義済み

// ページ読み込み時に実行
(async () => {
    initUserLayout('history.html');
    await checkAuth();
    loadHistory(1);
})();

