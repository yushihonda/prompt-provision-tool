// ユーザー スキル実行画面 JavaScript

let skillId = null;
let skillDetail = null;
let executions = [];
let allExecutions = []; // 全ての実行履歴
let displayedHistoryCount = 3; // 表示する履歴の件数

async function loadPromptDetail() {
    skillId = getQueryParam('id');
    if (!skillId) {
        showAlert('スキルIDが指定されていません', 'error');
        return;
    }

    try {
        skillDetail = await apiRequest(`/api/user/skills/${skillId}`);

        // スキル情報を表示
        document.getElementById('skill-name').textContent = skillDetail.name;
        document.getElementById('skill-description').textContent = skillDetail.description || '説明なし';
        document.getElementById('skill-model').innerHTML = formatModelDisplay(skillDetail.model_type, null, skillDetail);

        // ファイル出力オプションの表示/非表示
        const fileOutputContainer = document.getElementById('file-output-container');
        if (skillDetail.allows_file_output) {
            fileOutputContainer.style.display = 'block';
        } else {
            fileOutputContainer.style.display = 'none';
        }


        // 入力フィールドを生成
        generateInputFields(skillDetail.input_schema);

        // 実行履歴を読み込む
        loadHistory();

        // URLパラメータにexecution_idがある場合は、その実行の入力データを復元
        const executionIdParam = getQueryParam('execution_id');
        if (executionIdParam && executionIdParam !== 'undefined' && executionIdParam !== 'null') {
            await restoreExecutionData(executionIdParam);
        } else {
            // 実行中のタスクがあるかチェックして復元
            await restoreActiveExecution();
        }
    } catch (error) {
        showAlert('スキル情報の読み込みに失敗しました', 'error');
    }
}

async function restoreActiveExecution() {
    // PersistentStatusBarに実行中のタスクがあるか確認
    if (!PersistentStatusBar.executionId || !PersistentStatusBar.skillId) {
        return;
    }

    // 現在のスキルIDと一致するか確認
    const currentPromptId = parseInt(skillId);
    if (PersistentStatusBar.skillId !== currentPromptId) {
        return; // 別のスキルの実行中なので何もしない
    }

    const executionId = PersistentStatusBar.executionId;

    // 実行ステータスを確認
    try {
        const execution = await apiRequest(`/api/user/executions/${executionId}`);

        if (execution.status === 'success') {
            // 既に完了している場合は結果を表示
            // 完了状態をDockに表示（履歴として残す）
            if (PersistentStatusBar.executionId === executionId) {
                PersistentStatusBar.markAsCompleted('success');
            }

            // 入力データを入力フィールドに復元
            restoreInputData(execution);

            // 実行ボタンを再有効化（完了したので）
            setExecutionButtonState(false);

            // 実行履歴を再読み込みして最新の状態を表示
            await loadHistory();

            // 結果を表示
            // output_formatが保存されている場合は使用、ない場合はデフォルト値'txt'を使用
            displayExecutionResult(execution, executionId, null);

            // 完了ポップアップは廃止（Dockの詳細パネルに表示）
        } else if (execution.status === 'error' || execution.status === 'cancelled') {
            // エラーまたはキャンセル済み
            // 完了状態をDockに表示（履歴として残す）
            if (PersistentStatusBar.executionId === executionId) {
                PersistentStatusBar.markAsCompleted(execution.status);
            }

            // 入力データを入力フィールドに復元
            restoreInputData(execution);

            // 実行ボタンを再有効化（エラー/キャンセルなので）
            setExecutionButtonState(false);

            displayExecutionError(execution);
            // 実行履歴を再読み込み
            await loadHistory();
        } else if (execution.status === 'pending' || execution.status === 'processing') {
            // 実行中なので入力データを復元してからポーリングを再開
            restoreInputData(execution);
            setExecutionButtonState(true); // 実行ボタンを非活性化
            resumeStreaming(executionId);
        }
    } catch (error) {
        // エラーが発生した場合は、PersistentStatusBarを停止
        PersistentStatusBar.stop();
    }
}

