// 管理者 プロンプト一覧画面 JavaScript

let prompts = [];
let currentPage = 1;
const itemsPerPage = 10;
let totalItems = 0;

// ワークフロー一覧用
let workflows = [];
let wfCurrentPage = 1;
const wfItemsPerPage = 10;
let wfTotalItems = 0;

async function loadPrompts(page = 1) {
    try {
        const skip = (page - 1) * itemsPerPage;
        const response = await apiRequest(`/api/admin/prompts?skip=${skip}&limit=${itemsPerPage}`);

        prompts = response.items || response;
        totalItems = response.total !== undefined ? response.total : (prompts.length === itemsPerPage ? page * itemsPerPage + 1 : page * itemsPerPage);

        currentPage = page;
        renderPrompts();
        renderPagination();
    } catch (error) {
        showAlert('プロンプトの読み込みに失敗しました', 'error');
        console.error('Load prompts error:', error);
    }
}

function renderPrompts() {
    const tbody = document.getElementById('prompts-tbody');

    if (prompts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: rgba(255, 255, 255, 0.6);">プロンプトがまだ登録されていません</td></tr>';
        return;
    }

    tbody.innerHTML = prompts.map(prompt => {
        let modelDisplay = prompt.model_type;

        // Deep Thinkモデルの場合はサフィックスを削除して表示
        let isDeepThinkModel = false;
        if (modelDisplay && modelDisplay.includes('deep-think')) {
            modelDisplay = modelDisplay.replace('-deep-think', '');
            isDeepThinkModel = true;
        }

        // Thinkingモデルの場合はサフィックスを削除して表示
        let isThinkingModel = false;
        if (modelDisplay && modelDisplay.includes('thinking')) {
            modelDisplay = modelDisplay.replace('-thinking', '');
            isThinkingModel = true;
        }

        // Proモデルの場合は「-pro」を削除してProバッジを追加
        const isProModel = prompt.model_type && (prompt.model_type.includes('-pro') || prompt.model_type.endsWith('-pro'));
        if (isProModel) {
            // 「-pro」を削除（「-pro-」の場合は「-pro」のみ削除、「-pro」で終わる場合は「-pro」を削除）
            modelDisplay = modelDisplay.replace(/-pro(?=-|$)/g, '');
            modelDisplay += `<span class="pro-badge">Pro</span>`;
        }

        // 「-preview」を削除
        modelDisplay = modelDisplay.replace(/-preview/g, '');

        // Deep Thinkバッジを追加（Geminiモデルで有効な場合）
        const isDeepThinkEnabled = isDeepThinkModel || (prompt.enable_deep_think === true || prompt.enable_deep_think === 1 || prompt.enable_deep_think === 'true');

        if (isDeepThinkEnabled && prompt.model_type && prompt.model_type.startsWith('gemini-')) {
            modelDisplay += `<span class="deep-think-badge">Deep Think</span>`;
        }

        // Thinkingバッジを追加（GPT-5.1 Thinkingの場合）
        if (isThinkingModel || prompt.model_type === 'gpt-5.1-thinking') {
            modelDisplay += `<span class="thinking-badge">Thinking</span>`;
        }

        // NEWバッジを追加（gpt-5.2系のみ）
        if (prompt.model_type === 'gpt-5.2' || prompt.model_type === 'gpt-5.2-pro' || prompt.model_type === 'gpt-5.2-thinking') {
            modelDisplay += `<span class="new-badge">NEW</span>`;
        }
        return `
        <tr>
            <td>${prompt.id}</td>
            <td>${prompt.name}</td>
            <td>${prompt.description || '説明なし'}</td>
            <td>${modelDisplay}</td>
            <td>
                <div style="display: flex; align-items: center; gap: 6px;">
                    ${prompt.is_active ? `
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#28a745" style="flex-shrink: 0;">
                            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                        </svg>
                    ` : `
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#dc3545" style="flex-shrink: 0;">
                            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                        </svg>
                    `}
                    <span style="color: ${prompt.is_active ? '#28a745' : '#dc3545'}; font-weight: ${prompt.is_active ? 'bold' : 'normal'};">${prompt.is_active ? '有効' : '無効'}</span>
                </div>
            </td>
            <td>
                <div style="display: flex; flex-direction: column; gap: 4px;">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        ${prompt.allows_file_output ? `
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#28a745" style="flex-shrink: 0;">
                            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                        </svg>
                    ` : `
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#dc3545" style="flex-shrink: 0;">
                            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                        </svg>
                    `}
                        <span style="color: ${prompt.allows_file_output ? '#28a745' : '#dc3545'}; font-weight: ${prompt.allows_file_output ? 'bold' : 'normal'};">ファイル出力: ${prompt.allows_file_output ? '許可' : '不可'}</span>
                    </div>
                    <div style="display: flex; flex-wrap: wrap; gap: 4px 8px; font-size: 11px; color: rgba(255,255,255,0.8);">
                        <span>web_search: ${prompt.enable_web_search ? 'ON' : 'OFF'}</span>
                        <span>code_interpreter: ${prompt.enable_code_interpreter ? 'ON' : 'OFF'}</span>
                        <span>file_search: ${prompt.enable_file_search ? 'ON' : 'OFF'}</span>
                    </div>
                </div>
            </td>
            <td>
                <div class="actions">
                    <button onclick="viewPromptContent(${prompt.id})" title="プロンプトを表示" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #9c27b0; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m15.985 17.031c-1.479 1.238-3.384 1.985-5.461 1.985-4.697 0-8.509-3.812-8.509-8.508s3.812-8.508 8.509-8.508c4.695 0 8.508 3.812 8.508 8.508 0 2.078-.747 3.984-1.985 5.461l4.749 4.75c.146.146.219.338.219.531 0 .587-.537.75-.75.75-.192 0-.384-.073-.531-.22zm-5.461-13.53c-3.868 0-7.007 3.14-7.007 7.007s3.139 7.007 7.007 7.007c3.866 0 7.007-3.14 7.007-7.007s-3.141-7.007-7.007-7.007zm.741 8.499h-4.5c-.414 0-.75.336-.75.75s.336.75.75.75h4.5c.414 0 .75-.336.75-.75s-.336-.75-.75-.75zm3-2.5h-7.5c-.414 0-.75.336-.75.75s.336.75.75.75h7.5c.414 0 .75-.336.75-.75s-.336-.75-.75-.75zm0-2.5h-7.5c-.414 0-.75.336-.75.75s.336.75.75.75h7.5c.414 0 .75-.336.75-.75s-.336-.75-.75-.75z" fill-rule="nonzero"/></svg>
                    </button>
                    <button onclick="editPrompt(${prompt.id})" title="編集" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #28a745; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m11.239 15.533c-1.045 3.004-1.238 3.451-1.238 3.84 0 .441.385.627.627.627.272 0 1.108-.301 3.829-1.249zm.888-.888 3.22 3.22 6.408-6.401c.163-.163.245-.376.245-.591 0-.213-.082-.427-.245-.591-.58-.579-1.458-1.457-2.039-2.036-.163-.163-.377-.245-.591-.245-.213 0-.428.082-.592.245zm-3.127-.895c0-.402-.356-.75-.75-.75-2.561 0-2.939 0-5.5 0-.394 0-.75.348-.75.75s.356.75.75.75h5.5c.394 0 .75-.348.75-.75zm5-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75zm0-3c0-.402-.356-.75-.75-.75-2.561 0-7.939 0-10.5 0-.394 0-.75.348-.75.75s.356.75.75.75h10.5c.394 0 .75-.348.75-.75z" fill-rule="nonzero"/></svg>
                    </button>
                    <button onclick="deletePrompt(${prompt.id})" title="削除" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="width: 24px; height: 24px; fill: #dc3545; transition: fill 0.2s ease, transform 0.2s ease;"><path d="m20.015 6.506h-16v14.423c0 .591.448 1.071 1 1.071h14c.552 0 1-.48 1-1.071 0-3.905 0-14.423 0-14.423zm-5.75 2.494c.414 0 .75.336.75.75v8.5c0 .414-.336.75-.75.75s-.75-.336-.75-.75v-8.5c0-.414.336-.75.75-.75zm-4.5 0c.414 0 .75.336.75.75v8.5c0 .414-.336.75-.75.75s-.75-.336-.75-.75v-8.5c0-.414.336-.75.75-.75zm-.75-5v-1c0-.535.474-1 1-1h4c.526 0 1 .465 1 1v1h5.254c.412 0 .746.335.746.747s-.334.747-.746.747h-16.507c-.413 0-.747-.335-.747-.747s.334-.747.747-.747zm4.5 0v-.5h-3v.5z" fill-rule="nonzero"/></svg>
                    </button>
                    <button onclick="manageWorkflowsForPrompt(${prompt.id})" title="ワークフロー/Skillを編集" class="icon-btn" style="display: flex; align-items: center; justify-content: center; padding: 8px; background: none; border: none; cursor: pointer; transition: transform 0.2s ease, opacity 0.2s ease;">
                        <img src="../img/iconmonstr-apps-filled.svg" alt="WF" style="width: 20px; height: 20px; filter: invert(58%) sepia(86%) saturate(470%) hue-rotate(210deg) brightness(95%) contrast(90%);">
                    </button>
                </div>
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
        <button onclick="loadPrompts(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>前へ</button>
    `;

    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, startPage + 4);

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="page-number ${i === currentPage ? 'active' : ''}" onclick="loadPrompts(${i})">${i}</button>`;
    }

    html += `
        <span class="page-info">${currentPage} / ${totalPages}</span>
        <button onclick="loadPrompts(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>次へ</button>
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

async function showCreateModal() {
    const { value: formValues } = await Swal.fire({
        title: '新しいプロンプト',
        html: `
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">プロンプト名 <span style="color: #ff6b6b;">*</span></label>
                <input id="swal-prompt-name" class="swal2-input" placeholder="例: 記事要約プロンプト" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">説明</label>
                <textarea id="swal-prompt-description" class="swal2-textarea" placeholder="このプロンプトの用途や説明を入力してください" style="min-height: 80px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;"></textarea>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">AIモデル <span style="color: #ff6b6b;">*</span></label>
                <select id="swal-prompt-model" class="swal2-select" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <optgroup label="OpenAI">
                        <option value="gpt-5.2" selected>GPT-5.2 NEW</option>
                        <option value="gpt-5.2-pro">GPT-5.2 Pro NEW</option>
                        <option value="gpt-5.2-thinking">GPT-5.2 Thinking NEW</option>
                        <option value="gpt-5.1">GPT-5.1</option>
                        <option value="gpt-5.1-thinking">GPT-5.1 Thinking</option>
                        <option value="gpt-5-pro">GPT-5 Pro</option>
                        <option value="gpt-5">GPT-5</option>
                        <option value="gpt-4o-mini">GPT-4o Mini</option>
                    </optgroup>
                    <optgroup label="Gemini">
                        <option value="gemini-3-pro-preview">Gemini 3.0 Pro NEW</option>
                        <option value="gemini-3-pro-preview-deep-think">Gemini 3.0 Pro Deep Think NEW</option>
                        <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                        <option value="gemini-2.5-pro-deep-think">Gemini 2.5 Pro Deep Think</option>
                        <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
                        <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
                    </optgroup>
                </select>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">プロンプト内容 <span style="color: #ff6b6b;">*</span></label>
                <textarea id="swal-prompt-content" class="swal2-textarea" placeholder="プロンプトを入力してください。&#10;変数は {{variable_name}} の形式で記述できます。&#10;例: {{article_text}} を要約してください。" required style="min-height: 200px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;"></textarea>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">変数の例: {{article_text}}, {{input}}, {{query}} など</small>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">入力スキーマ（JSON形式、オプション）</label>
                <textarea id="swal-prompt-schema" class="swal2-textarea" placeholder='{"field_name": {"type": "string", "label": "フィールドラベル", "required": true}}' style="min-height: 120px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%; font-family: monospace; font-size: 12px;"></textarea>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">ユーザー入力フィールドの定義をJSON形式で指定します（省略可能）</small>
            </div>
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-prompt-is-active" checked style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">有効にする</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このプロンプトが有効になり、ユーザーが使用できるようになります</small>
            </div>
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-prompt-allows-file-output" style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">ファイル出力を許可する</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このプロンプトの実行結果をCSV、PDF、DOCXなどの形式で出力できます</small>
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-enable-web-search" style="margin-right: 6px; width: 16px; height: 16px; cursor: pointer;">
                    <span style="font-size: 13px; color: rgba(255, 255, 255, 0.9);">web_search を許可</span>
                </label>
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-enable-code-interpreter" style="margin-right: 6px; width: 16px; height: 16px; cursor: pointer;">
                    <span style="font-size: 13px; color: rgba(255, 255, 255, 0.9);">code_interpreter を許可</span>
                </label>
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-enable-file-search" style="margin-right: 6px; width: 16px; height: 16px; cursor: pointer;">
                    <span style="font-size: 13px; color: rgba(255, 255, 255, 0.9);">file_search を許可</span>
                </label>
            </div>
        `,
        focusConfirm: false,
        showCancelButton: true,
        confirmButtonText: '保存',
        cancelButtonText: 'キャンセル',
        confirmButtonColor: '#28a745',
        cancelButtonColor: '#6c757d',
        width: '800px',
        customClass: {
            popup: 'swal-no-scroll',
            htmlContainer: 'swal-no-scroll'
        },
        didOpen: () => {
            // チェックボックスロジックは削除されました
        },
        preConfirm: () => {
            const name = document.getElementById('swal-prompt-name').value.trim();
            const description = document.getElementById('swal-prompt-description').value.trim();
            const model = document.getElementById('swal-prompt-model').value;
            const content = document.getElementById('swal-prompt-content').value.trim();
            const schemaText = document.getElementById('swal-prompt-schema').value.trim();
            const isActive = document.getElementById('swal-prompt-is-active').checked;
            const allowsFileOutput = document.getElementById('swal-prompt-allows-file-output').checked;
            const enableWebSearch = document.getElementById('swal-enable-web-search').checked;
            const enableCodeInterpreter = document.getElementById('swal-enable-code-interpreter').checked;
            const enableFileSearch = document.getElementById('swal-enable-file-search').checked;

            // モデル名からDeep Think設定を判定
            const enableDeepThink = model.includes('deep-think');

            if (!name) {
                Swal.showValidationMessage('プロンプト名は必須です');
                return false;
            }
            if (!content) {
                Swal.showValidationMessage('プロンプト内容は必須です');
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
                enableWebSearch,
                enableCodeInterpreter,
                enableFileSearch
            };
        }
    });

    if (formValues) {
        await savePrompt(null, formValues);
    }
}

async function editPrompt(id) {
    const prompt = prompts.find(p => p.id === id);
    if (!prompt) return;

    // プロンプト内容を取得
    let promptContent = '';
    try {
        const data = await apiRequest(`/api/admin/prompts/${id}/content`);
        promptContent = data.content;
    } catch (error) {
        await showAlert('プロンプト内容の読み込みに失敗しました', 'error');
        return;
    }

    const { value: formValues } = await Swal.fire({
        title: 'プロンプトを編集',
        html: `
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">プロンプト名 <span style="color: #ff6b6b;">*</span></label>
                <input id="swal-prompt-name" class="swal2-input" placeholder="例: 記事要約プロンプト" value="${prompt.name.replace(/"/g, '&quot;')}" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">説明</label>
                <textarea id="swal-prompt-description" class="swal2-textarea" placeholder="このプロンプトの用途や説明を入力してください" style="min-height: 80px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;">${(prompt.description || '').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</textarea>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">AIモデル <span style="color: #ff6b6b;">*</span></label>
                <select id="swal-prompt-model" class="swal2-select" required style="width: 100%; margin-top: 0; box-sizing: border-box; max-width: 100%;">
                    <optgroup label="OpenAI">
                        <option value="gpt-5.2" ${prompt.model_type === 'gpt-5.2' ? 'selected' : ''}>GPT-5.2 NEW</option>
                        <option value="gpt-5.2-pro" ${prompt.model_type === 'gpt-5.2-pro' ? 'selected' : ''}>GPT-5.2 Pro NEW</option>
                        <option value="gpt-5.2-thinking" ${prompt.model_type === 'gpt-5.2-thinking' ? 'selected' : ''}>GPT-5.2 Thinking NEW</option>
                        <option value="gpt-5.1" ${prompt.model_type === 'gpt-5.1' ? 'selected' : ''}>GPT-5.1</option>
                        <option value="gpt-5.1-thinking" ${prompt.model_type === 'gpt-5.1-thinking' ? 'selected' : ''}>GPT-5.1 Thinking</option>
                        <option value="gpt-5-pro" ${prompt.model_type === 'gpt-5-pro' ? 'selected' : ''}>GPT-5 Pro</option>
                        <option value="gpt-5" ${prompt.model_type === 'gpt-5' ? 'selected' : ''}>GPT-5</option>
                        <option value="gpt-4o-mini" ${prompt.model_type === 'gpt-4o-mini' ? 'selected' : ''}>GPT-4o Mini</option>
                    </optgroup>
                    <optgroup label="Gemini">
                        <option value="gemini-3-pro-preview" ${prompt.model_type === 'gemini-3-pro-preview' && !prompt.enable_deep_think ? 'selected' : ''}>Gemini 3.0 Pro NEW</option>
                        <option value="gemini-3-pro-preview-deep-think" ${(prompt.model_type === 'gemini-3-pro-preview' && prompt.enable_deep_think) || prompt.model_type.includes('deep-think') && prompt.model_type.includes('gemini-3-pro') ? 'selected' : ''}>Gemini 3.0 Pro Deep Think NEW</option>
                        <option value="gemini-2.5-pro" ${prompt.model_type === 'gemini-2.5-pro' && !prompt.enable_deep_think ? 'selected' : ''}>Gemini 2.5 Pro</option>
                        <option value="gemini-2.5-pro-deep-think" ${(prompt.model_type === 'gemini-2.5-pro' && prompt.enable_deep_think) || prompt.model_type.includes('deep-think') && prompt.model_type.includes('gemini-2.5-pro') ? 'selected' : ''}>Gemini 2.5 Pro Deep Think</option>
                        <option value="gemini-2.5-flash" ${prompt.model_type === 'gemini-2.5-flash' && !prompt.enable_deep_think ? 'selected' : ''}>Gemini 2.5 Flash</option>
                        <option value="gemini-2.0-flash" ${prompt.model_type === 'gemini-2.0-flash' ? 'selected' : ''}>Gemini 2.0 Flash</option>
                    </optgroup>
                </select>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">プロンプト内容 <span style="color: #ff6b6b;">*</span></label>
                <textarea id="swal-prompt-content" class="swal2-textarea" placeholder="プロンプトを入力してください。&#10;変数は {{variable_name}} の形式で記述できます。&#10;例: {{article_text}} を要約してください。" required style="min-height: 200px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%;">${promptContent.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</textarea>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">変数の例: {{article_text}}, {{input}}, {{query}} など</small>
            </div>
            <div style="text-align: left; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <label style="display: block; font-weight: bold; margin-bottom: 5px; color: rgba(255, 255, 255, 0.9);">入力スキーマ（JSON形式、オプション）</label>
                <textarea id="swal-prompt-schema" class="swal2-textarea" placeholder='{"field_name": {"type": "string", "label": "フィールドラベル", "required": true}}' style="min-height: 120px; width: 100%; margin-top: 0; box-sizing: border-box; resize: vertical; max-width: 100%; font-family: monospace; font-size: 12px;">${prompt.input_schema ? formatJSON(prompt.input_schema).replace(/</g, '&lt;').replace(/>/g, '&gt;') : ''}</textarea>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px;">ユーザー入力フィールドの定義をJSON形式で指定します（省略可能）</small>
            </div>
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-prompt-is-active" ${prompt.is_active ? 'checked' : ''} style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;">
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">有効にする</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このプロンプトが有効になり、ユーザーが使用できるようになります</small>
            </div>
            <div style="text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-prompt-allows-file-output" style="margin-right: 8px; width: 18px; height: 18px; cursor: pointer;" ${prompt.allows_file_output ? 'checked' : ''}>
                    <span style="font-weight: bold; color: rgba(255, 255, 255, 0.9);">ファイル出力を許可する</span>
                </label>
                <small style="color: rgba(255, 255, 255, 0.6); display: block; margin-top: 5px; margin-left: 26px;">チェックすると、このプロンプトの実行結果をCSV、PDF、DOCXなどの形式で出力できます</small>
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; text-align: left; margin-bottom: 10px; width: 100%; box-sizing: border-box;">
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-enable-web-search" style="margin-right: 6px; width: 16px; height: 16px; cursor: pointer;" ${prompt.enable_web_search ? 'checked' : ''}>
                    <span style="font-size: 13px; color: rgba(255, 255, 255, 0.9);">web_search を許可</span>
                </label>
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-enable-code-interpreter" style="margin-right: 6px; width: 16px; height: 16px; cursor: pointer;" ${prompt.enable_code_interpreter ? 'checked' : ''}>
                    <span style="font-size: 13px; color: rgba(255, 255, 255, 0.9);">code_interpreter を許可</span>
                </label>
                <label style="display: flex; align-items: center; cursor: pointer;">
                    <input type="checkbox" id="swal-enable-file-search" style="margin-right: 6px; width: 16px; height: 16px; cursor: pointer;" ${prompt.enable_file_search ? 'checked' : ''}>
                    <span style="font-size: 13px; color: rgba(255, 255, 255, 0.9);">file_search を許可</span>
                </label>
            </div>
        `,
        focusConfirm: false,
        showCancelButton: true,
        confirmButtonText: '保存',
        cancelButtonText: 'キャンセル',
        confirmButtonColor: '#28a745',
        cancelButtonColor: '#6c757d',
        width: '800px',
        customClass: {
            popup: 'swal-no-scroll',
            htmlContainer: 'swal-no-scroll'
        },
        didOpen: () => {
            // チェックボックスロジックは削除されました
        },
        preConfirm: () => {
            const name = document.getElementById('swal-prompt-name').value.trim();
            const description = document.getElementById('swal-prompt-description').value.trim();
            const model = document.getElementById('swal-prompt-model').value;
            const content = document.getElementById('swal-prompt-content').value.trim();
            const schemaText = document.getElementById('swal-prompt-schema').value.trim();
            const isActive = document.getElementById('swal-prompt-is-active').checked;
            const allowsFileOutput = document.getElementById('swal-prompt-allows-file-output').checked;
            const enableWebSearch = document.getElementById('swal-enable-web-search').checked;
            const enableCodeInterpreter = document.getElementById('swal-enable-code-interpreter').checked;
            const enableFileSearch = document.getElementById('swal-enable-file-search').checked;

            // モデル名からDeep Think設定を判定
            const enableDeepThink = model.includes('deep-think');

            if (!name) {
                Swal.showValidationMessage('プロンプト名は必須です');
                return false;
            }
            if (!content) {
                Swal.showValidationMessage('プロンプト内容は必須です');
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
                enableWebSearch,
                enableCodeInterpreter,
                enableFileSearch
            };
        }
    });

    if (formValues) {
        await savePrompt(id, formValues);
    }
}

async function savePrompt(id, formValues) {
    const data = {
        name: formValues.name,
        description: formValues.description,
        model_type: formValues.model,
        content: formValues.content,
        input_schema: formValues.inputSchema,
        is_active: formValues.isActive,
        allows_file_output: formValues.allowsFileOutput,
        enable_deep_think: formValues.enableDeepThink,
        enable_web_search: formValues.enableWebSearch,
        enable_code_interpreter: formValues.enableCodeInterpreter,
        enable_file_search: formValues.enableFileSearch
    };

    try {
        if (id) {
            // 更新
            await apiRequest(`/api/admin/prompts/${id}`, {
                method: 'PATCH',
                body: JSON.stringify(data)
            });
            await Swal.fire({
                title: '更新完了',
                text: 'プロンプトを更新しました',
                icon: 'success',
                confirmButtonText: 'OK'
            });
            loadPrompts(currentPage);
        } else {
            // 作成
            await apiRequest('/api/admin/prompts', {
                method: 'POST',
                body: JSON.stringify(data)
            });
            await Swal.fire({
                title: '作成完了',
                text: 'プロンプトを作成しました',
                icon: 'success',
                confirmButtonText: 'OK'
            });
            loadPrompts(1);
        }
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'プロンプトの保存に失敗しました',
            icon: 'error',
            confirmButtonText: 'OK'
        });
        console.error('Save prompt error:', error);
    }
}

