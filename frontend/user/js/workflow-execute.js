// ユーザー ワークフロー実行画面 JavaScript

let workflowId = null;
let workflowDetail = null;
let workflowExecutionId = null;
let stepExecutions = new Map(); // skill_order -> { executionId, status, output, stepName, skillName }
let allExecutions = []; // 全ての実行履歴
let displayedHistoryCount = 5; // 表示する履歴の件数
let streamingWorkers = new Map(); // executionId -> worker
let _wfStageMeta = { currentStage: null, finalVerdict: null, handoffSummary: null, coordinatorView: null, synthesisEvents: [] };
let desktopWorkflowRun = null;

async function createDesktopWorkflowRun(workflowExecutionIdValue) {
    if (!window.NexMAGIRuntime.canRecordDesktopEvents()) {
        return;
    }

    const workflowName = workflowDetail?.workflow?.name || `Workflow ${workflowId}`;
    const correlationId = `workflow-execution-${workflowExecutionIdValue}`;
    const run = await window.NexMAGIRuntime.createWorkflowRun(`Workflow Execution: ${workflowName}`);
    const recorder = window.NexMAGIRuntime.createDesktopEventRecorder({
        runId: run.id,
        correlationId,
    });
    const commonPayload = {
        workflow_execution_id: workflowExecutionIdValue,
        workflow_id: parseInt(workflowId, 10),
        workflow_name: workflowName,
    };
    const uiIntent = await recorder.append('ui.workflow_execute_clicked', {
        attemptNo: 0,
        originLayer: 'ui',
        idempotencyKey: `run:${run.id}:ui:workflow_execute_clicked`,
        payloadJson: commonPayload,
    });
    const workflowCreated = await recorder.append('workflow_run_created', {
        attemptNo: 0,
        causationId: uiIntent.eventId,
        triggerEventId: uiIntent.eventId,
        originLayer: 'engine',
        idempotencyKey: `run:${run.id}:workflow_run_created`,
        payloadJson: commonPayload,
    });
    desktopWorkflowRun = {
        runId: run.id,
        correlationId,
        workflowExecutionId: workflowExecutionIdValue,
        recorder,
        rootEventId: recorder.getState().rootEventId,
        uiIntentEventId: uiIntent.eventId,
        workflowCreatedEventId: workflowCreated.eventId,
        lastNodeFinishedEventId: workflowCreated.eventId,
        stepEvents: new Map(),
        isFinalized: false,
    };
}

function getDesktopWorkflowNodeState(executionId, stepOrder) {
    if (!desktopWorkflowRun) {
        return null;
    }

    const nodeKey = `${stepOrder}:${executionId}`;
    let nodeState = desktopWorkflowRun.stepEvents.get(nodeKey);
    if (!nodeState) {
        nodeState = {
            nodeKey,
            nodeId: `workflow-${desktopWorkflowRun.workflowExecutionId}-step-${stepOrder}-execution-${executionId}`,
            executionId,
            stepOrder,
            nodeStartedEventId: null,
            providerStartedEventId: null,
            providerFinishedEventId: null,
            retryDecisionEventId: null,
            nodeFinishedEventId: null,
        };
        desktopWorkflowRun.stepEvents.set(nodeKey, nodeState);
    }
    return nodeState;
}

async function appendDesktopWorkflowNodeEvent(eventType, executionId, stepOrder, payloadJson = {}) {
    if (!desktopWorkflowRun || !window.NexMAGIRuntime.canRecordDesktopEvents()) {
        return;
    }

    const nodeState = getDesktopWorkflowNodeState(executionId, stepOrder);
    const nodeId = nodeState.nodeId;
    const suffix = eventType === 'node_execution_started' ? 'started' : 'finished';
    const event = await desktopWorkflowRun.recorder.append(eventType, {
        nodeId,
        attemptNo: 1,
        causationId: desktopWorkflowRun.workflowCreatedEventId,
        triggerEventId: desktopWorkflowRun.workflowCreatedEventId,
        originLayer: 'engine',
        idempotencyKey: `run:${desktopWorkflowRun.runId}:node:${nodeId}:${suffix}`,
        payloadJson: {
            workflow_execution_id: desktopWorkflowRun.workflowExecutionId,
            execution_id: executionId,
            step_order: stepOrder,
            ...payloadJson,
        }
    });
    if (eventType === 'node_execution_started') {
        nodeState.nodeStartedEventId = event.eventId;
    }
    return event;
}

async function ensureDesktopWorkflowProviderStarted(executionId, stepOrder, payloadJson = {}) {
    if (!desktopWorkflowRun || !window.NexMAGIRuntime.canRecordDesktopEvents()) {
        return;
    }
    if (!window.NexMAGIRuntime.shouldRecordProxyLifecycleEvents('http-api')) {
        return null;
    }

    const nodeState = getDesktopWorkflowNodeState(executionId, stepOrder);
    if (!nodeState || nodeState.providerStartedEventId) {
        return nodeState;
    }

    const providerStarted = await desktopWorkflowRun.recorder.append('provider_request_started', {
        nodeId: nodeState.nodeId,
        attemptNo: 1,
        causationId: nodeState.nodeStartedEventId || desktopWorkflowRun.workflowCreatedEventId,
        triggerEventId: nodeState.nodeStartedEventId || desktopWorkflowRun.workflowCreatedEventId,
        originLayer: 'provider',
        idempotencyKey: `run:${desktopWorkflowRun.runId}:node:${nodeState.nodeId}:provider:start:1`,
        payloadJson: {
            workflow_execution_id: desktopWorkflowRun.workflowExecutionId,
            execution_id: executionId,
            step_order: stepOrder,
            observation_source: window.NexMAGIRuntime.getObservationSource('provider', 'http-api'),
            boundary_kind: payloadJson.boundaryKind || 'sse_stream',
            ...payloadJson,
        }
    });
    nodeState.providerStartedEventId = providerStarted.eventId;
    return nodeState;
}

async function finishDesktopWorkflowNode(executionId, stepOrder, status, errorMessage = null, details = {}) {
    if (!desktopWorkflowRun || !window.NexMAGIRuntime.canRecordDesktopEvents()) {
        return null;
    }

    const nodeState = await ensureDesktopWorkflowProviderStarted(executionId, stepOrder, {
        boundaryKind: details.boundaryKind || 'completion_fallback',
    });
    if (!nodeState || nodeState.nodeFinishedEventId) {
        return nodeState;
    }

    let nodeFinishedCausationId = nodeState.nodeStartedEventId || desktopWorkflowRun.workflowCreatedEventId;

    if (window.NexMAGIRuntime.shouldRecordProxyLifecycleEvents('http-api')) {
        const providerFinished = await desktopWorkflowRun.recorder.append('provider_request_finished', {
            nodeId: nodeState.nodeId,
            attemptNo: 1,
            causationId: nodeState.providerStartedEventId || nodeState.nodeStartedEventId || desktopWorkflowRun.workflowCreatedEventId,
            triggerEventId: nodeState.providerStartedEventId || nodeState.nodeStartedEventId || desktopWorkflowRun.workflowCreatedEventId,
            originLayer: 'provider',
            idempotencyKey: `run:${desktopWorkflowRun.runId}:node:${nodeState.nodeId}:provider:finish:1`,
            payloadJson: {
                workflow_execution_id: desktopWorkflowRun.workflowExecutionId,
                execution_id: executionId,
                step_order: stepOrder,
                status,
                error_message: errorMessage,
                error_code: details.errorCode || null,
                observation_source: window.NexMAGIRuntime.getObservationSource('provider', 'http-api'),
                boundary_kind: details.boundaryKind || 'sse_stream',
            }
        });
        nodeState.providerFinishedEventId = providerFinished.eventId;

        const retryDecision = window.NexMAGIRuntime.classifyRetryDecision({
            status,
            errorCode: details.errorCode || null,
        });
        const retryEvent = await desktopWorkflowRun.recorder.append('retry_decision_made', {
            nodeId: nodeState.nodeId,
            attemptNo: 1,
            causationId: providerFinished.eventId,
            triggerEventId: providerFinished.eventId,
            originLayer: 'retry',
            idempotencyKey: `run:${desktopWorkflowRun.runId}:node:${nodeState.nodeId}:retry:1`,
            payloadJson: {
                workflow_execution_id: desktopWorkflowRun.workflowExecutionId,
                execution_id: executionId,
                step_order: stepOrder,
                status,
                error_message: errorMessage,
                error_code: details.errorCode || null,
                observation_source: window.NexMAGIRuntime.getObservationSource('retry', 'http-api'),
                ...retryDecision,
            }
        });
        nodeState.retryDecisionEventId = retryEvent.eventId;
        nodeFinishedCausationId = retryEvent.eventId;
    }

    const nodeFinished = await desktopWorkflowRun.recorder.append('node_execution_finished', {
        nodeId: nodeState.nodeId,
        attemptNo: 1,
        causationId: nodeFinishedCausationId,
        triggerEventId: nodeFinishedCausationId,
        originLayer: 'engine',
        idempotencyKey: `run:${desktopWorkflowRun.runId}:node:${nodeState.nodeId}:finished`,
        payloadJson: {
            workflow_execution_id: desktopWorkflowRun.workflowExecutionId,
            execution_id: executionId,
            step_order: stepOrder,
            status,
            error_message: errorMessage,
        }
    });
    nodeState.nodeFinishedEventId = nodeFinished.eventId;
    desktopWorkflowRun.lastNodeFinishedEventId = nodeFinished.eventId;
    return nodeState;
}