function displayExecutionResult(execution, executionIdForDownload = null, outputFormatForDownload = null) {
    // 結果パネルを表示
    showOutputPanel();

    // 結果を表示
    updateOutputContent(execution.output_data || '');

    // スクロールを確実に機能させるため、スタイルを再適用
    const outputContent = document.getElementById('output-content');
    if (outputContent) {
        outputContent.style.overflowY = 'auto';
        outputContent.style.overflowX = 'hidden';
        outputContent.style.maxHeight = '100%';
    }

    // モデル表示を更新
    const statModel = document.getElementById('stat-model');
    if (statModel) {
        statModel.innerHTML = formatModelDisplay(execution.model_used, execution, skillDetail);
    }

    const statTime = document.getElementById('stat-time');
    if (statTime) {
        statTime.textContent = `${execution.execution_time}ms`;
    }

    const statTokens = document.getElementById('stat-tokens');
    if (statTokens) {
        statTokens.textContent = execution.tokens_used || '-';
    }

    // コピーボタンを有効化
    const copyBtn = document.getElementById('copy-output-btn');
    if (copyBtn) {
        copyBtn.style.opacity = '1';
    }

    // 結果パネルにスクロール
    const outputPanel = document.querySelector('.execute-output-panel');
    if (outputPanel) {
        outputPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    // ファイル出力結果の処理
    const fileOutputDiv = document.getElementById('file-output-result');
    // executionIdForDownloadがnullの場合は、execution.idを使用
    const finalExecutionId = executionIdForDownload || execution.id;

    // output_formatの取得優先順位:
    // 1. execution.output_format（APIレスポンスから取得、最優先）
    // 2. outputFormatForDownload（引数で明示的に指定された場合、nullまたは'txt'でない場合のみ）
    // 3. 'txt'（デフォルト値）
    let finalOutputFormat = execution?.output_format;
    // execution.output_formatがない場合、または'txt'の場合のみ、outputFormatForDownloadを使用
    if (!finalOutputFormat || finalOutputFormat === 'txt') {
        if (outputFormatForDownload && outputFormatForDownload !== 'txt') {
            finalOutputFormat = outputFormatForDownload;
        } else if (!finalOutputFormat) {
            finalOutputFormat = 'txt'; // デフォルト値
        }
    }

    // デバッグ用ログ
    console.log('[displayExecutionResult] Output format check:', {
        executionId: finalExecutionId,
        executionIdForDownload: executionIdForDownload,
        outputFormatForDownload: outputFormatForDownload,
        'execution.output_format': execution?.output_format,
        'execution keys': execution ? Object.keys(execution) : 'no execution',
        finalOutputFormat: finalOutputFormat,
        willShowDownload: finalExecutionId && finalOutputFormat && finalOutputFormat !== 'txt'
    });

    if (finalExecutionId && finalOutputFormat && finalOutputFormat !== 'txt') {
        // ファイルダウンロードボタンを表示
        const downloadLink = document.createElement('a');
        downloadLink.href = "#";
        downloadLink.className = 'btn btn-success';
        downloadLink.textContent = `結果をダウンロード (${finalOutputFormat.toUpperCase()})`;
        downloadLink.style.marginTop = '10px';
        downloadLink.style.display = 'inline-block';
        downloadLink.onclick = async (e) => {
            e.preventDefault();
            try {
                const response = await fetch(`/api/execute/download/${executionIdForDownload}?output_format=${finalOutputFormat}`, {
                    headers: {
                        'Authorization': `Bearer ${sessionStorage.getItem('token')}`
                    }
                });
                if (!response.ok) throw new Error('Download failed');

                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `execution_${executionIdForDownload}.${finalOutputFormat}`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            } catch (err) {
                showAlert('ダウンロードに失敗しました', 'error');
            }
        };

        if (fileOutputDiv) {
            fileOutputDiv.innerHTML = '';
            fileOutputDiv.appendChild(downloadLink);
            fileOutputDiv.style.display = 'block';
        }
    } else {
        if (fileOutputDiv) {
            fileOutputDiv.style.display = 'none';
        }
    }
}

function displayExecutionError(execution) {
    // 結果パネルを表示
    showOutputPanel();

    const errorMsg = execution.error_message || '実行エラーが発生しました';
    const outputContent = document.getElementById('output-content');
    if (outputContent) {
        outputContent.innerHTML = `<div style="color: ${execution.status === 'cancelled' ? '#ffc107' : '#dc3545'}; text-align: center; padding: 20px;">${execution.status === 'cancelled' ? '実行がキャンセルされました' : `エラー: ${escapeHtml(errorMsg.trim())}`}</div>`;
    }

    // 結果パネルにスクロール
    const outputPanel = document.querySelector('.execute-output-panel');
    if (outputPanel) {
        outputPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// Web Workerを使用したストリーミング実行
let executionWorker = null;
let currentExecutionId = null;
let accumulatedOutput = '';
let currentOutputFormat = 'txt';  // 現在の実行の出力形式を保持

// escapeHtml, formatJSON, getQueryParam は user-common.js で定義済み

// formatModelDisplay は ../js/model-display.js で共通定義

// 出力コンテンツを更新する関数
function updateOutputContent(text) {
    const outputContent = document.getElementById('output-content');
    if (!outputContent) {
        return;
    }

    const escapedOutput = escapeHtml(text);
    outputContent.innerHTML = `<div style="white-space: pre-wrap; word-wrap: break-word; color: rgba(255, 255, 255, 0.9); padding: 20px; background-color: rgba(0, 0, 0, 0.2); border-radius: 4px; min-height: 100px;">${escapedOutput}</div>`;

    // スクロール位置を調整
    if (outputContent.scrollHeight > outputContent.clientHeight) {
        outputContent.scrollTop = outputContent.scrollHeight;
    }

    const outputBox = outputContent.closest('.output-box');
    if (outputBox && outputBox.scrollHeight > outputBox.clientHeight) {
        outputBox.scrollTop = outputBox.scrollHeight;
    }
}

// 出力パネルを表示する関数
function showOutputPanel() {
    const outputPanel = document.querySelector('.execute-output-panel');
    if (outputPanel) {
        outputPanel.style.display = 'flex';
        outputPanel.style.visibility = 'visible';
    }
}

// 実行中メッセージを表示する関数
function showProcessingMessage() {
    const outputContent = document.getElementById('output-content');
    if (outputContent) {
        outputContent.innerHTML = `<div style="text-align: center; padding: 20px; color: rgba(255, 255, 255, 0.7);"><p>AIが応答を生成しています...</p></div>`;
    }
}

// Web Workerのメッセージハンドラを生成する関数
function createWorkerMessageHandler(executionId) {
    return (event) => {
        const { type, data } = event.data;

        if (type === 'chunk') {
            // チャンクデータがJSON文字列の場合（ワークフロー次のステップ通知など）
            let chunkText = data.text || data;
            try {
                const parsed = JSON.parse(chunkText);
                if (parsed.type === 'workflow_next_step' && parsed.next_execution_id) {
                    // ワークフロー実行の次のステップが起動された
                    const nextExecutionId = parsed.next_execution_id;
                    const nextSkillOrder = parsed.next_skill_order;
                    const stepName = parsed.skill_name || `Step ${nextSkillOrder}`;
                    const workflowName = parsed.workflow_name || 'ワークフロー';
                    
                    // バックグラウンドパネルに次のステップを追加
                    if (typeof PersistentStatusBar !== 'undefined') {
                        PersistentStatusBar.handleWorkflowNextStep(
                            nextExecutionId,
                            nextStepOrder,
                            stepName,
                            workflowName
                        );
                    }
                    return; // チャンクとして表示しない
                }
            } catch (e) {
                // JSONパースに失敗した場合は通常のチャンクとして処理
            }
            
            const chunk = chunkText;
            accumulatedOutput += chunk;
            updateOutputContent(accumulatedOutput);
        } else if (type === 'complete') {
            if (PersistentStatusBar.executionId === executionId) {
                PersistentStatusBar.markAsCompleted('success');
            }

            setTimeout(() => {
                handleStreamingComplete(executionId);
            }, 100);
        } else if (type === 'error') {
            if (PersistentStatusBar.executionId === executionId) {
                PersistentStatusBar.markAsCompleted('error');
            }
            const errorMsg = typeof data === 'string' ? data : (data?.message || data?.text || '実行エラーが発生しました');
            handleStreamingError(executionId, errorMsg);
        } else if (type === 'cancel') {
            if (PersistentStatusBar.executionId === executionId) {
                PersistentStatusBar.markAsCompleted('cancelled');
            }
            handleStreamingError(executionId, '実行がキャンセルされました', 'cancelled');
        }
    };
}

// ストリーミング接続を開始する関数
function startStreaming(executionId, outputFormat = 'txt') {
    // 以前のストリーミング接続を確実に終了
    if (executionWorker) {
        stopStreaming();
    }

    // 出力を確実にクリア
    accumulatedOutput = '';
    currentExecutionId = executionId;
    currentOutputFormat = outputFormat;  // 出力形式を保持

    // Web Workerを作成
    executionWorker = new Worker('/user/js/execution-worker.js');

    // メッセージ受信ハンドラを設定
    executionWorker.onmessage = createWorkerMessageHandler(executionId);

    executionWorker.onerror = (error) => {
        handleStreamingError(executionId, 'ストリーミング接続エラーが発生しました');
    };

    // Workerを開始
    const token = sessionStorage.getItem('token');
    executionWorker.postMessage({
        type: 'start',
        executionId: executionId,
        token: token
    });
}

// 推論モデルかどうかを判定する関数
function isReasoningModel(modelType) {
    if (!modelType) return false;
    const model = modelType.toLowerCase();
    return model.includes('-pro') ||
            model.includes('-thinking') ||
            model === 'gpt-5-pro' ||
            model === 'gpt-5.2-pro' ||
            model === 'gpt-5.1-thinking' ||
            model === 'gpt-5.2-thinking';
}

// 推論モデルの場合、ポーリングで完了を待つ関数
async function waitForReasoningModelCompletion(executionId, outputFormat) {
    const maxAttempts = 3600; // 最大1時間（1秒ごとにチェック）
    let attempts = 0;

    while (attempts < maxAttempts) {
        try {
            const execution = await apiRequest(`/api/user/executions/${executionId}`);

            if (execution.status === 'success' || execution.status === 'error' || execution.status === 'cancelled') {
                // 完了したので結果を表示
                restoreInputData(execution);
                setExecutionButtonState(false);

                // ステータスバーを更新
                if (PersistentStatusBar.executionId === executionId) {
                    if (execution.status === 'success') {
                        PersistentStatusBar.markAsCompleted('success');
                    } else if (execution.status === 'error') {
                        PersistentStatusBar.markAsCompleted('error');
                    } else if (execution.status === 'cancelled') {
                        PersistentStatusBar.markAsCompleted('cancelled');
                    }
                }

                // 結果を表示
                if (execution.status === 'success') {
                    displayExecutionResult(execution, executionId, outputFormat);
                } else {
                    displayExecutionError(execution);
                }

                // 出力パネルを確実に表示
                showOutputPanel();

                // 完了ポップアップを表示
                await Swal.fire({
                    title: '実行完了',
                    text: '実行が完了しました',
                    icon: execution.status === 'success' ? 'success' : 'error',
                    confirmButtonText: USER_SWAL.btnClose,
                    confirmButtonColor: USER_SWAL.primary
                });

                // 実行履歴を再読み込み
                await loadHistory();
                return;
            }

            // まだ実行中の場合は1秒待機
            await new Promise(resolve => setTimeout(resolve, 1000));
            attempts++;
        } catch (error) {
            await new Promise(resolve => setTimeout(resolve, 1000));
            attempts++;
        }
    }

    // タイムアウト
    setExecutionButtonState(false);
    await Swal.fire({
        title: 'タイムアウト',
        text: '実行がタイムアウトしました',
        icon: 'warning',
        confirmButtonText: USER_SWAL.btnClose,
        confirmButtonColor: USER_SWAL.primary
    });
}

async function resumeStreaming(executionId) {
    // 実行データを取得して入力データを復元（まだ取得していない場合）
    let execution;
    try {
        execution = await apiRequest(`/api/user/executions/${executionId}`);
        restoreInputData(execution);

        // 既に完了している場合は完了処理を実行
        if (execution.status === 'success' || execution.status === 'error' || execution.status === 'cancelled') {
            // ステータスバーを更新
            if (PersistentStatusBar.executionId === executionId) {
                if (execution.status === 'success') {
                    PersistentStatusBar.markAsCompleted('success');
                } else if (execution.status === 'error') {
                    PersistentStatusBar.markAsCompleted('error');
                } else if (execution.status === 'cancelled') {
                    PersistentStatusBar.markAsCompleted('cancelled');
                }
            }

            // 実行ボタンを再有効化
            setExecutionButtonState(false);

            // 結果を表示
            if (execution.status === 'success') {
                // output_formatが保存されている場合は使用、ない場合はデフォルト値'txt'を使用
                const outputFormat = execution.output_format || 'txt';
                displayExecutionResult(execution, executionId, outputFormat !== 'txt' ? outputFormat : null);
            } else {
                displayExecutionError(execution);
            }

            // 実行履歴を再読み込み
            await loadHistory();

            // 出力パネルを確実に表示
            showOutputPanel();
            return; // 既に完了しているのでストリーミングを開始しない
        }

        // 推論モデルの場合はストリーミング接続を開始せずに、ポーリングで完了を待つ
        const modelType = execution.model_used;
        const isReasoning = isReasoningModel(modelType);
        if (isReasoning) {
            // outputFormatは実行情報に保存されていないため、デフォルト値を使用
            await waitForReasoningModelCompletion(executionId, 'txt');
            return;
        }
    } catch (error) {
    }

    // 実行ボタンを非活性化（実行中なので）
    setExecutionButtonState(true);

    // 出力エリアに実行中表示を設定
    showProcessingMessage();

    // ストリーミング接続を開始（outputFormatは実行情報に保存されていないため、デフォルト値を使用）
    startStreaming(executionId, 'txt');
}

function stopStreaming() {
    if (executionWorker) {
        executionWorker.postMessage({ type: 'stop' });
        executionWorker.terminate();
        executionWorker = null;
    }
    currentExecutionId = null;
    accumulatedOutput = '';
}

async function handleStreamingComplete(executionId) {
    stopStreaming();

    try {
        const execution = await apiRequest(`/api/user/executions/${executionId}`);

        restoreInputData(execution);
        setExecutionButtonState(false);

        // ステータスバーを更新
        if (PersistentStatusBar.executionId === executionId) {
            if (execution.status === 'success') {
                PersistentStatusBar.markAsCompleted('success');
            } else if (execution.status === 'error') {
                PersistentStatusBar.markAsCompleted('error');
            } else if (execution.status === 'cancelled') {
                PersistentStatusBar.markAsCompleted('cancelled');
            }
        }

        // 結果を表示
        if (execution.status === 'success') {
            // execution.output_formatを優先的に使用（APIレスポンスから取得）
            const finalOutputFormat = execution?.output_format || currentOutputFormat || 'txt';
            displayExecutionResult(execution, executionId, finalOutputFormat !== 'txt' ? finalOutputFormat : null);
        } else {
            displayExecutionError(execution);
        }

        await loadHistory();
        showOutputPanel();
    } catch (error) {
        setExecutionButtonState(false);
    }
}

async function handleStreamingError(executionId, errorMessage, status = 'error') {
    stopStreaming();
    setExecutionButtonState(false);

    // 実行データを取得してエラー情報を表示
    try {
        const execution = await apiRequest(`/api/user/executions/${executionId}`);
        const finalStatus = execution.status || status;
        const finalErrorMessage = execution.error_message || errorMessage || 'エラーが発生しました';

        displayExecutionError({
            status: finalStatus,
            error_message: finalErrorMessage
        });
    } catch (err) {
        displayExecutionError({
            status: status,
            error_message: errorMessage || 'エラーが発生しました'
        });
    }

    loadHistory();
}

async function loadHistory() {
    try {
        const response = await apiRequest('/api/user/executions?limit=100');
        const responseExecutions = response.items || response;
        // 現在のスキルIDでフィルタリング
        allExecutions = responseExecutions.filter(exec => exec.skill_id === parseInt(skillId));
        displayedHistoryCount = 3; // リセット
        renderHistory();
    } catch (error) {
        showAlert('実行履歴の読み込みに失敗しました', 'error');
    }
}

function renderHistory() {
    const container = document.getElementById('history-container');

    if (allExecutions.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: rgba(255, 255, 255, 0.6); padding: 20px;">このスキルの実行履歴がありません</p>';
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
                    const modelDisplay = formatModelDisplay(execution.model_used, execution, skillDetail);

                    return `
                    <tr>
                        <td>${formatDate(execution.executed_at)}</td>
                        <td>${modelDisplay}</td>
                        <td>${execution.output_format ? execution.output_format.toUpperCase() : 'TXT'}</td>
                        <td>${execution.execution_time}ms</td>
                        <td>${execution.tokens_used || '-'}</td>
                        <td>
                            <span style="color: ${execution.status === 'success' ? '#28a745' : execution.status === 'error' ? '#dc3545' : execution.status === 'cancelled' ? '#ffc107' : execution.status === 'pending' || execution.status === 'processing' ? '#7c3aed' : 'rgba(255, 255, 255, 0.6)'}">
                                ${execution.status}
                            </span>
                        </td>
                        <td>
                            <div class="actions">
                                <button onclick="editExecution(${execution.id})" title="編集" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                                    <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #28a745; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m11.239 15.533c-1.045 3.004-1.238 3.451-1.238 3.84 0 .441.385.627.627.627.272 0 1.108-.301 3.829-1.249zm.888-.888 3.22 3.22 6.408-6.401c.163-.163.245-.376.245-.591 0-.213-.082-.427-.245-.591-.58-.579-1.458-1.457-2.039-2.036-.163-.163-.377-.245-.591-.245-.213 0-.428.082-.592.245zm-3.127-.895c0-.402-.356-.75-.75-.75-2.561 0-2.939 0-5.5 0-.394 0-.75.348-.75.75s.356.75.75.75h5.5c.394 0 .75-.348.75-.75zm5-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75z" fill-rule="nonzero"/></svg>
                                </button>
                                <button onclick="showHistoryDetail(${execution.id})" title="詳細" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                                    <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #17a2b8; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m15 17.75c0-.414-.336-.75-.75-.75h-11.5c-.414 0-.75.336-.75.75s.336.75.75.75h11.5c.414 0 .75-.336.75-.75zm7-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75z" fill-rule="nonzero"/></svg>
                                </button>
                            </div>
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

        // 実行時に保存されたenable_deep_thinkを使用（実行時点の状態を保持）
        // 保存されていない場合はスキル情報を取得（後方互換性のため）
        let enableDeepThink = false;
        if (execution.enable_deep_think !== undefined && execution.enable_deep_think !== null) {
            // 実行時に保存された値を使用
            const isDeepThinkEnabled = execution.enable_deep_think === true || execution.enable_deep_think === 1 || execution.enable_deep_think === 'true';
            enableDeepThink = isDeepThinkEnabled && execution.model_used && execution.model_used.startsWith('gemini-');
        } else if (execution.skill_id) {
            // 古い実行履歴の場合、スキル情報を取得
            try {
                const skill = await apiRequest(`/api/user/skills/${execution.skill_id}`);
                const isDeepThinkEnabled = skill.enable_deep_think === true || skill.enable_deep_think === 1 || skill.enable_deep_think === 'true';
                enableDeepThink = isDeepThinkEnabled && execution.model_used && execution.model_used.startsWith('gemini-');
            } catch (e) {
            }
        }

        const modelHtml = formatModelDisplay(execution.model_used, execution, skillDetail);
        const { escapeHtml, buildHtml } = execDetailModal;

        let afterSummaryHtml = '';
        if (execution.workflow_name) {
            afterSummaryHtml = `<div class="exec-detail-meta-block">
                <div class="exec-detail-meta-block-title">ワークフロー</div>
                <div class="exec-detail-meta-line" style="color:#c4b5fd;font-weight:600;">${escapeHtml(execution.workflow_name)}</div>
                ${
                    execution.skill_name
                        ? `<div class="exec-detail-meta-line exec-detail-meta-line--sub">スキル: ${escapeHtml(execution.skill_name)}</div>`
                        : ''
                }
            </div>`;
        }

        const summaryChips = [
            { label: '実行日時', valueHtml: escapeHtml(formatDate(execution.executed_at)) },
        ];
        if (!execution.workflow_name) {
            summaryChips.push({
                label: 'スキル',
                valueHtml: escapeHtml(execution.skill_name || '-'),
            });
        }
        summaryChips.push({ label: 'モデル', valueHtml: modelHtml });

        const detailHTML = buildHtml(execution, {
            formatJSON,
            summaryChips,
            afterSummaryHtml,
            showOutputFormat: true,
            outputCopyId: String(execution.id),
        });

        await Swal.fire({
            title: '実行履歴詳細',
            html: detailHTML,
            width: '880px',
            confirmButtonText: USER_SWAL.btnClose,
            confirmButtonColor: USER_SWAL.primary,
            customClass: {
                popup: 'swal-wide swal-exec-detail',
            },
        });
    } catch (error) {
        await showAlert('実行履歴の詳細取得に失敗しました', 'error');
    }
}

function restoreInputData(execution) {
    // 入力データを入力フィールドに設定
    if (execution.input_data) {
        let inputData;
        try {
            // input_dataが文字列の場合はJSONパース
            if (typeof execution.input_data === 'string') {
                inputData = JSON.parse(execution.input_data);
            } else {
                inputData = execution.input_data;
            }

            // 各入力フィールドに値を設定
            Object.entries(inputData).forEach(([key, value]) => {
                const inputElement = document.querySelector(`#${key}, [name="${key}"]`);
                if (inputElement) {
                    inputElement.value = value || '';
                }
            });
        } catch (e) {
        }
    }

    // 出力形式も復元（ファイル出力が許可されている場合）
    if (execution.output_format) {
        const fileOutputContainer = document.getElementById('file-output-container');
        if (fileOutputContainer && fileOutputContainer.style.display === 'block') {
            const outputFormatSelect = document.getElementById('output-format');
            if (outputFormatSelect) {
                outputFormatSelect.value = execution.output_format;
            }
        }
    }
}

