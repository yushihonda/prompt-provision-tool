// ユーザー ログイン画面 JavaScript

const API_BASE = window.location.origin;

function _loginEsc(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// 前回の認証エラーを確認
window.addEventListener('DOMContentLoaded', () => {
    const authError = localStorage.getItem('auth_error');
    if (authError) {
        try {
            const error = JSON.parse(authError);
            const respSnippet = error.response ? String(error.response).substring(0, 200) : '';
            Swal.fire({
                title: '認証エラー',
                html: `
                    <div class="swal-auth-error" style="text-align:left;font-size:14px;line-height:1.5;">
                        <p style="margin:0 0 8px;"><span style="color:rgba(255,255,255,0.55);font-size:12px;text-transform:uppercase;">タイプ</span><br>${_loginEsc(error.type)}</p>
                        <p style="margin:0 0 8px;"><span style="color:rgba(255,255,255,0.55);font-size:12px;text-transform:uppercase;">メッセージ</span><br>${_loginEsc(error.message || '不明なエラー')}</p>
                        ${error.status ? `<p style="margin:0 0 8px;"><span style="color:rgba(255,255,255,0.55);font-size:12px;text-transform:uppercase;">ステータス</span><br>${_loginEsc(error.status)}</p>` : ''}
                        ${respSnippet ? `<p style="margin:0 0 8px;"><span style="color:rgba(255,255,255,0.55);font-size:12px;text-transform:uppercase;">レスポンス抜粋</span><br>${_loginEsc(respSnippet)}</p>` : ''}
                        <p style="margin:0 0 10px;"><span style="color:rgba(255,255,255,0.55);font-size:12px;text-transform:uppercase;">時刻</span><br>${_loginEsc(new Date(error.timestamp).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' }))}</p>
                        <details style="margin-top: 10px;">
                            <summary style="cursor:pointer;color:rgba(199,182,255,0.95);">詳細ログ（展開）</summary>
                            <pre style="text-align: left; font-size: 11px; max-height: 200px; overflow: auto; margin-top:8px; padding:10px; border-radius:8px; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.1);">${_loginEsc(JSON.stringify(error, null, 2))}</pre>
                        </details>
                    </div>
                `,
                icon: 'error',
                width: 'min(92vw, 520px)',
                confirmButtonText: '閉じる',
                confirmButtonColor: '#7c3aed',
                customClass: { popup: 'swal-wide' }
            });
            // エラー情報をクリア
            localStorage.removeItem('auth_error');
        } catch (e) {
            // エラー情報のパースに失敗した場合は無視
        }
    }
});

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

                    // ユーザーログイン画面ではCHILDアカウントのみ許可
                    if (accountType !== 'CHILD') {
                        showAlert('このアカウントはユーザーアカウントではありません。管理者ログイン画面をご利用ください。', 'error');
                        return;
                    }
                } catch (e) {
                    console.error('Token decode error:', e);
                }
            }

            // トークンをセッションストレージに保存
            sessionStorage.setItem('token', data.access_token);
            sessionStorage.setItem('username', username);

            // ダッシュボードへリダイレクト
            window.location.href = 'dashboard.html';
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

    const longMessage = message && String(message).length > 220;
    await Swal.fire({
        title: icon === 'error' ? 'エラー' : icon === 'success' ? '成功' : icon === 'warning' ? '警告' : '情報',
        text: message,
        icon: icon,
        confirmButtonText: '閉じる',
        confirmButtonColor: '#7c3aed',
        timer: longMessage ? undefined : 3000,
        timerProgressBar: !longMessage
    });
}

