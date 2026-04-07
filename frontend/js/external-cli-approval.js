// External CLI approval modal — subscribes to
// `external_cli:approval_requested` events and prompts the user to
// allow or reject a shell-capable step at runtime.
//
// Loaded on any page that can trigger CLI execution (cli-terminal,
// workflow-execute). The modal uses SweetAlert2 so it inherits the
// existing app styling.

(function () {
    'use strict';

    const tauri = window.__TAURI__;
    if (!tauri) return;

    async function subscribe() {
        if (!tauri.event || !tauri.event.listen) return;
        await tauri.event.listen('external_cli:approval_requested', async function (e) {
            const p = e.payload || {};
            if (typeof Swal === 'undefined') {
                console.warn('[external-cli-approval] Swal not loaded, auto-rejecting');
                await reject(p.approval_id);
                return;
            }
            const summary = p.summary || 'This step wants to run shell commands.';
            const promptPreview = p.prompt_preview || '';
            const html =
                '<div style="text-align:left;">'
                + '<p style="font-size:13px; margin-bottom:10px;">'
                + escapeHtml(summary)
                + '</p>'
                + '<div style="font-size:11px; color:#6b7280; margin-bottom:6px;">task: '
                + escapeHtml(p.task_id || '-') + ' / runtime: '
                + escapeHtml(p.runtime || '-') + '</div>'
                + '<div style="font-size:11px; color:#6b7280; margin-bottom:10px;">cwd: <code>'
                + escapeHtml(p.cwd || '-') + '</code></div>'
                + (promptPreview
                    ? '<pre style="background:#f3f4f6; padding:8px; border-radius:6px; font-size:11px; white-space:pre-wrap; max-height:200px; overflow-y:auto;">'
                        + escapeHtml(promptPreview) + '</pre>'
                    : '')
                + '<p style="font-size:11px; color:#92400e; margin-top:10px;">'
                + '⚠ 承認するとこの実行でシェルコマンド実行が許可されます。5分で自動拒否。'
                + '</p>'
                + '</div>';

            const result = await Swal.fire({
                title: 'シェル実行を許可しますか？',
                html: html,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: '許可',
                cancelButtonText: '拒否',
                confirmButtonColor: '#dc2626',
                cancelButtonColor: '#6b7280',
                width: '640px',
                allowOutsideClick: false,
                allowEscapeKey: false,
            });
            if (result.isConfirmed) {
                await approve(p.approval_id);
            } else {
                await reject(p.approval_id);
            }
        });
    }

    async function approve(approvalId) {
        try {
            await tauri.core.invoke('external_cli_approve', {
                req: { approval_id: approvalId },
            });
        } catch (e) {
            console.error('external_cli_approve failed', e);
        }
    }

    async function reject(approvalId) {
        try {
            await tauri.core.invoke('external_cli_reject', {
                req: { approval_id: approvalId },
            });
        } catch (e) {
            console.error('external_cli_reject failed', e);
        }
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    document.addEventListener('DOMContentLoaded', function () {
        subscribe();
    });
})();
