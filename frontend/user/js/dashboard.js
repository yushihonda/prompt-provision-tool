// ユーザー ダッシュボード画面 JavaScript

let prompts = [];
let currentPage = 1;
const itemsPerPage = 9;
let totalItems = 0;

async function loadDashboardStats() {
    try {
        const stats = await apiRequest('/api/user/dashboard');

        document.getElementById('available-prompts').textContent = stats.available_prompts;
        document.getElementById('executions-month').textContent = stats.executions_this_month;

        const tokens = stats.total_tokens_this_month || 0;
        document.getElementById('total-tokens-month').textContent = tokens.toLocaleString();

        const cost = stats.total_cost_this_month || 0;
        document.getElementById('total-cost-month').textContent = `$${cost.toFixed(2)}`;
    } catch (error) {
        showAlert('統計情報の読み込みに失敗しました', 'error');
        console.error('Dashboard stats error:', error);
    }
}

async function loadPrompts(page = 1) {
    try {
        const skip = (page - 1) * itemsPerPage;
        const response = await apiRequest(`/api/user/prompts?skip=${skip}&limit=${itemsPerPage}`);

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
    const container = document.getElementById('prompts-container');

    if (prompts.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: rgba(255, 255, 255, 0.6);">利用可能なプロンプトがありません</p>';
        return;
    }

    // 実行中のプロンプトIDを取得
    const executingPromptId = PersistentStatusBar?.promptId ? parseInt(PersistentStatusBar.promptId) : null;

    container.innerHTML = prompts.map(prompt => {
        const isExecuting = executingPromptId && prompt.id === executingPromptId;
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
        <div class="card ${isExecuting ? 'card-executing' : ''}" data-prompt-id="${prompt.id}">
            <div class="card-content">
                <h3>${prompt.name}${isExecuting ? '<span class="executing-badge">実行中</span>' : ''}</h3>
                <p>${prompt.description || '説明なし'}</p>
                <p><strong>モデル:</strong> ${modelDisplay}</p>
            </div>
            <div class="card-corner">
                <button class="btn btn-primary card-execute-btn"
                        onclick="location.href='execute.html?id=${prompt.id}'">
                    ${isExecuting ? '実行中' : '実行'}
                </button>
            </div>
        </div>
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

// 実行中プロンプトの状態を更新する関数
function updateExecutingPrompts() {
    // プロンプトが表示されている場合のみ更新
    if (prompts.length > 0) {
        renderPrompts();
    }
}

// PersistentStatusBarの状態変更を監視
if (typeof PersistentStatusBar !== 'undefined') {
    // 定期的に実行中プロンプトの状態をチェック（1秒ごと）
    setInterval(() => {
        updateExecutingPrompts();
    }, 1000);

    // カスタムイベントで即座に更新
    window.addEventListener('executionStarted', () => {
        updateExecutingPrompts();
    });

    window.addEventListener('executionCompleted', () => {
        updateExecutingPrompts();
    });
}

// 年の選択肢を生成
function initializeYearSelect() {
    const yearSelect = document.getElementById('year-select');
    if (!yearSelect) return;

    const currentYear = new Date().getFullYear();
    // 今年から未来2年まで
    for (let year = currentYear; year <= currentYear + 2; year++) {
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        if (year === currentYear) {
            option.selected = true;
        }
        yearSelect.appendChild(option);
    }

    // 年の変更時にグラフを再読み込み
    yearSelect.addEventListener('change', () => {
        const selectedYear = parseInt(yearSelect.value);
        loadContributionGraph(selectedYear);
    });
}

// コントリビューショングラフを読み込む
async function loadContributionGraph(year = null) {
    try {
        if (year === null) {
            year = new Date().getFullYear();
        }
        const data = await apiRequest(`/api/user/dashboard/contribution-graph?year=${year}`);
        console.log('Contribution graph data:', data);
        renderContributionGraph(data, year);
    } catch (error) {
        console.error('Failed to load contribution graph:', error);
        const container = document.getElementById('contribution-graph-container');
        if (container) {
            container.innerHTML = '<p style="text-align: center; color: rgba(255, 255, 255, 0.6);">グラフの読み込みに失敗しました</p>';
        }
    }
}

// コントリビューショングラフをレンダリング（Qiita記事を参考に実装）
function renderContributionGraph(data, year) {
    const container = document.getElementById('contribution-graph-container');
    if (!container) return;

    const yearStr = year ? year.toString() : new Date().getFullYear().toString();

    // 1年の開始日と終了日
    const beginDate = new Date(yearStr + '-01-01');
    const endDate = new Date(yearStr + '-12-31');

    // 日付ごとの実行回数をマップに変換
    const dayCountMap = new Map();
    for (const monthKey in data) {
        for (const day of data[monthKey] || []) {
            dayCountMap.set(day.date, day.count);
        }
    }

    // 最大実行回数を取得（色の濃さを決定するため）
    let maxCount = 0;
    for (const count of dayCountMap.values()) {
        if (count > maxCount) {
            maxCount = count;
        }
    }

    // 色のレベルを決定（0-4の5段階）
    function getColorLevel(count) {
        if (count === 0) return 0;
        if (maxCount === 0) return 0;
        const ratio = count / maxCount;
        if (ratio >= 0.8) return 4;
        if (ratio >= 0.6) return 3;
        if (ratio >= 0.4) return 2;
        if (ratio >= 0.2) return 1;
        return 1;
    }

    // 1月1日の週の開始（月曜日）を計算
    const firstMonday = new Date(beginDate);
    const firstDayOfWeek = firstMonday.getDay(); // 0=Sunday, 1=Monday, ..., 6=Saturday
    const daysToMonday = firstDayOfWeek === 0 ? 6 : firstDayOfWeek - 1; // 月曜日までの日数
    firstMonday.setDate(firstMonday.getDate() - daysToMonday); // 最初の月曜日に調整

    // 週数を計算（最初の月曜日から12月31日までの週数）
    const totalDays = Math.ceil((endDate - firstMonday) / (1000 * 60 * 60 * 24)) + 1;
    const weekNum = Math.ceil(totalDays / 7);

    // 2次元配列を初期化（1次元目が曜日(縦)、2次元目が週(横)）
    // 0=月曜日, 1=火曜日, ..., 6=日曜日
    const calendar = Array(7).fill(null).map(() => Array(weekNum).fill(null));

    // 各日をカレンダーに配置
    const currentDate = new Date(firstMonday);
    for (let week = 0; week < weekNum; week++) {
        for (let dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
            const dateStr = currentDate.toISOString().split('T')[0];
            const count = dayCountMap.get(dateStr) || 0;
            const level = getColorLevel(count);
            const dateLabel = currentDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

            calendar[dayOfWeek][week] = {
                date: dateStr,
                count: count,
                level: level,
                label: dateLabel,
                inYear: currentDate.getFullYear() === parseInt(yearStr)
            };

            currentDate.setDate(currentDate.getDate() + 1);
        }
    }

    // 各月の開始位置を計算（その月の最初の日が表示される週の位置）
    const monthPositions = {};
    const months = ['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'];

    for (let monthIndex = 0; monthIndex < months.length; monthIndex++) {
        const monthKey = `${yearStr}-${months[monthIndex]}`;
        const monthDate = new Date(monthKey + '-01');

        // その月の最初の日がカレンダーのどの週にあるか探す
        let startWeek = -1;
        for (let week = 0; week < weekNum; week++) {
            for (let dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
                const cell = calendar[dayOfWeek][week];
                if (cell && cell.date === monthKey + '-01') {
                    startWeek = week;
                    break;
                }
            }
            if (startWeek !== -1) break;
        }

        if (startWeek !== -1) {
            // 開始位置は週のインデックス（横軸の位置）
            monthPositions[monthKey] = {
                start: startWeek
            };
        }
    }

    let html = '<div class="contribution-graph-grid">';

    // ヘッダー行（月のラベル）
    html += '<div class="contribution-header-row">';
    html += '<div class="contribution-week-label-column"></div>';
    html += '<div class="contribution-months-header" style="position: relative;">';
    for (const monthKey of Object.keys(monthPositions).sort()) {
        const monthDate = new Date(monthKey + '-01');
        const monthName = monthDate.toLocaleDateString('en-US', { month: 'short' });
        const position = monthPositions[monthKey];
        const cellWidth = 12;
        const cellGap = 3;
        const cellTotalWidth = cellWidth + cellGap;
        // ヘッダーの幅は月名が表示できる最小限の幅に固定
        const headerWidth = 35; // 月名が表示できる最小幅
        html += `<div class="contribution-month-header" style="position: absolute; left: ${position.start * cellTotalWidth}px; width: ${headerWidth}px;">${monthName}</div>`;
    }
    html += '</div></div>';

    // 曜日のラベル（左側）- 月曜日から日曜日まで（7行固定）
    const weekDayLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

    // 曜日ごとの行（左に曜日ラベル、右に日のセル）- 7行固定
    for (let dayOfWeek = 0; dayOfWeek < 7; dayOfWeek++) {
        html += '<div class="contribution-week-row">';

        // 曜日のラベル（左側）
        html += `<div class="contribution-week-label-column">${weekDayLabels[dayOfWeek]}</div>`;

        // 週ごとのセル（横に並べる）
        html += '<div class="contribution-weeks-grid">';
        for (let week = 0; week < weekNum; week++) {
            const cell = calendar[dayOfWeek][week];
            if (cell && cell.inYear) {
                html += `<div class="contribution-week contribution-level-${cell.level}" title="${cell.label}: ${cell.count} executions" data-count="${cell.count}">
                            <div class="contribution-week-tooltip">${cell.label}<br>${cell.count} executions</div>
                        </div>`;
            } else {
                // 年の範囲外のセルは空
                html += `<div class="contribution-week contribution-level-0" style="opacity: 0;"></div>`;
            }
        }
        html += '</div></div>';
    }

    html += '</div>';
    html += '<div class="contribution-legend">';
    html += '<span>少ない</span>';
    for (let i = 0; i < 5; i++) {
        html += `<div class="contribution-legend-item contribution-level-${i}"></div>`;
    }
    html += '<span>多い</span>';
    html += '</div>';

    container.innerHTML = html;
}

// ページ読み込み時に実行
(async () => {
    await checkAuth();
    loadDashboardStats();
    loadPrompts(1);
    initializeYearSelect();
    loadContributionGraph();
})();
