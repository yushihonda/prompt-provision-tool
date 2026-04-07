// Runtime badge helper.
// Renders a compact "runtime" chip from artifact extra_metadata so the
// workflow timeline / execution detail can show which engine ran each
// step (claude_code / codex / ollama / openai / gemini / etc.).
//
// Both runtime kinds (http_provider / external_cli) carry the same
// base keys (`step_execution_kind`, `runtime`, `adapter_name`,
// `selection_reason`) — see backend/app/services/completion_service.py
// build_external_cli_provenance / build_http_provider_provenance.

(function () {
    'use strict';

    const STYLE_BY_RUNTIME = {
        claude_code:    { bg: '#fef3c7', fg: '#92400e', label: 'cli://claude' },
        codex:          { bg: '#dbeafe', fg: '#1e40af', label: 'cli://codex' },
        generic:        { bg: '#e5e7eb', fg: '#374151', label: 'cli://generic' },
        local_preferred:{ bg: '#dcfce7', fg: '#166534', label: 'http://local' },
        local_only:     { bg: '#dcfce7', fg: '#166534', label: 'http://local' },
        remote_only:    { bg: '#ede9fe', fg: '#5b21b6', label: 'http://remote' },
        hybrid_auto:    { bg: '#ede9fe', fg: '#5b21b6', label: 'http://auto' },
    };

    function styleFor(runtime) {
        return STYLE_BY_RUNTIME[runtime] || { bg: '#e5e7eb', fg: '#374151', label: runtime || 'unknown' };
    }

    /**
     * Render a runtime chip from a flat artifact metadata dict.
     * Returns an HTML string suitable for innerHTML embedding.
     */
    function renderRuntimeBadge(artifactMeta) {
        if (!artifactMeta || typeof artifactMeta !== 'object') return '';
        const kind = artifactMeta.step_execution_kind || artifactMeta.execution_kind;
        const runtime = artifactMeta.runtime;
        const adapter = artifactMeta.adapter_name || artifactMeta.adapter_id || '';
        if (!kind && !runtime) return '';
        const style = styleFor(runtime);
        const label = style.label;
        const adapterSuffix = adapter ? ` <span style="opacity:0.7;">(${escapeHtml(adapter)})</span>` : '';
        return (
            '<span style="display:inline-block; padding:2px 8px; border-radius:999px;'
            + ' font-size:10px; font-weight:600;'
            + ' background:' + style.bg + '; color:' + style.fg + ';">'
            + escapeHtml(label) + adapterSuffix
            + '</span>'
        );
    }

    /**
     * Render a one-line provenance summary (badge + selection_reason +
     * cli_status / fallback_applied) for the execution detail modal.
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
