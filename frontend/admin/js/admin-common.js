// 共通の管理者用JavaScript関数

const runtimeFetch = (path, options) => window.PPTRuntime.fetchWithRuntime(path, options);
const navigateToAdmin = (path) => window.PPTRuntime.navigate(path);

// SweetAlert2のデフォルト設定は swal-defaults.js で共通化

/** HTML特殊文字をエスケープ（XSS防止） */
function escapeHtmlAdmin(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/** 管理画面 SweetAlert2 の統一（ワークフロー系モーダルと同系色・文言） */
const ADMIN_SWAL = {
    primary: '#9c27b0',
    secondary: '#6c757d',
    danger: '#d33',
    btnClose: '閉じる',
};

// 認証チェック（非同期）
async function checkAuth() {
    const token = await window.PPTRuntime.getAuthToken();
    const username = await window.PPTRuntime.getAuthUsername();

    if (!token) {
        navigateToAdmin('login.html');
        return;
    }

    // トークンの有効性をサーバー側で確認
    try {
        // 管理者側のAPIエンドポイントを呼び出してトークンを検証
        const response = await runtimeFetch('/api/admin/dashboard', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });

        if (response.status === 401) {
            // トークンが無効な場合
            await window.PPTRuntime.clearAuthSession();
            navigateToAdmin('login.html');
            return;
        }

        if (!response.ok) {
            // その他のエラー
            throw new Error('認証チェックに失敗しました');
        }

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
        console.error('Auth check error:', error);
        await window.PPTRuntime.clearAuthSession();
        navigateToAdmin('login.html');
    }
}

// ログアウト
async function logout() {
    const result = await Swal.fire({
        title: 'ログアウト',
        text: 'ログアウトしますか？',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: ADMIN_SWAL.primary,
        cancelButtonColor: ADMIN_SWAL.secondary,
        confirmButtonText: 'ログアウト',
        cancelButtonText: ADMIN_SWAL.btnClose
    });

    if (result.isConfirmed) {
        await window.PPTRuntime.clearAuthSession();
        await Swal.fire({
            title: 'ログアウトしました',
            text: 'ログイン画面に戻ります',
            icon: 'success',
            confirmButtonColor: ADMIN_SWAL.primary,
            timer: 1500,
            showConfirmButton: false
        });
        navigateToAdmin('login.html');
    }
}

// API リクエスト
async function apiRequest(endpoint, options = {}) {
    const token = await window.PPTRuntime.getAuthToken();

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
            await window.PPTRuntime.clearAuthSession();
            navigateToAdmin('login.html');
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
            // FastAPIのバリデーションエラーの詳細を取得
            let errorMessage = 'リクエストに失敗しました';
            if (data) {
                if (data.detail) {
                    if (Array.isArray(data.detail)) {
                        // バリデーションエラーの配列の場合
                        errorMessage = data.detail.map(err => {
                            if (typeof err === 'string') return err;
                            return `${err.loc?.join('.')}: ${err.msg}`;
                        }).join(', ');
                    } else if (typeof data.detail === 'string') {
                        errorMessage = data.detail;
                    } else {
                        errorMessage = JSON.stringify(data.detail);
                    }
                } else if (data.message) {
                    errorMessage = data.message;
                } else {
                    errorMessage = JSON.stringify(data);
                }
            }
            throw new Error(errorMessage);
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

    await Swal.fire({
        title: icon === 'error' ? 'エラー' : icon === 'success' ? '成功' : icon === 'warning' ? '警告' : '情報',
        text: message,
        icon: icon,
        confirmButtonText: ADMIN_SWAL.btnClose,
        confirmButtonColor: ADMIN_SWAL.primary,
        timer: 3000,
        timerProgressBar: true
    });
}

// モーダル表示
function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
        // 背景のスクロールを無効化
        document.body.style.overflow = 'hidden';
    }
}

// モーダル非表示
function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
        // 背景のスクロールを再有効化
        document.body.style.overflow = '';
    }
}

// 確認ダイアログ
function confirmAction(message) {
    return confirm(message);
}

// 日時フォーマット
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });
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
const ADMIN_NAV_ITEMS = [
    { href: 'dashboard.html', label: 'ワークフロー / スキル管理' },
    { href: 'accounts.html',  label: 'アカウント管理' },
    { href: 'executions.html', label: '実行ログ' },
];

/**
 * ヘッダー + モバイルメニュー + ナビを自動挿入する。
 * 各 HTML の <div class="content"> の直前に呼び出す。
 *
 * @param {string} activePage - 現在のページ href (例: 'dashboard.html')
 */