async function restoreExecutionData(executionId) {
    // URLパラメータで指定されたexecution_idのデータを復元
    // executionIdが有効でない場合は処理をスキップ
    if (!executionId || executionId === 'undefined' || executionId === 'null' || executionId === '') {
        return;
    }

    // 数値に変換して有効性をチェック
    const executionIdNum = parseInt(executionId, 10);
    if (isNaN(executionIdNum) || executionIdNum <= 0) {
        return;
    }

    try {
        const execution = await apiRequest(`/api/user/executions/${executionIdNum}`);

        // 現在のスキルIDと一致するか確認
        const currentPromptId = parseInt(skillId);
        if (execution.skill_id !== currentPromptId) {
            return;
        }

        // 入力データを復元（キャンセル時も復元）
        restoreInputData(execution);

        // 実行ボタンの状態を設定（完了済みの場合は有効化）
        if (execution.status === 'success' || execution.status === 'error' || execution.status === 'cancelled') {
            setExecutionButtonState(false);
        } else {
            // 実行中またはpendingの場合は無効化
            setExecutionButtonState(true);
        }

        // キャンセル時は入力データのみ復元し、出力パネルは表示しない
        if (execution.status === 'cancelled') {
            // 出力パネルは表示しない（入力データのみ復元）
            return;
        }

        // 出力パネルを確実に表示（先に表示してから結果を表示）
        showOutputPanel();

        // 結果がある場合は表示
        if (execution.status === 'success') {
            // output_formatをそのまま渡す（displayExecutionResult内で処理）
            displayExecutionResult(execution, executionId, null);
        } else if (execution.status === 'error') {
            displayExecutionError(execution);
        }

        // 出力パネルにスクロール（少し遅延させて確実に表示されるように）
        setTimeout(() => {
            const outputPanel = document.querySelector('.execute-output-panel');
            if (outputPanel) {
                outputPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }, 100);
    } catch (error) {
        showAlert('実行データの復元に失敗しました', 'error');
    }
}

function setExecutionButtonState(isExecuting) {
    const executeBtn = document.getElementById('execute-btn');
    const executeBtnText = document.getElementById('execute-btn-text');
    const executeBtnSpinner = document.getElementById('execute-btn-spinner');
    const form = document.getElementById('execute-form');

    if (executeBtn) {
        executeBtn.disabled = isExecuting;
    }

    if (isExecuting) {
        // 実行中状態
        if (executeBtnText) {
            executeBtnText.textContent = '実行中...';
        }
        if (executeBtnSpinner) {
            executeBtnSpinner.style.display = 'inline';
        }
        // 全ての入力フィールドを無効化
        if (form) {
            const inputFields = form.querySelectorAll('input, textarea, select, button');
            inputFields.forEach(field => {
                if (field !== executeBtn) {
                    field.disabled = true;
                }
            });
        }
    } else {
        // 通常状態
        if (executeBtnText) {
            executeBtnText.textContent = '実行';
        }
        if (executeBtnSpinner) {
            executeBtnSpinner.style.display = 'none';
        }
        // 全ての入力フィールドを再有効化
        if (form) {
            const inputFields = form.querySelectorAll('input, textarea, select, button');
            inputFields.forEach(field => {
                if (field !== executeBtn) {
                    field.disabled = false;
                }
            });
        }
    }
}

async function editExecution(id) {
    try {
        const execution = await apiRequest(`/api/user/executions/${id}`);

        // 入力データを復元
        restoreInputData(execution);

        // 入力パネルにスクロール
        document.querySelector('.execute-input-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });

        showAlert('入力データを読み込みました。必要に応じて編集してから実行ボタンを押してください。', 'success');
    } catch (error) {
        showAlert('実行履歴の読み込みに失敗しました', 'error');
    }
}

function generateInputFields(inputSchema) {
    const container = document.getElementById('input-fields-container');

    // inputSchemaがnullまたは空の場合はシンプルなテキストエリア
    if (!inputSchema || (typeof inputSchema !== 'object')) {
        container.innerHTML = `
            <div class="form-group">
                <label for="input">入力</label>
                <textarea id="input" name="input" rows="10" required></textarea>
            </div>
        `;
        return;
    }

    // 2つの形式に対応:
    // 1. JSON Schema形式: { properties: { fieldName: { type, title, ... } }, required: [...] }
    // 2. シンプル形式: { fieldName: { type, label, required, placeholder, ... } }
    let properties = {};
    let requiredFields = [];

    if (inputSchema.properties) {
        // JSON Schema形式
        properties = inputSchema.properties;
        requiredFields = inputSchema.required || [];
    } else {
        // シンプル形式（直接フィールド名をキーとした辞書）
        properties = inputSchema;
        requiredFields = Object.entries(properties)
            .filter(([_, config]) => config.required === true)
            .map(([fieldName, _]) => fieldName);
    }

    if (Object.keys(properties).length === 0) {
        // プロパティが空の場合はシンプルなテキストエリア
        container.innerHTML = `
            <div class="form-group">
                <label for="input">入力</label>
                <textarea id="input" name="input" rows="10" required></textarea>
            </div>
        `;
        return;
    }

    // スキーマに基づいて入力フィールドを生成
    const fieldsHTML = Object.entries(properties).map(([fieldName, fieldConfig]) => {
        // ラベルの取得（title または label）
        const label = fieldConfig.title || fieldConfig.label || fieldName;
        const description = fieldConfig.description || '';
        const required = requiredFields.includes(fieldName) || fieldConfig.required === true ? 'required' : '';
        const type = fieldConfig.type || 'string';
        const format = fieldConfig.format || '';
        const language = fieldConfig.language || fieldConfig.lang || '';
        const placeholder = fieldConfig.placeholder || description || '';
        const placeholderAttr = placeholder ? `placeholder="${placeholder}"` : '';
        const rows = fieldConfig.rows || (type === 'code' || format === 'code' ? 20 : 10);

        // コードタイプの場合はコード入力用のtextareaを使用
        if (type === 'code' || format === 'code') {
            const langAttr = language ? `data-language="${language}"` : '';
            return `
                <div class="form-group">
                    <label for="${fieldName}">${label}${language ? ` <span style="color: rgba(255, 255, 255, 0.5); font-size: 0.9em;">(${language})</span>` : ''}</label>
                    ${description ? `<small style="color: rgba(255, 255, 255, 0.6);">${description}</small>` : ''}
                    <div style="position: relative;">
                        <textarea
                            id="${fieldName}"
                            name="${fieldName}"
                            rows="${rows}"
                            ${required}
                            ${placeholderAttr}
                            ${langAttr}
                            class="code-input"
                            style="
                                font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', 'source-code-pro', monospace;
                                font-size: 14px;
                                line-height: 1.5;
                                tab-size: 4;
                                white-space: pre;
                                overflow-wrap: normal;
                                overflow-x: auto;
                                background-color: rgba(0, 0, 0, 0.3);
                                border: 1px solid rgba(255, 255, 255, 0.2);
                                border-radius: 4px;
                                padding: 12px;
                                color: rgba(255, 255, 255, 0.9);
                                resize: vertical;
                            "
                        ></textarea>
                    </div>
                </div>
            `;
        }
        // textareaタイプの場合は常にtextareaを使用
        else if (type === 'textarea' || (type === 'string' && (description.includes('長文') || placeholder.length > 50))) {
            return `
                <div class="form-group">
                    <label for="${fieldName}">${label}</label>
                    ${description ? `<small style="color: rgba(255, 255, 255, 0.6);">${description}</small>` : ''}
                    <textarea id="${fieldName}" name="${fieldName}" rows="10" ${required} ${placeholderAttr}></textarea>
                </div>
            `;
        } else if (type === 'string' || type === 'text') {
            return `
                <div class="form-group">
                    <label for="${fieldName}">${label}</label>
                    ${description ? `<small style="color: rgba(255, 255, 255, 0.6);">${description}</small>` : ''}
                    <textarea id="${fieldName}" name="${fieldName}" rows="5" ${required} ${placeholderAttr}></textarea>
                </div>
            `;
        } else if (type === 'number' || type === 'integer') {
            return `
                <div class="form-group">
                    <label for="${fieldName}">${label}</label>
                    ${description ? `<small style="color: rgba(255, 255, 255, 0.6);">${description}</small>` : ''}
                    <input type="number" id="${fieldName}" name="${fieldName}" ${required} ${placeholderAttr}>
                </div>
            `;
        } else {
            return `
                <div class="form-group">
                    <label for="${fieldName}">${label}</label>
                    ${description ? `<small style="color: rgba(255, 255, 255, 0.6);">${description}</small>` : ''}
                    <input type="text" id="${fieldName}" name="${fieldName}" ${required} ${placeholderAttr}>
                </div>
            `;
        }
    }).join('');

    container.innerHTML = fieldsHTML;

    // コード入力フィールドにタブキーの処理を追加
    container.querySelectorAll('.code-input').forEach(textarea => {
        textarea.addEventListener('keydown', function(e) {
            // Tabキーが押された場合、スペース4つに変換
            if (e.key === 'Tab') {
                e.preventDefault();
                const start = this.selectionStart;
                const end = this.selectionEnd;
                const value = this.value;

                // 選択範囲がある場合はインデント/アンインデント
                if (start !== end) {
                    const lines = value.substring(0, start).split('\n');
                    const selectedLines = value.substring(start, end).split('\n');

                    const indentedLines = selectedLines.map(line => {
                        if (e.shiftKey) {
                            // アンインデント（先頭のスペースを削除）
                            return line.replace(/^ {0,4}/, '');
                        } else {
                            // インデント（スペース4つを追加）
                            return '    ' + line;
                        }
                    });

                    const newValue = lines.slice(0, -1).join('\n') +
                                    (lines.length > 1 ? '\n' : '') +
                                    indentedLines.join('\n') +
                                    value.substring(end);

                    this.value = newValue;
                    const firstLineIndent = selectedLines[0].match(/^ */)?.[0].length || 0;
                    const newStart = start + (e.shiftKey ? -Math.min(4, firstLineIndent) : 4);
                    const newEnd = newStart + indentedLines.join('\n').length;
                    this.setSelectionRange(newStart, newEnd);
                } else {
                    // 選択範囲がない場合はスペース4つを挿入
                    this.value = value.substring(0, start) + '    ' + value.substring(end);
                    this.setSelectionRange(start + 4, start + 4);
                }
            }
        });
    });

    // 入力フィールド生成後に高さを同期
    setTimeout(() => {
        syncPanelHeights();
        setupPanelHeightSync();
    }, 50);
}

document.getElementById('execute-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const executeBtn = document.getElementById('execute-btn');
    const executeBtnText = document.getElementById('execute-btn-text');
    const executeBtnSpinner = document.getElementById('execute-btn-spinner');
    const form = e.target;

    // 入力データを収集（フィールドを無効化する前に収集する必要がある）
    const formData = new FormData(e.target);
    const inputData = {};
    for (const [key, value] of formData.entries()) {
        inputData[key] = value;
    }

    // 実行ボタンを無効化
    executeBtn.disabled = true;
    executeBtnText.textContent = '実行中...';

    // スピナーを表示
    if (executeBtnSpinner) {
        executeBtnSpinner.style.display = 'inline';
    }

    // 全ての入力フィールドを無効化
    const inputFields = form.querySelectorAll('input, textarea, select, button');
    inputFields.forEach(field => {
        if (field !== executeBtn) {
            field.disabled = true;
        }
    });

    // 出力形式を取得（ファイル出力が許可されている場合）
    // ファイル出力形式を取得
    let outputFormat = 'txt'; // デフォルト値
    const fileOutputContainer = document.getElementById('file-output-container');
    if (fileOutputContainer && fileOutputContainer.style.display === 'block') {
        const outputFormatSelect = document.getElementById('output-format');
        if (outputFormatSelect) {
            outputFormat = outputFormatSelect.value || 'txt';
        }
    }

    // デバッグログ
    console.log('[Execute] Output format selected:', outputFormat);

    // 既に実行中の場合、キューに追加
    if (PersistentStatusBar.executionId) {
        // キューが満杯かチェック
        if (PersistentStatusBar.executionQueue.length >= PersistentStatusBar.MAX_QUEUE_SIZE) {
            await Swal.fire({
                title: 'キューが満杯です',
                text: `最大${PersistentStatusBar.MAX_QUEUE_SIZE}つまで予約できます。現在の実行が完了するまでお待ちください。`,
                icon: 'warning',
                confirmButtonText: USER_SWAL.btnClose,
                confirmButtonColor: USER_SWAL.primary
            });
            // ボタンを再有効化
            executeBtn.disabled = false;
            executeBtnText.textContent = '実行';
            if (executeBtnSpinner) {
                executeBtnSpinner.style.display = 'none';
            }
            inputFields.forEach(field => {
                if (field !== executeBtn) {
                    field.disabled = false;
                }
            });
            return;
        }

        // キューに追加
        const skillName = document.getElementById('skill-name').textContent;
        PersistentStatusBar.addToQueue({
            skillId: parseInt(skillId),
            skillName: skillName,
            inputData: inputData,
            outputFormat: outputFormat !== 'txt' ? outputFormat : undefined
        });

        // ボタンを再有効化
        executeBtn.disabled = false;
        executeBtnText.textContent = '実行';
        if (executeBtnSpinner) {
            executeBtnSpinner.style.display = 'none';
        }
        inputFields.forEach(field => {
            if (field !== executeBtn) {
                field.disabled = false;
            }
        });
        return;
    }

    try {
        // 以前のストリーミング接続を確実に終了
        stopStreaming();

        // 出力エリアをクリア
        const outputContent = document.getElementById('output-content');
        if (outputContent) {
            outputContent.innerHTML = '';
        }

        // デバッグログ
        console.log('[Execute] Sending request with output_format:', outputFormat);

        const requestBody = {
            skill_id: parseInt(skillId),
            input_data: inputData,
            output_format: outputFormat,
        };

        console.log('[Execute] Request body:', requestBody);

        const initialResponse = await apiRequest('/api/execute', {
            method: 'POST',
            body: JSON.stringify(requestBody)
        });

        const executionId = initialResponse.execution_id;
        executeBtnText.textContent = '実行中...';

        // ドロップアニメーションとステータスバー開始
        const targetDock = document.getElementById('task-dock');

        if (targetDock) {
            // アニメーション用パーティクルの生成
            const startRect = executeBtn.getBoundingClientRect();
            const targetRect = targetDock.getBoundingClientRect();

            const particle = document.createElement('div');
            Object.assign(particle.style, {
                position: 'fixed',
                width: '20px',
                height: '20px',
                backgroundColor: '#007bff',
                borderRadius: '50%',
                zIndex: '9999',
                left: `${startRect.left + startRect.width / 2 - 10}px`,
                top: `${startRect.top + startRect.height / 2 - 10}px`,
                transition: 'all 0.6s cubic-bezier(0.68, -0.55, 0.27, 1.55)',
                boxShadow: '0 0 10px #007bff',
                pointerEvents: 'none'
            });

            document.body.appendChild(particle);

            // アニメーション開始（少し遅延させてDOM反映を待つ）
            requestAnimationFrame(() => {
                particle.style.left = `${targetRect.left + targetRect.width / 2 - 10}px`;
                particle.style.top = `${targetRect.top + targetRect.height / 2 - 10}px`;
                particle.style.transform = 'scale(0.5)';
                particle.style.opacity = '0.5';
            });

            // アニメーション完了時の処理
            setTimeout(() => {
                if (document.body.contains(particle)) {
                    document.body.removeChild(particle);
                }

                // ターゲットのエフェクト（受け取った感）
                targetDock.style.transform = 'scale(1.2)';
                targetDock.style.background = 'rgba(0, 123, 255, 0.4)'; // 一瞬明るく

                setTimeout(() => {
                    targetDock.style.transform = 'scale(1)';
                    // PersistentStatusBar.updateUIで背景色は上書きされるのでここでは戻さない
                }, 200);

                // ステータスバーを開始（ここでアイコンが青くなる）
                const skillName = document.getElementById('skill-name').textContent;
                PersistentStatusBar.start(executionId, parseInt(skillId), skillName);
            }, 600);
        } else {
            // ターゲットが見つからない場合は即座に開始（フォールバック）
            const skillName = document.getElementById('skill-name').textContent;
            PersistentStatusBar.start(executionId, parseInt(skillId), skillName);
        }

        // 2. 出力エリアに実行中表示を設定
        showProcessingMessage();

        // 3. 履歴テーブルに仮の行を追加（即時反映）
        const historyTableBody = document.querySelector('#history-container tbody');
        if (historyTableBody) {
            const now = new Date();
            const tempRow = document.createElement('tr');
            tempRow.id = `exec-row-${executionId}`;
            tempRow.className = 'highlight-new-row'; // CSSでアニメーションなどをつけると良い
            tempRow.innerHTML = `
                <td>${formatDate(now.toISOString())}</td>
                <td>${document.getElementById('skill-model').textContent.replace(/<[^>]*>/g, '')}</td>
                <td>-</td>
                <td>-</td>
                <td><span style="color: orange;">pending</span> <div class="spinner" style="width: 12px; height: 12px; border-width: 1px; display: inline-block; vertical-align: middle;"></div></td>
                <td>
                    <div class="actions">
                        <button disabled class="icon-btn" style="opacity: 0.5; cursor: not-allowed;">
                            <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #ccc;"><path d="m11.239 15.533c-1.045 3.004-1.238 3.451-1.238 3.84 0 .441.385.627.627.627.272 0 1.108-.301 3.829-1.249zm.888-.888 3.22 3.22 6.408-6.401c.163-.163.245-.376.245-.591 0-.213-.082-.427-.245-.591-.58-.579-1.458-1.457-2.039-2.036-.163-.163-.377-.245-.591-.245-.213 0-.428.082-.592.245zm-3.127-.895c0-.402-.356-.75-.75-.75-2.561 0-2.939 0-5.5 0-.394 0-.75.348-.75.75s.356.75.75.75h5.5c.394 0 .75-.348.75-.75zm5-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75z" fill-rule="nonzero"/></svg>
                        </button>
                        <button onclick="showHistoryDetail(${executionId})" title="詳細" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                            <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #17a2b8; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m15 17.75c0-.414-.336-.75-.75-.75h-11.5c-.414 0-.75.336-.75.75s.336.75.75.75h11.5c.414 0 .75-.336.75-.75zm7-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75z" fill-rule="nonzero"/></svg>
                        </button>
                    </div>
                </td>
            `;
            historyTableBody.insertBefore(tempRow, historyTableBody.firstChild);

            // 3件以上なら最後を削除
            if (historyTableBody.children.length > displayedHistoryCount) {
                historyTableBody.removeChild(historyTableBody.lastChild);
            }
        }

        // スキルのモデルタイプを取得して推論モデルかどうかを判定
        const skillDetail = await apiRequest(`/api/user/skills/${skillId}`);
        const modelType = skillDetail.model_type;
        const isReasoning = isReasoningModel(modelType);

        if (isReasoning) {
            // 推論モデルの場合はストリーミング接続を開始せずに、ポーリングで完了を待つ
            await waitForReasoningModelCompletion(executionId, outputFormat);
            return;
        }

        // ストリーミング開始（完了は createWorkerMessageHandler が独立して処理）
        startStreaming(executionId, outputFormat);
        // fire-and-forget: ユーザーは自由にページ遷移可能
        // 完了時の処理:
        //   - SSE接続中: createWorkerMessageHandler → handleStreamingComplete()
        //   - ページ遷移後: PersistentStatusBar.verifyStatus() → executionCompleted event
        //   - ページ復帰時: restoreActiveExecution() → resumeStreaming() or 結果表示

    } catch (error) {
        // POST /api/execute の失敗のみをキャッチ（SSEエラーは handleStreamingError が処理）
        stopStreaming();
        setExecutionButtonState(false);

        showAlert('実行に失敗しました: ' + error.message, 'error');
        document.getElementById('output-content').innerHTML =
            `<div style="color: #dc3545; text-align: center; padding: 20px;">エラー: ${escapeHtml(error.message.trim())}</div>`;
    }
});

// 出力をコピーする関数
async function copyOutput() {
    const outputContent = document.getElementById('output-content');
    const text = outputContent.textContent || outputContent.innerText;

    if (!text || text === '実行ボタンを押すと結果がここに表示されます') {
        showAlert('コピーする内容がありません', 'warning');
        return;
    }

    try {
        await navigator.clipboard.writeText(text);
        showAlert('出力をクリップボードにコピーしました', 'success');

        // ボタンの視覚的フィードバック
        const copyBtn = document.getElementById('copy-output-btn');
        const originalOpacity = copyBtn.style.opacity;
        copyBtn.style.opacity = '1';
        setTimeout(() => {
            copyBtn.style.opacity = originalOpacity;
        }, 500);
    } catch (error) {
        // フォールバック: テキストエリアを使用
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showAlert('出力をクリップボードにコピーしました', 'success');
        } catch (err) {
            showAlert('コピーに失敗しました', 'error');
        }
        document.body.removeChild(textarea);
    }
}

