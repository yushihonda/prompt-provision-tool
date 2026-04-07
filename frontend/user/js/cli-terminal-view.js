// Claude Code CLI terminal viewer (Phase 1: read-only streaming via Tauri events).
// xterm.js is loaded from CDN by cli-terminal.html.
// Phase 2 will add PTY duplex (keystroke -> child stdin).

(function () {
    'use strict';

    const tauri = window.__TAURI__;
    if (!tauri) {
        console.warn('[cli-terminal] Tauri runtime not available');
    }

    // ───────────────────────────────────────────────
    // xterm.js terminal setup
    // ───────────────────────────────────────────────
    let term = null;

    function ensureTerm() {
        if (term) return term;
        if (typeof Terminal === 'undefined') {
            console.error('[cli-terminal] xterm.js not loaded');
            return null;
        }
        term = new Terminal({
            convertEol: true,
            cursorBlink: false,
            disableStdin: true,
            fontSize: 12,
            fontFamily: 'Menlo, Monaco, "Courier New", monospace',
            scrollback: 5000,
            theme: {
                background: '#0b0b0b',
                foreground: '#e5e7eb',
                cursor: '#e5e7eb',
                black: '#1f2937',
                red: '#ef4444',
                green: '#22c55e',
                yellow: '#eab308',
                blue: '#3b82f6',
                magenta: '#a855f7',
                cyan: '#06b6d4',
                white: '#f3f4f6',
            },
        });
        const mount = document.getElementById('cli-terminal-mount');
        term.open(mount);
        return term;
    }

    function writeStdout(chunk) {
        const t = ensureTerm();
        if (t) t.write(chunk);
    }

    function writeStderr(chunk) {
        const t = ensureTerm();
        if (t) t.write('\x1b[31m' + chunk + '\x1b[0m');
    }

    function writeFooter(text, color) {
        const t = ensureTerm();
        if (t) t.write('\r\n\x1b[' + color + 'm' + text + '\x1b[0m\r\n');
    }

    function clearTerm() {
        if (term) term.clear();
    }

    // ───────────────────────────────────────────────
    // status / metadata
    // ───────────────────────────────────────────────
    function setStatus(status) {
        const el = document.getElementById('cli-status');
        if (!el) return;
        el.textContent = status;
        el.className = 'cli-status-badge ' + status;
    }

    function setMeta(adapter, runtime, cwd, exitCode) {
        document.getElementById('cli-meta-adapter').textContent = adapter || '-';
        document.getElementById('cli-meta-runtime').textContent = runtime || '-';
        document.getElementById('cli-meta-cwd').textContent = cwd || '-';
        document.getElementById('cli-meta-exit').textContent =
            exitCode === null || exitCode === undefined ? '-' : String(exitCode);
    }

    function setChangedFiles(files) {
        const ul = document.getElementById('cli-changed-list');
        if (!ul) return;
        if (!files || files.length === 0) {
            ul.innerHTML = '<li style="color: var(--content-text-muted);">（なし）</li>';
            return;
        }
        ul.innerHTML = files.map(function (f) {
            return '<li><code>' + escapeHtml(f) + '</code></li>';
        }).join('');
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    // ───────────────────────────────────────────────
    // Tauri event subscriptions
    // ───────────────────────────────────────────────
    let unlisteners = [];

    async function subscribe() {
        if (!tauri || !tauri.event || !tauri.event.listen) {
            console.warn('[cli-terminal] tauri.event not available');
            return;
        }
        const off1 = await tauri.event.listen('external_cli:planned', function (e) {
            const p = e.payload || {};
            setStatus('pending');
            setMeta(p.adapter_id, p.runtime, p.cwd, null);
            setChangedFiles([]);
            clearTerm();
            writeFooter('[planned] adapter=' + p.adapter_id + ' runtime=' + p.runtime + ' cwd=' + p.cwd, '36');
        });
        const off2 = await tauri.event.listen('external_cli:started', function (e) {
            const p = e.payload || {};
            setStatus('running');
            writeFooter('[started] ' + (p.command_preview || '') + '  @' + (p.started_at || ''), '36');
        });
        const off3 = await tauri.event.listen('external_cli:stdout_chunk', function (e) {
            const p = e.payload || {};
            writeStdout(p.chunk || '');
        });
        const off4 = await tauri.event.listen('external_cli:stderr_chunk', function (e) {
            const p = e.payload || {};
            writeStderr(p.chunk || '');
        });
        const off5 = await tauri.event.listen('external_cli:finished', function (e) {
            const p = e.payload || {};
            setStatus(p.status || 'succeeded');
            const exit = p.exit_code === null || p.exit_code === undefined ? '?' : p.exit_code;
            writeFooter(
                '[finished] status=' + p.status + ' exit=' + exit + ' duration=' + p.duration_ms + 'ms changed=' + p.changed_files_count,
                p.status === 'succeeded' ? '32' : '31'
            );
            const dur = document.getElementById('cli-duration');
            if (dur) dur.textContent = p.duration_ms + ' ms';
            setMeta(undefined, undefined, undefined, p.exit_code);
        });
        const off6 = await tauri.event.listen('external_cli:failed', function (e) {
            const p = e.payload || {};
            setStatus(p.status || 'failed');
            writeFooter('[failed] ' + (p.status || '') + ': ' + (p.reason || ''), '31');
        });
        unlisteners = [off1, off2, off3, off4, off5, off6];
    }

    // ───────────────────────────────────────────────
    // run button handler
    // ───────────────────────────────────────────────
    async function onRun() {
        if (!tauri || !tauri.core || !tauri.core.invoke) {
            alert('Tauri ランタイムが利用できません');
            return;
        }
        const cwd = (document.getElementById('cli-cwd').value || '').trim();
        const prompt = (document.getElementById('cli-prompt').value || '').trim();
        const allowWrites = document.getElementById('cli-allow-writes').checked;
        const allowShell = document.getElementById('cli-allow-shell').checked;
        const timeoutSec = parseInt(document.getElementById('cli-timeout-sec').value, 10) || 900;

        if (!cwd) {
            alert('作業ディレクトリを入力してください');
            return;
        }
        if (!prompt) {
            alert('プロンプトを入力してください');
            return;
        }

        // Phase 3.7: read runtime selector — adapter_id and command come
        // from the registry on the Rust side, so we only need to send the
        // adapter_id that maps to the chosen runtime.
        const runtimeSel = document.getElementById('cli-runtime-select');
        const runtime = runtimeSel ? runtimeSel.value : 'claude_code';
        const adapterByRuntime = {
            claude_code: { id: 'claude-code-local', cmd: 'claude' },
            codex:       { id: 'codex-local',       cmd: 'codex' },
            generic:     { id: 'generic-cli',       cmd: '/bin/sh' },
        };
        const choice = adapterByRuntime[runtime] || adapterByRuntime.claude_code;
        const adapterLabel = document.getElementById('cli-runtime-adapter');
        if (adapterLabel) adapterLabel.textContent = 'adapter: ' + choice.id;

        const req = {
            task_id: 'cli-' + Date.now(),
            workflow_run_id: 'manual',
            task_role: null,
            adapter_id: choice.id,
            runtime: runtime,
            command: choice.cmd,
            args: [],
            cwd: cwd,
            prompt: prompt,
            timeout_ms: timeoutSec * 1000,
            required_capabilities: [],
            allow_writes: allowWrites,
            allow_shell: allowShell,
            workspace_id: null,
            workspace_mode: null,
            env_overrides: {},
            metadata: {},
        };

        try {
            const result = await tauri.core.invoke('external_cli_run', { req: req });
            // The 'finished' event already updated UI; here we just refresh the
            // changed-files list which is only present on the result.
            if (result && Array.isArray(result.changed_files)) {
                setChangedFiles(result.changed_files);
            }
        } catch (e) {
            console.error(e);
            setStatus('failed');
            writeFooter('[invoke_error] ' + String(e), '31');
        }
    }

    // ───────────────────────────────────────────────
    // bootstrap
    // ───────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        ensureTerm();
        subscribe();
        const btn = document.getElementById('cli-run-btn');
        if (btn) btn.addEventListener('click', onRun);
        // Pre-fill cwd with home as a safe default.
        const cwdEl = document.getElementById('cli-cwd');
        if (cwdEl && !cwdEl.value) {
            cwdEl.value = '';
            cwdEl.placeholder = '/Users/you/your-project';
        }
        // Phase 3.7: keep adapter label in sync with the runtime selector.
        const runtimeSel = document.getElementById('cli-runtime-select');
        const adapterLabel = document.getElementById('cli-runtime-adapter');
        function updateAdapterLabel() {
            if (!runtimeSel || !adapterLabel) return;
            const map = {
                claude_code: 'claude-code-local',
                codex: 'codex-local',
                generic: 'generic-cli',
            };
            adapterLabel.textContent = 'adapter: ' + (map[runtimeSel.value] || runtimeSel.value);
        }
        if (runtimeSel) {
            runtimeSel.addEventListener('change', updateAdapterLabel);
            updateAdapterLabel();
        }
    });
})();
