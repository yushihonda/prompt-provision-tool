// 共通の管理者用JavaScript関数

const API_BASE = window.location.origin;

// 認証チェック
function checkAuth() {
    const token = localStorage.getItem('token');
    const username = localStorage.getItem('username');

    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    // ユーザー名を表示
    const usernameDisplay = document.getElementById('username-display');
    if (usernameDisplay && username) {
        usernameDisplay.textContent = username;
    }
}

// ログアウト
function logout() {
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    window.location.href = 'login.html';
}

// API リクエスト
async function apiRequest(endpoint, options = {}) {
    const token = localStorage.getItem('token');

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
            localStorage.removeItem('token');
            window.location.href = 'login.html';
            return;
        }

        // レスポンスのContent-Typeをチェック
        const contentType = response.headers.get('content-type');
        let data;

        if (contentType && contentType.includes('application/json')) {
            data = await response.json();
        } else {
            // JSONでない場合はテキストとして取得
            const text = await response.text();
            console.error('Non-JSON response:', text);
            throw new Error(`サーバーエラー (${response.status}): 予期しないレスポンス形式`);
        }

        if (!response.ok) {
            throw new Error(data.detail || 'リクエストに失敗しました');
        }

        return data;
    } catch (error) {
        console.error('API request error:', error);
        throw error;
    }
}

// アラート表示
function showAlert(message, type = 'info') {
    const alertContainer = document.getElementById('alert-container');
    if (!alertContainer) return;

    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.textContent = message;

    alertContainer.innerHTML = '';
    alertContainer.appendChild(alert);

    // 5秒後に自動削除
    setTimeout(() => {
        alert.remove();
    }, 5000);
}

// モーダル表示
function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
    }
}

// モーダル非表示
function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
    }
}

// 確認ダイアログ
function confirmAction(message) {
    return confirm(message);
}

// 日時フォーマット
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('ja-JP');
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

