// 共通のユーザー用JavaScript関数

// API_BASEの設定（本番環境ではNginx経由でアクセス）
const API_BASE = window.location.origin;

// 認証チェック（非同期）
async function checkAuth() {
    const token = sessionStorage.getItem('token');
    const username = sessionStorage.getItem('username');

    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    // トークンの有効性をサーバー側で確認
    try {
        // ユーザー側のAPIエンドポイントを呼び出してトークンを検証
        const response = await fetch(`${API_BASE}/api/user/prompts?skip=0&limit=1`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });

        if (response.status === 401) {
            // トークンが無効な場合
            const errorText = await response.text().catch(() => '');
            // エラー情報をlocalStorageに保存（リダイレクト後も確認できるように）
            localStorage.setItem('auth_error', JSON.stringify({
                type: '401',
                message: 'トークンが無効です',
                response: errorText,
                timestamp: new Date().toISOString()
            }));
            sessionStorage.removeItem('token');
            sessionStorage.removeItem('username');
            window.location.href = 'login.html';
            return;
        }

        if (!response.ok) {
            // その他のエラー
            const errorText = await response.text().catch(() => '');
            // エラー情報をlocalStorageに保存
            localStorage.setItem('auth_error', JSON.stringify({
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
        // エラー情報をlocalStorageに保存
        localStorage.setItem('auth_error', JSON.stringify({
            type: 'exception',
            message: error.message,
            stack: error.stack,
            timestamp: new Date().toISOString()
        }));
        sessionStorage.removeItem('token');
        sessionStorage.removeItem('username');
        window.location.href = 'login.html';
    }
}

// ログアウト
async function logout() {
    const result = await Swal.fire({
        title: 'ログアウト',
        text: 'ログアウトしますか？',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#6c757d',
        confirmButtonText: 'ログアウト',
        cancelButtonText: 'キャンセル'
    });

    if (result.isConfirmed) {
        sessionStorage.removeItem('token');
        sessionStorage.removeItem('username');
        await Swal.fire({
            title: 'ログアウトしました',
            text: 'ログイン画面に戻ります',
            icon: 'success',
            timer: 1500,
            showConfirmButton: false
        });
        window.location.href = 'login.html';
    }
}

// API リクエスト
async function apiRequest(endpoint, options = {}) {
    const token = sessionStorage.getItem('token');

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
        const response = await fetch(`${API_BASE}${endpoint}`, mergedOptions);

        // 認証エラーの場合はログイン画面へ
        if (response.status === 401) {
            sessionStorage.removeItem('token');
            sessionStorage.removeItem('username');
            window.location.href = 'login.html';
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
            throw new Error(data?.detail || 'リクエストに失敗しました');
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
        confirmButtonText: 'OK',
        timer: 3000,
        timerProgressBar: true
    });
}

// 日時フォーマット
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('ja-JP');
}

// URLパラメータ取得
function getQueryParam(name) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(name);
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