// 実行キャンセルイベントのリスナー
window.addEventListener('executionCancelled', async (event) => {
    const { executionId } = event.detail;
    if (!executionId) return;

    // ストリーミングを停止
    stopStreaming();

    // 実行データを取得して入力データを復元（出力は復元しない）
    try {
        const execution = await apiRequest(`/api/user/executions/${executionId}`);
        // 入力データを復元
        restoreInputData(execution);
    } catch (error) {
    }

    // 実行ボタンの状態をリセット
    setExecutionButtonState(false);

    // 出力エリアにキャンセルメッセージを表示（出力は復元しない）
    const outputContent = document.getElementById('output-content');
    if (outputContent) {
        outputContent.innerHTML = '<div style="color: #ffc107; text-align: center; padding: 20px; font-weight: 500;">実行がキャンセルされました</div>';
    }

    // 出力パネルを表示
    showOutputPanel();

    // 実行履歴を再読み込み
    if (typeof loadHistory === 'function') {
        loadHistory();
    }
});

// 実行完了イベントのリスナー（他のページから戻ってきた時や、ページ読み込み後に完了した場合）
window.addEventListener('executionCompleted', async (event) => {
    const { execution, executionId } = event.detail;
    if (!execution || !executionId) return;

    // 現在のスキルIDと一致するか確認
    const currentPromptId = parseInt(skillId);
    if (execution.skill_id !== currentPromptId) return;

    // 既に処理済みかチェック（重複実行を防ぐ）
    if (execution.status === 'success') {
        // 入力データを復元
        restoreInputData(execution);

        // 実行ボタンを再有効化（完了したので）
        setExecutionButtonState(false);

        // 結果を表示
        // output_formatが保存されている場合は使用、ない場合はデフォルト値'txt'を使用
        const outputFormat = execution.output_format || 'txt';
        displayExecutionResult(execution, executionId, outputFormat !== 'txt' ? outputFormat : null);

        // 実行履歴を再読み込み
        loadHistory();
    } else if (execution.status === 'error' || execution.status === 'cancelled') {
        // エラーまたはキャンセル済み
        restoreInputData(execution);

        // 実行ボタンを再有効化（エラー/キャンセルなので）
        setExecutionButtonState(false);

        displayExecutionError(execution);
        loadHistory();
    }
});