async function viewPromptContent(id) {
    try {
        const data = await apiRequest(`/api/admin/prompts/${id}/content`);
        const contentHTML = `
            <div style="text-align: left; max-height: 70vh; overflow-y: auto;">
                <div style="background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.1); padding: 15px; border-radius: 8px; white-space: pre-wrap; word-wrap: break-word; font-family: monospace; font-size: 13px; line-height: 1.6; color: rgba(255, 255, 255, 0.9);">${data.content}</div>
            </div>
        `;

        await Swal.fire({
            title: 'プロンプト内容',
            html: contentHTML,
            width: '900px',
            confirmButtonText: '閉じる',
            confirmButtonColor: '#6c757d',
            customClass: {
                popup: 'swal-wide'
            }
        });
    } catch (error) {
        await showAlert('プロンプト内容の読み込みに失敗しました', 'error');
    }
}

async function deletePrompt(id) {
    const prompt = prompts.find(p => p.id === id);
    if (!prompt) return;

    const result = await Swal.fire({
        title: '削除の確認',
        html: `本当に「<strong>${prompt.name}</strong>」を削除しますか？<br>この操作は取り消せません。`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#6c757d',
        confirmButtonText: '削除',
        cancelButtonText: 'キャンセル'
    });

    if (result.isConfirmed) {
        try {
            await apiRequest(`/api/admin/prompts/${id}`, {
                method: 'DELETE'
            });
            await Swal.fire({
                title: '削除完了',
                text: 'プロンプトを削除しました',
                icon: 'success',
                confirmButtonText: 'OK'
            });
            loadPrompts(currentPage);
        } catch (error) {
            await Swal.fire({
                title: 'エラー',
                text: 'プロンプトの削除に失敗しました',
                icon: 'error',
                confirmButtonText: 'OK'
            });
            console.error('Delete prompt error:', error);
        }
    }
}

