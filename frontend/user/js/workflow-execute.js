// ユーザー ワークフロー実行画面 JavaScript

let workflowId = null;
let workflowDetail = null;
let workflowExecutionId = null;
let stepExecutions = new Map(); // step_order -> { executionId, status, output, stepName, promptName }
let allExecutions = []; // 全ての実行履歴
let displayedHistoryCount = 3; // 表示する履歴の件数
let streamingWorkers = new Map(); // executionId -> worker

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
    } catch (error) {
        showAlert('ワークフロー情報の読み込みに失敗しました', 'error');
        console.error('loadWorkflowDetail error:', error);
    }
}

async function generateWorkflowInputFields(detail) {
    const container = document.getElementById('workflow-input-fields-container');
    if (!container) return;

    // 1. このワークフローに含まれる全Promptの詳細(input_schema)を取得
    const promptsById = {};
    for (const step of detail.skills || []) {
        const pid = step.prompt_id;
        if (!promptsById[pid]) {
            try {
                const p = await apiRequest(`/api/user/prompts/${pid}`);
                promptsById[pid] = p;
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

    // 3. 各Stepの入力スキーマを統合して、必要な項目だけを1つのセクションに表示
    const mergedInputFields = {};
    const stepFieldMapping = {}; // フィールド名 -> 最初に見つかったSTEPの情報

    for (const step of detail.skills || []) {
        const prompt = promptsById[step.prompt_id];
        const inputSchema = prompt ? prompt.input_schema : null;

        // input_schemaがないStepは「入力欄を自動生成しない」(ワークフローでは前ステップ出力を自動受け渡しするため)
        // どうしても入力が必要な場合は、workflowのinput_schema（共通入力）を使うか、promptのinput_schemaを定義する。
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

        // 各フィールドを統合（重複する場合は最初に見つかったものを優先）
        for (const [fieldName, cfg] of Object.entries(properties)) {
            if (!mergedInputFields[fieldName]) {
                mergedInputFields[fieldName] = {
                    label: cfg.title || cfg.label || fieldName,
                    description: cfg.description || '',
                    required: requiredFields.includes(fieldName) || cfg.required === true,
                    type: cfg.type || 'string',
                    placeholder: cfg.placeholder || cfg.description || '',
                    rows: cfg.rows || (cfg.type === 'code' ? 12 : 6),
                    step: step,
                    workflow_skill_id: step.workflow_skill_id
                };
                stepFieldMapping[fieldName] = step;
            }
        }
    }

    // 4. 入力欄が1つも無い場合のフォールバック
    // - workflow共通入力も無く、どのStepにもinput_schemaが無い場合のみ、最初のStep向けに「入力」1つを出す
    if (!hasWorkflowGlobalSchema && Object.keys(mergedInputFields).length === 0) {
        const firstStep = (detail.skills || [])[0];
        if (firstStep) {
            mergedInputFields.input = {
                label: '入力',
                description: '',
                required: true,
                type: 'string',
                placeholder: '',
                rows: 6,
                step: firstStep,
                workflow_skill_id: firstStep.workflow_skill_id
            };
            stepFieldMapping.input = firstStep;
        }
    }

    // 4. 統合された入力フィールドを1つのセクションに表示
    if (Object.keys(mergedInputFields).length > 0) {
        const fieldsHTML = Object.entries(mergedInputFields)
            .map(([fieldName, fieldConfig]) => {
                const { label, description, required, type, placeholder, rows, workflow_skill_id } = fieldConfig;
                const requiredAttr = required ? 'required' : '';
                const placeholderAttr = placeholder ? `placeholder="${placeholder}"` : '';
                const fullName = `${workflow_skill_id}__${fieldName}`;

                if (type === 'number' || type === 'integer') {
                    return `
                        <div class="form-group">
                            <label for="${fullName}">${label}</label>
                            ${description ? `<small style="color: rgba(255,255,255,0.6);">${description}</small>` : ''}
                            <input type="number" id="${fullName}" name="${fullName}" ${requiredAttr} ${placeholderAttr}>
                        </div>
                    `;
                }

                // 文字列はtextareaで統一
                return `
                    <div class="form-group">
                        <label for="${fullName}">${label}</label>
                        ${description ? `<small style="color: rgba(255,255,255,0.6);">${description}</small>` : ''}
                        <textarea id="${fullName}" name="${fullName}" rows="${rows}" ${requiredAttr} ${placeholderAttr}></textarea>
                    </div>
                `;
            })
            .join('');

        parts.push(`
            <div class="workflow-unified-input-section" style="margin-top: 24px;">
                <h3 style="margin-top: 0; margin-bottom: 12px; color: rgba(255,255,255,0.9);">
                    入力データ
                </h3>
                <p style="font-size: 12px; color: rgba(255,255,255,0.7); margin-bottom: 12px;">
                    ワークフロー実行に必要な入力項目を入力してください。後続のステップには前ステップの出力が自動的に渡されます。
                </p>
                <div>
                    ${fieldsHTML}
                </div>
            </div>
        `);
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

// ステップの実行結果を表示
function renderStepExecutions() {
    const container = document.getElementById('workflow-output-content');
    if (!container) return;

    if (stepExecutions.size === 0) {
        container.innerHTML = '<div style="padding: 16px; color: rgba(255,255,255,0.8);">ワークフローを実行すると、各ステップの実行結果がここに表示されます</div>';
        return;
    }

    // ステップ順序でソート
    const sortedSteps = Array.from(stepExecutions.entries())
        .sort(([orderA], [orderB]) => orderA - orderB);

    const stepsHTML = sortedSteps.map(([stepOrder, stepData]) => {
        const { executionId, status, output, stepName, promptName, errorMessage } = stepData;
        const statusColor = status === 'success' ? '#28a745' :
                            status === 'error' ? '#dc3545' :
                            status === 'cancelled' ? '#ffc107' :
                            status === 'processing' ? '#7c3aed' :
                            status === 'pending' ? '#7c3aed' : 'rgba(255, 255, 255, 0.6)';
        const statusText = status === 'success' ? '完了' :
                            status === 'error' ? 'エラー' :
                            status === 'cancelled' ? 'キャンセル' :
                            status === 'processing' ? '実行中...' :
                            status === 'pending' ? '待機中...' : '不明';

        return `
            <div class="workflow-step-result" style="margin-bottom: 20px; padding: 16px; background: rgba(0, 0, 0, 0.2); border-radius: 8px; border-left: 4px solid ${statusColor};">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <h4 style="margin: 0; color: rgba(255,255,255,0.9);">
                        Step ${stepOrder}: ${stepName || promptName || 'ステップ'}
                    </h4>
                    <span style="color: ${statusColor}; font-weight: bold; font-size: 12px;">${statusText}</span>
                </div>
                ${status === 'processing' ? `
                    <div style="padding: 12px; background: rgba(124, 58, 237, 0.1); border-radius: 4px; color: rgba(255,255,255,0.7);">
                        <div class="spinner" style="display: inline-block; width: 16px; height: 16px; border-width: 2px; vertical-align: middle; margin-right: 8px;"></div>
                        AIが応答を生成しています...
                    </div>
                ` : ''}
                ${status === 'success' && output ? `
                    <div style="padding: 12px; background: rgba(0, 0, 0, 0.3); border-radius: 4px; margin-top: 8px;">
                        <div style="color: rgba(255,255,255,0.9); white-space: pre-wrap; word-wrap: break-word; font-size: 13px;">${escapeHtml(output)}</div>
                    </div>
                ` : ''}
                ${status === 'error' && errorMessage ? `
                    <div style="padding: 12px; background: rgba(220, 53, 69, 0.2); border-radius: 4px; margin-top: 8px; color: #dc3545;">
                        ${escapeHtml(errorMessage)}
                    </div>
                ` : ''}
                ${status === 'cancelled' ? `
                    <div style="padding: 12px; background: rgba(255, 193, 7, 0.2); border-radius: 4px; margin-top: 8px; color: #ffc107;">
                        実行がキャンセルされました
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');

    container.innerHTML = stepsHTML;
    
    // スクロール位置を調整
    if (container.scrollHeight > container.clientHeight) {
        container.scrollTop = container.scrollHeight;
    }
}

// HTMLエスケープ処理（XSS対策）
function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ステップのストリーミングを開始
function startStepStreaming(executionId, stepOrder, stepName, promptName) {
    // 既にストリーミング中の場合はスキップ
    if (streamingWorkers.has(executionId)) {
        return;
    }

    // ステップ実行情報を初期化
    stepExecutions.set(stepOrder, {
        executionId,
        status: 'processing',
        output: '',
        stepName,
        promptName,
        errorMessage: null
    });
    renderStepExecutions();

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
                const nextStepOrder = stepData.next_step_order;
                const nextStepName = stepData.step_name || `Step ${nextStepOrder}`;
                const nextPromptName = stepData.prompt_name || nextStepName;
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
        console.log('Execution data retrieved:', { 
            executionId, 
            stepOrder, 
            status: execution.status,
            workflow_execution_id: execution.workflow_execution_id,
            workflow_skill_id: execution.workflow_skill_id,
            output_length: execution.output_data ? execution.output_data.length : 0
        });

        // ステップ実行情報を更新（画面表示用のみ）
        const stepData = stepExecutions.get(stepOrder);
        if (stepData) {
            stepData.status = execution.status || status;
            stepData.output = execution.output_data || stepData.output || '';
            stepData.errorMessage = execution.error_message || errorMessage;
            console.log('Step data updated:', { stepOrder, status: stepData.status, outputLength: stepData.output.length });
            renderStepExecutions();
        } else {
            // stepDataが存在しない場合は新規作成
            const stepInfo = workflowDetail?.skills?.find(s => s.step_order === stepOrder);
            stepExecutions.set(stepOrder, {
                executionId,
                status: execution.status || status,
                output: execution.output_data || '',
                stepName: execution.step_name || stepInfo?.step_name || stepInfo?.prompt_name || `Step ${stepOrder}`,
                promptName: stepInfo?.prompt_name || `Step ${stepOrder}`,
                errorMessage: execution.error_message || errorMessage
            });
            renderStepExecutions();
        }

        // ワークフロー単位で完了管理するため、ここではバックグラウンドパネルへの保存は行わない

        // リーダーステップ（workflow_skill_idがNone）の場合はワークフロー全体が完了
        const isLeaderStep = execution.workflow_skill_id === null || execution.workflow_skill_id === undefined;
        if (isLeaderStep && execution.workflow_execution_id && workflowExecutionId === execution.workflow_execution_id) {
            console.log('Leader step completed, handling workflow complete');
            // ワークフロー全体が完了したので、プロンプト実行と同様の処理を実行
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

// ワークフロー全体の完了処理（プロンプト実行と同様の挙動）
async function handleWorkflowComplete(workflowExecutionId, leaderExecution) {
    console.log('handleWorkflowComplete called:', { workflowExecutionId, leaderExecutionId: leaderExecution.id });
    
    try {
        // ワークフロー実行の全実行を取得して統合結果を表示
        const response = await apiRequest(`/api/user/executions?limit=100`);
        const responseExecutions = response.items || response;
        const workflowExecutions = responseExecutions.filter(exec => exec.workflow_execution_id === workflowExecutionId);
        
        console.log('Workflow executions found:', { 
            count: workflowExecutions.length,
            executionIds: workflowExecutions.map(e => e.id),
            stepOrders: workflowExecutions.map(e => e.step_order)
        });
        
        // ステップ順序でソート
        workflowExecutions.sort((a, b) => (a.step_order || 0) - (b.step_order || 0));

        // 全ステップの結果を統合（stepExecutionsからも取得）
        const allStepResults = workflowExecutions.map(exec => {
            const stepInfo = workflowDetail?.skills?.find(s => s.step_order === exec.step_order);
            // stepExecutionsからも取得を試みる（リアルタイム表示の結果を優先）
            const stepData = stepExecutions.get(exec.step_order);
            return {
                stepOrder: exec.step_order,
                stepName: exec.step_name || stepInfo?.step_name || stepInfo?.prompt_name || `Step ${exec.step_order}`,
                status: exec.status,
                output: stepData?.output || exec.output_data || '',
                errorMessage: exec.error_message
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
                const finalStatus = leaderExecution.status === 'success' ? 'success' : 'error';
                PersistentStatusBar.markAsCompleted(finalStatus);
                console.log('Workflow completed, PersistentStatusBar updated:', finalStatus);
            }
        }

        // 入力データを復元（最初の実行から）
        const firstExecution = workflowExecutions[0];
        if (firstExecution) {
            restoreWorkflowInputData(firstExecution);
        }

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

        // 全ステップの結果を統合して表示（リーダーステップの結果を最終結果として表示）
        const finalOutput = leaderExecution.output_data || '';
        displayWorkflowResult(finalOutput, allStepResults, leaderExecution);
        
        // 出力パネルを確実に表示（プロンプト実行と同様）
        const outputContent = document.getElementById('workflow-output-content');
        if (outputContent) {
            // 出力パネルが表示されるようにスクロール
            outputContent.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        // 完了ポップアップを表示（プロンプト実行と同様）
        await Swal.fire({
            title: 'ワークフロー実行完了',
            text: 'ワークフロー実行が完了しました',
            icon: leaderExecution.status === 'success' ? 'success' : 'error',
            confirmButtonText: 'OK'
        });

        // 履歴を再読み込み
        await loadHistory();
    } catch (error) {
        console.error('Failed to handle workflow complete:', error);
        await showAlert('ワークフロー完了処理に失敗しました', 'error');
    }
}

// ワークフロー結果を表示（プロンプト実行のdisplayExecutionResultと同様）
function displayWorkflowResult(finalOutput, allStepResults, leaderExecution) {
    // 結果パネルを表示（存在する場合）
    const outputContent = document.getElementById('workflow-output-content');
    if (!outputContent) {
        console.warn('workflow-output-content element not found');
        return;
    }

    // 全ステップの結果をカード形式で表示（renderStepExecutionsと同様の形式）
    const stepsHTML = allStepResults.map(step => {
        const statusColor = step.status === 'success' ? '#28a745' :
                            step.status === 'error' ? '#dc3545' :
                            step.status === 'cancelled' ? '#ffc107' :
                            'rgba(255, 255, 255, 0.6)';
        const statusText = step.status === 'success' ? '完了' :
                            step.status === 'error' ? 'エラー' :
                            step.status === 'cancelled' ? 'キャンセル' : '不明';

        return `
            <div class="workflow-step-result" style="margin-bottom: 20px; padding: 16px; background: rgba(0, 0, 0, 0.2); border-radius: 8px; border-left: 4px solid ${statusColor};">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <h4 style="margin: 0; color: rgba(255,255,255,0.9);">
                        Step ${step.stepOrder}: ${step.stepName}
                    </h4>
                    <span style="color: ${statusColor}; font-weight: bold; font-size: 12px;">${statusText}</span>
                </div>
                ${step.status === 'success' && step.output ? `
                    <div style="padding: 12px; background: rgba(0, 0, 0, 0.3); border-radius: 4px; margin-top: 8px;">
                        <div style="color: rgba(255,255,255,0.9); white-space: pre-wrap; word-wrap: break-word; font-size: 13px;">${escapeHtml(step.output)}</div>
                    </div>
                ` : ''}
                ${step.status === 'error' && step.errorMessage ? `
                    <div style="padding: 12px; background: rgba(220, 53, 69, 0.2); border-radius: 4px; margin-top: 8px; color: #dc3545;">
                        ${escapeHtml(step.errorMessage)}
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');

    // リーダーステップの最終結果を追加（リーダーステップがある場合）
    let finalResultHTML = '';
    if (finalOutput) {
        finalResultHTML = `
            <div class="workflow-step-result" style="margin-bottom: 20px; padding: 16px; background: rgba(124, 58, 237, 0.1); border-radius: 8px; border-left: 4px solid #7c3aed;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <h4 style="margin: 0; color: rgba(255,255,255,0.9);">
                        最終結果（リーダー統合）
                    </h4>
                    <span style="color: #7c3aed; font-weight: bold; font-size: 12px;">完了</span>
                </div>
                <div style="padding: 12px; background: rgba(0, 0, 0, 0.3); border-radius: 4px; margin-top: 8px;">
                    <div style="color: rgba(255,255,255,0.9); white-space: pre-wrap; word-wrap: break-word; font-size: 13px;">${escapeHtml(finalOutput)}</div>
                </div>
            </div>
        `;
    } else if (allStepResults.length > 0) {
        // リーダーステップがない場合は、最後のステップの結果を最終結果として表示
        const lastStep = allStepResults[allStepResults.length - 1];
        if (lastStep.status === 'success' && lastStep.output) {
            finalResultHTML = `
                <div class="workflow-step-result" style="margin-bottom: 20px; padding: 16px; background: rgba(124, 58, 237, 0.1); border-radius: 8px; border-left: 4px solid #7c3aed;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <h4 style="margin: 0; color: rgba(255,255,255,0.9);">
                            最終結果
                        </h4>
                        <span style="color: #7c3aed; font-weight: bold; font-size: 12px;">完了</span>
                    </div>
                    <div style="padding: 12px; background: rgba(0, 0, 0, 0.3); border-radius: 4px; margin-top: 8px;">
                        <div style="color: rgba(255,255,255,0.9); white-space: pre-wrap; word-wrap: break-word; font-size: 13px;">${escapeHtml(lastStep.output)}</div>
                    </div>
                </div>
            `;
        }
    }

    // 結果が空の場合はメッセージを表示
    if (!stepsHTML && !finalResultHTML) {
        outputContent.innerHTML = '<div style="padding: 16px; color: rgba(255,255,255,0.8);">結果がありません</div>';
    } else {
        outputContent.innerHTML = stepsHTML + finalResultHTML;
    }
    
    // スクロール位置を調整
    if (outputContent.scrollHeight > outputContent.clientHeight) {
        outputContent.scrollTop = outputContent.scrollHeight;
    }
    
    console.log('Workflow result displayed:', { 
        stepCount: allStepResults.length, 
        hasFinalOutput: !!finalOutput,
        stepsHTML: stepsHTML.length,
        finalResultHTML: finalResultHTML.length
    });
}

// ワークフロー入力データを復元（プロンプト実行のrestoreInputDataと同様）
function restoreWorkflowInputData(execution) {
    if (!execution.input_data) return;

    try {
        let inputData;
        if (typeof execution.input_data === 'string') {
            inputData = JSON.parse(execution.input_data);
        } else {
            inputData = execution.input_data;
        }

        // ワークフロー共通入力の復元
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

// 次のステップが開始されているか確認し、開始されていなければ開始する
async function checkAndStartNextStep(workflowExecutionId, completedStepOrder) {
    try {
        console.log('checkAndStartNextStep called:', { workflowExecutionId, completedStepOrder });
        
        // ワークフロー実行の全実行を取得
        const response = await apiRequest(`/api/user/executions?limit=100`);
        const responseExecutions = response.items || response;
        const workflowExecutions = responseExecutions.filter(exec => exec.workflow_execution_id === workflowExecutionId);

        console.log('Workflow executions found:', { 
            count: workflowExecutions.length,
            executionIds: workflowExecutions.map(e => e.id),
            stepOrders: workflowExecutions.map(e => e.step_order)
        });

        // 次のステップの実行を探す
        const nextStepOrder = completedStepOrder + 1;
        const nextExecution = workflowExecutions.find(exec => exec.step_order === nextStepOrder);

        if (nextExecution) {
            console.log('Next step execution found:', { 
                nextExecutionId: nextExecution.id, 
                nextStepOrder,
                status: nextExecution.status,
                alreadyStreaming: streamingWorkers.has(nextExecution.id)
            });

            // 既にストリーミング中の場合はスキップ
            if (streamingWorkers.has(nextExecution.id)) {
                console.log('Next step already streaming, skipping');
                return;
            }

            // 次のステップの情報を取得
            const nextStepInfo = workflowDetail?.skills?.find(s => s.step_order === nextStepOrder);
            const nextStepName = nextStepInfo?.step_name || nextStepInfo?.prompt_name || nextExecution.step_name || `Step ${nextStepOrder}`;
            const nextPromptName = nextStepInfo?.prompt_name || nextStepName;
            const workflowName = workflowDetail?.workflow?.name || 'ワークフロー';

            // バックグラウンドパネルを次のステップに更新
            if (typeof PersistentStatusBar !== 'undefined') {
                PersistentStatusBar.handleWorkflowNextStep(
                    nextExecution.id,
                    nextStepOrder,
                    nextStepName,
                    workflowName
                );
            }

            // 次のステップのストリーミングを開始
            console.log('Starting next step streaming:', { nextExecutionId: nextExecution.id, nextStepOrder, nextStepName });
            startStepStreaming(nextExecution.id, nextStepOrder, nextStepName, nextPromptName);
        } else {
            console.log('Next step execution not found yet, will retry...', { nextStepOrder });
            // 次のステップが見つからない場合は、少し待ってから再試行
            setTimeout(async () => {
                await checkAndStartNextStep(workflowExecutionId, completedStepOrder);
            }, 3000);
        }
    } catch (error) {
        console.error('Failed to check next step:', error);
    }
}

// 実行履歴を読み込む
async function loadHistory() {
    try {
        const response = await apiRequest(`/api/user/executions?limit=100`);
        const responseExecutions = response.items || response;
        // ワークフロー実行IDでフィルタリング
        if (workflowExecutionId) {
            allExecutions = responseExecutions.filter(exec => exec.workflow_execution_id === workflowExecutionId);
        } else {
            // workflowExecutionIdがない場合は、このワークフローのIDに一致するプロンプトIDでフィルタリング
            const workflowPromptIds = workflowDetail?.skills?.map(s => s.prompt_id) || [];
            allExecutions = responseExecutions.filter(exec => 
                workflowPromptIds.includes(exec.prompt_id) && exec.workflow_execution_id
            );
        }
        
        // ステップ順序でソート
        allExecutions.sort((a, b) => (a.step_order || 0) - (b.step_order || 0));
        
        console.log('History loaded:', { 
            workflowExecutionId,
            count: allExecutions.length,
            executionIds: allExecutions.map(e => e.id),
            stepOrders: allExecutions.map(e => e.step_order)
        });
        
        displayedHistoryCount = 3; // リセット
        renderHistory();
    } catch (error) {
        console.error('Load history error:', error);
    }
}

// 実行履歴を表示
function renderHistory() {
    const container = document.getElementById('history-container');
    if (!container) return;

    if (allExecutions.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: rgba(255, 255, 255, 0.6); padding: 20px;">このワークフローの実行履歴がありません</p>';
        return;
    }

    // 表示する履歴を取得（最新から順に）
    const displayedExecutions = allExecutions.slice(0, displayedHistoryCount);
    const hasMore = allExecutions.length > displayedHistoryCount;

    container.innerHTML = `
        <table class="table">
            <thead>
                <tr>
                    <th>実行日時</th>
                    <th>ステップ</th>
                    <th>モデル</th>
                    <th>出力形式</th>
                    <th>実行時間</th>
                    <th>トークン数</th>
                    <th>ステータス</th>
                    <th>アクション</th>
                </tr>
            </thead>
            <tbody>
                ${displayedExecutions.map(execution => {
                    const stepInfo = execution.step_name ? `${execution.step_name}` : (execution.step_order ? `Step ${execution.step_order}` : '-');
                    const modelDisplay = execution.model_used || '-';

                    return `
                    <tr>
                        <td>${formatDate(execution.executed_at)}</td>
                        <td>${stepInfo}</td>
                        <td>${modelDisplay}</td>
                        <td>${execution.output_format ? execution.output_format.toUpperCase() : 'TXT'}</td>
                        <td>${execution.execution_time || '-'}${execution.execution_time ? 'ms' : ''}</td>
                        <td>${execution.tokens_used || '-'}</td>
                        <td>
                            <span style="color: ${execution.status === 'success' ? '#28a745' : execution.status === 'error' ? '#dc3545' : execution.status === 'cancelled' ? '#ffc107' : execution.status === 'pending' || execution.status === 'processing' ? '#7c3aed' : 'rgba(255, 255, 255, 0.6)'}">
                                ${execution.status}
                            </span>
                        </td>
                        <td>
                            <button onclick="showHistoryDetail(${execution.id})" title="詳細" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer;">
                                <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #17a2b8;"><path d="m15 17.75c0-.414-.336-.75-.75-.75h-11.5c-.414 0-.75.336-.75.75s.336.75.75.75h11.5c.414 0 .75-.336.75-.75zm7-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75z" fill-rule="nonzero"/></svg>
                            </button>
                        </td>
                    </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
        ${hasMore ? `
            <div style="text-align: center; margin-top: 15px;">
                <button class="btn btn-secondary" onclick="loadMoreHistory()">もっと見る</button>
            </div>
        ` : ''}
    `;
}

function loadMoreHistory() {
    displayedHistoryCount += 3;
    renderHistory();
}

async function showHistoryDetail(id) {
    try {
        const execution = await apiRequest(`/api/user/executions/${id}`);
        const detailHTML = `
            <div style="text-align: left; max-height: 70vh; overflow-y: auto;">
                <div style="margin-bottom: 15px;">
                    <strong>実行日時:</strong><br>
                    <span>${formatDate(execution.executed_at)}</span>
                </div>
                ${execution.workflow_name ? `
                <div style="margin-bottom: 15px;">
                    <strong>ワークフロー:</strong><br>
                    <span style="color: #7c3aed; font-weight: 500;">${execution.workflow_name}</span>
                    ${execution.step_name ? `<br><span style="font-size: 12px; color: rgba(255,255,255,0.7);">ステップ: ${execution.step_name}</span>` : ''}
                </div>
                ` : ''}
                <div style="margin-bottom: 15px;">
                    <strong>使用モデル:</strong><br>
                    <span>${execution.model_used || '-'}</span>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>入力データ:</strong><br>
                    <div style="background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.1); padding: 10px; border-radius: 8px; margin-top: 5px; max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word; color: rgba(255, 255, 255, 0.9);">${formatJSON(execution.input_data)}</div>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>出力データ:</strong><br>
                    <div style="background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.1); padding: 10px; border-radius: 8px; margin-top: 5px; max-height: 300px; overflow-y: auto; color: rgba(255, 255, 255, 0.9); white-space: pre-wrap; word-wrap: break-word;">${execution.output_data || '-'}</div>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>実行時間:</strong><br>
                    <span>${execution.execution_time ? `${execution.execution_time}ms` : '-'}</span>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>使用トークン数:</strong><br>
                    <span>${execution.tokens_used || '-'}</span>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>ステータス:</strong><br>
                    <span style="color: ${execution.status === 'success' ? '#28a745' : execution.status === 'error' ? '#dc3545' : execution.status === 'cancelled' ? '#ffc107' : 'rgba(255, 255, 255, 0.6)'}">${execution.status}</span>
                </div>
                ${execution.error_message ? `
                <div style="margin-bottom: 15px;">
                    <strong>エラーメッセージ:</strong><br>
                    <div style="background: rgba(220, 53, 69, 0.2); border: 1px solid rgba(220, 53, 69, 0.4); color: rgba(255, 107, 107, 0.9); padding: 10px; border-radius: 8px; margin-top: 5px;">${execution.error_message}</div>
                </div>
                ` : ''}
            </div>
        `;

        await Swal.fire({
            title: '実行詳細',
            html: detailHTML,
            width: '800px',
            confirmButtonText: '閉じる',
            confirmButtonColor: '#6c757d',
            customClass: {
                popup: 'swal-wide'
            }
        });
    } catch (error) {
        await showAlert('詳細情報の読み込みに失敗しました', 'error');
        console.error('Load detail error:', error);
    }
}

function formatJSON(json) {
    try {
        if (typeof json === 'string') {
            json = JSON.parse(json);
        }
        return JSON.stringify(json, null, 2);
    } catch {
        return json;
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
            output_format: outputFormat
        };

        // ボタン無効化（入力取得後）
        executeBtn.disabled = true;
        executeBtnText.textContent = '実行中...';
        if (executeBtnSpinner) executeBtnSpinner.style.display = 'inline';

        // 全フィールド無効化（入力取得後）
        inputs.forEach((el) => {
            if (el !== executeBtn) el.disabled = true;
        });

        const resp = await apiRequest('/api/execute/workflow', {
            method: 'POST',
            body: JSON.stringify(body)
        });

        // workflow_execution_idを保存
        workflowExecutionId = resp.workflow_execution_id;
        stepExecutions.clear();

        // 最初のステップのストリーミングを開始
        const firstExecutionId = resp.execution_ids[0];
        if (firstExecutionId) {
            const firstStep = workflowDetail?.skills?.[0];
            const firstStepName = firstStep?.step_name || firstStep?.prompt_name || 'Step 1';
            const firstPromptName = firstStep?.prompt_name || 'プロンプト';
            const firstStepOrder = firstStep?.step_order || 1;

            // バックグラウンドパネルに最初の実行を追加
            if (typeof PersistentStatusBar !== 'undefined') {
                const workflowName = workflowDetail?.workflow?.name || 'ワークフロー';
                PersistentStatusBar.start(
                    firstExecutionId,
                    null,
                    firstStepName,
                    workflowExecutionId,
                    workflowName,
                    firstStepOrder,
                    firstStepName
                );
            }

            // 最初のステップのストリーミングを開始
            startStepStreaming(firstExecutionId, firstStepOrder, firstStepName, firstPromptName);
        }

        // 履歴を再読み込み
        await loadHistory();
    } catch (error) {
        await showAlert('ワークフロー実行に失敗しました', 'error');
        console.error('execute workflow error:', error);
    } finally {
        executeBtn.disabled = false;
        executeBtnText.textContent = 'ワークフロー実行';
        if (executeBtnSpinner) executeBtnSpinner.style.display = 'none';
        inputs.forEach((el) => {
            if (el !== executeBtn) el.disabled = false;
        });
    }
});

// URLパラメータ取得ヘルパー
function getQueryParam(name) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(name);
}

// ページ読み込み時に実行
(async () => {
    await checkAuth();
    await loadWorkflowDetail();
})();