// キューからタスクを実行する関数（グローバルスコープに公開）
window.executeQueuedTask = async function(taskData) {
    try {
        const initialResponse = await apiRequest('/api/execute', {
            method: 'POST',
            body: JSON.stringify({
                skill_id: parseInt(taskData.skillId),
                input_data: taskData.inputData,
                output_format: taskData.outputFormat !== 'txt' ? taskData.outputFormat : undefined
            })
        });

        const executionId = initialResponse.execution_id;
        const skillName = taskData.skillName || document.getElementById('skill-name')?.textContent || '実行中...';

        // ステータスバーを開始
        PersistentStatusBar.start(executionId, parseInt(taskData.skillId), skillName);

        // 以前のストリーミング接続を確実に終了
        stopStreaming();

        // 出力エリアに実行中表示を設定
        showProcessingMessage();

        // ストリーミング開始（完了は createWorkerMessageHandler が独立して処理）
        const outputFormat = taskData.outputFormat || 'txt';
        startStreaming(executionId, outputFormat);
        // fire-and-forget

    } catch (error) {
        setExecutionButtonState(false);
        displayExecutionError({ status: 'error', error_message: error.message });
        loadHistory();
    }
};

// getQueryParam は user-common.js で定義済み

// モバイルデバイスかどうかを判定する関数
function isMobileDevice() {
    return window.innerWidth <= 768;
}