async function togglePromptStatus(id, isActive) {
    try {
        await apiRequest(`/api/admin/prompts/${id}`, {
            method: 'PATCH',
            body: JSON.stringify({ is_active: isActive })
        });
        await showAlert(`プロンプトを${isActive ? '有効' : '無効'}にしました`, 'success');
        loadPrompts(currentPage);
    } catch (error) {
        await showAlert('ステータスの更新に失敗しました', 'error');
        console.error('Toggle prompt status error:', error);
        // エラー時は元に戻すために再読み込み
        loadPrompts(currentPage);
    }
}

async function manageWorkflowsForPrompt(promptId) {
    const prompt = prompts.find(p => p.id === promptId);
    if (!prompt) return;

    let workflowsForPrompt = [];
    let allWorkflows = [];

    const { value: formValues } = await Swal.fire({
        title: 'ワークフロー / Skill を編集',
        html: `
            <div style="max-height: 70vh; overflow-y: auto; text-align: left;">
                <div style="margin-bottom: 12px;">
                    <div style="font-size: 12px; color: rgba(255,255,255,0.7); margin-bottom: 4px;">対象プロンプト</div>
                    <div style="padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3);">
                        <div style="font-weight: bold; font-size: 14px;">${prompt.name}</div>
                        <div style="font-size: 11px; color: rgba(255,255,255,0.7);">ID: ${prompt.id} / ${prompt.model_type}</div>
                    </div>
                </div>

                <hr style="border-color: rgba(255,255,255,0.1); margin: 10px 0;">

                <h3 style="font-size: 13px; margin-bottom: 6px;">既存ワークフローへの所属</h3>
                <p style="font-size: 12px; color: rgba(255,255,255,0.7); margin-bottom: 6px;">
                    このプロンプトを含めるワークフローにチェックを付けてください（チェックを外すとそのワークフローから除外されます）。
                </p>
                <div id="wf-membership-container" style="border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 8px; max-height: 220px; overflow-y: auto; background: rgba(0,0,0,0.25);">
                    <div style="text-align:center; padding: 12px; color: rgba(255,255,255,0.6);">読み込み中...</div>
                </div>

                <hr style="border-color: rgba(255,255,255,0.1); margin: 12px 0;">

                <h3 style="font-size: 13px; margin-bottom: 6px;">新しいワークフローを作成</h3>
                <p style="font-size: 12px; color: rgba(255,255,255,0.7); margin-bottom: 8px;">
                    このプロンプトを Step 1 として含む新しいワークフローを作成できます（他のSkillは後からワークフロー管理画面で追加できます）。
                </p>
                <div style="margin-bottom: 10px;">
                    <label style="display:block; font-size: 12px; font-weight:bold; margin-bottom:4px;">ワークフロー名</label>
                    <input id="swal-new-wf-name" class="swal2-input" placeholder="例: 記事作成ワークフロー" style="width:100%; box-sizing:border-box; margin-top:0;">
                </div>
                <div style="margin-bottom: 8px;">
                    <label style="display:block; font-size: 12px; font-weight:bold; margin-bottom:4px;">説明</label>
                    <textarea id="swal-new-wf-description" class="swal2-textarea" placeholder="このワークフローの用途や流れを説明してください" style="min-height:60px;"></textarea>
                </div>
                <div>
                    <label style="display:flex; align-items:center; cursor:pointer;">
                        <input type="checkbox" id="swal-new-wf-is-active" checked style="margin-right:6px;">
                        <span style="font-size: 12px;">有効なワークフローとして作成する</span>
                    </label>
                </div>
            </div>
        `,
        focusConfirm: false,
        showCancelButton: true,
        confirmButtonText: '保存',
        cancelButtonText: 'キャンセル',
        confirmButtonColor: '#28a745',
        cancelButtonColor: '#6c757d',
        width: '800px',
        didOpen: async () => {
            const container = document.getElementById('wf-membership-container');
            try {
                const resp = await apiRequest('/api/admin/workflows?skip=0&limit=1000');
                allWorkflows = resp.items || [];

                // それぞれのWorkflowの詳細を取得して、このプロンプトが含まれているか判定
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
                    container.innerHTML = '<div style="text-align:center; padding: 12px; color: rgba(255,255,255,0.6);">ワークフローがまだ登録されていません</div>';
                    return;
                }

                container.innerHTML = details
                    .map(wf => {
                        const hasPrompt = (wf.skills || []).some(s => s.prompt_id === promptId);
                        return `
                            <label style="display:flex; align-items:flex-start; gap:8px; padding:6px 4px; border-radius:4px; cursor:pointer;">
                                <input type="checkbox" class="wf-membership-checkbox" data-workflow-id="${wf.id}" ${hasPrompt ? 'checked' : ''} style="margin-top:3px;">
                                <div style="flex:1 1 auto; min-width:0;">
                                    <div style="font-size:13px; font-weight:bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${wf.name}</div>
                                    <div style="font-size:11px; color: rgba(255,255,255,0.7); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                                        ID: ${wf.id} / ${wf.is_active ? '有効' : '無効'}
                                    </div>
                                </div>
                            </label>
                        `;
                    })
                    .join('');
            } catch (e) {
                console.error('Load workflows for prompt error:', e);
                container.innerHTML = '<div style="text-align:center; padding: 12px; color: rgba(255,255,255,0.6);">ワークフローの取得に失敗しました</div>';
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
                const currentlyHas = (wfDetail.skills || []).some(s => s.prompt_id === promptId);
                const wantHas = cb.checked;
                if (currentlyHas === wantHas) continue; // 変更なし

                // 新しいskills配列を作る
                let newSkills = (wfDetail.skills || []).filter(s => s.prompt_id !== promptId);
                if (wantHas) {
                    // 末尾に追加
                    const newOrder = newSkills.length + 1;
                    newSkills.push({
                        prompt_id: promptId,
                        step_order: newOrder,
                        step_name: `Step ${newOrder}: ${prompt.name}`
                    });
                }
                // step_order を振り直す
                newSkills = newSkills
                    .sort((a, b) => a.step_order - b.step_order)
                    .map((s, idx) => ({
                        prompt_id: s.prompt_id,
                        step_order: idx + 1,
                        step_name: s.step_name || `Step ${idx + 1}`
                    }));

                membershipChanges.push({
                    workflow_id: wfId,
                    skills: newSkills
                });
            }

            const newWfName = document.getElementById('swal-new-wf-name').value.trim();
            const newWfDescription = document.getElementById('swal-new-wf-description').value.trim();
            const newWfIsActive = document.getElementById('swal-new-wf-is-active').checked;

            return {
                membershipChanges,
                newWorkflow:
                    newWfName
                        ? {
                              name: newWfName,
                              description: newWfDescription,
                              is_active: newWfIsActive
                          }
                        : null
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

            // このプロンプトだけをStep1として紐付け
            await apiRequest(`/api/admin/workflows/${created.id}/skills`, {
                method: 'PUT',
                body: JSON.stringify({
                    skills: [
                        {
                            prompt_id: promptId,
                            step_order: 1,
                            step_name: `Step 1: ${prompt.name}`
                        }
                    ]
                })
            });
        }

        await Swal.fire({
            title: '更新完了',
            text: 'ワークフロー/Skill設定を更新しました',
            icon: 'success',
            confirmButtonText: 'OK'
        });
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'ワークフロー/Skill設定の更新に失敗しました',
            icon: 'error',
            confirmButtonText: 'OK'
        });
        console.error('manageWorkflowsForPrompt error:', error);
    }
}