async function finishDesktopWorkflowRun(status, payloadJson = {}, details = {}) {
    if (!desktopWorkflowRun || !window.NexMAGIRuntime.canRecordDesktopEvents()) {
        return;
    }

    if (desktopWorkflowRun.isFinalized) {
        return;
    }

    desktopWorkflowRun.isFinalized = true;

    try {
        await desktopWorkflowRun.recorder.append('workflow_run_finished', {
            nodeId: null,
            attemptNo: 1,
            causationId: details.causationId || desktopWorkflowRun.lastNodeFinishedEventId || desktopWorkflowRun.workflowCreatedEventId,
            triggerEventId: details.triggerEventId || desktopWorkflowRun.lastNodeFinishedEventId || desktopWorkflowRun.workflowCreatedEventId,
            originLayer: 'engine',
            idempotencyKey: `run:${desktopWorkflowRun.runId}:workflow_run_finished`,
            payloadJson: {
                workflow_execution_id: desktopWorkflowRun.workflowExecutionId,
                status,
                ...payloadJson,
            }
        });
        await window.NexMAGIRuntime.updateWorkflowRunStatus(desktopWorkflowRun.runId, status);
    } catch (error) {
        console.error('Failed to finish desktop workflow run:', error);
    } finally {
        desktopWorkflowRun = null;
    }
}

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

        // フロービューを初期表示（ステータスなし = 全 pending）
        _flowViewDetail = workflowDetail;
        renderFlowView(workflowDetail, {});

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

        // 詳細遷移時: Coordinator データを先にロードしてキューブに反映
        try { await loadCoordinatorPlan(weId); } catch (_) {}
        // 再レンダーハッシュをクリアして強制再描画
        _lastFlowRenderHash = null;
        _lastFlowDataKey = null;
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

        // フロービューを初期化・更新（詳細へ遷移時 + 実行中復帰時）
        if (workflowDetail) {
            _flowViewDetail = workflowDetail;
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
                _flowStepStatuses['leader'] = leaderExecForStatus.status === 'pending_local' ? 'pending' : leaderExecForStatus.status;
            }
            // オーケストレーション状況を復元
            _orchestrationStatuses = specialExecs.map(e => ({
                role: e.execution_role,
                groupId: e.execution_group_id,
                status: e.status,
                action: '',
            }));
            renderFlowView(_flowViewDetail, _flowStepStatuses);
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
                updateStatusBar();
            } catch (e) {}

            // ワークフロー結果を表示（統合結果 + 各ステップ）
            const resultExec = leaderExec || (allStepResults.length > 0 ? allStepResults[allStepResults.length - 1] : null);
            if (resultExec) {
                displayWorkflowResult(finalOutput, allStepResults, resultExec);
            }
        } else {
            // 実行中: Stageメタデータを復元
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
                updateStatusBar();
                if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);
            } catch (e) {}

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
            // 入力パネル全体を無効化 + 切り抜き円をスピナーに
            const inputPanel = document.querySelector('.wf-io-input');
            if (inputPanel) inputPanel.classList.add('is-disabled');
            const execCircle = document.getElementById('workflow-execute-circle');
            const execIcon = document.getElementById('wf-exec-icon');
            const execSpinner = document.getElementById('wf-exec-spinner');
            if (execCircle) execCircle.style.pointerEvents = 'none';
            if (execIcon) execIcon.style.display = 'none';
            if (execSpinner) execSpinner.style.display = 'flex';

            // デスクトップポーリングを再開（ページ遷移後の復帰）
            const allSkills = workflowDetail?.skills || [];
            const _resumePoll = async () => {
                const pollInterval = 3000;
                while (true) {
                    await new Promise(r => setTimeout(r, pollInterval));
                    try {
                        const execsResp = await apiRequest('/api/user/executions?limit=100');
                        const allExecs = execsResp.items || execsResp;
                        const resumeWfExecs = allExecs.filter(e => e.workflow_execution_id === weId);
                        if (resumeWfExecs.length === 0) continue;

                        let hasChanged = false;
                        let hasProcessing = false;

                        // 通常ステップ
                        const latestResume = {};
                        for (const exec of resumeWfExecs) {
                            if (exec.execution_role) continue;
                            if (!exec.workflow_skill_id) continue;
                            const prev = latestResume[exec.workflow_skill_id];
                            if (!prev || exec.id > prev.id) latestResume[exec.workflow_skill_id] = exec;
                        }
                        for (const exec of Object.values(latestResume)) {
                            const mapped = exec.status === 'success' ? 'success'
                                : exec.status === 'error' ? 'error'
                                : (exec.status === 'processing' || exec.status === 'pending' || exec.status === 'pending_local') ? 'processing' : null;
                            if (!mapped) continue;
                            const key = 'ws_' + exec.workflow_skill_id;
                            if (_flowStepStatuses[key] !== mapped) { _flowStepStatuses[key] = mapped; hasChanged = true; }
                            if (exec.skill_id) _flowStepStatuses[exec.skill_id] = mapped;
                            if (mapped === 'processing') hasProcessing = true;
                            if (exec.skill_order) {
                                stepExecutions.set(exec.skill_order, {
                                    executionId: exec.id, workflowSkillId: exec.workflow_skill_id,
                                    status: exec.status, output: exec.output_data || '',
                                    stepName: exec.skill_name || `Step ${exec.skill_order}`,
                                    skillName: exec.skill_name,
                                    errorMessage: exec.status === 'success' ? null : (exec.error_message || null),
                                });
                            }
                        }

                        // リーダー（parent skill: workflow_skill_id=null）
                        const leaderResume = resumeWfExecs.find(e => !e.workflow_skill_id && !e.execution_role);
                        if (leaderResume) {
                            const lm = leaderResume.status === 'success' ? 'success'
                                : leaderResume.status === 'error' ? 'error'
                                : (leaderResume.status === 'processing' || leaderResume.status === 'pending' || leaderResume.status === 'pending_local') ? 'processing' : 'pending';
                            if (_flowStepStatuses['leader'] !== lm) { _flowStepStatuses['leader'] = lm; hasChanged = true; }
                            if (lm === 'success') _flowLeaderOutput = leaderResume.output_data || _flowLeaderOutput;
                            if (lm === 'processing') hasProcessing = true;
                        }
                        // 特殊ロール
                        for (const exec of resumeWfExecs) {
                            if (!exec.execution_role) continue;
                            const lm = exec.status === 'success' ? 'success' : exec.status === 'error' ? 'error' : 'processing';
                            if (_flowStepStatuses['leader'] !== lm) { _flowStepStatuses['leader'] = lm; hasChanged = true; }
                            if (lm === 'success') _flowLeaderOutput = exec.output_data || _flowLeaderOutput;
                            if (lm === 'processing') hasProcessing = true;
                        }

                        if (hasChanged && _flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);

                        // 完了チェック
                        const wfStatusResp = await apiRequest(`/api/user/workflow-executions/${weId}/status`).catch(() => null);
                        if (wfStatusResp && (wfStatusResp.status === 'success' || wfStatusResp.status === 'error' || wfStatusResp.status === 'cancelled')) {
                            const leaderExec = resumeWfExecs.find(e => e.execution_role && (e.status === 'success' || e.status === 'error'))
                                || resumeWfExecs.find(e => !e.workflow_skill_id && !e.execution_role);
                            const leaderExecution = leaderExec
                                ? await apiRequest(`/api/user/executions/${leaderExec.id}`).catch(() => null)
                                : { id: null, status: wfStatusResp.status, output_data: '' };
                            await handleWorkflowComplete(weId, leaderExecution || { id: null, status: wfStatusResp.status, output_data: '' });
                            return;
                        }
                    } catch (e) {
                        console.warn('[ResumePoll] error:', e);
                    }
                }
            };
            _resumePoll().catch(err => console.error('[ResumePoll] fatal:', err));
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
            <div class="workflow-global-section" style="margin-bottom: 24px; padding-bottom: 24px; border-bottom: 2px solid rgba(0,0,0,0.08);">
                <h3 style="margin-top: 0; margin-bottom: 12px; color: var(--content-text);">
                    ワークフロー共通入力
                </h3>
                <p style="font-size: 12px; color: var(--content-text-muted); margin-bottom: 12px;">
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
            // _nexmagi_ プレフィックス（内部メタデータ）を除外
            if (name.startsWith('_nexmagi_')) continue;
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
                    ${description ? `<small style="color: var(--content-text-muted);">${description}</small>` : ''}
                    <input type="number" id="${fullName}" name="${fullName}" ${requiredAttr} ${placeholderAttr}>
                </div>`;
            }
            return `<div class="form-group">
                <label for="${fullName}">${label}</label>
                ${description ? `<small style="color: var(--content-text-muted);">${description}</small>` : ''}
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
                <div class="workflow-step-input-section workflow-step-section" style="margin-top: 24px;">
                    <h3 style="margin-top: 0; margin-bottom: 12px; color: var(--content-text);">入力データ</h3>
                    <div class="workflow-step-fields">${stepSections[0].fieldsHTML}</div>
                </div>
            `);
        } else {
            parts.push(`
                <div class="workflow-step-input-section workflow-step-section" style="margin-top: 24px;">
                    <h3 style="margin-top: 0; margin-bottom: 12px; color: var(--content-text);">各ステップの入力データ</h3>
                    <p style="font-size: 12px; color: var(--content-text-muted); margin-bottom: 12px;">
                        各ステップに個別の入力を設定できます
                    </p>
                    ${stepSections.map(sec => `
                        <div style="margin-bottom: 16px; padding: 12px; border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; border-left: 3px solid #7c3aed;">
                            <div style="font-size: 12px; font-weight: 600; color: #c4b5fd; margin-bottom: 8px;">${sec.stepLabel}</div>
                            <div class="workflow-step-fields">${sec.fieldsHTML}</div>
                        </div>
                    `).join('')}
                </div>
            `);
        }
    }

    if (!parts.length) {
        container.innerHTML =
            '<p style="text-align:center; color: var(--content-text-muted);">このワークフローに有効なステップがありません</p>';
    } else {
        container.innerHTML = parts.join('');
    }
}

// ワークフロー共通入力のinput_schemaから入力フィールドHTMLを生成
function renderInputFieldsForWorkflowGlobal(inputSchema) {
    if (!inputSchema || typeof inputSchema !== 'object') {
        return '<p style="color: var(--content-text-muted);">入力スキーマが定義されていません</p>';
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
        return '<p style="color: var(--content-text-muted);">入力フィールドが定義されていません</p>';
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
                        ${description ? `<small style="color: var(--content-text-muted);">${description}</small>` : ''}
                        <input type="number" id="${fullName}" name="${fullName}" ${required} ${placeholderAttr}>
                    </div>
                `;
            }

            // 文字列はtextareaで統一
            return `
                <div class="form-group">
                    <label for="${fullName}">${label}</label>
                    ${description ? `<small style="color: var(--content-text-muted);">${description}</small>` : ''}
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
                        ${description ? `<small style="color: var(--content-text-muted);">${description}</small>` : ''}
                        <input type="number" id="${fullName}" name="${fullName}" ${required} ${placeholderAttr}>
                    </div>
                `;
            }

            // 文字列はtextareaで統一
            return `
                <div class="form-group">
                    <label for="${fullName}">${label}</label>
                    ${description ? `<small style="color: var(--content-text-muted);">${description}</small>` : ''}
                    <textarea id="${fullName}" name="${fullName}" rows="${rows}" ${required} ${placeholderAttr}></textarea>
                </div>
            `;
        })
        .join('');

    return fieldsHTML;
}

// ステータスバー更新（フロービュー内のサマリーバーで代替）
function updateStatusBar() {
    if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);
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
    const map = { default: 'Leader', explore: 'Explore', plan: 'Plan', implement: 'Implement', verification: 'Verification' };
    return map[stage] || stage;
}