function initAdminLayout(activePage) {
    const container = document.querySelector('.container');
    if (!container) return;

    const navHtml = (extraClass = '') =>
        ADMIN_NAV_ITEMS.map(n =>
            `<button class="nav-item${n.href === activePage ? ' active' : ''}${extraClass}" onclick="window.PPTRuntime.navigate('${n.href}')">${n.label}</button>`
        ).join('\n');

    const pillNavHtml = ADMIN_NAV_ITEMS.map(p =>
        `<button class="nav-pill${p.href === activePage ? ' active' : ''}" onclick="window.PPTRuntime.navigate('${p.href}')">${p.label}</button>`
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
                <span id="username-display">admin</span>
                <button class="btn-logout" onclick="logout()">ログアウト</button>
            </div>
            <button class="hamburger-menu" onclick="toggleMobileMenu()">
                <span></span><span></span><span></span>
            </button>
        </div>
        <div class="menu-overlay" onclick="toggleMobileMenu()"></div>
        <div class="mobile-menu" id="mobile-menu">
            <div class="mobile-menu-header">
                <span class="tool-name">NexMAGI</span>
                <button class="hamburger-menu active" onclick="toggleMobileMenu()">
                    <span></span><span></span><span></span>
                </button>
            </div>
            <div class="mobile-menu-content">
                <div class="nav">${navHtml('')}</div>
                <div class="user-info">
                    <span id="mobile-username-display">admin</span>
                    <button class="btn btn-logout" onclick="logout()">ログアウト</button>
                </div>
            </div>
        </div>`;

    // content div の前に挿入
    const content = container.querySelector('.content');
    if (content) {
        content.insertAdjacentHTML('beforebegin', headerHtml);
    }

    // デスクトップナビ（#desktop-nav があれば中身を生成）
    const desktopNav = document.getElementById('desktop-nav');
    if (desktopNav) {
        desktopNav.insertAdjacentHTML('afterbegin', navHtml(''));
    }
}

// ---------------------------------------------------------------------------
// 共通ページネーション
// ---------------------------------------------------------------------------

/**
 * ページネーション HTML を生成して指定コンテナに描画する。
 *
 * @param {string} containerId - ページネーションを描画する要素の ID
 * @param {number} currentPage
 * @param {number} totalItems
 * @param {number} itemsPerPage
 * @param {string} loadFnName - ページ切替時に呼ぶグローバル関数名 (例: 'loadAccounts')
 */
function renderAdminPagination(containerId, currentPage, totalItems, itemsPerPage, loadFnName) {
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

// ---------------------------------------------------------------------------
// 共通 SVG アイコン・ステータスバッジ
// ---------------------------------------------------------------------------

const ADMIN_ICONS = {
    check: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#28a745" style="flex-shrink: 0;"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>`,
    cross: `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="#dc3545" style="flex-shrink: 0;"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`,
};

/** 有効/無効ステータスバッジ HTML を返す */
function statusBadgeHtml(isActive) {
    const icon = isActive ? ADMIN_ICONS.check : ADMIN_ICONS.cross;
    const color = isActive ? '#28a745' : '#dc3545';
    const label = isActive ? '有効' : '無効';
    return `<div style="display:flex;align-items:center;gap:6px;">${icon}<span style="color:${color};font-weight:${isActive ? 'bold' : 'normal'};">${label}</span></div>`;
}

/** 実行ステータス色付き span を返す */
function executionStatusHtml(status) {
    const colors = { success: '#28a745', error: '#dc3545', cancelled: '#ffc107', pending: '#7c3aed', processing: '#7c3aed', pending_local: '#7c3aed' };
    const color = colors[status] || 'var(--content-text-muted)';
    return `<span style="color:${color}">${escapeHtmlAdmin(status)}</span>`;
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
document.addEventListener('DOMContentLoaded', function() {
    const mobileNavItems = document.querySelectorAll('.mobile-menu .nav-item');
    mobileNavItems.forEach(item => {
        item.addEventListener('click', function() {
            // 少し遅延させてからメニューを閉じる（ページ遷移前に閉じる）
            setTimeout(() => {
                toggleMobileMenu();
            }, 100);
        });
    });

    // モバイルメニューのログアウトボタンクリック時にメニューを閉じる
    const mobileLogoutBtn = document.querySelector('.mobile-menu .btn-logout');
    if (mobileLogoutBtn) {
        mobileLogoutBtn.addEventListener('click', function() {
            setTimeout(() => {
                toggleMobileMenu();
            }, 100);
        });
    }
});

