// 共通のユーザー用JavaScript関数

// runtime adapter を唯一の読取窓口にする
const getApiBase = () => window.NexMAGIRuntime.getApiBase();
const runtimeFetch = (path, options) => window.NexMAGIRuntime.fetchWithRuntime(path, options);
const navigateTo = (path) => window.NexMAGIRuntime.navigate(path);

// SweetAlert2のデフォルト設定は swal-defaults.js で共通化

/** HTML特殊文字をエスケープ（XSS防止） */
function escapeHtmlCommon(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
/** 数値をK/M表記に短縮 */
function formatCompact(n) {
    if (n == null) return '-';
    n = Number(n);
    if (n >= 1000000) return (n / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
    return String(n);
}

// renderMiniCube は mini-cube.js に統一（共通ファイル）

/** escapeHtml のエイリアス — 各ページ JS から参照 */
const escapeHtml = escapeHtmlCommon;

/** ユーザー画面 SweetAlert2 の統一 */
const USER_SWAL = {
    primary: '#7c3aed',
    secondary: '#6c757d',
    danger: '#d33',
    btnClose: '閉じる',
};

// 認証チェック（非同期）
async function checkAuth() {
    const token = await window.NexMAGIRuntime.getAuthToken();
    const username = await window.NexMAGIRuntime.getAuthUsername();

    if (!token) {
        navigateTo('login.html');
        return;
    }

    // トークンの有効性をサーバー側で確認
    try {
        // ユーザー側のAPIエンドポイントを呼び出してトークンを検証
        const response = await runtimeFetch('/api/user/skills?skip=0&limit=1', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });

        if (response.status === 401) {
            // トークンが無効な場合
            const errorText = await response.text().catch(() => '');
            // エラー情報をsessionStorageに保存（リダイレクト後も確認できるように）
            sessionStorage.setItem('auth_error', JSON.stringify({
                type: '401',
                message: 'トークンが無効です',
                response: errorText,
                timestamp: new Date().toISOString()
            }));
            await window.NexMAGIRuntime.clearAuthSession();
            navigateTo('login.html');
            return;
        }

        if (!response.ok) {
            // その他のエラー
            const errorText = await response.text().catch(() => '');
            // エラー情報をsessionStorageに保存
            sessionStorage.setItem('auth_error', JSON.stringify({
                type: 'http_error',
                status: response.status,
                message: `認証チェックに失敗しました (${response.status})`,
                response: errorText,
                timestamp: new Date().toISOString()
            }));
            throw new Error(`認証チェックに失敗しました (${response.status})`);
        }

        // レスポンスが正常な場合
        const data = await response.json();

        // ユーザー名を表示
        const usernameDisplay = document.getElementById('username-display');
        if (usernameDisplay && username) {
            usernameDisplay.textContent = username;
        }

        // モバイルメニューのユーザー名も更新
        const mobileUsernameDisplay = document.getElementById('mobile-username-display');
        if (mobileUsernameDisplay && username) {
            mobileUsernameDisplay.textContent = username;
        }
    } catch (error) {
        // エラー情報をsessionStorageに保存
        sessionStorage.setItem('auth_error', JSON.stringify({
            type: 'exception',
            message: error.message,
            stack: error.stack,
            timestamp: new Date().toISOString()
        }));
        await window.NexMAGIRuntime.clearAuthSession();
        navigateTo('login.html');
    }
}

// ログアウト
async function logout() {
    const result = await Swal.fire({
        title: 'ログアウト',
        text: 'ログアウトしますか？',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: USER_SWAL.primary,
        cancelButtonColor: USER_SWAL.secondary,
        confirmButtonText: 'ログアウト',
        cancelButtonText: USER_SWAL.btnClose
    });

    if (result.isConfirmed) {
        await window.NexMAGIRuntime.clearAuthSession();
        await Swal.fire({
            title: 'ログアウトしました',
            text: 'ログイン画面に戻ります',
            icon: 'success',
            confirmButtonColor: USER_SWAL.primary,
            timer: 1500,
            showConfirmButton: false
        });
        navigateTo('login.html');
    }
}

// API リクエスト
async function apiRequest(endpoint, options = {}) {
    const token = await window.NexMAGIRuntime.getAuthToken();

    const defaultOptions = {
        headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        }
    };

    const mergedOptions = {
        ...defaultOptions,
        ...options,
        headers: {
            ...defaultOptions.headers,
            ...options.headers
        }
    };

    try {
        const response = await runtimeFetch(endpoint, mergedOptions);

        // 認証エラーの場合はログイン画面へ
        if (response.status === 401) {
            await window.NexMAGIRuntime.clearAuthSession();
            navigateTo('login.html');
            return;
        }

        // 204 No Contentの場合はレスポンスボディがない
        if (response.status === 204) {
            if (!response.ok) {
                throw new Error('リクエストに失敗しました');
            }
            return null;
        }

        // レスポンスのContent-Typeをチェック
        const contentType = response.headers.get('content-type');
        let data;

        if (contentType && contentType.includes('application/json')) {
            const text = await response.text();
            // 空のレスポンスの場合はnullを返す
            if (!text || text.trim() === '') {
                data = null;
            } else {
                try {
                    data = JSON.parse(text);
                } catch (e) {
                    console.error('JSON parse error:', e, 'Response text:', text);
                    throw new Error(`サーバーエラー (${response.status}): 無効なJSONレスポンス`);
                }
            }
        } else {
            // JSONでない場合はテキストとして取得
            const text = await response.text();
            if (text && text.trim() !== '') {
                console.error('Non-JSON response:', text);
                throw new Error(`サーバーエラー (${response.status}): 予期しないレスポンス形式`);
            }
            data = null;
        }

        if (!response.ok) {
            // 409 Conflict はデスクトップのワークフロー完了後に発生しうる（完了済み実行への再アクセス）
            // データが取得できていればエラーとして扱わない
            if (response.status === 409 && data) {
                console.warn(`API 409 (ignored): ${data?.detail || 'conflict'}`);
                return data;
            }
            throw new Error(`API error ${response.status}: ${JSON.stringify(data?.detail || 'リクエストに失敗しました')}`);
        }

        return data;
    } catch (error) {
        console.error('API request error:', error);
        throw error;
    }
}

// アラート表示（SweetAlert2を使用）
async function showAlert(message, type = 'info') {
    // typeをSweetAlertのiconにマッピング
    let icon = 'info';
    if (type === 'success') icon = 'success';
    else if (type === 'error') icon = 'error';
    else if (type === 'warning') icon = 'warning';
    else icon = 'info';

    const longMessage = message && String(message).length > 220;
    await Swal.fire({
        title: icon === 'error' ? 'エラー' : icon === 'success' ? '成功' : icon === 'warning' ? '警告' : '情報',
        text: message,
        icon: icon,
        confirmButtonText: USER_SWAL.btnClose,
        confirmButtonColor: USER_SWAL.primary,
        timer: longMessage ? undefined : 3000,
        timerProgressBar: !longMessage
    });
}

// 日時フォーマット
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });
}

// URLパラメータ取得
function getQueryParam(name) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(name);
}

// JSON整形
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

// ---------------------------------------------------------------------------
// 共通レイアウト（ヘッダー＋ナビゲーション）
// ---------------------------------------------------------------------------
const USER_NAV_ITEMS = [
    { href: 'dashboard.html', label: 'ワークフロー / スキル' },
    { href: 'history.html',   label: '実行履歴' },
    { href: 'settings.html',  label: 'API設定' },
    { href: 'cli-terminal.html', label: 'ローカル実行環境' },
];

/**
 * NexMAGI app shell — dark header bar with cutout brand + pill nav.
 */
function initUserLayout(activePage) {
    const container = document.querySelector('.container');
    if (!container) return;

    const pillNavHtml = USER_NAV_ITEMS.map(n =>
        `<button class="nav-pill${n.href === activePage ? ' active' : ''}" onclick="window.NexMAGIRuntime.navigate('${n.href}')">${n.label}</button>`
    ).join('\n');

    const headerHtml = `
        <div class="header">
            <div class="brand-cutout">
                <span class="tool-name">NexMAGI</span>
            </div>
            <div class="header-nav">
                ${pillNavHtml}
            </div>
            <div class="header-user">
                <span id="username-display">-</span>
                <button class="btn-logout" onclick="logout()">ログアウト</button>
            </div>
        </div>`;

    const content = container.querySelector('.content');
    if (content) {
        content.insertAdjacentHTML('beforebegin', headerHtml);
    }
}

// ---------------------------------------------------------------------------
// 共通ページネーション
// ---------------------------------------------------------------------------

/**
 * @param {string} containerId
 * @param {number} currentPage
 * @param {number} totalItems
 * @param {number} itemsPerPage
 * @param {string} loadFnName - ページ切替時に呼ぶグローバル関数名
 */
