// Runtime resolver: given a workflow/group/skill/step execution_config
// chain, compute the *effective* runtime badge that will be shown to
// the user before execution starts.
//
// Inheritance chain (top -> bottom, later overrides earlier):
//   workflow.config_json        (WorkflowListItem.config_json)
//   group.config_json           (WorkflowGroupItem.config_json)
//   skill.config_json           (Skill.config_json — the skill default)
//   step.config_json            (WorkflowSkill.config_json — per-step override)
//
// Each level's `config_json` wraps an `execution_config` object whose
// `execution.execution_kind` is one of: "provider" | "external_cli" |
// "auto". Lower levels override the higher levels block-by-block; we
// mirror the Python merge logic loosely enough to pick a single kind
// for display purposes.
//
// We intentionally keep this file plain ES5 + IIFE so it can be loaded
// from any page (admin or user) via a regular <script> tag without a
// bundler.

(function () {
    'use strict';

    function _execBlock(cfg) {
        if (!cfg || typeof cfg !== 'object') return null;
        var wrapped = cfg.execution_config || cfg;
        if (!wrapped || typeof wrapped !== 'object') return null;
        return wrapped.execution || null;
    }

    /**
     * Resolve the effective runtime for a step.
     *
     * @param {object} ctx
     * @param {object=} ctx.workflow   workflow-level container (with config_json)
     * @param {object=} ctx.group      group-level container (with config_json)
     * @param {object=} ctx.skill      skill default container (with config_json)
     * @param {object=} ctx.step       step-level container (with config_json)
     * @returns {{
     *   kind: string,            // "api" | "cli" | "auto"
     *   adapter: string|null,    // preferred_adapter when kind=cli
     *   runtimeHint: string|null,// cli_runtime_hint when kind=cli
     *   label: string,           // short label for the badge ("API", "CLI: codex-local", ...)
     *   color: string,           // chip color hex
     *   source: string,          // which level decided the kind ("workflow"|"group"|"skill"|"step"|"default")
     * }}
     */
    function resolveEffectiveRuntime(ctx) {
        ctx = ctx || {};
        var layers = [
            { key: 'workflow', cfg: ctx.workflow && ctx.workflow.config_json },
            { key: 'group',    cfg: ctx.group    && ctx.group.config_json },
            { key: 'skill',    cfg: ctx.skill    && ctx.skill.config_json },
            { key: 'step',     cfg: ctx.step     && ctx.step.config_json },
        ];

        var effective = {
            kind: null,
            adapter: null,
            runtimeHint: null,
            cliModel: null,
            source: 'default',
        };
        // Walk top -> bottom; later layer overrides if it has an
        // execution.execution_kind set. preferred_adapter/runtime_hint/
        // cli_model follow whichever layer wrote them last.
        for (var i = 0; i < layers.length; i++) {
            var exec = _execBlock(layers[i].cfg);
            if (!exec) continue;
            if (exec.execution_kind) {
                effective.kind = exec.execution_kind;
                effective.source = layers[i].key;
            }
            if (exec.preferred_adapter) effective.adapter = exec.preferred_adapter;
            if (exec.cli_runtime_hint) effective.runtimeHint = exec.cli_runtime_hint;
            if (exec.cli_model) effective.cliModel = exec.cli_model;
        }

        var normKind;
        if (effective.kind === 'external_cli') normKind = 'cli';
        else if (effective.kind === 'provider') normKind = 'api';
        else if (effective.kind === 'auto' || !effective.kind) normKind = 'auto';
        else normKind = effective.kind;

        // Match the runtime-badge.js color palette so the predictive
        // chip (this file) and the post-execution chip share one look.
        // Label = "API" / "CLI: claude" / "CLI: codex" / "CLI: generic".
        // adapter ids carry a "-local" suffix that we strip for display.
        function _shortRuntime() {
            if (effective.runtimeHint === 'claude_code') return 'claude';
            if (effective.runtimeHint === 'codex') return 'codex';
            if (effective.runtimeHint === 'generic') return 'generic';
            var ad = effective.adapter || '';
            if (ad.indexOf('claude') === 0) return 'claude';
            if (ad.indexOf('codex') === 0) return 'codex';
            if (ad.indexOf('generic') === 0) return 'generic';
            return ad || 'external';
        }
        var label, bg, color;
        if (normKind === 'cli') {
            var short = _shortRuntime();
            label = 'CLI: ' + short;
            if (short === 'claude') { bg = '#fef3c7'; color = '#92400e'; }
            else if (short === 'codex') { bg = '#dbeafe'; color = '#1e40af'; }
            else { bg = '#e5e7eb'; color = '#374151'; }
        } else if (normKind === 'api') {
            label = 'API';
            bg = '#dcfce7';
            color = '#166534';
        } else {
            label = 'auto';
            bg = '#e5e7eb';
            color = '#9ca3af';
        }

        return {
            kind: normKind,
            adapter: effective.adapter,
            runtimeHint: effective.runtimeHint,
            cliModel: effective.cliModel,
            label: label,
            bg: bg,
            color: color,
            source: effective.source,
        };
    }

    // Derive a runtime name like "claude_code" / "codex" / "generic"
    // when only the adapter id is known. Mirrors the Python side's
    // _apply_step_config_to_task name-prefix heuristic.
    function _runtimeNameFromAdapter(adapter) {
        if (!adapter) return null;
        if (adapter.indexOf('claude') === 0) return 'claude_code';
        if (adapter.indexOf('codex') === 0) return 'codex';
        if (adapter.indexOf('generic') === 0) return 'generic';
        return null;
    }

    /**
     * Pick the best "model name" string to show in compact UI:
     *  - CLI mode: returns the configured cli_model when set; otherwise
     *    the runtime name (claude_code / codex / generic) so users still
     *    see which CLI binary will run even when no model override exists.
     *  - API mode: returns fallbackApiModel (typically Skill.model_type)
     *    so existing behavior is preserved.
     *  - Auto mode: same as API.
     */
    function effectiveModelLabel(ctx, fallbackApiModel) {
        var r = resolveEffectiveRuntime(ctx);
        if (r.kind === 'cli') {
            if (r.cliModel) return r.cliModel;
            return r.runtimeHint || _runtimeNameFromAdapter(r.adapter) || 'cli';
        }
        return fallbackApiModel || '';
    }

    /**
     * Render a compact chip HTML string for the resolved runtime.
     * Safe to drop into innerHTML.
     */
    function renderResolvedRuntimeChip(ctx) {
        var r = resolveEffectiveRuntime(ctx);
        // Same chip shape as runtime-badge.js renderRuntimeBadge so the
        // pre-execution and post-execution badges are visually identical.
        return (
            '<span style="display:inline-block; padding:2px 8px; border-radius:999px;'
            + ' font-size:10px; font-weight:600;'
            + ' background:' + r.bg + '; color:' + r.color + ';"'
            + ' title="effective runtime (resolved from ' + r.source + ')">'
            + _esc(r.label)
            + '</span>'
        );
    }

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    window.runtimeResolver = {
        resolveEffectiveRuntime: resolveEffectiveRuntime,
        renderResolvedRuntimeChip: renderResolvedRuntimeChip,
        effectiveModelLabel: effectiveModelLabel,
    };
})();