// profile / stage の固定色（全画面で統一）
function _profileColor(profile) {
    const colors = {
        default: '#ce93d8',
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

    let html = `<div style="padding:12px 16px; background:#fff; border:1px solid rgba(0,0,0,0.06); border-radius:12px; margin-bottom:12px;">`;

    // 1行目: Stage + Verdict + 進捗
    html += `<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-bottom:${latestSummary || events.length ? '8px' : '0'};">`;
    html += `<span style="font-size:11px; color:#999;">Stage</span>`;
    html += `<span style="font-size:12px; font-weight:bold; color:${_profileColor(_wfStageMeta.currentStage || 'default')};">${esc(stage)}</span>`;
    if (verdict !== '-') {
        html += `<span style="font-size:11px; color:#999; margin-left:8px;">Verdict</span>`;
        html += `<span style="font-size:12px; font-weight:bold; color:${verdict === 'PASS' ? '#28a745' : verdict === 'FAIL' ? '#dc3545' : verdict === 'PARTIAL' ? '#ffc107' : '#555'};">${esc(verdict)}</span>`;
    }
    if (totalExecs > 0) {
        html += `<span style="font-size:10px; color:#aaa; margin-left:auto;">${completedCount}/${totalExecs} steps</span>`;
    }
    if (failedStage) {
        html += `<span style="font-size:12px; font-weight:bold; color:#dc3545; margin-left:8px;">${esc(failedStage)} failed</span>`;
    }
    html += `</div>`;

    // 2行目: coordinator latest_summary
    if (latestSummary) {
        html += `<div style="display:flex; align-items:center; gap:6px; margin-bottom:${events.length > 0 ? '8px' : '0'};">`;
        html += `<span style="color:${actionColor}; font-size:12px;">${actionIcon}</span>`;
        html += `<span style="font-size:11px; color:#555;">${esc(latestSummary)}</span>`;
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
            html += `<span style="font-size:10px; padding:2px 8px; background:rgba(0,0,0,0.04); border-radius:10px; color:#666; display:inline-flex; align-items:center; gap:3px;">`;
            html += `<span style="color:${evColor};">${evIcon}</span>${esc(ev.summary || ev.step_name || '')}`;
            html += `</span>`;
        }
        html += `</div>`;
    }

    // key_points
    const cvKeyPoints = cv?.key_points || [];
    if (cvKeyPoints.length > 0) {
        html += `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-top:4px;">`;
        cvKeyPoints.forEach(kp => { html += `<span style="font-size:10px; padding:2px 8px; background:rgba(76,175,80,0.08); border-radius:10px; color:#555;">${esc(kp)}</span>`; });
        html += `</div>`;
    }

    // Blackboard refs
    if (refs.length) {
        html += `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-top:6px;">${refs.map(ref => `<span style="font-size:10px; padding:2px 8px; background:rgba(33,150,243,0.08); border-radius:10px; color:#555;">${esc(ref)}</span>`).join('')}</div>`;
    }

    html += `</div>`;
    return html;
}

// Coordinator 観測層の状態 (renderFlowView から参照されるため上で宣言)
let _coordinatorData = null;
let _coordinatorTaskByWsId = {};   // workflow_skill_id → task
let _coordinatorArtifactByWsId = {}; // workflow_skill_id → artifact[]
let _coordinatorJudgedGroups = new Set(); // judged 済み task_id
let _coordinatorEvalMetrics = null; // 完了時の評価メトリクス

// 直近のレンダーハッシュ (ちらつき抑制)
let _lastFlowRenderHash = null;
let _lastFlowDataKey = null;

function _computeFlowRenderHash(wfDetail, statuses) {
    const wf = wfDetail.workflow || wfDetail;
    const groups = wf.groups || [];
    const skillIds = [];
    for (const g of groups) {
        for (const s of (g.skills || [])) skillIds.push(s.workflow_skill_id || s.id);
    }
    const taskIds = Object.keys(_coordinatorTaskByWsId).sort().join(',');
    const artifactCounts = Object.keys(_coordinatorArtifactByWsId)
        .sort()
        .map(k => `${k}:${_coordinatorArtifactByWsId[k].length}`)
        .join('|');
    const judgedCount = _coordinatorJudgedGroups.size;
    const orchHash = (_orchestrationStatuses || []).map(o => `${o.role}:${o.status}`).join(',');
    return JSON.stringify({
        wfId: wf.id,
        skillIds,
        statuses: statuses || {},
        taskIds,
        artifactCounts,
        judgedCount,
        orchHash,
    });
}

