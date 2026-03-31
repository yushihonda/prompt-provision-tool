// 管理者 ログイン画面 JavaScript

const API_BASE = window.location.origin;

// リロード時はリダイレクトしない（セッション管理）

document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;

    try {
        const formData = new FormData();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            body: formData
        });

        // レスポンスのContent-Typeをチェック
        const contentType = response.headers.get('content-type');
        let data;

        if (contentType && contentType.includes('application/json')) {
            data = await response.json();
        } else {
            // JSONでない場合はテキストとして取得
            const text = await response.text();
            console.error('Non-JSON response:', text);
            throw new Error(`サーバーエラー (${response.status}): JSONレスポンスが期待されましたが、テキストが返されました`);
        }

        if (response.ok) {
            // JWTトークンをデコードしてアカウントタイプを確認
            const tokenParts = data.access_token.split('.');
            if (tokenParts.length === 3) {
                try {
                    const payload = JSON.parse(atob(tokenParts[1]));
                    const accountType = payload.type;

                    // 管理者ログイン画面ではPARENTアカウントのみ許可
                    if (accountType !== 'PARENT') {
                        showAlert('このアカウントは管理者アカウントではありません。ユーザーログイン画面をご利用ください。', 'error');
                        return;
                    }
                } catch (e) {
                    console.error('Token decode error:', e);
                }
            }

            // トークンをセッションストレージに保存
            sessionStorage.setItem('token', data.access_token);
            sessionStorage.setItem('username', username);

            // スキル管理へリダイレクト
            window.location.href = 'skills.html';
        } else {
            showAlert(data.detail || 'ログインに失敗しました', 'error');
        }
    } catch (error) {
        showAlert(`サーバーとの通信に失敗しました: ${error.message}`, 'error');
        console.error('Login error:', error);
    }
});

async function showAlert(message, type) {
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
        confirmButtonText: '閉じる',
        confirmButtonColor: '#9c27b0',
        timer: 3000,
        timerProgressBar: true
    });
}

