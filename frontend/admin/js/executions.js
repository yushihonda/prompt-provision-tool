// 管理者 実行ログ画面 JavaScript

let executions = [];
let currentPage = 1;
const itemsPerPage = 10;
let totalItems = 0;

async function loadExecutions(page = 1) {
    try {
        const skip = (page - 1) * itemsPerPage;
        const response = await apiRequest(`/api/admin/executions?skip=${skip}&limit=${itemsPerPage}`);

        executions = response.items || response;
        totalItems = response.total !== undefined ? response.total : (executions.length === itemsPerPage ? page * itemsPerPage + 1 : page * itemsPerPage);

        currentPage = page;
        renderExecutions();
        renderPagination();
    } catch (error) {
        showAlert('実行ログの読み込みに失敗しました', 'error');
        console.error('Load executions error:', error);
    }
}

function renderExecutions() {
    const tbody = document.getElementById('executions-tbody');

    if (executions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: rgba(255, 255, 255, 0.6);">実行ログがありません</td></tr>';
        return;
    }

    tbody.innerHTML = executions.map(execution => {
        let modelDisplay = execution.model_used;

        // Thinkingモデルの場合はサフィックスを削除して表示
        let isThinkingModel = false;
        if (modelDisplay && modelDisplay.includes('thinking')) {
            modelDisplay = modelDisplay.replace('-thinking', '');
            isThinkingModel = true;
        }

        // Deep Thinkモデルの場合はサフィックスを削除して表示
        let isDeepThinkModel = false;
        if (modelDisplay && modelDisplay.includes('deep-think')) {
            modelDisplay = modelDisplay.replace('-deep-think', '');
            isDeepThinkModel = true;
        }

        // Proモデルの場合は「-pro」を削除してProバッジを追加
        const isProModel = execution.model_used && (execution.model_used.includes('-pro') || execution.model_used.endsWith('-pro'));
        if (isProModel) {
            // 「-pro」を削除（「-pro-」の場合は「-pro」のみ削除、「-pro」で終わる場合は「-pro」を削除）
            modelDisplay = modelDisplay.replace(/-pro(?=-|$)/g, '');
            modelDisplay += `<span class="pro-badge">Pro</span>`;
        }

        // 「-preview」を削除
        modelDisplay = modelDisplay.replace(/-preview/g, '');

        // Deep Thinkバッジを追加（モデル名にdeep-thinkが含まれる場合、またはenable_deep_thinkが有効でGeminiモデルの場合）
        const isDeepThinkEnabled = execution.enable_deep_think === true || execution.enable_deep_think === 1 || execution.enable_deep_think === 'true';
        const enableDeepThink = isDeepThinkEnabled && execution.model_used && execution.model_used.startsWith('gemini-');
        if (isDeepThinkModel || enableDeepThink) {
            modelDisplay += `<span class="deep-think-badge">Deep Think</span>`;
        }

        // Thinkingバッジを追加（GPT-5.1 Thinkingの場合）
        if (isThinkingModel || execution.model_used === 'gpt-5.1-thinking') {
            modelDisplay += `<span class="thinking-badge">Thinking</span>`;
        }

        // NEWバッジを追加
        if (execution.model_used === 'gpt-5.1' || execution.model_used === 'gemini-3-pro-preview' || execution.model_used === 'gemini-3-pro-preview-deep-think') {
            modelDisplay += `<span class="new-badge">NEW</span>`;
        } else if (isThinkingModel || execution.model_used === 'gpt-5.1-thinking') {
            modelDisplay += `<span class="new-badge">NEW</span>`;
        }
        return `
        <tr>
            <td>${execution.id}</td>
            <td>${formatDate(execution.executed_at)}</td>
            <td>${execution.account_id}</td>
            <td>${execution.prompt_name || '-'}</td>
            <td>${modelDisplay}</td>
            <td>${execution.execution_time}ms</td>
            <td>${execution.tokens_used || '-'}</td>
            <td>
                <span style="color: ${execution.status === 'success' ? '#28a745' : execution.status === 'error' ? '#dc3545' : execution.status === 'cancelled' ? '#ffc107' : execution.status === 'pending' || execution.status === 'processing' ? '#7c3aed' : 'rgba(255, 255, 255, 0.6)'}">
                    ${execution.status}
                </span>
            </td>
            <td>
                <button onclick="showDetail(${execution.id})" title="詳細" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                    <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #17a2b8; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m15 17.75c0-.414-.336-.75-.75-.75h-11.5c-.414 0-.75.336-.75.75s.336.75.75.75h11.5c.414 0 .75-.336.75-.75zm7-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75zm0-4c0-.414-.336-.75-.75-.75h-18.5c-.414 0-.75.336-.75.75s.336.75.75.75h18.5c.414 0 .75-.336.75-.75z" fill-rule="nonzero"/></svg>
                </button>
            </td>
        </tr>
        `;
    }).join('');
}

