// ランタイムバッジヘルパー。
// アーティファクトの extra_metadata からコンパクトな「ランタイム」チップを
// レンダリングし、ワークフロータイムライン / 実行詳細で各ステップを
// どのエンジンが実行したか（claude_code / codex / ollama / openai / gemini 等）
// を表示できるようにする。
//
// 両方のランタイム種別（http_provider / external_cli）は同じベースキー
// （`step_execution_kind`, `runtime`, `adapter_name`, `selection_reason`）
// を持つ — backend/app/services/completion_service.py の
// build_external_cli_provenance / build_http_provider_provenance を参照。

(function () {
    'use strict';

    const STYLE_BY_RUNTIME = {
        claude_code:    { bg: '#fef3c7', fg: '#92400e', label: 'CLI: claude' },
        codex:          { bg: '#dbeafe', fg: '#1e40af', label: 'CLI: codex' },
        generic:        { bg: '#e5e7eb', fg: '#374151', label: 'CLI: generic' },
        // HTTP プロバイダーのバリアントはユーザーにとってすべて「API」。
        // remote/local/hybrid の区別はルーティング層の内部詳細であり、
        // UI には不要。CLI: claude（アンバー）とは異なる色を使い、
        // 視覚的に混同しないようにする。
        local_preferred:{ bg: '#dcfce7', fg: '#166534', label: 'API' },
        local_only:     { bg: '#dcfce7', fg: '#166534', label: 'API' },
        remote_only:    { bg: '#dcfce7', fg: '#166534', label: 'API' },
        hybrid_auto:    { bg: '#dcfce7', fg: '#166534', label: 'API' },
    };

    function styleFor(runtime) {
        return STYLE_BY_RUNTIME[runtime] || { bg: '#e5e7eb', fg: '#374151', label: runtime || 'unknown' };
    }

    /**
     * フラットなアーティファクトメタデータ辞書からランタイムチップをレンダリングする。
     * innerHTML 埋め込みに適した HTML 文字列を返す。
     */
    function renderRuntimeBadge(artifactMeta) {
        if (!artifactMeta || typeof artifactMeta !== 'object') return '';
        const kind = artifactMeta.step_execution_kind || artifactMeta.execution_kind;
        let runtime = artifactMeta.runtime;
        // レガシーの http_provider アーティファクトは selected_provider_mode のみ持ち
        // （`runtime` キーなし）、API バッジが表示されるよう手動でマッピングする。
        if (!runtime && artifactMeta.selected_provider_mode) {
            runtime = artifactMeta.selected_provider_mode;
        }
        if (!kind && !runtime && !artifactMeta.selected_provider_mode) return '';
        const style = styleFor(runtime);
        return (
            '<span style="display:inline-block; padding:2px 8px; border-radius:999px;'
            + ' font-size:10px; font-weight:600;'
            + ' background:' + style.bg + '; color:' + style.fg + ';">'
            + escapeHtml(style.label)
            + '</span>'
        );
    }

    /**
     * 実行詳細モーダル用の1行プロベナンスサマリー（バッジ + selection_reason +
     * cli_status / fallback_applied）をレンダリングする。
     */
    function renderRuntimeProvenanceLine(artifactMeta) {
        if (!artifactMeta || typeof artifactMeta !== 'object') return '';
        const badge = renderRuntimeBadge(artifactMeta);
        const reason = artifactMeta.selection_reason
            ? ' <span style="font-size:11px; color:#6b7280;">' + escapeHtml(artifactMeta.selection_reason) + '</span>'
            : '';
        const status = artifactMeta.cli_status
            ? ' <span style="font-size:11px; color:#6b7280;">cli=' + escapeHtml(artifactMeta.cli_status) + '</span>'
            : '';
        const fallback = artifactMeta.fallback_applied
            ? ' <span style="font-size:11px; color:#92400e;">fallback</span>'
            : '';
        return badge + reason + status + fallback;
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    window.runtimeBadge = {
        renderRuntimeBadge: renderRuntimeBadge,
        renderRuntimeProvenanceLine: renderRuntimeProvenanceLine,
        styleFor: styleFor,
    };
})();
