// 管理者 ダッシュボード画面 JavaScript

async function loadDashboardStats() {
    try {
        const stats = await apiRequest('/api/admin/dashboard');

        document.getElementById('total-accounts').textContent = stats.total_accounts;
        document.getElementById('total-skills').textContent = stats.total_skills;
        document.getElementById('total-executions').textContent = stats.total_executions;
    } catch (error) {
        showAlert('統計情報の読み込みに失敗しました', 'error');
        console.error('Dashboard error:', error);
    }
}

// ページ読み込み時に実行
(async () => {
    initAdminLayout('dashboard.html');
    await checkAuth();
    loadDashboardStats();
})();