function renderFlowView(wfDetail, allStepStatuses) {
    const flowEl = document.getElementById('workflow-flow-view');
    if (!flowEl) return;

    const wf = wfDetail.workflow || wfDetail;
    const groups = wf.groups || [];

    if (groups.length === 0) {
        flowEl.style.display = 'none';
        return;
    }
    flowEl.style.display = 'block';

    // 再レンダー最適化: ステータスや coordinator データに変化が無ければスキップ
    const dataKey = `${wf.id}`;
    const renderHash = _computeFlowRenderHash(wfDetail, allStepStatuses);
    if (dataKey === _lastFlowDataKey && renderHash === _lastFlowRenderHash) {
        return;  // 変化なし → DOM 操作スキップ
    }
    _lastFlowDataKey = dataKey;
    _lastFlowRenderHash = renderHash;

    // Hide the empty placeholder
    const emptyEl = document.getElementById('workflow-output-content');
    if (emptyEl) emptyEl.style.display = 'none';

    const esc = typeof escapeHtml === 'function' ? escapeHtml : (t => t);
    const profileColors = { default: '#9c27b0', explore: '#2196f3', plan: '#ff9800', implement: '#4caf50', verification: '#e91e63' };
    // SVG icons — used both in cube (wf-cube-icon-img) and profile tag (wf-tag-icon)
    function _mkSvg(paths, cls) { return `<svg viewBox="0 0 512 512" class="${cls}">${paths}</svg>`; }
    const _pathExplore = '<path d="M465.6,24H46.4C20.8,24,0,44.8,0,70.5V441.6c0,25.7,20.8,46.4,46.4,46.4h419.2c25.6,0,46.4-20.7,46.4-46.4V70.5C512,44.8,491.2,24,465.6,24zM464,440H48V120h416V440z"/><path d="M368,348.2H144v52.7h224V348.2zM160,384.8v-20.7h192v20.7H160z"/><circle cx="241.6" cy="225.6" r="30.2" fill="none" stroke-width="20"/><path d="M300.8,268.7l16.7,16.8c7,7,18.4,7,25.4,0c7-7,7-18.5,0-25.5l-17-17L300.8,268.7z"/>';
    const _pathPlan = '<path d="M473.2,39.6c-5.2-18.2-19.2-32.1-37.1-37.3C431.1,0.8,426,0,420.4,0H91.6c-30.3,0-55,24.7-55,55v403.4c0.9,29.6,24.7,53.2,54.3,53.6h205.1c10.6,0,20.8-2.2,30.6-6.6c8.2-3.8,15.5-8.9,21.7-15.1L453.8,384.8c6.3-6.3,11.6-13.9,15.1-21.9c4.3-9.4,6.5-19.9,6.5-30.5V55C475.4,49.4,474.7,44.3,473.2,39.6zM303.6,356.5V466.5c-2.5,0.7-5,1-7.6,1H91.4c-5.6-0.1-10.2-4.7-10.3-10.2V55c0-5.8,4.7-10.5,10.5-10.5h328.9c1,0,1.6,0.1,2.9,0.5c3.5,0.9,6.3,3.7,7.4,7.9c0.2,0.5,0.3,1.1,0.3,2.1v277.4c0,2.6-0.3,5.2-1,7.7H320C311,340.1,303.6,347.5,303.6,356.5z"/><rect x="166.5" y="115.3" width="178.9" height="19.9" rx="2.2"/><rect x="166.5" y="192.8" width="178.9" height="19.9" rx="2.2"/><rect x="166.5" y="270.3" width="178.9" height="19.7" rx="2.2"/><rect x="166.5" y="347.9" width="94.5" height="19.9" rx="2.2"/>';
    const _pathImplement = '<path d="M362,300.9v-0.2l-33.3,33.3v78.4c0,12.9-10.5,23.4-23.5,23.4H156c-8.6,0-16.9-0.9-25-2.5V353.2c0-8.4-6.8-15.1-15.1-15.1H35.9c-1.7-8.1-2.5-16.4-2.5-25V99.7c0-12.9,10.5-23.4,23.4-23.4h248.4c13,0,23.5,10.5,23.5,23.4v11l-0.1,7.8l0.1-0.1v0.2l31.8-31.8c-5.9-25-28.4-43.8-55.3-43.8H56.8C25.5,42.9,0,68.4,0,99.7v213.5c0,10.7,1.1,21.4,3.2,31.8c12.7,60.8,60.1,108.3,121.1,120.9c10.3,2.1,21,3.3,31.7,3.3h149.2c31.4,0,56.8-25.5,56.8-56.8v-65.5l0.1-46L362,300.9z"/><path d="M508.4,99.9L455,46.5c-2.8-2.8-6.7-4-10.5-3.5c-0.9-0.1-1.9,0-2.9,0.2c-0.4,0.1-0.8,0.2-1.3,0.3c-1,0.3-1.9,0.6-2.9,1.2c-0.4,0.3-0.9,0.5-1.4,0.9c-0.4,0.3-0.9,0.5-1.3,0.9L202.7,282.1l-28.1,90c-1.3,4.2,2.1,8.4,6.3,8.4c0.6,0,1.2-0.1,1.9-0.3l90-28.1L508.8,116.1C513.2,111.7,513,104.5,508.4,99.9z"/>';
    const _pathVerification = '<path d="M492.7,41l-5-5.4L250.9,252.3l-39.5-42.3c-13.9-14.8-33.5-23.4-53.8-23.4c-18.7,0-36.6,7-50.3,19.8l-5.3,5L218.2,336c7.9,8.4,19,13.3,30.6,13.3c10.5,0,20.5-3.9,28.2-11L488.1,145.1C518.1,117.7,520.1,71,492.7,41z"/><path d="M454.2,231.7v-0.1l-52,47.6v117.7c0,18.9-15.4,34.2-34.2,34.2H86.2c-18.9,0-34.2-15.3-34.2-34.2V115.1c0-18.8,15.3-34.2,34.2-34.2h281.7c2.9,0,5.7,0.4,8.4,1l40.9-37.4c-14-9.9-31-15.6-49.4-15.6H86.2C38.7,28.9,0,67.6,0,115.1v281.7c0,47.6,38.7,86.2,86.2,86.2h281.7c47.5,0,86.2-38.7,86.2-86.2v-97.6l0.1-67.7L454.2,231.7z"/>';
    const _pathLeader = '<path d="M484.1,176.9H350.3c-12,0-22.7-7.8-26.4-19.2L282.4,30.4c-8.3-25.6-44.6-25.6-52.9,0l-41.4,127.3c-3.7,11.5-14.4,19.2-26.4,19.2H27.9c-26.9,0-38.1,34.5-16.3,50.3l108.3,78.7c9.7,7.1,13.8,19.6,10.1,31.1L88.6,464.3c-8.3,25.6,21,46.9,42.8,31.1l108.3-78.7c9.7-7.1,22.9-7.1,32.7,0l108.3,78.7c21.8,15.8,51.1-5.5,42.8-31.1L382.1,337c-3.7-11.5,0.4-24,10.1-31.1l108.3-78.7C522.3,211.4,511.1,176.9,484.1,176.9z"/>';
    // Cube icons (inherit color from .wf-node-icon via CSS)
    const _svgExplore = _mkSvg(_pathExplore, 'wf-cube-icon-img');
    const _svgPlan = _mkSvg(_pathPlan, 'wf-cube-icon-img');
    const _svgImplement = _mkSvg(_pathImplement, 'wf-cube-icon-img');
    const _svgVerification = _mkSvg(_pathVerification, 'wf-cube-icon-img');
    const _svgLeader = _mkSvg(_pathLeader, 'wf-cube-icon-img');
    // Tag icons (inherit color from .wf-node-profile-tag via CSS)
    const _tagExplore = _mkSvg(_pathExplore, 'wf-tag-icon');
    const _tagPlan = _mkSvg(_pathPlan, 'wf-tag-icon');
    const _tagImplement = _mkSvg(_pathImplement, 'wf-tag-icon');
    const _tagVerification = _mkSvg(_pathVerification, 'wf-tag-icon');
    const _tagLeader = _mkSvg(_pathLeader, 'wf-tag-icon');
    const profileTagIcons = { explore: _tagExplore, plan: _tagPlan, implement: _tagImplement, verification: _tagVerification, default: _tagLeader };
    const profileIcons = {
        explore: _svgExplore,
        plan: _svgPlan,
        implement: _svgImplement,
        verification: _svgVerification,
        default: _svgLeader
    };

    // Collect all steps (for output lookup)
    const allSteps = [];
    groups.forEach(grp => {
        (grp.skills || []).forEach(sk => allSteps.push(sk));
    });

    // Build skill output lookup from stepExecutions
    const skillOutputByWsId = {};
    if (stepExecutions && stepExecutions.size > 0) {
        for (const [, data] of stepExecutions.entries()) {
            if (data.workflowSkillId) {
                skillOutputByWsId[data.workflowSkillId] = data;
                skillOutputByWsId[String(data.workflowSkillId)] = data;
            }
        }
    }

    function skillOutputHtml(wsId, sk) {
        const data = skillOutputByWsId[wsId] || skillOutputByWsId[String(wsId)];
        let html = '';
        if (!data) return html;
        if (data.status === 'processing') {
            const len = data.output ? data.output.length : 0;
            html += `<div class="wf-node-output processing">${len > 0 ? len + '文字受信中...' : '実行中...'}</div>`;
        } else if (data.status === 'success' && data.output) {
            const outputId = `wf-output-${wsId}`;
            html += `<button class="wf-node-output-btn" onclick="showNodeOutputPopup('${esc(sk?.skill_name || 'Step')}', '${outputId}')">出力を表示</button>`;
            html += `<div id="${outputId}" style="display:none;">${esc(data.output)}</div>`;
        } else if (data.status === 'error' && data.errorMessage) {
            html += `<div class="wf-node-output error">${esc(data.errorMessage.substring(0, 80))}</div>`;
        }
        return html;
    }

    const statuses = allStepStatuses || {};
    const leaderStatus = statuses['leader'] || 'pending';
    const leaderOutput = _flowLeaderOutput || '';

    // Helper: render a single node HTML
    function renderNodeHtml(sk, stepIdx) {
        const sName = sk.skill_name || `Step ${stepIdx + 1}`;
        let sStatus = (statuses['ws_' + sk.workflow_skill_id] || statuses[sk.skill_id]) || 'pending';
        const profile = sk.agent_profile || 'default';
        const pColor = profileColors[profile] || '#9e9e9e';
        const pLabel = formatStageLabel ? formatStageLabel(profile) : profile;
        const pIcon = profileIcons[profile] || profileIcons.default;

        const stepExecData = stepExecutions.get(sk.skill_order);
        const reflectionLoop = stepExecData?.reflectionLoop || 0;
        const orchForStep = _orchestrationStatuses.find(o =>
            (o.role === 'quality_gate' || o.role === 'supervisor') &&
            o.status === 'processing'
        );
        const isVerifying = orchForStep && sStatus === 'success';
        const isRetrying = sStatus === 'processing' && reflectionLoop > 0;

        let displayStatus = sStatus;
        if (isVerifying) displayStatus = 'verifying';
        if (isRetrying) displayStatus = 'retrying';

        const iconContent = (displayStatus === 'processing' || displayStatus === 'retrying')
            ? '<div class="wf-node-loader"><span></span><span></span><span></span></div>'
            : displayStatus === 'verifying'
            ? '<svg viewBox="0 0 24 24" class="wf-cube-icon-img wf-icon-verifying"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" fill="currentColor"/></svg>'
            : pIcon;

        const nodeStateClass = displayStatus === 'processing' || displayStatus === 'retrying' ? 'is-processing'
            : displayStatus === 'verifying' ? 'is-verifying'
            : sStatus === 'success' ? 'is-success'
            : sStatus === 'error' ? 'is-error' : '';

        const stepSuffix = isVerifying ? ' <span class="wf-step-badge wf-badge-verify">検証中</span>'
            : isRetrying ? ` <span class="wf-step-badge wf-badge-retry">再試行 #${reflectionLoop}</span>`
            : reflectionLoop > 0 && sStatus === 'success' ? ` <span class="wf-step-badge wf-badge-passed">検証済</span>`
            : '';

        // Coordinator メタを参照: 役割バッジ・provider枠色・artifact チップ
        const coordTask = _coordinatorTaskByWsId[sk.workflow_skill_id];
        const coordRole = coordTask?.role;
        const coordProviderMode = coordTask?.resolved_provider_mode || coordTask?.provider_mode_hint;
        const roleBadgeHtml = coordRole ? _coordRoleBadge(coordRole) : '';
        const providerBadgeHtml = coordProviderMode ? _coordProviderBadge(coordProviderMode) : '';
        const artifactChipHtml = _coordArtifactChip(sk.workflow_skill_id);
        const dataProviderAttr = coordProviderMode ? ` data-provider-mode="${coordProviderMode}"` : '';
        const tooltipText = coordTask
            ? `${coordTask.objective || ''} | impact:${coordTask.impact_level || '-'} | provider:${coordProviderMode || '-'}`
            : '';

        return { sStatus, html: `
            <div class="wf-node ${nodeStateClass}"${tooltipText ? ` title="${esc(tooltipText)}"` : ''}>
                <div class="wf-node-step"><span class="wf-node-status-indicator status-${sStatus}">${sStatus === 'success' ? '✓' : sStatus === 'error' ? '✗' : ''}</span>STEP ${stepIdx + 1}${roleBadgeHtml}${stepSuffix}</div>
                <span class="wf-node-profile-tag" style="color:${pColor}; background:${pColor}12; border:1px solid ${pColor}30;"><span class="wf-profile-icon" style="color:${pColor};">${profileTagIcons[profile] || profileTagIcons.default}</span>${esc(pLabel)}</span>
                <div class="wf-node-card-wrap status-${displayStatus}"${dataProviderAttr} style="--cube-color: ${pColor};">
                    <div class="wf-node-face-right"></div>
                    <div class="wf-node-face-top"></div>
                    <div class="wf-node-card">
                        <div class="wf-node-icon status-${displayStatus}">
                            ${iconContent}
                        </div>
                    </div>
                    ${artifactChipHtml}
                </div>
                <div class="wf-node-label">
                    <div class="wf-node-name">${esc(sName)}</div>
                    <div class="wf-node-model">${typeof formatModelDisplay === 'function' ? formatModelDisplay(sk?.model_type || '', null, sk) : (sk?.model_type || '')}</div>
                    ${providerBadgeHtml ? `<div class="wf-node-provider-line">${providerBadgeHtml}</div>` : ''}
                </div>
                ${skillOutputHtml(sk.workflow_skill_id, sk)}
            </div>
        ` };
    }

    // SVG connector helper — 丸い1本矢印（通常・並列共通）
    function svgArrow(cls) {
        return `<div class="wf-connector ${cls}">
            <svg width="40" height="16" viewBox="0 0 40 16">
                <path d="M0,8 Q20,8 32,8" class="wf-connector-path"/>
                <path d="M28,4 L36,8 L28,12" class="wf-connector-arrow-head"/>
            </svg>
        </div>`;
    }

    let html = renderWorkflowStageSummary(esc);
    html += '<div class="wf-pipeline">';

    let stepCounter = 0;
    groups.forEach((grp, grpIdx) => {
        const skills = grp.skills || [];
        if (skills.length === 0) return;
        const isParallel = grp.execution_type === 'parallel' && skills.length > 1;

        if (isParallel) {
            // Parallel group: stack nodes vertically in one column
            let groupWorstStatus = 'pending';
            let nodesHtml = '';
            const groupSkillIds = [];
            skills.forEach((sk) => {
                const result = renderNodeHtml(sk, stepCounter);
                nodesHtml += result.html;
                if (result.sStatus === 'error') groupWorstStatus = 'error';
                else if (result.sStatus === 'processing' && groupWorstStatus !== 'error') groupWorstStatus = 'processing';
                else if (result.sStatus === 'success' && groupWorstStatus === 'pending') groupWorstStatus = 'success';
                groupSkillIds.push(sk.workflow_skill_id);
                stepCounter++;
            });
            // Coordinator: ジャッジ状態を判定
            const allDone = groupSkillIds.every(id => (statuses['ws_' + id] || 'pending') === 'success');
            const judgedTaskIds = groupSkillIds.map(id => `task_${id}`);
            const judged = judgedTaskIds.some(tid => _coordinatorJudgedGroups.has(tid));
            const judgeBadge = judged
                ? '<span class="wf-parallel-judge-badge wf-parallel-judge-done">JUDGED ✓</span>'
                : (allDone ? '<span class="wf-parallel-judge-badge wf-parallel-judge-ready">JUDGE READY</span>' : '');
            html += `<div class="wf-parallel-group">`
                + `<div class="wf-parallel-label">並列${judgeBadge}</div>`
                + `<div class="wf-parallel-nodes">${nodesHtml}</div>`
                + `</div>`;
            const connCls = groupWorstStatus === 'success' ? 'active' : groupWorstStatus === 'processing' ? 'running' : '';
            html += svgArrow(connCls);
        } else {
            // Serial group: render each node with its own connector
            skills.forEach((sk) => {
                const result = renderNodeHtml(sk, stepCounter);
                html += result.html;
                const connCls = result.sStatus === 'success' ? 'active' : result.sStatus === 'processing' ? 'running' : '';
                html += svgArrow(connCls);
                stepCounter++;
            });
        }
    });

    // Leader node — use first step's model as fallback
    // リーダーキューブ内: processing=ローダー、それ以外=星アイコン
    const leaderIcon = leaderStatus === 'processing'
        ? '<div class="wf-node-loader"><span></span><span></span><span></span></div>'
        : _svgLeader;
    const leaderModelRaw = wf.parent_model_type || allSteps[0]?.model_type || '';
    const leaderModelDisplay = typeof formatModelDisplay === 'function' ? formatModelDisplay(leaderModelRaw, null, { enable_deep_think: wf.parent_enable_deep_think }) : leaderModelRaw;

    const leaderStateClass = leaderStatus === 'processing' ? 'is-processing' : leaderStatus === 'success' ? 'is-success' : leaderStatus === 'error' ? 'is-error' : '';
    html += `
        <div class="wf-node ${leaderStateClass}">
            <div class="wf-node-step"><span class="wf-node-status-indicator status-${leaderStatus}">${leaderStatus === 'success' ? '✓' : leaderStatus === 'error' ? '✗' : ''}</span>FINAL</div>
            <span class="wf-node-profile-tag" style="color:#9c27b0; background:#9c27b012; border:1px solid #9c27b030;"><span class="wf-profile-icon" style="color:#9c27b0;">${_tagLeader}</span>Leader</span>
            <div class="wf-node-card-wrap status-${leaderStatus}" style="--cube-color: #9c27b0;">
                <div class="wf-node-face-right"></div>
                <div class="wf-node-face-top"></div>
                <div class="wf-node-card">
                    <div class="wf-node-icon status-${leaderStatus}">
                        ${leaderIcon}
                    </div>
                </div>
            </div>
            <div class="wf-node-label">
                <div class="wf-node-name">結果統合</div>
                <div class="wf-node-model">${leaderModelDisplay}</div>
            </div>
        </div>
    `;

    html += '</div>';

    // Preserve open <details> state before re-render
    const openDetails = new Set();
    flowEl.querySelectorAll('details[open][data-ws-id]').forEach(d => {
        openDetails.add(d.getAttribute('data-ws-id'));
    });

    flowEl.innerHTML = html;

    // Coordinator eval メトリクスを描画 (完了後のみ表示)
    try { _renderEvalMetrics(); } catch (_) {}

    // Restore open state
    if (openDetails.size > 0) {
        flowEl.querySelectorAll('details[data-ws-id]').forEach(d => {
            if (openDetails.has(d.getAttribute('data-ws-id'))) d.open = true;
        });
    }

    // Update leader output in the bottom output panel
    const outputEl = document.getElementById('wf-leader-output');
    if (outputEl) {
        if (leaderOutput) {
            outputEl.textContent = leaderOutput;
            outputEl.style.color = 'var(--content-text)';
        }
    }
}