// execute-input-panelの高さに合わせてexecute-output-panelの高さを調整する関数
function syncPanelHeights() {
    // モバイルデバイスの場合は高さ同期を行わない
    if (isMobileDevice()) {
        return;
    }

    const inputPanel = document.querySelector('.execute-input-panel');
    const outputPanel = document.querySelector('.execute-output-panel');

    if (inputPanel && outputPanel) {
        // input-panelの実際の高さを取得
        const inputHeight = inputPanel.offsetHeight;
        // output-panelの高さをinput-panelに合わせる
        outputPanel.style.height = `${inputHeight}px`;
    }
}

// ResizeObserverでinput-panelの高さ変更を監視
let panelResizeObserver = null;
function setupPanelHeightSync() {
    // モバイルデバイスの場合は高さ同期を設定しない
    if (isMobileDevice()) {
        // 既存のオブザーバーがあれば切断
        if (panelResizeObserver) {
            panelResizeObserver.disconnect();
            panelResizeObserver = null;
        }
        return;
    }

    const inputPanel = document.querySelector('.execute-input-panel');
    if (inputPanel && typeof ResizeObserver !== 'undefined') {
        // 既存のオブザーバーがあれば切断
        if (panelResizeObserver) {
            panelResizeObserver.disconnect();
        }

        // 新しいResizeObserverを作成
        panelResizeObserver = new ResizeObserver(() => {
            syncPanelHeights();
        });

        // input-panelとその子要素を監視
        panelResizeObserver.observe(inputPanel);
        const inputFieldsContainer = inputPanel.querySelector('#input-fields-container');
        if (inputFieldsContainer) {
            panelResizeObserver.observe(inputFieldsContainer);
        }

        // テキストエリアのリサイズも監視
        inputPanel.querySelectorAll('textarea').forEach(textarea => {
            panelResizeObserver.observe(textarea);
        });
    }
}