async function showCreateWorkflowFromPrompts() {
    const { value: formValues } = await Swal.fire({
        title: 'ワークフローを作成',
        html: `
            <div style="max-height: 70vh; overflow-y: auto; text-align: left;">
                <!-- ワークフロー基本情報 -->
                <div style="margin-bottom: 12px;">
                    <label style="display:block; font-size: 12px; font-weight:bold; margin-bottom:4px;">ワークフロー名 <span style="color:#ff6b6b;">*</span></label>
                    <input id="swal-wf-name" class="swal2-input" placeholder="例: 記事作成ワークフロー" style="width:100%; box-sizing:border-box; margin-top:0;">
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="display:block; font-size: 12px; font-weight:bold; margin-bottom:4px;">説明</label>
                    <textarea id="swal-wf-description" class="swal2-textarea" placeholder="このワークフローの用途や流れを説明してください" style="min-height:70px;"></textarea>
                </div>
                <div style="margin-bottom: 12px;">
                    <label style="display:flex; align-items:center; cursor:pointer;">
                        <input type="checkbox" id="swal-wf-is-active" checked style="margin-right:6px;">
                        <span style="font-size: 12px;">有効なワークフローとして作成する</span>
                    </label>
                </div>

                <hr style="border-color: rgba(255,255,255,0.1); margin: 16px 0;">

                <!-- 親プロンプト（統合プロンプト）作成 -->
                <h3 style="font-size: 14px; margin-bottom: 8px; color: #9c27b0;">統合プロンプト（親プロンプト）</h3>
                <p style="font-size: 11px; color: rgba(255,255,255,0.6); margin-bottom: 12px;">
                    全ステップ完了後に実行される統合用プロンプトです。子プロンプトの結果をまとめて最終出力を生成します。
                </p>
                
                <div style="margin-bottom: 10px;">
                    <label style="display:block; font-size: 12px; font-weight:bold; margin-bottom:4px;">統合プロンプト名 <span style="color:#ff6b6b;">*</span></label>
                    <input id="swal-leader-name" class="swal2-input" placeholder="例: 記事統合プロンプト" style="width:100%; box-sizing:border-box; margin-top:0;">
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="display:block; font-size: 12px; font-weight:bold; margin-bottom:4px;">統合プロンプト説明</label>
                    <textarea id="swal-leader-description" class="swal2-textarea" placeholder="統合プロンプトの説明" style="min-height:50px;"></textarea>
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="display:block; font-size: 12px; font-weight:bold; margin-bottom:4px;">モデル <span style="color:#ff6b6b;">*</span></label>
                    <select id="swal-leader-model" class="swal2-select" style="width:100%; box-sizing:border-box; margin-top:0;">
                        <optgroup label="OpenAI">
                            <option value="gpt-5.2">GPT-5.2 NEW</option>
                            <option value="gpt-5.2-pro">GPT-5.2 Pro NEW</option>
                            <option value="gpt-5.1" selected>GPT-5.1</option>
                            <option value="gpt-5.1-thinking">GPT-5.1 Thinking</option>
                            <option value="gpt-5-pro">GPT-5 Pro</option>
                        </optgroup>
                        <optgroup label="Gemini">
                            <option value="gemini-3-pro-preview">Gemini 3.0 Pro</option>
                            <option value="gemini-2.5-pro">Gemini 2.5 Pro</option>
                            <option value="gemini-2.5-pro-deep-think">Gemini 2.5 Pro Deep Think</option>
                        </optgroup>
                    </select>
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="display:block; font-size: 12px; font-weight:bold; margin-bottom:4px;">統合プロンプト本文 <span style="color:#ff6b6b;">*</span></label>
                    <textarea id="swal-leader-content" class="swal2-textarea" placeholder="統合プロンプトの内容を入力してください" style="min-height:150px; font-family: monospace; font-size: 12px;">あなたはワークフローの統合エージェントです。

# 利用可能な入力データ
- all_step_results: これまでのすべてのステップ結果（配列）
  - 各要素: {"step_order": int, "workflow_skill_id": int, "prompt_id": int, "output": str}
- previous_output: 直前のステップの出力
- global_input_data: ワークフロー共通入力データ

# あなたの役割
すべてのステップ結果を統合し、ユーザーへの最終的な出力を日本語でわかりやすく生成してください。</textarea>
                    <small style="color: rgba(255,255,255,0.6); display: block; margin-top: 5px;">利用可能な入力: all_step_results, previous_output, global_input_data</small>
                </div>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px;">
                    <label style="display:flex; align-items:center; cursor:pointer; font-size: 11px;">
                        <input type="checkbox" id="swal-leader-deep-think" checked style="margin-right:4px;">
                        Deep Think
                    </label>
                    <label style="display:flex; align-items:center; cursor:pointer; font-size: 11px;">
                        <input type="checkbox" id="swal-leader-web-search" style="margin-right:4px;">
                        web_search
                    </label>
                    <label style="display:flex; align-items:center; cursor:pointer; font-size: 11px;">
                        <input type="checkbox" id="swal-leader-code-interpreter" style="margin-right:4px;">
                        code_interpreter
                    </label>
                </div>

                <hr style="border-color: rgba(255,255,255,0.1); margin: 16px 0;">

                <!-- 子プロンプト（Skills）選択 -->
                <h3 style="font-size: 14px; margin-bottom: 8px;">子プロンプト（Skills）</h3>
                <p style="font-size: 11px; color: rgba(255,255,255,0.6); margin-bottom: 8px;">
                    右側のプロンプト一覧からステップに追加し、左側で順序を調整してください。
                </p>

                <div style="display:flex; gap:16px; flex-wrap:wrap;">
                    <div style="flex:1 1 260px; min-width:260px;">
                        <h4 style="font-size: 13px; margin-bottom: 6px;">現在のステップ</h4>
                        <div id="wf-current-steps" style="border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:8px; max-height:260px; overflow-y:auto; background:rgba(0,0,0,0.25);">
                            <div style="text-align:center; padding: 12px; color: rgba(255,255,255,0.6);">まだステップが追加されていません</div>
                        </div>
                    </div>
                    <div style="flex:1 1 260px; min-width:260px;">
                        <h4 style="font-size: 13px; margin-bottom: 6px;">利用可能なプロンプト</h4>
                        <div id="wf-available-prompts" style="border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:8px; max-height:260px; overflow-y:auto; background:rgba(0,0,0,0.25);">
                            <div style="text-align:center; padding: 12px; color: rgba(255,255,255,0.6);">読み込み中...</div>
                        </div>
                    </div>
                </div>
            </div>
        `,
        focusConfirm: false,
        showCancelButton: true,
        confirmButtonText: '作成',
        cancelButtonText: 'キャンセル',
        confirmButtonColor: '#28a745',
        cancelButtonColor: '#6c757d',
        width: '900px',
        didOpen: async () => {
            // ステップ状態を初期化
            wfSetStepsState([]);

            // プロンプト一覧を読み込み
            const container = document.getElementById('wf-available-prompts');
            try {
                const resp = await apiRequest('/api/admin/prompts?skip=0&limit=1000');
                const allPrompts = resp.items || [];

                if (!allPrompts.length) {
                    container.innerHTML = '<div style="text-align:center; padding: 12px; color: rgba(255,255,255,0.6);">利用可能なプロンプトがありません</div>';
                    return;
                }

                container.innerHTML = allPrompts
                    .map(p => `
                        <div style="display:flex; align-items:center; justify-content:space-between; padding:6px 8px; border-radius:4px; margin-bottom:4px; background: rgba(0,0,0,0.2);">
                            <div style="flex:1 1 auto; min-width:0;">
                                <div style="font-size:13px; font-weight:bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${p.name}</div>
                                <div style="font-size:11px; color: rgba(255,255,255,0.7); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                                    ID: ${p.id} / ${p.model_type}
                                </div>
                            </div>
                            <button class="btn btn-sm" style="margin-left:8px; padding:4px 8px; font-size:11px;" onclick="wfAddStepFromPrompt(${p.id}, '${p.name.replace(/'/g, "\\'")}')">
                                追加
                            </button>
                        </div>
                    `)
                    .join('');
            } catch (e) {
                console.error('Load prompts for workflow create error:', e);
                container.innerHTML = '<div style="text-align:center; padding: 12px; color: rgba(255,255,255,0.6);">プロンプトの取得に失敗しました</div>';
            }
        },
        preConfirm: () => {
            const name = document.getElementById('swal-wf-name').value.trim();
            const description = document.getElementById('swal-wf-description').value.trim();
            const isActive = document.getElementById('swal-wf-is-active').checked;

            // 親プロンプト情報
            const leaderName = document.getElementById('swal-leader-name').value.trim();
            const leaderDescription = document.getElementById('swal-leader-description').value.trim();
            const leaderModel = document.getElementById('swal-leader-model').value;
            const leaderContent = document.getElementById('swal-leader-content').value.trim();
            const leaderDeepThink = document.getElementById('swal-leader-deep-think').checked;
            const leaderWebSearch = document.getElementById('swal-leader-web-search').checked;
            const leaderCodeInterpreter = document.getElementById('swal-leader-code-interpreter').checked;

            if (!name) {
                Swal.showValidationMessage('ワークフロー名は必須です');
                return false;
            }

            if (!leaderName) {
                Swal.showValidationMessage('統合プロンプト名は必須です');
                return false;
            }

            if (!leaderContent) {
                Swal.showValidationMessage('統合プロンプト本文は必須です');
                return false;
            }

            const steps = wfCollectCurrentSteps();
            if (!steps.length) {
                Swal.showValidationMessage('少なくとも1つの子プロンプト（Skill）を追加してください');
                return false;
            }

            return { 
                name, 
                description, 
                isActive, 
                steps,
                leaderPrompt: {
                    name: leaderName,
                    description: leaderDescription,
                    model_type: leaderModel,
                    content: leaderContent,
                    enable_deep_think: leaderDeepThink,
                    enable_web_search: leaderWebSearch,
                    enable_code_interpreter: leaderCodeInterpreter,
                    enable_file_search: false
                }
            };
        }
    });

    if (!formValues) return;

    try {
        // 新しいAPI（親プロンプト＋子プロンプトを一括作成）を使用
        const created = await apiRequest('/api/admin/workflows/with-prompt', {
            method: 'POST',
            body: JSON.stringify({
                name: formValues.name,
                description: formValues.description,
                is_active: formValues.isActive,
                leader_prompt: formValues.leaderPrompt,
                skills: formValues.steps
            })
        });

        await Swal.fire({
            title: '作成完了',
            text: `ワークフロー「${formValues.name}」を作成しました`,
            icon: 'success',
            confirmButtonText: 'OK'
        });

        // ワークフロー一覧を再読み込み
        await loadWorkflows(wfCurrentPage);
    } catch (error) {
        await Swal.fire({
            title: 'エラー',
            text: 'ワークフローの作成に失敗しました',
            icon: 'error',
            confirmButtonText: 'OK'
        });
        console.error('showCreateWorkflowFromPrompts error:', error);
    }
}