function showNodeOutputPopup(stepName, outputId) {
    const el = document.getElementById(outputId);
    if (!el) return;
    const text = el.textContent || '';
    Swal.fire({
        title: stepName,
        html: `<div style="text-align:left; max-height:60vh; overflow-y:auto; padding:16px; background:#f8f8f6; border-radius:10px; font-size:12px; line-height:1.6; white-space:pre-wrap; word-wrap:break-word; color:#2d2d2d;">${escapeHtml(text)}</div>`,
        width: '700px',
        showCloseButton: true,
        showConfirmButton: false,
        footer: `<button id="node-swal-copy-btn" style="padding:6px 20px; font-size:13px; font-weight:500; background:var(--accent, #7c3aed); border:none; border-radius:8px; cursor:pointer; color:#fff;">コピー</button>`,
        didOpen: () => {
            document.getElementById('node-swal-copy-btn')?.addEventListener('click', () => {
                navigator.clipboard.writeText(text).then(() => {
                    if (typeof showAlert === 'function') showAlert('コピーしました', 'success');
                }).catch(() => {});
            });
        },
    });
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
        // clipboard API 失敗時のフォールバック
        try {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            showAlert('クリップボードにコピーしました', 'success');
        } catch (fallbackErr) {
            showAlert('コピーに失敗しました', 'error');
        }
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
    // デスクトップローカル実行ではSSEストリーミング不要
    if (window.NexMAGIRuntime?.shouldUseDesktopLocalExecution?.()) {
        return;
    }
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
    const worker = window.NexMAGIRuntime.createWorker();
    streamingWorkers.set(executionId, worker);
    void window.NexMAGIRuntime.getAuthToken()
        .then((token) => {
            worker.postMessage({
                type: 'start',
                executionId: executionId,
                token,
                apiBase: window.NexMAGIRuntime.getApiBase()
            });
        })
        .catch((error) => {
            console.error('Failed to resolve auth token for workflow streaming:', error);
            stepExecutions.set(stepOrder, {
                ...stepExecutions.get(stepOrder),
                status: 'error',
                errorMessage: `認証情報の取得に失敗しました: ${error.message}`,
            });
            renderStepExecutions();
        });
    const nodeStartEventPromise = appendDesktopWorkflowNodeEvent('node_execution_started', executionId, stepOrder, {
        step_name: stepName,
        skill_name: skillName,
    });
    void nodeStartEventPromise.catch((error) => {
        console.error('Failed to append desktop workflow start event:', error);
    });
    void nodeStartEventPromise
        .then(() => ensureDesktopWorkflowProviderStarted(executionId, stepOrder, {
            step_name: stepName,
            skill_name: skillName,
            boundaryKind: 'sse_stream',
            api_base: window.NexMAGIRuntime.getApiBase(),
        }))
        .catch((error) => {
            console.error('Failed to append desktop workflow provider start event:', error);
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
            handleStepComplete(executionId, stepOrder, 'error', data.message || 'エラーが発生しました', {
                errorCode: data?.code || null,
                boundaryKind: 'sse_stream',
            });
        } else if (type === 'runtime_error') {
            console.error('Step runtime error event received:', { executionId, stepOrder, error: data });
            handleStepComplete(executionId, stepOrder, 'error', data?.message || 'runtime error', {
                errorCode: data?.code || null,
                boundaryKind: 'sse_stream',
            });
        } else if (type === 'diagnostic') {
            console.debug('Step worker diagnostic:', { executionId, stepOrder, diagnostic: data });
        } else if (type === 'cancel') {
            console.log('Step cancel event received:', { executionId, stepOrder });
            handleStepComplete(executionId, stepOrder, 'cancelled', null, {
                errorCode: 'cancelled_by_user',
                boundaryKind: 'sse_stream',
            });
        }
    };

    worker.onerror = (error) => {
        console.error('Stream worker error:', error);
        handleStepComplete(executionId, stepOrder, 'error', 'ストリーミングエラーが発生しました', {
            errorCode: 'worker_error',
            boundaryKind: 'sse_stream',
        });
    };
}

// ステップの完了処理
async function handleStepComplete(executionId, stepOrder, status, errorMessage = null, details = {}) {
    console.log('handleStepComplete called:', { executionId, stepOrder, status, errorMessage });
    await finishDesktopWorkflowNode(executionId, stepOrder, status, errorMessage, details).catch((error) => {
        console.error('Failed to append desktop workflow finish chain:', error);
    });

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
let _workflowCompleteHandled = false;
async function handleWorkflowComplete(workflowExecutionId, leaderExecution) {
    if (_workflowCompleteHandled) {
        console.log('handleWorkflowComplete already handled, skipping');
        return;
    }
    _workflowCompleteHandled = true;
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
                // stepExecutions をAPI最新データで上書き（ポーリング中の古いエラー情報をクリア）
                stepExecutions.set(exec.skill_order, {
                    executionId: exec.id,
                    workflowSkillId: exec.workflow_skill_id,
                    status: exec.status,
                    output: exec.output_data || stepData?.output || '',
                    stepName: exec.skill_name || stepInfo?.skill_name || `Step ${exec.skill_order}`,
                    skillName: exec.skill_name,
                    errorMessage: exec.status === 'success' ? null : (exec.error_message || null),
                });
                return {
                    stepOrder: exec.skill_order,
                    stepName: exec.skill_name || stepInfo?.skill_name || `Step ${exec.skill_order}`,
                    status: exec.status,
                    output: exec.output_data || stepData?.output || '',
                    errorMessage: exec.status === 'success' ? null : exec.error_message,
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

        // ステータスバーを更新（確実に完了状態にする — ID不一致でもクリア）
        if (typeof PersistentStatusBar !== 'undefined' && PersistentStatusBar.startTime) {
            const allStepsSuccess = allStepResults.every(s => s.status === 'success');
            const finalStatus = (leaderExecution?.status === 'success' || (!leaderExecution && allStepsSuccess)) ? 'success' : 'error';
            PersistentStatusBar.markAsCompleted(finalStatus);
            console.log('Workflow completed, PersistentStatusBar updated:', finalStatus);
        }
        const allStepsSuccess = allStepResults.every(s => s.status === 'success');
        const workflowStatus = (leaderExecution?.status === 'success' || (!leaderExecution && allStepsSuccess)) ? 'success' : 'error';
        await finishDesktopWorkflowRun(workflowStatus, {
            leader_execution_id: leaderExecution?.id || null,
            workflow_execution_id: workflowExecutionId,
        });

        // リーダー出力をフロービュー用に保存（リーダーがなければ最後のステップ出力をフォールバック）
        const lastStepResult = allStepResults.length > 0 ? allStepResults[allStepResults.length - 1].output : '';
        _flowLeaderOutput = leaderExecution?.output_data || lastStepResult || '';
        // リーダーステータスを確実に設定
        _flowStepStatuses['leader'] = (leaderExecution?.status === 'success' || (!leaderExecution && allStepsSuccess)) ? 'success' : 'error';

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
            executeBtnText.textContent = '実行';
        }
        if (executeBtnSpinner) {
            executeBtnSpinner.style.display = 'none';
        }
        // 入力パネル再有効化 + 切り抜き円を復元
        const inputPanel = document.querySelector('.wf-io-input');
        if (inputPanel) inputPanel.classList.remove('is-disabled');
        const execCircle = document.getElementById('workflow-execute-circle');
        const execIcon = document.getElementById('wf-exec-icon');
        const execSpinner = document.getElementById('wf-exec-spinner');
        if (execCircle) execCircle.style.pointerEvents = '';
        if (execIcon) execIcon.style.display = '';
        if (execSpinner) execSpinner.style.display = 'none';
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

        // 完了時: 最新ステータスを取得してステータスバーを確定
        try {
            const finalWfStatus = await apiRequest(`/api/user/workflow-executions/${workflowExecutionId}/status`);
            _wfStageMeta = {
                currentStage: finalWfStatus?.current_stage || null,
                finalVerdict: finalWfStatus?.final_verdict || null,
                handoffSummary: finalWfStatus?.handoff_summary || null,
                coordinatorView: finalWfStatus?.coordinator_view || null,
                synthesisEvents: finalWfStatus?.synthesis_events || [],
            };
            if (finalWfStatus?.blackboard_keys) _blackboardKeys = finalWfStatus.blackboard_keys;
        } catch (e) {}
        updateStatusBar();
        if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);

        // 完了ポップアップを表示
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
        // エラーが起きてもステータスバーを確実に完了にする
        if (typeof PersistentStatusBar !== 'undefined' && PersistentStatusBar.startTime) {
            PersistentStatusBar.markAsCompleted('error');
        }
        await showAlert('ワークフロー完了処理に失敗しました', 'error');
    }
}


