/**
 * SweetAlert2 共通設定
 * 全ページ（ユーザー・管理画面）で共通のポップアップデフォルトを適用
 * runtime-adapter.js の後、各ページJS の前に読み込む
 */
(function() {
    if (typeof Swal === 'undefined') return;

    const _origFire = Swal.fire.bind(Swal);
    Swal.fire = function(opts) {
        if (typeof opts === 'object' && opts !== null) {
            // ×ボタンを左上に表示（デフォルト）
            if (opts.showCloseButton === undefined) {
                opts.showCloseButton = true;
            }

            // 「閉じる」のみのconfirmButtonは非表示（×で閉じる）
            const closeLabels = ['閉じる', 'Close'];
            if (closeLabels.includes(opts.confirmButtonText)) {
                if (!opts.showCancelButton && !opts.showDenyButton) {
                    opts.showConfirmButton = false;
                }
            }

            // cancelButtonTextが「閉じる」の場合も非表示
            if (closeLabels.includes(opts.cancelButtonText)) {
                opts.showCancelButton = false;
            }
        }
        return _origFire(opts);
    };
})();
