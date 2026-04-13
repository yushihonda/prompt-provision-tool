// External CLI 承認モーダル — `external_cli:approval_requested` イベントを
// 購読し、シェル実行可能なステップの許可・拒否をユーザーに確認する。
//
// CLI 実行をトリガーできるページ（cli-terminal, workflow-execute）で
// 読み込まれる。モーダルは SweetAlert2 を使用し、既存のアプリスタイルを継承する。

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
                await approve(p.approval_id, p);
            } else {
                await reject(p.approval_id, p);
            }
        });
    }

    async function approve(approvalId, payload) {
        try {
            // バックエンドと同期する統合コマンドを優先
            await submitWorkflowApproval(approvalId, 'granted', payload);
        } catch (e) {
            // レガシーコマンドへフォールバック
            try {
                await tauri.core.invoke('external_cli_approve', {
                    req: { approval_id: approvalId },
                });
            } catch (e2) {
                console.error('external_cli_approve failed', e2);
            }
        }
    }

    async function reject(approvalId, payload) {
        try {
            await submitWorkflowApproval(approvalId, 'rejected', payload);
        } catch (e) {
            try {
                await tauri.core.invoke('external_cli_reject', {
                    req: { approval_id: approvalId },
                });
            } catch (e2) {
                console.error('external_cli_reject failed', e2);
            }
        }
    }

    async function submitWorkflowApproval(approvalId, decision, payload) {
        const rt = window.NexMAGIRuntime;
        const session = rt ? rt.getAuthSession() : null;
        const apiBase = rt ? rt.getApiBase() : '';
        const token = session ? (await session).token : '';
        // イベントペイロードまたはグローバル状態から workflow_execution_id を抽出
        const wfExecId = (payload && payload.workflow_run_id)
            ? parseInt(payload.workflow_run_id, 10)
            : (window.workflowExecutionId || 0);
        await tauri.core.invoke('submit_workflow_approval_response', {
            req: {
                approval_id: approvalId,
                decision: decision,
                api_base: apiBase,
                auth_token: token,
                workflow_execution_id: wfExecId,
                step_id: (payload && payload.task_id) || null,
                adapter_id: (payload && payload.adapter_id) || null,
                runtime: (payload && payload.runtime) || null,
                cwd: (payload && payload.cwd) || null,
                prompt_preview: (payload && payload.prompt_preview) || null,
            },
        });
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