function wfGetStepsState() {
    const container = document.getElementById('wf-current-steps');
    try {
        return JSON.parse(container.dataset.steps || '[]');
    } catch {
        return [];
    }
}

function wfSetStepsState(steps) {
    const container = document.getElementById('wf-current-steps');
    container.dataset.steps = JSON.stringify(steps || []);
    wfRenderCurrentSteps();
}

function wfRenderCurrentSteps() {
    const container = document.getElementById('wf-current-steps');
    const steps = wfGetStepsState();

    if (!steps.length) {
        container.innerHTML = '<div style="text-align:center; padding: 12px; color: rgba(255,255,255,0.6);">まだステップが追加されていません</div>';
        return;
    }

    container.innerHTML = steps
        .sort((a, b) => a.step_order - b.step_order)
        .map((s, index) => `
            <div style="display:flex; align-items:flex-start; padding:6px 8px; margin-bottom:4px; border-radius:4px; background: rgba(0,0,0,0.35);">
                <div style="width:28px; text-align:center; font-size:12px; font-weight:bold;">${index + 1}</div>
                <div style="flex:1 1 auto; min-width:0;">
                    <div style="font-size:13px; font-weight:bold; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${s.step_name || s.prompt_name || ('Step ' + (index + 1))}</div>
                    <div style="font-size:11px; color: rgba(255,255,255,0.7); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                        Prompt ID: ${s.prompt_id}${s.prompt_name ? ' / ' + s.prompt_name : ''}
                    </div>
                </div>
                <div style="display:flex; flex-direction:column; gap:4px; margin-left:8px;">
                    <button class="btn btn-sm" style="padding:2px 4px; font-size:10px;" onclick="wfMoveStep(${index}, -1)">↑</button>
                    <button class="btn btn-sm" style="padding:2px 4px; font-size:10px;" onclick="wfMoveStep(${index}, 1)">↓</button>
                    <button class="btn btn-sm btn-danger" style="padding:2px 4px; font-size:10px;" onclick="wfRemoveStep(${index})">削除</button>
                </div>
            </div>
        `)
        .join('');
}

