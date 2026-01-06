// 管理者 プロンプト一覧画面 JavaScript

let prompts = [];
let currentPage = 1;
const itemsPerPage = 10;
let totalItems = 0;

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
                    <span style="color: ${prompt.allows_file_output ? '#28a745' : '#dc3545'}; font-weight: ${prompt.allows_file_output ? 'bold' : 'normal'};">${prompt.allows_file_output ? '許可' : '不可'}</span>
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
                enableDeepThink
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
                enableDeepThink
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
        enable_deep_think: formValues.enableDeepThink
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


// ページ読み込み時に実行
(async () => {
    await checkAuth();
    loadPrompts(1);
})();