function renderUserPagination(containerId, currentPage, totalItems, itemsPerPage, loadFnName) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const totalPages = Math.ceil(totalItems / itemsPerPage);

    if (totalPages <= 1) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, startPage + 4);

    let html = `<button onclick="${loadFnName}(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>前へ</button>`;
    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="page-number ${i === currentPage ? 'active' : ''}" onclick="${loadFnName}(${i})">${i}</button>`;
    }
    html += `<span class="page-info">${currentPage} / ${totalPages}</span>`;
    html += `<button onclick="${loadFnName}(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled' : ''}>次へ</button>`;

    container.innerHTML = html;
}

// モバイルメニューの開閉
function toggleMobileMenu() {
    const menu = document.getElementById('mobile-menu');
    const overlay = document.querySelector('.menu-overlay');
    const hamburgers = document.querySelectorAll('.hamburger-menu');

    if (menu && overlay) {
        menu.classList.toggle('active');
        overlay.classList.toggle('active');
        hamburgers.forEach(hamburger => {
            hamburger.classList.toggle('active');
        });
    }
}

// モバイルメニューのナビゲーションアイテムクリック時にメニューを閉じる
document.addEventListener('DOMContentLoaded', function () {
    const mobileNavItems = document.querySelectorAll('.mobile-menu .nav-item');
    mobileNavItems.forEach(item => {
        item.addEventListener('click', function () {
            // 少し遅延させてからメニューを閉じる（ページ遷移前に閉じる）
            setTimeout(() => {
                toggleMobileMenu();
            }, 100);
        });
    });

    // モバイルメニューのログアウトボタンクリック時にメニューを閉じる
    const mobileLogoutBtn = document.querySelector('.mobile-menu .btn-logout');
    if (mobileLogoutBtn) {
        mobileLogoutBtn.addEventListener('click', function () {
            setTimeout(() => {
                toggleMobileMenu();
            }, 100);
        });
    }
});