function wfAddStepFromPrompt(promptId, promptName) {
    const steps = wfGetStepsState();
    const nextOrder = steps.length + 1;
    steps.push({
        prompt_id: promptId,
        prompt_name: promptName,
        step_order: nextOrder,
        step_name: null
    });
    wfSetStepsState(steps);
}

function wfMoveStep(index, delta) {
    const steps = wfGetStepsState();
    const newIndex = index + delta;
    if (newIndex < 0 || newIndex >= steps.length) return;
    const tmp = steps[index];
    steps[index] = steps[newIndex];
    steps[newIndex] = tmp;
    steps.forEach((s, i) => { s.step_order = i + 1; });
    wfSetStepsState(steps);
}

function wfRemoveStep(index) {
    const steps = wfGetStepsState();
    steps.splice(index, 1);
    steps.forEach((s, i) => { s.step_order = i + 1; });
    wfSetStepsState(steps);
}

function wfCollectCurrentSteps() {
    const steps = wfGetStepsState();
    return steps
        .sort((a, b) => a.step_order - b.step_order)
        .map((s, idx) => ({
            prompt_id: s.prompt_id,
            step_order: idx + 1,
            step_name: s.step_name || s.prompt_name || `Step ${idx + 1}`
        }));
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
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: rgba(255, 255, 255, 0.6);">ワークフローがまだ登録されていません</td></tr>';
        return;
    }

    tbody.innerHTML = workflows.map(wf => `
        <tr>
            <td>${wf.id}</td>
            <td>${wf.name}</td>
            <td>${wf.description || '説明なし'}</td>
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
                    <button onclick="openWorkflowDetail(${wf.id})" title="ステップを表示/編集" class="icon-btn" style="padding: 6px;">
                        <img src="../img/iconmonstr-magnifier-text-lined.svg" alt="詳細" style="width: 20px; height: 20px; filter: invert(60%) sepia(30%) saturate(400%) hue-rotate(200deg) brightness(95%) contrast(90%);">
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

async function openWorkflowDetail(id) {
    try {
        const wf = await apiRequest(`/api/admin/workflows/${id}`);

        // 親プロンプト情報を取得
        let leaderPromptInfo = '';
        if (wf.leader_prompt_id) {
            try {
                const leaderPrompt = await apiRequest(`/api/admin/prompts/${wf.leader_prompt_id}`);
                leaderPromptInfo = `
                    <div style="margin-bottom:10px; padding:12px; background:rgba(156,39,176,0.1); border:1px solid rgba(156,39,176,0.3); border-radius:6px;">
                        <div style="font-size:13px; font-weight:bold; margin-bottom:8px; color:#9c27b0;">統合プロンプト（親プロンプト）</div>
                        <div style="margin-bottom:6px;">
                            <span style="font-size:12px; color:rgba(255,255,255,0.7);">名前:</span>
                            <span style="font-size:12px; font-weight:bold; margin-left:6px;">${leaderPrompt.name}</span>
                        </div>
                        <div style="margin-bottom:6px;">
                            <span style="font-size:12px; color:rgba(255,255,255,0.7);">モデル:</span>
                            <span style="font-size:12px; margin-left:6px;">${leaderPrompt.model_type}</span>
                        </div>
                        <div style="margin-bottom:6px;">
                            <span style="font-size:12px; color:rgba(255,255,255,0.7);">Prompt ID:</span>
                            <span style="font-size:12px; margin-left:6px;">${wf.leader_prompt_id}</span>
                        </div>
                        <button class="btn btn-sm" style="margin-top:6px; padding:4px 10px; font-size:11px;" onclick="editPrompt(${wf.leader_prompt_id})">
                            統合プロンプトを編集
                        </button>
                    </div>
                `;
            } catch (e) {
                leaderPromptInfo = `
                    <div style="margin-bottom:10px; padding:12px; background:rgba(220,53,69,0.1); border:1px solid rgba(220,53,69,0.3); border-radius:6px;">
                        <div style="font-size:13px; color:#dc3545;">統合プロンプト（ID: ${wf.leader_prompt_id}）が見つかりません</div>
                    </div>
                `;
            }
        } else {
            leaderPromptInfo = `
                <div style="margin-bottom:10px; padding:12px; background:rgba(255,193,7,0.1); border:1px solid rgba(255,193,7,0.3); border-radius:6px;">
                    <div style="font-size:13px; color:#ffc107;">統合プロンプトが設定されていません</div>
                </div>
            `;
        }

        const skillsHtml = (wf.skills && wf.skills.length)
            ? wf.skills
                  .sort((a, b) => a.step_order - b.step_order)
                  .map(s => `
                    <tr>
                        <td>${s.step_order}</td>
                        <td>${s.step_name || ''}</td>
                        <td>${s.prompt_id}</td>
                        <td>${s.prompt_name || ''}</td>
                    </tr>
                `)
                  .join('')
            : '<tr><td colspan="4" style="text-align:center; color: rgba(255,255,255,0.6);">ステップがありません</td></tr>';

        await Swal.fire({
            title: 'ワークフロー詳細',
            html: `
                <div style="max-height: 70vh; overflow-y: auto; text-align:left;">
                    <div style="margin-bottom:10px;">
                        <div style="font-size:13px; font-weight:bold; margin-bottom:4px;">ワークフロー名</div>
                        <div style="padding:6px 8px; border-radius:4px; background:rgba(0,0,0,0.3);">${wf.name}</div>
                    </div>
                    <div style="margin-bottom:10px;">
                        <div style="font-size:13px; font-weight:bold; margin-bottom:4px;">説明</div>
                        <div style="padding:6px 8px; border-radius:4px; background:rgba(0,0,0,0.3); white-space:pre-wrap;">${wf.description || ''}</div>
                    </div>
                    <div style="margin-bottom:10px;">
                        <div style="font-size:13px; font-weight:bold; margin-bottom:4px;">ステータス</div>
                        <div style="display:flex; align-items:center; gap:6px;">
                            ${wf.is_active ? `
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#28a745" style="flex-shrink: 0;">
                                    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                                </svg>
                            ` : `
                                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#dc3545" style="flex-shrink: 0;">
                                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                                </svg>
                            `}
                            <span style="color:${wf.is_active ? '#28a745' : '#dc3545'}; font-weight:${wf.is_active ? 'bold' : 'normal'};">
                                ${wf.is_active ? '有効' : '無効'}
                            </span>
                        </div>
                    </div>

                    <hr style="border-color: rgba(255,255,255,0.1); margin: 12px 0;">

                    ${leaderPromptInfo}

                    <hr style="border-color: rgba(255,255,255,0.1); margin: 12px 0;">

                    <div>
                        <div style="font-size:13px; font-weight:bold; margin-bottom:8px;">子プロンプト（Skills）一覧</div>
                        <div style="border:1px solid rgba(255,255,255,0.1); border-radius:6px; overflow:hidden;">
                            <table class="table" style="margin:0;">
                                <thead>
                                    <tr>
                                        <th style="width:60px;">順序</th>
                                        <th>ステップ名</th>
                                        <th style="width:80px;">Prompt ID</th>
                                        <th>プロンプト名</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${skillsHtml}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            `,
            width: '900px',
            confirmButtonText: '閉じる',
            confirmButtonColor: '#6c757d'
        });
    } catch (error) {
        await showAlert('ワークフローの取得に失敗しました', 'error');
        console.error('openWorkflowDetail error:', error);
    }
}


// ページ読み込み時に実行
(async () => {
    await checkAuth();
    loadPrompts(1);
    loadWorkflows(1);
})();
