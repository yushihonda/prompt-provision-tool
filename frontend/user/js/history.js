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
        tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: rgba(255, 255, 255, 0.6);">実行履歴がありません</td></tr>';
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
    const totalTime = execs.reduce((s, e) => s + (e.execution_time || 0), 0);
    const totalTokens = execs.reduce((s, e) => s + (e.tokens_used || 0), 0);
    const overallStatus = getOverallStatus(execs);
    const statusColor = getStatusColor(overallStatus);
    const stepExecs = execs.filter(e => e.skill_order && e.workflow_skill_id);
    const weId = group.workflowExecutionId;

    // 各スキルの小さなバー
    const skillBars = stepExecs.map(e => {
        const sc = getStatusColor(e.status);
        const name = escapeHtmlCommon(e.skill_name || `Step ${e.skill_order}`);
        return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:4px;font-size:10px;background:rgba(0,0,0,0.2);border-left:2px solid ${sc};color:rgba(255,255,255,0.8);">${name}</span>`;
    }).join(' ');

    return `
    <tr>
        <td>${group.executedAt ? formatDate(group.executedAt) : '-'}</td>
        <td>
            <div style="margin-bottom:4px;">
                <span style="color: #7c3aed; font-weight: 600; font-size: 13px;">${escapeHtmlCommon(group.workflowName)}</span>
                <span style="color: rgba(255,255,255,0.4); font-size: 11px; margin-left: 6px;">${stepExecs.length} steps</span>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;">${skillBars}</div>
        </td>
        <td style="font-size:11px;color:rgba(255,255,255,0.5);">-</td>
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
    return 'rgba(255, 255, 255, 0.6)';
}

function getOverallStatus(execs) {
    if (execs.some(e => e.status === 'error')) return 'error';
    if (execs.some(e => e.status === 'cancelled')) return 'cancelled';
    if (execs.some(e => e.status === 'pending' || e.status === 'pending_local' || e.status === 'processing')) return 'processing';
    if (execs.every(e => e.status === 'success')) return 'success';
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
        const leaderExec = execs.find(e => !e.workflow_skill_id || e.workflow_skill_id === null);
        const stepExecs = execs.filter(e => e.skill_order && e.workflow_skill_id);
        const totalTime = execs.reduce((s, e) => s + (e.execution_time || 0), 0);
        const totalTokens = execs.reduce((s, e) => s + (e.tokens_used || 0), 0);

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
        }));
        const finalOutput = leaderExec?.output_data || '';
        const resultHtml = execDetailModal.buildWorkflowFlowHTML({
            finalOutput, allStepResults, workflowName, groups,
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