// ワークフロー結果を出力パネルに表示
function displayWorkflowResult(finalOutput, allStepResults, leaderExecution) {
    // 出力パネルにリーダー結果を反映（詳細遷移時にも見えるよう）
    const outputEl = document.getElementById('wf-leader-output');
    if (outputEl && finalOutput) {
        outputEl.textContent = finalOutput;
        outputEl.classList.remove('wf-flow-placeholder');
        outputEl.style.color = 'var(--content-text)';
    }

    // フロービューを更新（再レンダーハッシュをクリアして強制反映）
    _lastFlowRenderHash = null;
    _lastFlowDataKey = null;
    if (_flowViewDetail) {
        renderFlowView(_flowViewDetail, _flowStepStatuses);
    }
    updateStatusBar();

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
        updateStatusBar();

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

        // このワークフローに関連する実行をフィルタリング（ワークフロー実行のみ、スキル単体実行は除外）
        const thisWorkflowId = workflowDetail?.workflow?.id ? parseInt(workflowDetail.workflow.id) : null;
        const relevantExecs = responseExecutions.filter(exec =>
            exec.workflow_execution_id && exec.workflow_id === thisWorkflowId
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
    return '#999';
}

function _wfOverallStatus(execs) {
    // 特殊ロール（quality_gate, supervisor等）のエラーはWF全体のエラーとしない
    const normalExecs = execs.filter(e => !e.execution_role);
    if (normalExecs.some(e => e.status === 'error')) return 'error';
    if (normalExecs.some(e => e.status === 'cancelled')) return 'cancelled';
    if (normalExecs.some(e => e.status === 'pending' || e.status === 'pending_local' || e.status === 'processing')) return 'processing';
    if (normalExecs.every(e => e.status === 'success')) return 'success';
    return 'pending';
}

// 実行履歴を表示（テーブル形式 — history.html と同じ見た目）
function renderHistory() {
    const tbody = document.getElementById('history-tbody');
    if (!tbody) return;

    if (allExecutions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--content-text-muted);">このワークフローの実行履歴がありません</td></tr>';
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
        const totalTime = execs.reduce((sum, e) => sum + (e.execution_time || 0), 0);
        const totalTokens = execs.reduce((sum, e) => sum + (e.tokens_used || 0), 0);
        const overallStatus = _wfOverallStatus(execs);
        const statusColor = _wfStatusColor(overallStatus);
        const stepExecs = normalExecsHist.filter(e => e.skill_order && e.workflow_skill_id);
        const leaderExecHist = normalExecsHist.find(e => !e.workflow_skill_id);
        const parentModelHist = leaderExecHist?.model_used || normalExecsHist[0]?.model_used || '-';
        const modelDisplayHist = typeof formatModelDisplay === 'function' ? formatModelDisplay(parentModelHist, null, {}) : parentModelHist;

        // 各スキルの小さなバー（history.html と同じ形式）
        let skillBars = stepExecs.map((e, i) => {
            const sc = _wfStatusColor(e.status);
            const cube = renderMiniCube(e.agent_profile || 'default', { size: 22, borderColor: sc, showLabel: false });
            return (i > 0 ? '<span style="color:#ccc; font-size:10px; vertical-align:middle;">→</span>' : '') + cube;
        }).join('');
        // リーダーキューブを追加
        const leaderSc = _wfStatusColor(overallStatus);
        skillBars += '<span style="color:#ccc; font-size:10px; vertical-align:middle;">→</span>' + renderMiniCube('default', { size: 22, borderColor: leaderSc, showLabel: false });

        return `
        <tr>
            <td>${firstAt ? formatDate(firstAt) : '-'}</td>
            <td>
                <div style="margin-bottom:4px;">
                    <span style="color: var(--content-text-muted); font-size: 11px;">${stepExecs.length} steps</span>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:12px;perspective:300px;align-items:center;">${skillBars}</div>
            </td>
            <td>${modelDisplayHist}</td>
            <td>${totalTime ? totalTime + 'ms' : '-'}</td>
            <td>${formatCompact(totalTokens)}</td>
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
        <tr><td colspan="7" style="text-align: center; padding: 15px;">
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
        await execDetailModal.showWorkflowDetailPopup({
            workflowName, allStepResults, leaderExec, groups,
            leaderModel: leaderExec?.model_used || workflowDetail?.workflow?.parent_model_type || '',
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
                    { label: 'モデル', valueHtml: typeof formatModelDisplay === 'function' ? formatModelDisplay(execution.model_used || '', execution, null) : escapeHtml(execution.model_used || '-') },
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

async function executeWorkflowWithOrchestration({ workflowId, globalInputData, perSkillInput, outputFormat }) {
    const token = await window.NexMAGIRuntime.getAuthToken();
    if (!token) {
        throw new Error('ログイン情報が見つかりません');
    }

    // Start orchestrated workflow (returns immediately with status)
    const orchStatus = await window.NexMAGIRuntime.startOrchestratedWorkflow({
        authToken: token,
        workflowId: parseInt(workflowId),
        workflowName: workflowDetail?.workflow?.name || `Workflow ${workflowId}`,
        globalInputData,
        perSkillInput,
        outputFormat,
    });

    console.info('[Orchestration] started:', orchStatus);

    // Poll until orchestration completes (background tick handles actual execution)
    for (let i = 0; i < 1200; i++) {
        await new Promise(r => setTimeout(r, 500));
        const status = await window.NexMAGIRuntime.getOrchestrationStatus(orchStatus.workflowExecutionId);
        if (!status || status.status !== 'running') {
            break;
        }
    }

    // Fetch final results from backend to build the same shape as legacy path
    const execResp = await apiRequest('/api/user/executions?limit=100');
    const allExecs = (execResp.items || execResp);
    const wfExecs = allExecs.filter(e => e.workflow_execution_id === orchStatus.workflowExecutionId);
    const executionIds = wfExecs.map(e => e.id);
    const leaderExec = wfExecs.find(e => !e.workflow_skill_id && !e.execution_role);
    const wfStatus = await apiRequest(`/api/user/workflow-executions/${orchStatus.workflowExecutionId}/status`).catch(() => null);

    // Store result globally for the form handler (same as legacy path)
    const result = {
        workflowExecutionId: orchStatus.workflowExecutionId,
        executionIds,
        leaderExecutionId: leaderExec?.id || null,
        status: wfStatus?.status || 'error',
        output: leaderExec?.output_data || '',
    };
    window.__NEXMAGI_LAST_LOCAL_WORKFLOW_RESULT = result;

    return result;
}

async function executeWorkflowWithDesktopLocalEngine({ workflowId, globalInputData, perSkillInput, outputFormat }) {
    const token = await window.NexMAGIRuntime.getAuthToken();
    if (!token) {
        throw new Error('ログイン情報が見つかりません');
    }

    const result = await window.NexMAGIRuntime.runLocalWorkflowExecution({
        authToken: token,
        workflowId: parseInt(workflowId),
        workflowName: workflowDetail?.workflow?.name || `Workflow ${workflowId}`,
        globalInputData,
        perSkillInput,
        outputFormat,
    });
    window.__NEXMAGI_LAST_LOCAL_WORKFLOW_RESULT = result;
    console.info('[DesktopLocalWorkflowResult]', {
        configuredEngineMode: result.configuredEngineMode,
        effectiveEngineMode: result.effectiveEngineMode,
        providerMode: result.providerMode,
        providerTransport: result.providerTransport,
        providerAdapter: result.providerAdapter,
        providerRuntime: result.providerRuntime,
        providerImpl: result.providerImpl,
        authKeySource: result.authKeySource,
        observationSource: result.observationSource,
        tokenAccountingSource: result.tokenAccountingSource,
        providerErrorCode: result.providerErrorCode,
        retryReason: result.retryReason,
    });

    workflowExecutionId = result.workflowExecutionId;

    // PersistentStatusBar のワークフロー実行IDを確定（handleWorkflowComplete での一致チェック用）
    if (typeof PersistentStatusBar !== 'undefined' && result.workflowExecutionId) {
        PersistentStatusBar.workflowExecutionId = result.workflowExecutionId;
    }

    // フロービューのステップステータスを実際の結果で更新
    if (result.executionIds && workflowDetail?.skills) {
        const allSkills = workflowDetail.skills;
        const finalStatus = result.status === 'success' ? 'success' : 'error';
        for (const skill of allSkills) {
            if (skill.workflow_skill_id) {
                _flowStepStatuses['ws_' + skill.workflow_skill_id] = finalStatus;
            }
            if (skill.skill_id) {
                _flowStepStatuses[skill.skill_id] = finalStatus;
            }
        }
        if (_flowViewDetail) {
            renderFlowView(_flowViewDetail, _flowStepStatuses);
        }
    }

    await loadHistory();

    let leaderExecution = null;
    if (result.leaderExecutionId) {
        leaderExecution = await apiRequest(`/api/user/executions/${result.leaderExecutionId}`).catch(() => null);
    } else {
        leaderExecution = {
            id: null,
            status: result.status,
            output_data: result.output || '',
        };
    }

    // ポーリングループが先に handleWorkflowComplete を呼んでいなければ実行
    if (!_workflowCompleteHandled) {
        await handleWorkflowComplete(result.workflowExecutionId, leaderExecution);
    }
    return result;
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

        // ボタン無効化 + 入力パネル全体を無効化 + 切り抜き円をスピナーに
        executeBtn.disabled = true;
        executeBtnText.textContent = '実行中...';
        if (executeBtnSpinner) executeBtnSpinner.style.display = 'inline';
        inputs.forEach((el) => { if (el !== executeBtn) el.disabled = true; });
        const inputPanel = document.querySelector('.wf-io-input');
        if (inputPanel) inputPanel.classList.add('is-disabled');
        const execCircle = document.getElementById('workflow-execute-circle');
        const execIcon = document.getElementById('wf-exec-icon');
        const execSpinner = document.getElementById('wf-exec-spinner');
        if (execCircle) execCircle.style.pointerEvents = 'none';
        if (execIcon) execIcon.style.display = 'none';
        if (execSpinner) execSpinner.style.display = 'flex';

        const isDesktopLocal = window.NexMAGIRuntime?.shouldUseDesktopLocalExecution?.();
        const useOrchestrated = window.NexMAGIRuntime?.shouldUseOrchestratedExecution?.();

        let resp;
        if (useOrchestrated || isDesktopLocal) {
            // デスクトップ実行: オーケストレーション（マルチワーカー）または単一 sidecar
            let desktopPromise;
            if (useOrchestrated) {
                desktopPromise = executeWorkflowWithOrchestration({
                    workflowId,
                    globalInputData,
                    perSkillInput,
                    outputFormat,
                });
            } else {
                desktopPromise = executeWorkflowWithDesktopLocalEngine({
                    workflowId,
                    globalInputData,
                    perSkillInput,
                    outputFormat,
                });
            }

            // sidecar完了前に、バックエンドの最新execution IDを記録
            let prevMaxExecId = 0;
            try {
                const prevResp = await apiRequest('/api/user/executions?limit=1');
                const prevExecs = prevResp.items || prevResp;
                if (prevExecs.length > 0) prevMaxExecId = prevExecs[0].id || 0;
            } catch (e) { /* ignore */ }

            // フロービューを初期化して全ステップをprocessingで表示
            const resultContainer = document.getElementById('workflow-result-container');
            if (resultContainer) resultContainer.style.display = '';
            _flowStepStatuses = {};
            _flowLeaderOutput = '';
            _orchestrationStatuses = [];
            _blackboardKeys = [];
            _flowViewDetail = workflowDetail;
            const allSkillsInit = workflowDetail?.skills || [];
            for (let i = 0; i < allSkillsInit.length; i++) {
                const skill = allSkillsInit[i];
                const st = (i === 0) ? 'processing' : 'pending';
                if (skill.workflow_skill_id) _flowStepStatuses['ws_' + skill.workflow_skill_id] = st;
                if (skill.skill_id) _flowStepStatuses[skill.skill_id] = st;
            }
            _flowStepStatuses['leader'] = 'pending';
            if (workflowDetail) renderFlowView(workflowDetail, _flowStepStatuses);

            // バックグラウンドパネルを開始
            const wfNameInit = workflowDetail?.workflow?.name || 'ワークフロー';
            const firstSkillInit = allSkillsInit[0];
            if (typeof PersistentStatusBar !== 'undefined') {
                PersistentStatusBar.start(
                    null, null,
                    firstSkillInit?.skill_name || 'Step 1',
                    null, wfNameInit,
                    firstSkillInit?.skill_order || 1,
                    firstSkillInit?.skill_name || 'Step 1',
                    parseInt(workflowId)
                );
            }

            // 進捗ポーリング（sidecar完了まで2秒間隔で更新）
            let desktopDone = false;
            let progressPollWfExecId = null;
            const progressPoll = setInterval(async () => {
                if (desktopDone) { clearInterval(progressPoll); return; }
                try {
                    const execsResp = await apiRequest('/api/user/executions?limit=100');
                    const allExecs = execsResp.items || execsResp;

                    // 今回の実行を特定（prevMaxExecIdより新しいもの）
                    if (!progressPollWfExecId) {
                        const candidate = allExecs.find(e => e.id > prevMaxExecId && e.workflow_execution_id);
                        if (candidate) progressPollWfExecId = candidate.workflow_execution_id;
                    }
                    if (!progressPollWfExecId) return;

                    const wfExecs = allExecs.filter(e => e.workflow_execution_id === progressPollWfExecId);
                    if (wfExecs.length === 0) return;

                    if (typeof PersistentStatusBar !== 'undefined' && !PersistentStatusBar.workflowExecutionId) {
                        PersistentStatusBar.workflowExecutionId = progressPollWfExecId;
                    }

                    // ポーリング毎に CoordinatorPlan を再取得して観測値を反映 (await して renderFlowView に反映)
                    try { await loadCoordinatorPlan(progressPollWfExecId); } catch (_) {}

                    // 同じ workflow_skill_id に複数execution がある場合（再実行）、最新IDのみ使用
                    const latestByWsId = {};
                    for (const exec of wfExecs) {
                        if (exec.execution_role) continue;
                        if (!exec.workflow_skill_id) continue;
                        const prev = latestByWsId[exec.workflow_skill_id];
                        if (!prev || exec.id > prev.id) {
                            latestByWsId[exec.workflow_skill_id] = exec;
                        }
                    }

                    // 各ステップのステータスを更新
                    let hasChanged = false;
                    // 通常ステップ（最新executionのみ）
                    for (const exec of Object.values(latestByWsId)) {
                        const st = exec.status;
                        const mapped = (st === 'success') ? 'success'
                            : (st === 'error') ? 'error'
                            : (st === 'processing' || st === 'pending' || st === 'pending_local') ? 'processing'
                            : null;
                        if (!mapped) continue;

                        const key = 'ws_' + exec.workflow_skill_id;
                        if (_flowStepStatuses[key] !== mapped) {
                            _flowStepStatuses[key] = mapped;
                            hasChanged = true;
                        }
                        if (exec.skill_id) _flowStepStatuses[exec.skill_id] = mapped;

                        // stepExecutions に保持（handleWorkflowComplete用）
                        if (exec.skill_order) {
                            stepExecutions.set(exec.skill_order, {
                                executionId: exec.id,
                                workflowSkillId: exec.workflow_skill_id,
                                status: exec.status,
                                output: exec.output_data || '',
                                stepName: exec.skill_name || `Step ${exec.skill_order}`,
                                skillName: exec.skill_name,
                                errorMessage: exec.status === 'success' ? null : (exec.error_message || null),
                            });
                        }
                    }
                    // リーダー・特殊ロール
                    for (const exec of wfExecs) {
                        if (!exec.execution_role) continue;
                        const st = exec.status;
                        const mapped = (st === 'success') ? 'success'
                            : (st === 'error') ? 'error'
                            : (st === 'processing' || st === 'pending' || st === 'pending_local') ? 'processing'
                            : null;
                        if (!mapped) continue;
                        if (_flowStepStatuses['leader'] !== mapped) {
                            _flowStepStatuses['leader'] = mapped;
                            hasChanged = true;
                        }
                        if (mapped === 'success') _flowLeaderOutput = exec.output_data || _flowLeaderOutput;
                    }
                    // リーダー（workflow_skill_id=null, role=null）
                    const leaderExec = wfExecs.find(e => !e.workflow_skill_id && (!e.execution_role || e.execution_role === null));
                    if (leaderExec) {
                        const lm = leaderExec.status === 'success' ? 'success' : leaderExec.status === 'error' ? 'error' : (leaderExec.status === 'pending_local' || leaderExec.status === 'processing' || leaderExec.status === 'pending') ? 'processing' : 'pending';
                        if (_flowStepStatuses['leader'] !== lm) {
                            _flowStepStatuses['leader'] = lm;
                            hasChanged = true;
                        }
                        if (lm === 'success') _flowLeaderOutput = leaderExec.output_data || _flowLeaderOutput;
                    }

                    if (hasChanged && _flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);

                    // Stage メタ更新
                    try {
                        const wfStatus = await apiRequest(`/api/user/workflow-executions/${progressPollWfExecId}/status`).catch(() => null);
                        if (wfStatus) {
                            _wfStageMeta = {
                                currentStage: wfStatus.current_stage || null,
                                finalVerdict: wfStatus.final_verdict || null,
                                handoffSummary: wfStatus.handoff_summary || null,
                                coordinatorView: wfStatus.coordinator_view || null,
                                synthesisEvents: wfStatus.synthesis_events || [],
                            };
                            if (wfStatus.blackboard_keys) _blackboardKeys = wfStatus.blackboard_keys;
                            if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);
                        }
                    } catch (e) { /* ignore */ }

                    // PersistentStatusBar ステップ名更新
                    if (typeof PersistentStatusBar !== 'undefined') {
                        const proc = wfExecs.find(e => (e.status === 'processing' || e.status === 'pending_local') && !e.execution_role);
                        if (proc) {
                            const sk = allSkillsInit.find(s => s.workflow_skill_id == proc.workflow_skill_id);
                            if (sk) {
                                PersistentStatusBar.currentStepName = sk.skill_name || `Step ${sk.skill_order}`;
                                PersistentStatusBar.currentStepOrder = sk.skill_order;
                            }
                        }
                    }
                } catch (e) { /* ignore poll errors */ }
            }, 2000);

            // sidecar完了を待つ（UIはフリーズしない: spawn_blocking）
            const desktopResult = await desktopPromise;
            desktopDone = true;
            clearInterval(progressPoll);

            // sidecarの結果から正確なworkflow_execution_idを使用
            resp = {
                workflow_execution_id: desktopResult.workflowExecutionId,
                execution_ids: desktopResult.executionIds || [],
            };
        } else {
            resp = await apiRequest('/api/execute/workflow', {
                method: 'POST',
                body: JSON.stringify(body)
            });
        }

        // workflow_execution_idを保存
        workflowExecutionId = resp.workflow_execution_id;
        try {
            await createDesktopWorkflowRun(workflowExecutionId);
        } catch (error) {
            console.error('Failed to create desktop workflow run:', error);
        }

        // ワークフロー実行開始直後に CoordinatorPlan を取得して可視化
        try { loadCoordinatorPlan(workflowExecutionId); } catch (_) {}

        if (isDesktopLocal) {
            // デスクトップパス: sidecar完了済み → handleWorkflowComplete で結果表示
            // 進捗ポーリングで設定したステータスを保持（再初期化しない）
            _checkNextStepRetryCount = 0;

            // PersistentStatusBar のIDを確定 → UIを再描画
            if (typeof PersistentStatusBar !== 'undefined') {
                PersistentStatusBar.workflowExecutionId = workflowExecutionId;
                if (resp.execution_ids?.length > 0) {
                    PersistentStatusBar.executionId = resp.execution_ids[0];
                }
                PersistentStatusBar.updateUI(true);
                PersistentStatusBar.renderTasks();
            }

            // handleWorkflowComplete を呼んで最終結果を表示
            // （executeWorkflowWithDesktopLocalEngine 内で既に呼ばれた可能性あり → ガードで重複防止）
            if (!_workflowCompleteHandled) {
                // リーダー実行を取得
                let leaderExecution = null;
                const desktopResult = window.__NEXMAGI_LAST_LOCAL_WORKFLOW_RESULT;
                if (desktopResult?.leaderExecutionId) {
                    leaderExecution = await apiRequest(`/api/user/executions/${desktopResult.leaderExecutionId}`).catch(() => null);
                }
                if (!leaderExecution) {
                    leaderExecution = {
                        id: null,
                        status: desktopResult?.status || 'success',
                        output_data: desktopResult?.output || '',
                    };
                }
                await handleWorkflowComplete(workflowExecutionId, leaderExecution);
            }

            await loadHistory();
            return;
        }

        // --- 非オーケストレーション実行パス（APIゲートウェイモード） ---
        stepExecutions.clear();
        _checkNextStepRetryCount = 0;
        _workflowCompleteHandled = false;

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

        if (false) { /* dead code removed */
            const _desktopStepPoll = async () => {
                let pollCount = 0;
                const maxPolls = 300; // 最大10分（2秒×300）
                while (pollCount < maxPolls && !_workflowCompleteHandled) {
                    await new Promise(r => setTimeout(r, 2000));
                    if (_workflowCompleteHandled) return;
                    pollCount++;
                    try {
                        const execsResp = await apiRequest('/api/user/executions?limit=100');
                        const execs = (execsResp.items || execsResp).filter(e => e.workflow_execution_id === workflowExecutionId);

                        // ステップステータスを更新
                        let hasProcessing = false;
                        for (const exec of execs) {
                            // stepExecutions にデータを保持（handleWorkflowComplete用）
                            if (exec.skill_order && !exec.execution_role) {
                                const existing = stepExecutions.get(exec.skill_order);
                                if (!existing) {
                                    stepExecutions.set(exec.skill_order, {
                                        executionId: exec.id,
                                        workflowSkillId: exec.workflow_skill_id,
                                        status: exec.status,
                                        output: exec.output_data || '',
                                        stepName: exec.skill_name || `Step ${exec.skill_order}`,
                                        skillName: exec.skill_name,
                                        errorMessage: exec.error_message || null,
                                    });
                                } else {
                                    existing.status = exec.status;
                                    existing.output = exec.output_data || existing.output;
                                    // success の場合はエラーメッセージをクリア
                                    existing.errorMessage = exec.status === 'success' ? null : (exec.error_message || existing.errorMessage);
                                }
                            }

                            // フロービュー用ステータス
                            const status = exec.status;
                            if (exec.execution_role || (!exec.workflow_skill_id && !exec.execution_role && !exec.skill_id)) {
                                // リーダー（execution_role付き OR parent skill: workflow_skill_id=null, skill_id=null）
                                if (status === 'processing' || status === 'pending' || status === 'pending_local') {
                                    _flowStepStatuses['leader'] = 'processing';
                                    hasProcessing = true;
                                } else if (status === 'success') {
                                    _flowStepStatuses['leader'] = 'success';
                                    _flowLeaderOutput = exec.output_data || _flowLeaderOutput;
                                } else if (status === 'error') {
                                    _flowStepStatuses['leader'] = 'error';
                                }
                            } else if (exec.workflow_skill_id) {
                                const key = 'ws_' + exec.workflow_skill_id;
                                if (status === 'success') {
                                    _flowStepStatuses[key] = 'success';
                                } else if (status === 'error') {
                                    _flowStepStatuses[key] = 'error';
                                } else if (status === 'processing' || status === 'pending' || status === 'pending_local') {
                                    _flowStepStatuses[key] = 'processing';
                                    hasProcessing = true;
                                }
                                if (exec.skill_id) {
                                    _flowStepStatuses[exec.skill_id] = _flowStepStatuses[key];
                                }
                            }
                        }

                        if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);

                        // 現在実行中のステップをPersistentStatusBarに反映
                        if (typeof PersistentStatusBar !== 'undefined') {
                            const processingExec = execs.find(e => e.status === 'processing' && !e.execution_role);
                            if (processingExec) {
                                const stepSkill = allSkills.find(s => s.workflow_skill_id == processingExec.workflow_skill_id);
                                if (stepSkill) {
                                    PersistentStatusBar.handleWorkflowNextStep(
                                        processingExec.id,
                                        stepSkill.skill_order,
                                        stepSkill.skill_name || `Step ${stepSkill.skill_order}`,
                                        workflowDetail?.workflow?.name || 'ワークフロー'
                                    );
                                }
                            }
                        }

                        // ワークフロー進行状態（Stage）を更新
                        const wfStatusResp = await apiRequest(`/api/user/workflow-executions/${workflowExecutionId}/status`).catch(() => null);
                        if (wfStatusResp) {
                            _wfStageMeta = {
                                currentStage: wfStatusResp.current_stage || null,
                                finalVerdict: wfStatusResp.final_verdict || null,
                                handoffSummary: wfStatusResp.handoff_summary || null,
                                coordinatorView: wfStatusResp.coordinator_view || null,
                                synthesisEvents: wfStatusResp.synthesis_events || [],
                            };
                            if (wfStatusResp.blackboard_keys) _blackboardKeys = wfStatusResp.blackboard_keys;
                            // オーケストレーション状況も更新
                            const specialExecs = execs.filter(e => e.execution_role);
                            if (specialExecs.length > 0) {
                                _orchestrationStatuses = specialExecs.map(e => ({
                                    role: e.execution_role,
                                    groupId: e.execution_group_id,
                                    status: e.status,
                                    action: '',
                                }));
                            }
                            if (_flowViewDetail) renderFlowView(_flowViewDetail, _flowStepStatuses);
                        }

                        // ワークフロー完了判定
                        if (wfStatusResp && (wfStatusResp.status === 'success' || wfStatusResp.status === 'error' || wfStatusResp.status === 'cancelled')) {
                            // リーダー実行を取得
                            const leaderExec = execs.find(e => e.execution_role && (e.status === 'success' || e.status === 'error'));
                            const leaderExecution = leaderExec
                                ? await apiRequest(`/api/user/executions/${leaderExec.id}`).catch(() => null)
                                : { id: null, status: wfStatusResp.status, output_data: '' };
                            await handleWorkflowComplete(workflowExecutionId, leaderExecution || { id: null, status: wfStatusResp.status, output_data: '' });
                            return;
                        }

                        // フォールバック完了判定: workflow_execution status が未更新でも、
                        // 全ステップ（期待数以上）が完了していればworkflow完了とみなす
                        if (!hasProcessing && execs.length > 0) {
                            const expectedSteps = allSkills.length || 1;
                            const normalExecs = execs.filter(e => !e.execution_role);
                            const completedNormal = normalExecs.filter(e => e.status === 'success' || e.status === 'error' || e.status === 'cancelled');
                            if (completedNormal.length >= expectedSteps) {
                                const leaderExec = execs.find(e => e.execution_role);
                                const leaderExecution = leaderExec
                                    ? await apiRequest(`/api/user/executions/${leaderExec.id}`).catch(() => null)
                                    : { id: null, status: 'success', output_data: '' };
                                await handleWorkflowComplete(workflowExecutionId, leaderExecution || { id: null, status: 'success', output_data: '' });
                                return;
                            }
                        }
                    } catch (pollErr) {
                        console.warn('[DesktopPoll] error:', pollErr);
                    }
                }
            };
            _desktopStepPoll().catch(err => console.error('[DesktopPoll] fatal:', err));
        }

        // 履歴を再読み込み
        await loadHistory();
        // 実行成功 — ボタンは完了まで非活性のまま維持
        return;
    } catch (error) {
        await finishDesktopWorkflowRun('error', {
            workflow_execution_id: workflowExecutionId,
            error_message: error?.message || 'workflow execute error',
        });
        // バックグラウンドパネルをエラー完了
        if (typeof PersistentStatusBar !== 'undefined' && PersistentStatusBar.startTime) {
            PersistentStatusBar.markAsCompleted('error');
        }
        // フロービューのステップをエラー状態に更新
        if (_flowViewDetail?.skills) {
            for (const skill of _flowViewDetail.skills) {
                if (skill.workflow_skill_id) {
                    const key = 'ws_' + skill.workflow_skill_id;
                    if (_flowStepStatuses[key] === 'processing') _flowStepStatuses[key] = 'error';
                }
                if (skill.skill_id && _flowStepStatuses[skill.skill_id] === 'processing') {
                    _flowStepStatuses[skill.skill_id] = 'error';
                }
            }
            renderFlowView(_flowViewDetail, _flowStepStatuses);
        }
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

// ───────────────────────────────────────────────
//  Coordinator integration
//  バックエンドの coordinator 観測層を取得して、3Dキューブパイプラインに
//  直接統合する。独立した coordinator-plan-section は使わず、
//  各キューブに役割バッジ・provider枠色・artifact チップを注入する。
//  (状態変数の宣言は renderFlowView より前 = ファイル上部にある)
// ───────────────────────────────────────────────

function _buildCoordinatorMaps(data) {
    _coordinatorTaskByWsId = {};
    _coordinatorArtifactByWsId = {};
    _coordinatorJudgedGroups = new Set();

    if (!data || !data.plan) return;

    for (const t of (data.plan.tasks || [])) {
        if (t.workflow_skill_id != null) {
            _coordinatorTaskByWsId[t.workflow_skill_id] = t;
        }
    }
    for (const a of (data.artifacts || [])) {
        // task_id は "task_${workflow_skill_id}" 形式
        const m = (a.task_id || '').match(/^task_(\d+)$/);
        if (m) {
            const wsId = parseInt(m[1], 10);
            (_coordinatorArtifactByWsId[wsId] = _coordinatorArtifactByWsId[wsId] || []).push(a);
        }
    }
    for (const e of (data.events || [])) {
        if (e.event_type === 'judge_decision_made' && e.payload?.execution_id) {
            // ジャッジが完了したことだけ記録（task_id ベース）
            if (e.task_id) _coordinatorJudgedGroups.add(e.task_id);
        }
    }
    if (data._eval && data._eval.current) {
        _coordinatorEvalMetrics = data._eval.current;
    }
}

async function loadCoordinatorPlan(wfExecId) {
    if (!wfExecId) return null;
    try {
        const [planData, evalData] = await Promise.all([
            apiRequest(`/api/user/coordinator/plans/${wfExecId}`).catch(() => null),
            apiRequest(`/api/user/coordinator/eval/${wfExecId}`).catch(() => null),
        ]);
        if (!planData || !planData.plan) return null;
        if (evalData) planData._eval = evalData;
        _coordinatorData = planData;
        _buildCoordinatorMaps(planData);
        return planData;
    } catch (e) {
        console.warn('loadCoordinatorPlan failed:', e);
        return null;
    }
}

// 役割の表示名と色
const _COORD_ROLE_INFO = {
    researcher: { label: 'Researcher', color: '#2196f3' },
    writer:     { label: 'Writer',     color: '#4caf50' },
    reviewer:   { label: 'Reviewer',   color: '#e91e63' },
    judge:      { label: 'Judge',      color: '#9c27b0' },
};

function _coordRoleBadge(_role) { return ''; }

function _coordProviderBadge(mode) {
    if (!mode) return '';
    const cls = mode.startsWith('local') ? 'wf-badge-local'
        : mode === 'hybrid_auto' ? 'wf-badge-hybrid'
        : 'wf-badge-remote';
    const label = mode.replace('_', ' ');
    return `<span class="wf-step-badge ${cls}">${label}</span>`;
}

function _coordArtifactChip(_wsId) { return ''; }

function _renderEvalMetrics() {
    const target = document.getElementById('wf-eval-metrics');
    if (!target) return;
    const m = _coordinatorEvalMetrics;
    // 完成度100%のときだけ表示 (ワークフロー完了相当)
    if (!m || (m.completeness ?? 0) < 100) {
        target.style.display = 'none';
        return;
    }
    target.style.display = 'flex';
    target.innerHTML = `
        <div class="wf-eval-chip"><div class="wf-eval-label">完成度</div><strong>${m.completeness ?? 0}%</strong></div>
        <div class="wf-eval-chip"><div class="wf-eval-label">修正率</div><strong>${m.revision_rate ?? 0}%</strong></div>
        <div class="wf-eval-chip"><div class="wf-eval-label">judge通過</div><strong>${m.judge_pass_rate ?? 0}%</strong></div>
        <div class="wf-eval-chip"><div class="wf-eval-label">local使用</div><strong>${m.local_usage_rate ?? 0}%</strong></div>
        <div class="wf-eval-chip"><div class="wf-eval-label">overhead</div><strong>${(m.overhead_ms ?? 0)}ms</strong></div>
    `;
}

// 旧 renderCoordinatorPlan は撤去 (キューブ統合に置き換え)

// ページ読み込み時に実行
(async () => {
    initUserLayout('');  // workflow-execute.html はナビでactive無し
    await checkAuth();
    await loadWorkflowDetail();
})();