// Persistent Status Bar Logic
const PersistentStatusBar = {
    intervalId: null,
    startTime: null,
    executionId: null,
    skillId: null,
    skillName: null,
    activeTasks: [],
    workflowExecutionId: null,  // ワークフロー実行ID
    workflowName: null,  // ワークフロー名
    workflowId: null,  // ワークフロー定義ID（遷移用）
    currentStepOrder: null,  // 現在のステップ順序
    currentStepName: null,  // 現在のステップ名
    completedExecutions: [], // 完了した実行のリスト
    executionQueue: [], // 実行待ちキュー（最大3つ）
    greenDisplayTimeout: null, // 緑表示のタイムアウトID
    MAX_QUEUE_SIZE: 3, // キュー最大サイズ
    MAX_ACTIVE_TASKS: 3, // スキル + ワークフローの同時実行上限

    init() {
        // 完了タスクを読み込む
        this.loadCompletedTasks();

        // Inject HTML if not exists
        if (!document.getElementById('persistent-status-bar')) {
            const statusBarHTML = `
                <div id="persistent-status-bar" style="position: fixed; top: 68px; right: 20px; z-index: 1000; display: flex; flex-direction: column; align-items: flex-end;">
                    <div id="task-dock" style="width: 40px; height: 40px; background: rgba(94, 0, 255, 0.46); border: 1px solid rgba(94, 0, 255, 0.56); border-radius: 20px; overflow: hidden; transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1); box-shadow: 0 2px 12px rgba(94, 0, 255, 0.35); cursor: pointer;">

                        <div id="dock-header" style="height: 40px; display: flex; align-items: center; padding: 0 10px; width: 100%;">
                            <div style="width: 20px; height: 20px; display: flex; justify-content: center; align-items: center; flex-shrink: 0; margin-right: 10px;">
                                <svg id="task-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" style="fill: rgba(255,255,255,0.8); transition: fill 0.3s ease;"><path d="M19 4h-1V2h-2v2H8V2H6v2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V10h14v10zm0-12H5V6h14v2z"/></svg>
                                <div id="active-spinner" class="spinner" style="width: 18px; height: 18px; border-width: 2px; display: none; position: absolute; border-color: rgba(255,255,255,0.3); border-top-color: #fff;"></div>
                            </div>

                            <div id="dock-summary" style="flex-grow: 1; opacity: 0; display: flex; flex-direction: column; line-height: 1.2; overflow: hidden; white-space: nowrap; transition: opacity 0.3s ease;">
                                <span style="font-size: 10px; color: rgba(255,255,255,0.7); font-weight: bold;">バックグラウンド</span>
                                <span id="dock-prompt-name" style="font-size: 12px; color: #fff; font-weight: 500;">バックグラウンド</span>
                            </div>

                            <svg id="expand-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" style="fill: rgba(255,255,255,0.6); margin-left: auto; opacity: 0; transition: opacity 0.3s ease, transform 0.3s ease;"><path d="M16.293 9.293 12 13.586 7.707 9.293l-1.414 1.414L12 16.414l5.707-5.707z"/></svg>
                        </div>

                        <div id="dock-details" style="display: none; padding: 0 15px 15px 15px; opacity: 0; transform: translateY(-10px) scale(0.95); transition: opacity 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) 0.1s, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) 0.1s; max-height: 400px; overflow-y: auto; background: #DFDFD7; border-radius: 0 0 20px 20px;">
                            <hr style="border: 0; border-top: 1px solid rgba(0,0,0,0.06); margin: 0 0 10px 0;">

                            <div id="active-task-section" style="display: none; margin-bottom: 15px;">
                                <div style="color: #7a7a7a; font-size: 11px; margin-bottom: 8px; font-weight: bold;">実行中</div>
                                <div class="card-cutout-wrapper">
                                    <div id="active-task-content" class="card-cutout" style="--r:18px; --s:30px; background: #fff; padding: 12px 14px; border-radius: 18px;">
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                            <span id="active-task-name" style="color: #2d2d2d; font-size: 12px; font-weight: 500;"></span>
                                        </div>
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                            <span style="color: #a0a0a0; font-size: 10px;">開始:</span>
                                            <span id="active-task-start-time" style="font-family: monospace; color: #7c3aed; font-size: 10px;">00:00</span>
                                        </div>
                                        <button id="stop-execution-btn" class="btn" style="padding: 4px 8px; font-size: 11px; background: rgba(220, 53, 69, 0.1); border: 1px solid rgba(220,53,69,0.3); color: #dc3545; border-radius: 8px; pointer-events: auto; cursor: pointer; width: 100%;">
                                            <span style="display: flex; align-items: center; justify-content: center; gap: 5px;">
                                                <div class="spinner" id="stop-spinner" style="width: 10px; height: 10px; border-width: 1px; display: none;"></div>
                                                停止
                                            </span>
                                        </button>
                                    </div>
                                    <div class="active-task-nav-btn" style="width: 36px; height: 36px; position: absolute; top: 0; right: 0; border-radius: 50%; background: var(--accent); display: flex; justify-content: center; align-items: center; z-index: 2; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.2); pointer-events: auto; transition: transform 0.2s;" title="詳細へ">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14"/><polyline points="12 5 19 12 12 19"/></svg>
                                    </div>
                                </div>
                            </div>

                            <div id="queued-tasks-section" style="display: none; margin-bottom: 15px;">
                                <div style="color: #7a7a7a; font-size: 11px; margin-bottom: 8px; font-weight: bold;">待機中</div>
                                <div id="queued-tasks-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
                            </div>

                            <div id="completed-tasks-section" style="display: none;">
                                <div style="color: #7a7a7a; font-size: 11px; margin-bottom: 8px; font-weight: bold;">完了</div>
                                <div id="completed-tasks-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.insertAdjacentHTML('beforeend', statusBarHTML);

            // イベントリスナーの設定
            const dock = document.getElementById('task-dock');
            let hideTimeout;
            let isExpanding = false;

            const cancelHide = () => {
                if (hideTimeout) {
                    clearTimeout(hideTimeout);
                    hideTimeout = null;
                }
            };

            const scheduleHide = () => {
                cancelHide();
                // 展開中の場合は閉じない
                if (isExpanding) return;
                hideTimeout = setTimeout(() => {
                    this.collapseDock();
                }, 300); // 300msの猶予
            };

            // ホバーでパネル表示（実行中または完了タスクがある場合）
            dock.addEventListener('mouseenter', (e) => {
                // 実行中または完了タスクがある場合のみ展開
                const hasActive = this.getActiveTaskCount() > 0;
                const hasCompleted = Array.isArray(this.completedExecutions) && this.completedExecutions.length > 0;
                const hasTasks = hasActive || hasCompleted;

                if (hasTasks) {
                    cancelHide();
                    isExpanding = true;
                    this.expandDock();
                    // 展開完了後にフラグをリセット
                    setTimeout(() => {
                        isExpanding = false;
                    }, 200);
                }
            });

            // dock-detailsにもイベントリスナーを追加（マウスがパネル内に入った時）
            // 初期化時に設定（dock-detailsは既に存在する）
            const dockDetails = document.getElementById('dock-details');
            if (dockDetails) {
                dockDetails.addEventListener('mouseenter', (e) => {
                    cancelHide();
                });

                dockDetails.addEventListener('mouseleave', (e) => {
                    // dock内にマウスが移動した場合は閉じない
                    const relatedTarget = e.relatedTarget;
                    if (relatedTarget && dock.contains(relatedTarget)) {
                        return;
                    }
                    scheduleHide();
                });
            }

            // dock全体からマウスが離れた時
            dock.addEventListener('mouseleave', (e) => {
                // dock-details内にマウスが移動した場合は閉じない
                const relatedTarget = e.relatedTarget;
                if (relatedTarget && dock.contains(relatedTarget)) {
                    return;
                }
                scheduleHide();
            });

            // クリックでもパネル表示トグル
            dock.addEventListener('click', (e) => {
                // 実行中、待機中、または完了タスクがある場合のみ展開
                const hasActive = this.getActiveTaskCount() > 0;
                const hasQueued = Array.isArray(this.executionQueue) && this.executionQueue.length > 0;
                const hasCompleted = Array.isArray(this.completedExecutions) && this.completedExecutions.length > 0;
                const hasTasks = hasActive || hasQueued || hasCompleted;

                if (hasTasks) {
                    e.stopPropagation();
                    cancelHide();
                    // クラスチェックで判定
                    if (dock.classList.contains('expanded')) {
                        // 開いていれば閉じる
                        this.collapseDock();
                    } else {
                        isExpanding = true;
                        this.expandDock();
                        setTimeout(() => {
                            isExpanding = false;
                        }, 100);
                    }
                }
            });

            // Add event listener for stop button
            const stopBtn = document.getElementById('stop-execution-btn');
            if (stopBtn) {
                stopBtn.addEventListener('click', (e) => {
                    e.stopPropagation(); // Dockのクリックイベントを止める
                    this.stopExecution();
                });
            }

            // Add event listener for nav button
            const navBtn = document.getElementById('status-nav-btn');
            if (navBtn) {
                navBtn.addEventListener('click', (e) => {
                    e.stopPropagation(); // Dockのクリックイベントを止める
                    if (this.workflowId) {
                        // ワークフロー実行の場合はワークフロー実行画面へ遷移
                        const weParam = this.workflowExecutionId ? `&we_id=${this.workflowExecutionId}` : '';
                        window.location.href = `workflow-execute.html?id=${this.workflowId}${weParam}`;
                    } else if (this.skillId) {
                        window.location.href = `execute.html?id=${this.skillId}`;
                    } else {
                        // localStorageから取得を試みる
                        const completed = localStorage.getItem('completed_execution');
                        if (completed) {
                            try {
                                const data = JSON.parse(completed);
                                if (data.workflowId) {
                                    const weP = data.workflowExecutionId ? `&we_id=${data.workflowExecutionId}` : '';
                                    window.location.href = `workflow-execute.html?id=${data.workflowId}${weP}`;
                                } else if (data.skillId) {
                                    window.location.href = `execute.html?id=${data.skillId}`;
                                }
                            } catch (e) {
                                console.error('Failed to parse completed_execution:', e);
                            }
                        }
                    }
                });
            }
        }

        // Check localStorage for active execution
        this.checkStatus();

        // Check for completed executions (履歴として表示)
        this.loadCompletedTasks();

        // キューを読み込む
        this.loadQueue();

        // 初期化後にタスクリストを描画（少し遅延させて確実に実行）
        setTimeout(() => {
            this.renderTasks();
            // 完了タスクがある場合はDockを展開状態にする
            if (this.completedExecutions && this.completedExecutions.length > 0 && this.getActiveTaskCount() === 0) {
                const dock = document.getElementById('task-dock');
                if (dock) {
                    dock.style.width = '200px';
                    dock.style.height = '40px';
                }
            }
        }, 100);

        // Listen for storage changes (to sync across tabs)
        window.addEventListener('storage', (e) => {
            if (e.key === 'active_execution' || e.key === 'active_executions') {
                this.checkStatus();
            } else if (e.key === 'completed_executions') {
                this.loadCompletedTasks();
                this.renderTasks();
            } else if (e.key === 'execution_queue') {
                this.loadQueue();
                this.renderTasks();
            }
        });
    },

    expandDock() {
        const dock = document.getElementById('task-dock');
        const dockDetails = document.getElementById('dock-details');
        const expandIcon = document.getElementById('expand-icon');

        if (!dock) return;

        // 実行中、待機中、または完了タスクがある場合のみ展開
        const hasActive = this.getActiveTaskCount() > 0;
        const hasQueued = Array.isArray(this.executionQueue) && this.executionQueue.length > 0;
        const hasCompleted = Array.isArray(this.completedExecutions) && this.completedExecutions.length > 0;
        const hasTasks = hasActive || hasQueued || hasCompleted;

        if (hasTasks) {
            dock.classList.add('expanded');

            // アニメーション用にoverflowを調整
            dock.style.overflow = 'hidden';

            // 幅と高さをアニメーション
            dock.style.width = '300px';
            dock.style.maxHeight = '500px';

            // 展開時は紫
            dock.style.background = '#7c3aed';
            dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';

            // 高さをautoに設定（アニメーションのため）
            requestAnimationFrame(() => {
                dock.style.height = 'auto';
            });

            if (dockDetails) {
                // まずdisplayをblockに設定
                dockDetails.style.display = 'block';
                dockDetails.style.visibility = 'visible';

                // アニメーション開始（少し遅延させてスムーズに）
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        if (dockDetails) {
                            dockDetails.style.opacity = '1';
                            dockDetails.style.transform = 'translateY(0) scale(1)';
                        }
                    });
                });
            }

            if (expandIcon) {
                expandIcon.style.transform = 'rotate(180deg)';
            }

            // タスクリストを再描画（展開状態を保持したまま）
            this.renderTasks();

            // 展開時は確実にtask-dockを紫に設定（renderTasksの後に再度設定）
            if (dock) {
                dock.style.background = 'rgba(94, 0, 255, 0.46)';
                dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
            }
        }
    },

    collapseDock() {
        const dock = document.getElementById('task-dock');
        const dockDetails = document.getElementById('dock-details');
        const expandIcon = document.getElementById('expand-icon');

        if (!dock) return;

        // まずdock-detailsを閉じるアニメーション
        if (dockDetails) {
            dockDetails.style.opacity = '0';
            dockDetails.style.transform = 'translateY(-10px) scale(0.95)';
        }

        // 少し遅延させてからdockを閉じる
        setTimeout(() => {
            dock.classList.remove('expanded');

            // 実行中または完了タスクがある場合のデフォルト状態に戻す
            if (this.getActiveTaskCount() > 0) {
                dock.style.width = '200px';
                dock.style.height = '40px';
                dock.style.background = '#7c3aed';
                dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
            } else if ((this.executionQueue && this.executionQueue.length > 0) || (this.completedExecutions && this.completedExecutions.length > 0)) {
                dock.style.width = '200px';
                dock.style.height = '40px';
                const sortedTasks = [...this.completedExecutions].sort((a, b) => b.completedAt - a.completedAt);
                const latestTask = sortedTasks[0];
                const timeSinceCompletion = (Date.now() - (latestTask?.completedAt || 0)) / 1000;
                const isRecentlyCompleted = timeSinceCompletion < 5;

                if (latestTask?.status === 'success' && isRecentlyCompleted) {
                    dock.style.background = 'rgba(40, 167, 69, 0.08)';
                    dock.style.borderColor = 'rgba(40, 167, 69, 0.3)';
                } else if (latestTask?.status === 'error' && isRecentlyCompleted) {
                    dock.style.background = 'rgba(220, 53, 69, 0.08)';
                    dock.style.borderColor = 'rgba(220, 53, 69, 0.3)';
                } else {
                    dock.style.background = '#7c3aed';
                    dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
                }
            } else {
                dock.style.width = '40px';
                dock.style.height = '40px';
                dock.style.background = '#7c3aed';
                dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
            }

            dock.style.maxHeight = 'none';

            if (dockDetails) {
                dockDetails.style.display = 'none';
                dockDetails.style.visibility = 'hidden';
            }

            // タスクリストを再描画して、折りたたみ時の色を確実に反映
            this.renderTasks();
        }, 200); // アニメーション完了後に非表示

        if (expandIcon) {
            expandIcon.style.transform = 'rotate(0deg)';
        }
    },

    // 古いメソッドの互換性維持（念のため）
    showPanel() { this.expandDock(); },
    hidePanel() { this.collapseDock(); },

    _taskKey(task) {
        if (task.workflowExecutionId) return `wf:${task.workflowExecutionId}`;
        if (task.id) return `exec:${task.id}`;
        return `temp:${task.skillId || task.workflowId || 'task'}:${task.startTime || Date.now()}`;
    },

    _syncLegacyState() {
        const primary = this.activeTasks[0] || null;
        this.executionId = primary?.id || null;
        this.skillId = primary?.skillId || null;
        this.skillName = primary?.skillName || null;
        this.workflowExecutionId = primary?.workflowExecutionId || null;
        this.workflowName = primary?.workflowName || null;
        this.workflowId = primary?.workflowId || null;
        this.currentStepOrder = primary?.currentStepOrder || null;
        this.currentStepName = primary?.currentStepName || null;
        this.startTime = primary?.startTime || null;
    },

    _saveActiveTasks() {
        localStorage.setItem('active_executions', JSON.stringify(this.activeTasks));
        const primary = this.activeTasks[0] || null;
        if (primary) {
            localStorage.setItem('active_execution', JSON.stringify(primary));
        } else {
            localStorage.removeItem('active_execution');
        }
    },

    getActiveTaskCount() {
        return Array.isArray(this.activeTasks) ? this.activeTasks.length : 0;
    },

    canStartMoreTasks() {
        return this.getActiveTaskCount() < this.MAX_ACTIVE_TASKS;
    },

    _findActiveTaskIndex({ executionId = null, workflowExecutionId = null } = {}) {
        return this.activeTasks.findIndex((task) => (
            (executionId && task.id === executionId)
            || (workflowExecutionId && task.workflowExecutionId === workflowExecutionId)
        ));
    },

    attachWorkflowExecution(workflowExecutionId, executionId = null, workflowName = null, workflowId = null, taskKey = null) {
        if (!workflowExecutionId) return;

        let idx = this._findActiveTaskIndex({ workflowExecutionId });
        if (idx < 0 && taskKey) {
            idx = this.activeTasks.findIndex((task) => task.taskKey === taskKey);
        }
        if (idx < 0) {
            idx = this.activeTasks.findLastIndex((task) => !task.workflowExecutionId && (task.workflowId === workflowId || task.workflowName === workflowName));
        }
        if (idx < 0) {
            idx = this.activeTasks.findLastIndex((task) => !task.workflowExecutionId && !task.skillId);
        }
        if (idx < 0) return;

        this.activeTasks[idx] = {
            ...this.activeTasks[idx],
            workflowExecutionId,
            workflowName: workflowName || this.activeTasks[idx].workflowName,
            workflowId: workflowId || this.activeTasks[idx].workflowId,
            id: executionId || this.activeTasks[idx].id,
        };
        this._syncLegacyState();
        this._saveActiveTasks();
        this.updateUI(true);
        this.renderTasks();
    },

    start(executionId, skillId, skillName, workflowExecutionId = null, workflowName = null, stepOrder = null, stepName = null, workflowId = null, taskKey = null) {
        const nextTask = {
            id: executionId,
            skillId: skillId,
            skillName: skillName || '実行中...',
            workflowExecutionId: workflowExecutionId,
            workflowName: workflowName,
            workflowId: workflowId,
            taskKey: taskKey,
            currentStepOrder: stepOrder,
            currentStepName: stepName,
            startTime: Date.now()
        };
        const existingIndex = this._findActiveTaskIndex({ executionId, workflowExecutionId });
        if (existingIndex >= 0) {
            const previousStartTime = this.activeTasks[existingIndex]?.startTime;
            this.activeTasks[existingIndex] = {
                ...this.activeTasks[existingIndex],
                ...nextTask,
                startTime: previousStartTime || nextTask.startTime,
            };
        } else {
            this.activeTasks.unshift(nextTask);
        }

        this._syncLegacyState();
        this._saveActiveTasks();

        this.updateUI(true);
        this.renderTasks();

        // 実行開始イベントを発火（ダッシュボードでカードを更新するため）
        window.dispatchEvent(new CustomEvent('executionStarted', {
            detail: { executionId, skillId, skillName: nextTask.skillName, workflowExecutionId, workflowName }
        }));
    },

    // ワークフローの次のステップが起動された時に呼ばれる
    handleWorkflowNextStep(nextExecutionId, nextStepOrder, stepName, workflowName, workflowExecutionId = null, workflowId = null) {
        const targetWorkflowExecutionId = workflowExecutionId || this.workflowExecutionId;
        const idx = this._findActiveTaskIndex({ workflowExecutionId: targetWorkflowExecutionId });
        if (idx >= 0) {
            this.activeTasks[idx] = {
                ...this.activeTasks[idx],
                id: nextExecutionId,
                skillName: stepName || `Step ${nextStepOrder}`,
                workflowExecutionId: targetWorkflowExecutionId || this.activeTasks[idx].workflowExecutionId,
                workflowName: workflowName || this.activeTasks[idx].workflowName,
                workflowId: workflowId || this.activeTasks[idx].workflowId,
                currentStepOrder: nextStepOrder,
                currentStepName: stepName,
            };
            this._syncLegacyState();
            this._saveActiveTasks();
            this.updateUI(true);
            this.renderTasks();
            return;
        }

        this.start(nextExecutionId, null, stepName || `Step ${nextStepOrder}`, targetWorkflowExecutionId, workflowName, nextStepOrder, stepName, workflowId || this.workflowId);
    },

    stop() {
        const oldPromptId = this.skillId;
        // 完了状態を表示するため、すぐには非表示にしない
        // 代わりに完了状態に移行
        this.markAsCompleted();
        // 実行完了イベントを発火（ダッシュボードでカードを更新するため）
        if (oldPromptId) {
            window.dispatchEvent(new CustomEvent('executionCompleted', {
                detail: { skillId: oldPromptId }
            }));
        }
    },

    markAsCompleted(status = 'success', target = null) {
        const targetIndex = target ? this._findActiveTaskIndex(target) : 0;
        const activeTask = targetIndex >= 0 ? this.activeTasks[targetIndex] : null;
        if (!activeTask) return;

        const completedExecutionId = activeTask.id;
        const completedPromptId = activeTask.skillId;
        const completedPromptName = activeTask.skillName;
        const completedWorkflowExecutionId = activeTask.workflowExecutionId;
        const completedWorkflowName = activeTask.workflowName;
        const completedWorkflowId = activeTask.workflowId;

        // 実行完了イベントを発火（ダッシュボードでカードを更新するため）
        if (completedPromptId) {
            window.dispatchEvent(new CustomEvent('executionCompleted', {
                detail: { executionId: completedExecutionId, skillId: completedPromptId, status }
            }));
        }

        // ① 通常のスキル実行（workflowExecutionIdなし）の場合は従来通り execution 単位で保存
        if (completedExecutionId && completedPromptId && !completedWorkflowExecutionId) {
            const completedTask = {
                id: completedExecutionId,
                skillId: completedPromptId,
                skillName: completedPromptName,
                status: status,
                completedAt: Date.now()
            };

            // 完了タスクを配列に追加（重複チェック）
            const existingIndex = this.completedExecutions.findIndex(t => t.id === completedExecutionId);
            if (existingIndex >= 0) {
                this.completedExecutions[existingIndex] = completedTask;
            } else {
                this.completedExecutions.push(completedTask);
            }
        }

        // ② ワークフロー実行中の場合は「ワークフロー単位」で1件だけ保存
        if (completedWorkflowExecutionId) {
            const workflowId = completedWorkflowExecutionId;
            const workflowName = completedWorkflowName || completedPromptName || 'ワークフロー';

            const workflowTask = {
                id: workflowId,
                skillId: null,
                skillName: workflowName,
                status: status,
                completedAt: Date.now(),
                workflowExecutionId: workflowId,
                workflowName: workflowName,
                workflowId: completedWorkflowId  // ワークフロー定義ID（遷移用）
            };

            const existingWorkflowIndex = this.completedExecutions.findIndex(
                t => t.workflowExecutionId === workflowId
            );
            if (existingWorkflowIndex >= 0) {
                this.completedExecutions[existingWorkflowIndex] = workflowTask;
            } else {
                this.completedExecutions.push(workflowTask);
            }
        }

        // 24時間以上経過したタスクを削除
        this.completedExecutions = this.completedExecutions.filter(task => {
            const hoursSinceCompletion = (Date.now() - task.completedAt) / (1000 * 60 * 60);
            return hoursSinceCompletion < 24;
        });

        // localStorageに保存
        this.saveCompletedTasks();

        // タイマーを停止
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }

        // スピナーを非表示にする
        const activeSpinner = document.getElementById('active-spinner');
        const icon = document.getElementById('task-icon');
        if (activeSpinner) {
            activeSpinner.style.display = 'none';
        }
        if (icon) {
            icon.style.display = 'block';
        }

        // 実行中の状態をクリア
        this.activeTasks.splice(targetIndex, 1);
        this._syncLegacyState();
        this._saveActiveTasks();

        this.updateUI(this.getActiveTaskCount() > 0);
        setTimeout(() => {
            this.renderTasks();
        }, 100);

        // 完了直後はステータスに応じて色を表示、5秒後に紫に戻す
        this.showStatusTemporarily(status);

        // ブラウザ通知（タブが非アクティブでも通知）
        this._sendCompletionNotification(status, completedPromptName);

        // キューから次のタスクを開始
        this.processNextInQueue();
    },

    showStatusTemporarily(status) {
        // 完了直後（5秒間）のみステータス色を表示
        const dock = document.getElementById('task-dock');
        if (!dock) return;

        // 既存のタイムアウトをクリア
        if (this.greenDisplayTimeout) {
            clearTimeout(this.greenDisplayTimeout);
        }

        // 展開中でない場合のみ色を設定
        const isExpanded = dock.classList.contains('expanded');
        if (!isExpanded && this.completedExecutions && this.completedExecutions.length > 0) {
            const sortedTasks = [...this.completedExecutions].sort((a, b) => b.completedAt - a.completedAt);
            const latestTask = sortedTasks[0];

            // 最新タスクの状態に基づいて表示
            if (latestTask && latestTask.status === status) {
                const dockPromptName = document.getElementById('dock-prompt-name');

                if (status === 'success') {
                    dock.style.background = 'rgba(40, 167, 69, 0.15)';
                    dock.style.borderColor = '#28a745';
                    if (dockPromptName) {
                        dockPromptName.innerHTML = `<span style="color: #28a745; font-size: 14px; font-weight: bold;">✓ 完了</span>`;
                    }
                } else if (status === 'manual_review_required') {
                    dock.style.background = 'rgba(217, 119, 6, 0.15)';
                    dock.style.borderColor = '#d97706';
                    if (dockPromptName) {
                        dockPromptName.innerHTML = `<span style="color: #d97706; font-size: 14px; font-weight: bold;">! レビュー待ち</span>`;
                    }
                } else if (status === 'error') {
                    dock.style.background = 'rgba(220, 53, 69, 0.15)';
                    dock.style.borderColor = '#dc3545';
                    if (dockPromptName) {
                        dockPromptName.innerHTML = `<span style="color: #dc3545; font-size: 14px; font-weight: bold;">✗ エラー</span>`;
                    }
                } else if (status === 'cancelled') {
                    dock.style.background = 'rgba(255, 193, 7, 0.15)';
                    dock.style.borderColor = '#ffc107';
                    if (dockPromptName) {
                        dockPromptName.innerHTML = `<span style="color: #ffc107; font-size: 14px; font-weight: bold;">⊘ キャンセル</span>`;
                    }
                }

                // 5秒後に紫に戻し、完了サインも削除して「バックグラウンド」に戻す
                this.greenDisplayTimeout = setTimeout(() => {
                    const dock = document.getElementById('task-dock');
                    if (dock && !dock.classList.contains('expanded')) {
                        dock.style.background = 'rgba(94, 0, 255, 0.46)';
                        dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';

                        // 完了サインを削除して「バックグラウンド」に戻す
                        const dockPromptName = document.getElementById('dock-prompt-name');
                        if (dockPromptName) {
                            dockPromptName.textContent = 'バックグラウンド';
                        }
                    }
                }, 5000);
            }
        }
    },

    clearCompleted() {
        // 完了状態をクリア（手動で閉じる場合など）
        const statusCompleted = document.getElementById('status-completed');
        const statusError = document.getElementById('status-error');
        const statusCancelled = document.getElementById('status-cancelled');
        const dock = document.getElementById('task-dock');

        if (statusCompleted) {
            statusCompleted.style.display = 'none';
        }
        if (statusError) {
            statusError.style.display = 'none';
        }
        if (statusCancelled) {
            statusCancelled.style.display = 'none';
        }
        if (dock) {
            dock.style.background = '#7c3aed';
            dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
        }

        localStorage.removeItem('completed_execution');
        this.updateUI(false);
    },

    checkStatus() {
        const stored = localStorage.getItem('active_executions') || localStorage.getItem('active_execution');
        if (stored) {
            try {
                const data = JSON.parse(stored);
                this.activeTasks = Array.isArray(data) ? data : [data];
                this._syncLegacyState();
                this.updateUI(true);
                this.renderTasks();
                this._verifyStoredStatus();
            } catch (e) {
                console.error('Failed to parse active_execution:', e);
                this.activeTasks = [];
                localStorage.removeItem('active_execution');
                localStorage.removeItem('active_executions');
                this.updateUI(false);
                this.renderTasks();
            }
        } else {
            this.activeTasks = [];
            this._syncLegacyState();
            this.updateUI(false);
            this.renderTasks();
        }
    },

    async _verifyStoredStatus() {
        try {
            for (const task of [...this.activeTasks]) {
                if (task.workflowExecutionId) {
                    const wfStatus = await apiRequest(`/api/user/workflow-executions/${task.workflowExecutionId}/status`);
                    if (wfStatus && (wfStatus.status === 'success' || wfStatus.status === 'error' || wfStatus.status === 'cancelled' || wfStatus.status === 'manual_review_required')) {
                        this.markAsCompleted(wfStatus.status === 'success' ? 'success' : wfStatus.status, {
                            workflowExecutionId: task.workflowExecutionId,
                        });
                        continue;
                    }
                }
                if (task.id) {
                    const exec = await apiRequest(`/api/user/executions/${task.id}`);
                    if (exec && (exec.status === 'success' || exec.status === 'error' || exec.status === 'cancelled' || exec.status === 'manual_review_required')) {
                        if (!(task.workflowExecutionId && exec.workflow_skill_id)) {
                            this.markAsCompleted(exec.status === 'success' ? 'success' : exec.status, {
                                executionId: task.id,
                            });
                            continue;
                        }
                    }
                }
                if (!task.workflowExecutionId && !task.id) {
                    const age = Date.now() - (task.startTime || 0);
                    if (age > 10 * 60 * 1000) {
                        this._clearStale(task);
                    }
                }
            }
        } catch (e) {
            console.warn('Stored execution verify failed, clearing:', e);
            this._clearStale();
        }
    },

    _clearStale(task = null) {
        if (task) {
            const idx = this._findActiveTaskIndex({
                executionId: task.id || null,
                workflowExecutionId: task.workflowExecutionId || null,
            });
            if (idx >= 0) {
                this.activeTasks.splice(idx, 1);
            }
        } else {
            this.activeTasks = [];
        }
        this._syncLegacyState();
        this._saveActiveTasks();
        this.updateUI(this.getActiveTaskCount() > 0);
        this.renderTasks();
    },

    loadCompletedTasks() {
        const stored = localStorage.getItem('completed_executions');
        if (stored) {
            try {
                const tasks = JSON.parse(stored);
                // 24時間以内の完了タスクのみ保持
                this.completedExecutions = tasks.filter(task => {
                    const hoursSinceCompletion = (Date.now() - (task.completedAt || 0)) / (1000 * 60 * 60);
                    return hoursSinceCompletion < 24;
                });
                this.saveCompletedTasks(); // 古いタスクを削除して保存
            } catch (e) {
                console.error('Failed to parse completed_executions:', e);
                this.completedExecutions = [];
            }
        } else {
            this.completedExecutions = [];
        }
    },

    saveCompletedTasks() {
        localStorage.setItem('completed_executions', JSON.stringify(this.completedExecutions));
    },

    // キュー管理機能
    loadQueue() {
        const stored = localStorage.getItem('execution_queue');
        if (stored) {
            try {
                this.executionQueue = JSON.parse(stored);
                // 最大サイズを超えている場合は削除
                if (this.executionQueue.length > this.MAX_QUEUE_SIZE) {
                    this.executionQueue = this.executionQueue.slice(0, this.MAX_QUEUE_SIZE);
                    this.saveQueue();
                }
            } catch (e) {
                console.error('Failed to parse execution_queue:', e);
                this.executionQueue = [];
            }
        } else {
            this.executionQueue = [];
        }
    },

    saveQueue() {
        localStorage.setItem('execution_queue', JSON.stringify(this.executionQueue));
    },

    addToQueue(taskData) {
        // キューが満杯の場合は追加しない
        if (this.executionQueue.length >= this.MAX_QUEUE_SIZE) {
            return false;
        }
        this.executionQueue.push({
            ...taskData,
            queuedAt: Date.now()
        });
        this.saveQueue();
        this.renderTasks();
        return true;
    },

    removeFromQueue(index) {
        if (index >= 0 && index < this.executionQueue.length) {
            this.executionQueue.splice(index, 1);
            this.saveQueue();
            this.renderTasks();
        }
    },

    _sendCompletionNotification(status, taskName) {
        const name = taskName || 'タスク';
        const isSuccess = status === 'success';
        const title = isSuccess ? '実行完了' : '実行失敗';
        const body = isSuccess ? `${name} が完了しました` : `${name} でエラーが発生しました`;

        // ブラウザ通知（Notification API）— パーミッション取得済みの場合のみ送信
        // requestPermission はユーザージェスチャーが必要なため、非同期完了時には呼ばない
        try {
            if ('Notification' in window && Notification.permission === 'granted') {
                new Notification(title, { body, icon: '/favicon.ico' });
            }
        } catch (e) {
            // 通知送信失敗は無視
        }
    },

    async processNextInQueue() {
        // 既に実行中なら何もしない
        if (this.getActiveTaskCount() > 0) {
            return;
        }

        // キューが空なら何もしない
        if (!this.executionQueue || this.executionQueue.length === 0) {
            return;
        }

        // キューから最初のタスクを取り出す
        const nextTask = this.executionQueue.shift();
        this.saveQueue();

        // タスクを開始
        try {
            // execute.htmlページの場合、直接実行APIを呼び出す
            if (window.location.pathname.includes('execute.html')) {
                // execute.htmlの実行関数を呼び出す
                if (typeof window.executeQueuedTask === 'function') {
                    await window.executeQueuedTask(nextTask);
                }
            } else {
                // 他のページの場合、localStorageに次のタスクを保存してexecute.htmlにリダイレクト
                // URLパラメータではなくlocalStorageを使うことで、長いURLの問題を回避
                localStorage.setItem('pending_queue_task', JSON.stringify(nextTask));
                window.location.href = `execute.html?id=${nextTask.skillId}`;
            }
        } catch (error) {
            console.error('Failed to process queued task:', error);
            // エラー時は次のタスクを処理
            setTimeout(() => {
                this.processNextInQueue();
            }, 1000);
        }
    },

    renderTasks() {
        const activeTaskSection = document.getElementById('active-task-section');
        const activeTaskContent = document.getElementById('active-task-content');
        const queuedTasksSection = document.getElementById('queued-tasks-section');
        const queuedTasksList = document.getElementById('queued-tasks-list');
        const completedTasksSection = document.getElementById('completed-tasks-section');
        const completedTasksList = document.getElementById('completed-tasks-list');
        const activeTasks = Array.isArray(this.activeTasks) ? this.activeTasks : [];

        if (activeTasks.length > 0 && activeTaskSection && activeTaskContent) {
            activeTaskSection.style.display = 'block';
            activeTaskContent.innerHTML = activeTasks.map((task, index) => {
                const elapsed = Math.max(0, Math.floor((Date.now() - (task.startTime || Date.now())) / 1000));
                const minutes = Math.floor(elapsed / 60).toString().padStart(2, '0');
                const seconds = (elapsed % 60).toString().padStart(2, '0');
                const displayName = task.workflowName
                    ? `${task.workflowName}${task.currentStepName ? ` - ${task.currentStepName}` : (task.currentStepOrder ? ` - Step ${task.currentStepOrder}` : '')}`
                    : (task.skillName || '実行中...');
                return `
                    <div style="background:#fff; border-radius:18px; padding:12px 14px; margin-bottom:${index < activeTasks.length - 1 ? '10px' : '0'}; border:1px solid rgba(124,58,237,0.12);">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; gap:8px;">
                            <span style="color:#2d2d2d; font-size:12px; font-weight:500; flex:1;">${escapeHtmlCommon(displayName)}</span>
                            <span style="color:#7c3aed; font-size:10px; font-family:monospace;">${minutes}:${seconds}</span>
                        </div>
                        <div style="display:flex; gap:8px;">
                            <button class="active-task-nav-btn btn btn-sm btn-secondary"
                                    data-skill-id="${task.skillId || ''}"
                                    data-workflow-id="${task.workflowId || ''}"
                                    data-workflow-execution-id="${task.workflowExecutionId || ''}"
                                    style="padding:4px 8px; font-size:11px; background:rgba(94, 0, 255, 0.46); border:1px solid rgba(94, 0, 255, 0.56); color:#fff; pointer-events:auto; flex:1;">
                                詳細へ
                            </button>
                            <button class="active-task-stop-btn btn btn-sm btn-danger"
                                    data-execution-id="${task.id || ''}"
                                    data-workflow-execution-id="${task.workflowExecutionId || ''}"
                                    style="padding:4px 8px; font-size:11px; background:rgba(220,53,69,0.8); border:none; pointer-events:auto;">
                                停止
                            </button>
                        </div>
                    </div>
                `;
            }).join('');

            activeTaskContent.querySelectorAll('.active-task-nav-btn').forEach((navBtn) => {
                navBtn.onclick = (e) => {
                    e.stopPropagation();
                    const wfId = navBtn.getAttribute('data-workflow-id');
                    const weId = navBtn.getAttribute('data-workflow-execution-id');
                    const skillId = navBtn.getAttribute('data-skill-id');
                    if (wfId) {
                        const weParam = weId ? `&we_id=${weId}` : '';
                        window.location.href = `workflow-execute.html?id=${wfId}${weParam}`;
                    } else if (skillId) {
                        window.location.href = `execute.html?id=${skillId}`;
                    }
                };
            });
            activeTaskContent.querySelectorAll('.active-task-stop-btn').forEach((stopBtn) => {
                stopBtn.onclick = (e) => {
                    e.stopPropagation();
                    const executionId = parseInt(stopBtn.getAttribute('data-execution-id') || '', 10);
                    const workflowExecutionId = parseInt(stopBtn.getAttribute('data-workflow-execution-id') || '', 10);
                    this.stopExecution(executionId || null, workflowExecutionId || null);
                };
            });
        } else {
            if (activeTaskSection) activeTaskSection.style.display = 'none';
        }

        // 待機中のタスク（キュー）を表示
        const hasQueuedTasks = Array.isArray(this.executionQueue) && this.executionQueue.length > 0;
        if (hasQueuedTasks && queuedTasksSection && queuedTasksList) {
            queuedTasksSection.style.display = 'block';
            queuedTasksList.innerHTML = '';

            this.executionQueue.forEach((task, index) => {
                const taskItem = document.createElement('div');
                taskItem.style.cssText = 'background: #E9EAE5; border: 1px solid rgba(255, 193, 7, 0.3); border-radius: 12px; padding: 10px; transition: all 0.2s ease;';

                taskItem.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="color: #2d2d2d; font-size: 12px; font-weight: 500;">${escapeHtmlCommon(task.skillName || 'スキル')}</span>
                        <span style="color: #ffc107; font-size: 11px; font-weight: bold;">待機中 #${index + 1}</span>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button class="queued-task-nav-btn btn btn-sm btn-secondary"
                                data-prompt-id="${task.skillId}"
                                style="padding: 4px 8px; font-size: 11px; background: rgba(94, 0, 255, 0.46); border: 1px solid rgba(94, 0, 255, 0.56); color: #fff; pointer-events: auto; flex: 1;">
                            詳細へ
                        </button>
                        <button class="queued-task-remove-btn btn btn-sm btn-danger"
                                data-index="${index}"
                                style="padding: 4px 8px; font-size: 11px; background-color: rgba(220, 53, 69, 0.8); border: none; pointer-events: auto;">
                            削除
                        </button>
                    </div>
                `;

                // 詳細へボタンのイベント
                const navBtn = taskItem.querySelector('.queued-task-nav-btn');
                if (navBtn) {
                    navBtn.onclick = (e) => {
                        e.stopPropagation();
                        const skillId = navBtn.getAttribute('data-prompt-id');
                        if (skillId) {
                            window.location.href = `execute.html?id=${skillId}`;
                        }
                    };
                }

                // 削除ボタンのイベント
                const removeBtn = taskItem.querySelector('.queued-task-remove-btn');
                if (removeBtn) {
                    removeBtn.onclick = (e) => {
                        e.stopPropagation();
                        const index = parseInt(removeBtn.getAttribute('data-index'));
                        this.removeFromQueue(index);
                    };
                }

                queuedTasksList.appendChild(taskItem);
            });
        } else {
            if (queuedTasksSection) queuedTasksSection.style.display = 'none';
        }

        // 完了したタスクを表示
        // completedExecutionsが配列で、長さが0より大きい場合のみ表示
        const hasCompletedTasks = Array.isArray(this.completedExecutions) && this.completedExecutions.length > 0;

        if (hasCompletedTasks && completedTasksSection && completedTasksList) {
            completedTasksSection.style.display = 'block';
            completedTasksList.innerHTML = '';

            // 完了時刻でソート（新しい順）
            const sortedTasks = [...this.completedExecutions].sort((a, b) => b.completedAt - a.completedAt);

            sortedTasks.forEach(task => {
                const taskItem = document.createElement('div');
                taskItem.className = 'card-cutout-wrapper';
                taskItem.style.cssText = 'margin-bottom: 4px;';

                const isSuccess = task.status === 'success';
                const isCancelled = task.status === 'cancelled';
                const isManualReview = task.status === 'manual_review_required';
                const statusColor = isSuccess ? '#28a745' : (isManualReview ? '#d97706' : (task.status === 'error' ? '#dc3545' : (isCancelled ? '#ffc107' : '#7c3aed')));
                const statusText = isSuccess ? '✓' : (isManualReview ? '!' : (task.status === 'error' ? '✗' : isCancelled ? '⊘' : '•'));

                taskItem.innerHTML = `
                    <div class="card-cutout" style="--r:16px; --s:26px; background:#fff; padding:10px 12px; border-radius:16px; border-left:3px solid ${statusColor};">
                        <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                            <span style="color:${statusColor}; font-size:12px; font-weight:bold;">${statusText}</span>
                            <span style="color:#2d2d2d; font-size:11px; font-weight:500; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtmlCommon(task.skillName || 'スキル')}</span>
                        </div>
                        <span style="color:${statusColor}; font-size:10px; font-weight:600;">${isSuccess ? 'success' : isManualReview ? 'manual_review_required' : task.status === 'error' ? 'error' : isCancelled ? 'cancelled' : task.status}</span>
                    </div>
                    <div class="completed-task-nav-btn"
                         data-prompt-id="${task.skillId}"
                         data-execution-id="${task.id || task.executionId}"
                         data-workflow-id="${task.workflowId || ''}"
                         data-workflow-execution-id="${task.workflowExecutionId || ''}"
                         style="width:32px; height:32px; position:absolute; top:0; right:0; border-radius:50%; background:var(--accent); display:flex; justify-content:center; align-items:center; z-index:2; cursor:pointer; box-shadow:0 2px 6px rgba(0,0,0,0.2); pointer-events:auto; transition:transform 0.2s;" title="詳細へ">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14"/><polyline points="12 5 19 12 12 19"/></svg>
                    </div>
                `;

                // 詳細へボタンのイベント
                const navBtn = taskItem.querySelector('.completed-task-nav-btn');
                if (navBtn) {
                    navBtn.onclick = (e) => {
                        e.stopPropagation();
                        const wfId = navBtn.getAttribute('data-workflow-id');
                        const weId = navBtn.getAttribute('data-workflow-execution-id');
                        if (wfId) {
                            const weParam = weId ? `&we_id=${weId}` : '';
                            window.location.href = `workflow-execute.html?id=${wfId}${weParam}`;
                        } else {
                            const skillId = navBtn.getAttribute('data-prompt-id');
                            const executionId = navBtn.getAttribute('data-execution-id');
                            if (skillId) {
                                const url = executionId
                                    ? `execute.html?id=${skillId}&execution_id=${executionId}`
                                    : `execute.html?id=${skillId}`;
                                window.location.href = url;
                            }
                        }
                    };
                }

                completedTasksList.appendChild(taskItem);
            });
        } else {
            if (completedTasksSection) completedTasksSection.style.display = 'none';
        }

        // Dockの表示状態を更新（実行中または完了タスクがある場合）
        const dock = document.getElementById('task-dock');
        const dockSummary = document.getElementById('dock-summary');
        const dockPromptName = document.getElementById('dock-prompt-name');
        const expandIcon = document.getElementById('expand-icon');

        if (!dock) return;

        // 展開中かどうかをチェック
        const isExpanded = dock.classList.contains('expanded');

        // 実行中、待機中、または完了タスクがある場合
        const hasTasks = activeTasks.length > 0 || (this.executionQueue && this.executionQueue.length > 0) || (this.completedExecutions && this.completedExecutions.length > 0);

        if (hasTasks) {
            if (activeTasks.length > 0) {
                const primaryTask = activeTasks[0];
                // 実行中の場合
                if (!isExpanded) {
                    dock.style.width = '200px';
                    dock.style.height = '40px';
                }
                dock.style.background = 'rgba(94, 0, 255, 0.46)';
                dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
                if (dockPromptName) {
                    const stepInfo = primaryTask.workflowName
                        ? (primaryTask.currentStepName ? ` - ${primaryTask.currentStepName}` : (primaryTask.currentStepOrder ? ` - Step ${primaryTask.currentStepOrder}` : ''))
                        : '';
                    const displayName = primaryTask.workflowName
                        ? `${primaryTask.workflowName}${stepInfo}`
                        : (primaryTask.skillName || '実行中...');
                    const badgeCount = Math.max(0, activeTasks.length - 1) + (this.executionQueue?.length || 0);
                    if (badgeCount > 0) {
                        dockPromptName.innerHTML = `${escapeHtmlCommon(displayName)} <span style="color: #ffc107; font-size: 11px; margin-left: 5px;">+${badgeCount}</span>`;
                    } else {
                        dockPromptName.textContent = displayName;
                    }
                }
            } else if ((this.executionQueue && this.executionQueue.length > 0) || (this.completedExecutions && this.completedExecutions.length > 0)) {
                // 待機中または完了タスクがある場合
                const sortedTasks = [...this.completedExecutions].sort((a, b) => b.completedAt - a.completedAt);
                const latestTask = sortedTasks[0];
                if (!isExpanded) {
                    dock.style.width = '200px';
                    dock.style.height = '40px';
                }
                // 待機中タスクがある場合は黄色、それ以外は完了状態に応じて色を設定
                if (this.executionQueue && this.executionQueue.length > 0) {
                    // 待機中タスクがある場合は黄色
                    dock.style.background = 'rgba(255, 193, 7, 0.15)';
                    dock.style.borderColor = '#ffc107';
                    if (dockPromptName) {
                        if (isExpanded) {
                            dockPromptName.textContent = 'バックグラウンド';
                        } else {
                            dockPromptName.innerHTML = `<span style="color: #ffc107; font-size: 14px; font-weight: bold;">⏳ 待機中 (${this.executionQueue.length})</span>`;
                        }
                    }
                } else {
                    // 展開中は常に紫、折りたたみ時は完了直後（5秒以内）かつ成功時のみ緑
                    if (isExpanded) {
                        dock.style.background = 'rgba(94, 0, 255, 0.46)';
                        dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
                    } else {
                        // 完了直後（5秒以内）かつ成功時のみ緑
                        const timeSinceCompletion = (Date.now() - latestTask.completedAt) / 1000; // 秒
                        const isRecentlyCompleted = timeSinceCompletion < 5; // 5秒以内

                        if (latestTask.status === 'success' && isRecentlyCompleted) {
                            dock.style.background = 'rgba(40, 167, 69, 0.15)';
                            dock.style.borderColor = '#28a745';
                        } else if (latestTask.status === 'manual_review_required' && isRecentlyCompleted) {
                            dock.style.background = 'rgba(217, 119, 6, 0.15)';
                            dock.style.borderColor = '#d97706';
                        } else if (latestTask.status === 'error' && isRecentlyCompleted) {
                            dock.style.background = 'rgba(220, 53, 69, 0.15)';
                            dock.style.borderColor = '#dc3545';
                        } else if (latestTask.status === 'cancelled' && isRecentlyCompleted) {
                            dock.style.background = 'rgba(255, 193, 7, 0.15)';
                            dock.style.borderColor = '#ffc107';
                        } else {
                            dock.style.background = 'rgba(94, 0, 255, 0.46)';
                            dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
                        }
                    }
                    if (dockPromptName) {
                        // 展開中は常に「バックグラウンド」に戻す
                        if (isExpanded) {
                            dockPromptName.textContent = 'バックグラウンド';
                        } else {
                            // 折りたたみ時のみサインを表示
                            const timeSinceCompletion = (Date.now() - latestTask.completedAt) / 1000; // 秒
                            const isRecentlyCompleted = timeSinceCompletion < 5; // 5秒以内

                            if (latestTask.status === 'success' && isRecentlyCompleted) {
                                // 完了直後（5秒以内）かつ成功時は完了サインのみ
                                dockPromptName.innerHTML = `<span style="color: #28a745; font-size: 14px; font-weight: bold;">✓ 完了</span>`;
                            } else if (latestTask.status === 'manual_review_required' && isRecentlyCompleted) {
                                dockPromptName.innerHTML = `<span style="color: #d97706; font-size: 14px; font-weight: bold;">! レビュー待ち</span>`;
                            } else if (latestTask.status === 'error') {
                                dockPromptName.innerHTML = `<span style="color: #dc3545; font-size: 14px; font-weight: bold;">✗ エラー</span>`;
                            } else if (latestTask.status === 'cancelled' && isRecentlyCompleted) {
                                // キャンセル直後（5秒以内）のみキャンセルサインを表示
                                dockPromptName.innerHTML = `<span style="color: #ffc107; font-size: 14px; font-weight: bold;">⊘ キャンセル</span>`;
                            } else {
                                // 5秒経過後は「バックグラウンド」に戻す
                                dockPromptName.textContent = 'バックグラウンド';
                            }
                        }
                    }
                }
            }

            if (dockSummary) dockSummary.style.opacity = '1';
            if (expandIcon) expandIcon.style.opacity = '1';
        } else {
            // タスクがない場合はデフォルト状態に戻す
            dock.style.width = '40px';
            dock.style.height = '40px';
            dock.style.background = '#7c3aed';
            dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';
            if (dockSummary) dockSummary.style.opacity = '0';
            if (expandIcon) expandIcon.style.opacity = '0';
            // スキル名を「バックグラウンド」に戻す
            if (dockPromptName) {
                dockPromptName.textContent = 'バックグラウンド';
            }
        }
    },

    updateUI(isActive) {
        const dock = document.getElementById('task-dock');
        const icon = document.getElementById('task-icon');
        const activeSpinner = document.getElementById('active-spinner');
        const dockSummary = document.getElementById('dock-summary');
        const dockPromptName = document.getElementById('dock-prompt-name');
        const expandIcon = document.getElementById('expand-icon');
        const timerDisplay = document.getElementById('status-timer');
        const stopBtn = document.getElementById('stop-execution-btn');
        const stopSpinner = document.getElementById('stop-spinner');
        const navBtn = document.getElementById('status-nav-btn');
        const dockPanel = document.getElementById('dock-panel');
        const spinnerCircle = document.getElementById('dock-spinner-circle');

        if (!dock) return;

        if (isActive) {
            // アクティブ状態のスタイル（横長展開）
            dock.style.width = '200px';
            dock.style.height = '40px';
            dock.style.background = 'rgba(94, 0, 255, 0.46)';
            dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';

            if (icon) icon.style.display = 'none';
            if (activeSpinner) {
                activeSpinner.style.display = 'block';
                activeSpinner.style.borderColor = 'rgba(94, 0, 255, 0.56)';
                activeSpinner.style.borderTopColor = '#fff';
            }
            if (dockSummary) {
                dockSummary.style.opacity = '1';
            }
            if (expandIcon) {
                expandIcon.style.opacity = '1';
            }

            // 先頭タスク名を表示
            if (dockPromptName) {
                const primaryTask = this.activeTasks[0] || null;
                if (primaryTask) {
                    dockPromptName.textContent = primaryTask.workflowName || primaryTask.skillName || '実行中...';
                }
            }

            if (stopBtn) stopBtn.disabled = false;
            if (stopSpinner) stopSpinner.style.display = 'none';

            if (navBtn) navBtn.style.display = 'none';

            // タイマー開始
            // renderTasks は軽量（タイマー表示のみ）なので1秒、
            // verifyStatus はタスク数×API呼び出しなので 8秒間隔に緩和。
            // 3タスク同時でも 8秒ごとに最大6 API（十分許容範囲）。
            if (this.intervalId) clearInterval(this.intervalId);
            this._lastVerifyAt = 0;
            this.intervalId = setInterval(async () => {
                if (this.getActiveTaskCount() === 0) return;
                this.renderTasks();
                const now = Date.now();
                if (now - (this._lastVerifyAt || 0) >= 8000) {
                    this._lastVerifyAt = now;
                    await this.verifyStatus();
                }
            }, 1000);

            // タスクリストを再描画
            this.renderTasks();

        } else {
            // 非アクティブ状態のスタイル（円形に戻す）
            dock.style.width = '40px';
            dock.style.height = '40px';
            dock.style.background = '#7c3aed';
            dock.style.borderColor = 'rgba(94, 0, 255, 0.56)';

            if (icon) {
                icon.style.display = 'block';
                icon.style.fill = 'rgba(255,255,255,0.8)';
            }
            if (activeSpinner) activeSpinner.style.display = 'none';
            if (dockSummary) {
                dockSummary.style.opacity = '0';
            }
            if (expandIcon) {
                expandIcon.style.opacity = '0';
            }

            this.collapseDock();

            if (this.intervalId) clearInterval(this.intervalId);
            this.intervalId = null;
        }
    },

    async verifyStatus() {
        for (const task of [...this.activeTasks]) {
            try {
                if (!task.id && task.workflowExecutionId) {
                    const wfStatus = await apiRequest(`/api/user/workflow-executions/${task.workflowExecutionId}/status`);
                    if (wfStatus && (wfStatus.status === 'success' || wfStatus.status === 'error' || wfStatus.status === 'cancelled' || wfStatus.status === 'manual_review_required')) {
                        this.markAsCompleted(wfStatus.status === 'success' ? 'success' : wfStatus.status, {
                            workflowExecutionId: task.workflowExecutionId,
                        });
                    }
                    continue;
                }

                if (!task.id) continue;
                const execution = await apiRequest(`/api/user/executions/${task.id}`);
                if (execution.status === 'success' || execution.status === 'error' || execution.status === 'cancelled' || execution.status === 'manual_review_required') {
                    if (task.workflowExecutionId && execution.workflow_skill_id) {
                        continue;
                    }

                    this.markAsCompleted(execution.status === 'success' ? 'success' : execution.status, {
                        executionId: task.id,
                    });

                    if (window.location.pathname.includes('execute.html')) {
                        const currentUrl = new URL(window.location.href);
                        const currentPromptId = currentUrl.searchParams.get('id');
                        if (currentPromptId && parseInt(currentPromptId) === task.skillId) {
                            window.dispatchEvent(new CustomEvent('executionCompleted', {
                                detail: { execution: execution, executionId: task.id || execution.id }
                            }));
                        }
                    }
                }
            } catch (error) {
                console.error('Status verification failed:', error);
            }
        }
    },

    async stopExecution(targetExecutionId = null, targetWorkflowExecutionId = null) {
        const task = targetWorkflowExecutionId
            ? this.activeTasks.find((item) => item.workflowExecutionId === targetWorkflowExecutionId)
            : targetExecutionId
                ? this.activeTasks.find((item) => item.id === targetExecutionId)
                : this.activeTasks[0];
        if (!task || (!task.id && !task.workflowExecutionId)) {
            console.warn('No execution target to stop');
            return;
        }

        const stopBtn = document.getElementById('stop-execution-btn');
        const stopSpinner = document.getElementById('stop-spinner');

        // ボタンを無効化してスピナーを表示
        if (stopBtn) {
            stopBtn.disabled = true;
            stopBtn.style.opacity = '0.6';
        }
        if (stopSpinner) stopSpinner.style.display = 'inline-block';

        try {
            if (task.workflowExecutionId && typeof window.NexMAGIRuntime?.cancelOrchestration === 'function') {
                await window.NexMAGIRuntime.cancelOrchestration(task.workflowExecutionId);
            } else if (task.id) {
                await apiRequest(`/api/execute/${task.id}/cancel`, {
                    method: 'POST'
                });
            } else {
                throw new Error('停止対象が見つかりません');
            }

            // 成功メッセージを表示
            const Toast = Swal.mixin({
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 3000
            });
            Toast.fire({
                icon: 'success',
                title: '実行を停止しました'
            });

            // 実行IDを保存（後で完了状態として表示するため）
            const executionIdToMark = task.id;
            const skillIdToMark = task.skillId;
            const skillNameToMark = task.skillName;

            const taskIndex = this._findActiveTaskIndex({
                executionId: executionIdToMark,
                workflowExecutionId: task.workflowExecutionId || null,
            });
            if (taskIndex >= 0) {
                this.activeTasks.splice(taskIndex, 1);
            }
            this._syncLegacyState();
            this._saveActiveTasks();

            // ポーリングを停止（verifyStatusのポーリング）
            if (this.intervalId) {
                clearInterval(this.intervalId);
                this.intervalId = null;
            }

            // execute.htmlページのポーリングも停止
            if (window.location.pathname.includes('execute.html')) {
                // グローバルスコープのポーリングIDを探して停止
                if (typeof window.pollIntervalId !== 'undefined' && window.pollIntervalId) {
                    clearInterval(window.pollIntervalId);
                    window.pollIntervalId = null;
                }
                // cleanupPolling関数があれば呼び出す
                if (typeof cleanupPolling === 'function') {
                    cleanupPolling();
                }
            }

            // キャンセル状態として完了タスクに追加
            const cancelledTask = {
                id: executionIdToMark,  // markAsCompleted()と統一するためidを使用
                skillId: skillIdToMark,
                skillName: skillNameToMark || '実行中...',
                status: 'cancelled',
                completedAt: Date.now(),
                workflowExecutionId: task.workflowExecutionId || null,
                workflowName: task.workflowName || null,
                workflowId: task.workflowId || null,
            };
            this.completedExecutions = this.completedExecutions || [];
            this.completedExecutions.unshift(cancelledTask);
            this.saveCompletedTasks();

            // UIを更新
            this.updateUI(this.getActiveTaskCount() > 0);
            this.renderTasks();

            // execute.htmlページの場合、UIを更新
            if (window.location.pathname.includes('execute.html')) {
                // カスタムイベントを発火して、execute.html側で処理させる
                window.dispatchEvent(new CustomEvent('executionCancelled', {
                    detail: { executionId: executionIdToMark }
                }));

                // 実行ボタンの状態をリセット
                const executeBtn = document.getElementById('execute-btn');
                if (executeBtn) {
                    executeBtn.disabled = false;
                    const executeBtnText = document.getElementById('execute-btn-text');
                    const executeBtnSpinner = document.getElementById('execute-btn-spinner');
                    if (executeBtnText) executeBtnText.textContent = '実行';
                    if (executeBtnSpinner) executeBtnSpinner.style.display = 'none';
                }

                // 入力フィールドを再有効化
                const form = document.getElementById('execute-form');
                if (form) {
                    const inputFields = form.querySelectorAll('input, textarea, select, button');
                    inputFields.forEach(field => {
                        if (field.id !== 'stop-execution-btn') {
                            field.disabled = false;
                        }
                    });
                }

                // 出力エリアにキャンセルメッセージを表示
                const outputContent = document.getElementById('output-content');
                if (outputContent) {
                    outputContent.innerHTML = '<div style="color: #ffc107; text-align: center; padding: 20px; font-weight: 500;">実行がキャンセルされました</div>';
                }

                // 出力パネルを表示
                const outputPanel = document.querySelector('.execute-output-panel');
                if (outputPanel) {
                    outputPanel.style.display = 'flex';
                    outputPanel.style.visibility = 'visible';
                }
            }

            // キューから次のタスクを開始
            setTimeout(() => {
                this.processNextInQueue();
            }, 500);
        } catch (error) {
            console.error('Cancel error:', error);
            // エラー時も次のタスクを処理
            setTimeout(() => {
                this.processNextInQueue();
            }, 500);

            // エラーメッセージを表示
            const errorMessage = error.message || '停止に失敗しました';
            showAlert(errorMessage, 'error');

            // ボタンを再有効化
            if (stopBtn) {
                stopBtn.disabled = false;
                stopBtn.style.opacity = '1';
            }
            if (stopSpinner) stopSpinner.style.display = 'none';
        }
    }
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    PersistentStatusBar.init();
});