function renderPagination() {
    const container = document.getElementById('pagination-container');
    const totalPages = Math.ceil(totalItems / itemsPerPage);

    if (totalPages <= 1) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';

    let html = `
        <button onclick="loadExecutions(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>前へ</button>
    `;

    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, startPage + 4);

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="page-number ${i === currentPage ? 'active' : ''}" onclick="loadExecutions(${i})">${i}</button>`;
    }

    html += `
        <span class="page-info">${currentPage} / ${totalPages}</span>
        <button onclick="loadExecutions(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>次へ</button>
    `;

    container.innerHTML = html;
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

async function showDetail(id) {
    const execution = executions.find(e => e.id === id);
    if (!execution) return;

    // 実行時に保存されたenable_deep_thinkを使用（実行時点の状態を保持）
    // 保存されていない場合はプロンプト情報を取得（後方互換性のため）
    let enableDeepThink = false;
    if (execution.enable_deep_think !== undefined && execution.enable_deep_think !== null) {
        // 実行時に保存された値を使用
        const isDeepThinkEnabled = execution.enable_deep_think === true || execution.enable_deep_think === 1 || execution.enable_deep_think === 'true';
        enableDeepThink = isDeepThinkEnabled && execution.model_used && execution.model_used.startsWith('gemini-');
    } else if (execution.prompt_id) {
        // 古い実行履歴の場合、プロンプト情報を取得
        try {
            const prompt = await apiRequest(`/api/admin/prompts/${execution.prompt_id}`);
            const isDeepThinkEnabled = prompt.enable_deep_think === true || prompt.enable_deep_think === 1 || prompt.enable_deep_think === 'true';
            enableDeepThink = isDeepThinkEnabled && execution.model_used && execution.model_used.startsWith('gemini-');
        } catch (e) {
            console.error('Failed to load prompt detail:', e);
        }
    }

    const detailHTML = `
        <div style="text-align: left; max-height: 70vh; overflow-y: auto;">
            <div style="margin-bottom: 15px;">
                <strong>実行日時:</strong><br>
                <span>${formatDate(execution.executed_at)}</span>
            </div>
            <div style="margin-bottom: 15px;">
                <strong>アカウントID:</strong><br>
                <span>${execution.account_id}</span>
            </div>
            <div style="margin-bottom: 15px;">
                <strong>プロンプト:</strong><br>
                <span>${execution.prompt_name || '-'}</span>
            </div>
            <div style="margin-bottom: 15px;">
                <strong>使用モデル:</strong><br>
                <span>${(() => {
                    let modelDisplay = execution.model_used;

                    // Thinkingモデルの場合はサフィックスを削除して表示
                    let isThinkingModel = false;
                    if (modelDisplay && modelDisplay.includes('thinking')) {
                        modelDisplay = modelDisplay.replace('-thinking', '');
                        isThinkingModel = true;
                    }

                    // Deep Thinkモデルの場合はサフィックスを削除して表示
                    let isDeepThinkModel = false;
                    if (modelDisplay && modelDisplay.includes('deep-think')) {
                        modelDisplay = modelDisplay.replace('-deep-think', '');
                        isDeepThinkModel = true;
                    }

                    // Proモデルの場合は「-pro」を削除してProバッジを追加
                    const isProModel = execution.model_used && (execution.model_used.includes('-pro') || execution.model_used.endsWith('-pro'));
                    if (isProModel) {
                        // 「-pro」を削除（「-pro-」の場合は「-pro」のみ削除、「-pro」で終わる場合は「-pro」を削除）
                        modelDisplay = modelDisplay.replace(/-pro(?=-|$)/g, '');
                        modelDisplay += `<span class="pro-badge">Pro</span>`;
                    }

                    // 「-preview」を削除
                    modelDisplay = modelDisplay.replace(/-preview/g, '');

                    // Deep Thinkバッジを追加（モデル名にdeep-thinkが含まれる場合、またはenableDeepThinkが有効な場合）
                    if (isDeepThinkModel || enableDeepThink) {
                        modelDisplay += `<span class="deep-think-badge">Deep Think</span>`;
                    }

                    // Thinkingバッジを追加（GPT-5.1 Thinkingの場合）
                    if (isThinkingModel || execution.model_used === 'gpt-5.1-thinking') {
                        modelDisplay += `<span class="thinking-badge">Thinking</span>`;
                    }

                    // NEWバッジを追加
                    if (execution.model_used === 'gpt-5.1' || execution.model_used === 'gemini-3-pro-preview' || execution.model_used === 'gemini-3-pro-preview-deep-think') {
                        modelDisplay += `<span class="new-badge">NEW</span>`;
                    } else if (isThinkingModel || execution.model_used === 'gpt-5.1-thinking') {
                        modelDisplay += `<span class="new-badge">NEW</span>`;
                    }

                    return modelDisplay;
                })()}</span>
            </div>
            <div style="margin-bottom: 15px;">
                <strong>入力データ:</strong><br>
                <div style="background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.1); padding: 10px; border-radius: 8px; margin-top: 5px; max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word; color: rgba(255, 255, 255, 0.9);">${formatJSON(execution.input_data)}</div>
            </div>
            <div style="margin-bottom: 15px;">
                <strong>出力データ:</strong><br>
                <div style="background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.1); padding: 10px; border-radius: 8px; margin-top: 5px; max-height: 300px; overflow-y: auto; white-space: pre-wrap; word-wrap: break-word; color: rgba(255, 255, 255, 0.9);">${execution.output_data || '-'}</div>
            </div>
            <div style="margin-bottom: 15px;">
                <strong>実行時間:</strong><br>
                <span>${execution.execution_time}ms</span>
            </div>
            <div style="margin-bottom: 15px;">
                <strong>使用トークン数:</strong><br>
                <span>${execution.tokens_used || '-'}</span>
            </div>
            <div style="margin-bottom: 15px;">
                <strong>ステータス:</strong><br>
                <span style="color: ${execution.status === 'success' ? '#28a745' : execution.status === 'error' ? '#dc3545' : execution.status === 'cancelled' ? '#ffc107' : execution.status === 'pending' || execution.status === 'processing' ? '#7c3aed' : 'rgba(255, 255, 255, 0.6)'}">
                    ${execution.status}
                </span>
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
}

// ページ読み込み時に実行
(async () => {
    await checkAuth();
    loadExecutions(1);
})();