// ページ読み込み時に実行
(async () => {
    initUserLayout('');  // execute.html はナビでactive無し
    await checkAuth();
    loadPromptDetail();

    // localStorageにpending_queue_taskがある場合、キューからタスクを実行
    const pendingTaskData = localStorage.getItem('pending_queue_task');
    if (pendingTaskData) {
        try {
            const taskData = JSON.parse(pendingTaskData);
            // localStorageから削除
            localStorage.removeItem('pending_queue_task');
            // キューからタスクを実行
            await window.executeQueuedTask(taskData);
        } catch (error) {
            // エラー時もlocalStorageから削除
            localStorage.removeItem('pending_queue_task');
        }
    }

    // 高さを同期（DOMが完全に読み込まれた後、デスクトップのみ）
    setTimeout(() => {
        syncPanelHeights();
        setupPanelHeightSync();
    }, 100);

    // リサイズ時にも高さを同期（デスクトップのみ）
    window.addEventListener('resize', () => {
        // リサイズ時にモバイル/デスクトップの切り替えがあった場合に備えて、ResizeObserverを再設定
        setupPanelHeightSync();
        syncPanelHeights();
    });

    // MutationObserverでDOMの変更を監視して高さを同期（デスクトップのみ）
    const observer = new MutationObserver(() => {
        if (!isMobileDevice()) {
            syncPanelHeights();
            // 新しいテキストエリアが追加された場合に備えて、ResizeObserverを再設定
            setTimeout(() => {
                setupPanelHeightSync();
            }, 50);
        }
    });

    const inputPanel = document.querySelector('.execute-input-panel');
    if (inputPanel) {
        observer.observe(inputPanel, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['style', 'class']
        });
    }
})();
