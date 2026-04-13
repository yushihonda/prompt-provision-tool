// ワークフローステップ「実行ランタイム」フォームヘルパー。
//
// skills.js（またはワークフロースキルエディターがある場所）での使用法:
//
//   // 現在の値でフォームを構築:
//   const html = window.executionConfigForm.renderForm(currentExecutionConfig);
//   // ...DOM に注入...
//
//   // 保存時に値を収集:
//   const newExecutionConfig = window.executionConfigForm.collectForm(formRoot);
//   skillItem.config_json = skillItem.config_json || {};
//   skillItem.config_json.execution_config = newExecutionConfig;
//
// 形状は backend/app/services/workflow_step_schema.py の
// `StepExecutionConfig` に対応。デフォルト値は「レガシー」と同等で、
// このセクションを変更しないステップの動作は変わらない。

(function () {
    'use strict';

    const RUNTIME_OPTIONS = [
        { value: 'auto', label: '自動 (既存のルーティング)' },
        { value: 'provider', label: 'HTTP provider (OpenAI / Gemini / Ollama 等)' },
        { value: 'external_cli', label: 'External CLI (claude / codex)' },
    ];

    const ADAPTER_OPTIONS = [
        { value: '', label: '(指定なし)' },
        { value: 'claude-code-local', label: 'Claude Code (claude-code-local)' },
        { value: 'codex-local', label: 'OpenAI Codex (codex-local)' },
        { value: 'generic-cli', label: 'Generic (generic-cli)' },
    ];

    // CLI 側のモデルリスト。選択されたアダプターに基づいて cli_model
    // セレクターを設定し、各 CLI バイナリが実際に理解するモデルのみを
    // ユーザーに表示する。Rust アダプターは選択された値を
    // --model (Claude) または -m (Codex) 経由で転送する。
    const CLI_MODEL_OPTIONS = {
        'claude-code-local': [
            { value: '', label: '(CLI 既定)' },
            { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
            { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
            { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
        ],
        'codex-local': [
            { value: '', label: '(CLI 既定)' },
            { value: 'gpt-5-codex', label: 'GPT-5 Codex' },
            { value: 'o4-mini', label: 'o4-mini' },
        ],
        'generic-cli': [
            { value: '', label: '(指定なし)' },
        ],
    };

    function modelOptionsFor(adapterId) {
        return CLI_MODEL_OPTIONS[adapterId] || [{ value: '', label: '(指定なし)' }];
    }

    const CAPABILITY_OPTIONS = [
        'file_read', 'file_write', 'shell_exec', 'workspace_aware',
        'streaming_stdout', 'streaming_stderr', 'diff_review',
        'local_auth_session', 'json_output', 'pty',
    ];

    const WORKSPACE_OPTIONS = [
        { value: 'none', label: 'なし' },
        { value: 'temp_dir', label: 'temp_dir (使い捨てワークスペース)' },
        { value: 'shared', label: 'shared (共有)' },
        { value: 'worktree', label: 'worktree (git worktree 分離)' },
    ];

    const APPROVAL_OPTIONS = [
        { value: 'read_only', label: 'read_only (読み取りのみ)' },
        { value: 'ask_before_shell', label: 'ask_before_shell (確認モーダルは未実装)' },
        { value: 'plan_required', label: 'plan_required (実行前に計画承認)' },
        { value: 'allow_shell', label: 'allow_shell (シェル許可)' },
        { value: 'allow_write', label: 'allow_write (ファイル書込み許可)' },
    ];

    function defaultConfig() {
        return {
            schema_version: '1.0',
            execution: {
                execution_kind: 'auto',
                preferred_adapter: '',
                candidate_adapters: [],
                required_capabilities: [],
                cli_runtime_hint: null,
                cwd_hint: null,
                cli_model: null,
            },
            workspace: {
                workspace_policy: 'none',
                share_with_steps: [],
                promote_on: 'accepted',
                cleanup_on: 'failed',
            },
            approval: {
                policy: 'read_only',
                allow_writes: false,
                allow_shell: false,
            },
            artifact_contract: {
                expected_type: null,
                must_include_files: false,
                must_include_diff: false,
            },
        };
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function renderSelect(name, options, current) {
        return (
            '<select data-exec-field="' + name + '" style="width:100%; padding:8px 12px; border:1px solid rgba(0,0,0,0.1); border-radius:8px; font-size:13px;">'
            + options.map(function (o) {
                const v = typeof o === 'string' ? o : o.value;
                const l = typeof o === 'string' ? o : o.label;
                const sel = String(v) === String(current || '') ? ' selected' : '';
                return '<option value="' + escapeHtml(v) + '"' + sel + '>' + escapeHtml(l) + '</option>';
            }).join('')
            + '</select>'
        );
    }

    function renderCapabilityChecks(currentList) {
        const set = new Set(currentList || []);
        return CAPABILITY_OPTIONS.map(function (cap) {
            const checked = set.has(cap) ? ' checked' : '';
            return (
                '<label style="display:inline-flex; align-items:center; gap:4px; margin-right:12px; font-size:12px;">'
                + '<input type="checkbox" data-exec-capability="' + cap + '"' + checked + '> ' + escapeHtml(cap)
                + '</label>'
            );
        }).join('');
    }

    function renderForm(existingConfig) {
        const cfg = mergeWithDefaults(existingConfig);
        return (
            '<div data-exec-config-root style="border:1px solid rgba(0,0,0,0.1); border-radius:12px; padding:16px; margin-top:12px;">'
            + '<h4 style="margin:0 0 12px 0; font-size:14px;">実行ランタイム</h4>'

            + '<div style="display:grid; gap:8px;">'
            + '<label style="font-size:12px; color:#6b7280;">実行種別</label>'
            + renderSelect('execution.execution_kind', RUNTIME_OPTIONS, cfg.execution.execution_kind)

            + '<label style="font-size:12px; color:#6b7280;">推奨アダプター</label>'
            + renderSelect('execution.preferred_adapter', ADAPTER_OPTIONS, cfg.execution.preferred_adapter || '')

            + '<label style="font-size:12px; color:#6b7280;">CLI モデル (CLI バイナリに渡す --model / -m)</label>'
            + '<div data-exec-cli-model-mount>'
            + renderSelect('execution.cli_model', modelOptionsFor(cfg.execution.preferred_adapter || ''), cfg.execution.cli_model || '')
            + '</div>'

            + '<label style="font-size:12px; color:#6b7280;">cwd ヒント (絶対パス、home配下のみ許可)</label>'
            + '<input type="text" data-exec-field="execution.cwd_hint" value="' + escapeHtml(cfg.execution.cwd_hint || '') + '" placeholder="/Users/you/your-project" style="padding:8px 12px; border:1px solid rgba(0,0,0,0.1); border-radius:8px; font-size:13px; font-family:monospace;">'

            + '<label style="font-size:12px; color:#6b7280;">必須 capability</label>'
            + '<div data-exec-capabilities-row>' + renderCapabilityChecks(cfg.execution.required_capabilities) + '</div>'

            + '<label style="font-size:12px; color:#6b7280;">ワークスペースポリシー</label>'
            + renderSelect('workspace.workspace_policy', WORKSPACE_OPTIONS, cfg.workspace.workspace_policy)

            + '<label style="font-size:12px; color:#6b7280;">共有元ステップ (task_id をカンマ区切り)</label>'
            + '<input type="text" data-exec-field="workspace.share_with_steps" value="' + escapeHtml((cfg.workspace.share_with_steps || []).join(',')) + '" placeholder="step_42,step_43" style="padding:8px 12px; border:1px solid rgba(0,0,0,0.1); border-radius:8px; font-size:13px;">'

            + '<label style="font-size:12px; color:#6b7280;">承認ポリシー</label>'
            + renderSelect('approval.policy', APPROVAL_OPTIONS, cfg.approval.policy)

            + '<label style="font-size:12px; display:inline-flex; align-items:center; gap:6px;">'
            + '<input type="checkbox" data-exec-field="approval.allow_writes"' + (cfg.approval.allow_writes ? ' checked' : '') + '> ファイル書込み許可'
            + '</label>'
            + '<label style="font-size:12px; display:inline-flex; align-items:center; gap:6px;">'
            + '<input type="checkbox" data-exec-field="approval.allow_shell"' + (cfg.approval.allow_shell ? ' checked' : '') + '> シェル実行許可'
            + '</label>'
            + '</div>'
            + '</div>'
        );
    }

    function mergeWithDefaults(existing) {
        const base = defaultConfig();
        if (!existing || typeof existing !== 'object') return base;
        return {
            schema_version: existing.schema_version || base.schema_version,
            execution: Object.assign({}, base.execution, existing.execution || {}),
            workspace: Object.assign({}, base.workspace, existing.workspace || {}),
            approval: Object.assign({}, base.approval, existing.approval || {}),
            artifact_contract: Object.assign({}, base.artifact_contract, existing.artifact_contract || {}),
        };
    }

    function collectForm(rootEl) {
        if (!rootEl) return defaultConfig();
        const out = defaultConfig();
        const fields = rootEl.querySelectorAll('[data-exec-field]');
        fields.forEach(function (el) {
            const name = el.getAttribute('data-exec-field');
            const parts = name.split('.');
            let value;
            if (el.type === 'checkbox') value = !!el.checked;
            else value = el.value;
            // share_with_steps のカンマ区切りリストの特別処理。
            if (name === 'workspace.share_with_steps') {
                value = String(value || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
            }
            // 空の preferred_adapter / cwd_hint / cli_model を null にする。
            if ((name === 'execution.preferred_adapter'
                 || name === 'execution.cwd_hint'
                 || name === 'execution.cli_model') && !value) {
                value = null;
            }
            // パーツに沿って out オブジェクトの中を辿る。
            let cur = out;
            for (let i = 0; i < parts.length - 1; i++) {
                cur = cur[parts[i]];
            }
            cur[parts[parts.length - 1]] = value;
        });
        const caps = [];
        rootEl.querySelectorAll('[data-exec-capability]').forEach(function (el) {
            if (el.checked) caps.push(el.getAttribute('data-exec-capability'));
        });
        out.execution.required_capabilities = caps;
        return out;
    }

    // 新しくレンダリングされたフォームルートに動的挙動を接続する:
    // ユーザーが preferred_adapter ドロップダウンを変更した際、
    // CLI モデルのサブセレクトを新しいアダプターのモデルリストに
    // 合わせて差し替える。冪等 — 同じルートに複数回呼んでも安全。
    function attachDynamicWiring(rootEl) {
        if (!rootEl) return;
        const adapterSel = rootEl.querySelector('select[data-exec-field="execution.preferred_adapter"]');
        const modelMount = rootEl.querySelector('[data-exec-cli-model-mount]');
        if (!adapterSel || !modelMount) return;
        if (adapterSel._execModelWired) return;
        adapterSel._execModelWired = true;
        adapterSel.addEventListener('change', function () {
            const adapterId = adapterSel.value || '';
            // 現在の選択が新しいリストにまだ存在する場合は保持する。
            const currentModelSel = modelMount.querySelector('select[data-exec-field="execution.cli_model"]');
            const currentValue = currentModelSel ? currentModelSel.value : '';
            const newOptions = modelOptionsFor(adapterId);
            const stillValid = newOptions.some(function (o) { return String(o.value) === String(currentValue); });
            modelMount.innerHTML = renderSelect(
                'execution.cli_model',
                newOptions,
                stillValid ? currentValue : ''
            );
        });
    }

    window.executionConfigForm = {
        renderForm: renderForm,
        collectForm: collectForm,
        defaultConfig: defaultConfig,
        mergeWithDefaults: mergeWithDefaults,
        attachDynamicWiring: attachDynamicWiring,
        modelOptionsFor: modelOptionsFor,
    };
})();
