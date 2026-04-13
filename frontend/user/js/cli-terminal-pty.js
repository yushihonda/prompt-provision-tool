// Claude Code / OpenAI Codex の実 PTY（双方向 xterm.js ターミナル）。
// 短い `name`（例: 'claude', 'codex'）をキーとする複数の独立した
// PTY パネルをサポート。DOM ID は以下の命名規則に従う:
//   pty-<name>-status / pty-<name>-cwd / pty-<name>-spawn-btn /
//   pty-<name>-kill-btn / pty-<name>-session-id / pty-<name>-terminal-mount

(function () {
    'use strict';

    const tauri = window.__TAURI__;
    if (!tauri) {
        console.warn('[cli-terminal-pty] Tauri runtime not available');
    }

    // パネルレジストリ: name -> { term, fitAddon, sessionId, command, resizeObserver }
    const panels = new Map();
    // session_id -> パネル名（イベントルーティング用）
    const sessionIndex = new Map();

    function ensureTerm(panel) {
        if (panel.term) return panel.term;
        if (typeof Terminal === 'undefined') {
            console.error('[cli-terminal-pty] xterm.js not loaded');
            return null;
        }
        const term = new Terminal({
            convertEol: false,
            cursorBlink: true,
            fontSize: 12,
            fontFamily: 'Menlo, Monaco, "Courier New", monospace',
            scrollback: 5000,
            theme: {
                background: '#0b0b0b',
                foreground: '#e5e7eb',
                cursor: '#e5e7eb',
            },
        });
        if (window.FitAddon && window.FitAddon.FitAddon) {
            panel.fitAddon = new window.FitAddon.FitAddon();
            term.loadAddon(panel.fitAddon);
        }
        const mount = document.getElementById('pty-' + panel.name + '-terminal-mount');
        term.open(mount);
        if (panel.fitAddon) {
            try { panel.fitAddon.fit(); } catch (e) { /* ignore */ }
        }
        term.onData(function (data) {
            if (!panel.sessionId) return;
            tauri.core.invoke('external_cli_pty_write', {
                req: { session_id: panel.sessionId, data: data },
            }).catch(function (e) { console.error('pty_write', e); });
        });
        if (window.ResizeObserver) {
            panel.resizeObserver = new ResizeObserver(function () {
                if (!panel.fitAddon || !panel.sessionId) return;
                try {
                    panel.fitAddon.fit();
                    tauri.core.invoke('external_cli_pty_resize', {
                        req: { session_id: panel.sessionId, cols: term.cols, rows: term.rows },
                    }).catch(function (e) { console.warn('pty_resize', e); });
                } catch (e) { /* ignore */ }
            });
            panel.resizeObserver.observe(mount);
        }
        panel.term = term;
        return term;
    }

    function setStatus(panel, status) {
        const el = document.getElementById('pty-' + panel.name + '-status');
        if (!el) return;
        el.textContent = status;
        el.className = 'cli-status-badge ' + status;
    }

    async function subscribe() {
        if (!tauri || !tauri.event || !tauri.event.listen) return;
        await tauri.event.listen('external_cli_pty:stdout', function (e) {
            const p = e.payload || {};
            const name = sessionIndex.get(p.session_id);
            if (!name) return;
            const panel = panels.get(name);
            if (panel && panel.term) panel.term.write(p.chunk || '');
        });
        await tauri.event.listen('external_cli_pty:exit', function (e) {
            const p = e.payload || {};
            const name = sessionIndex.get(p.session_id);
            if (!name) return;
            const panel = panels.get(name);
            if (!panel) return;
            const code = p.exit_code === null || p.exit_code === undefined ? '?' : p.exit_code;
            setStatus(panel, p.exit_code === 0 ? 'succeeded' : 'failed');
            if (panel.term) panel.term.write('\r\n\x1b[36m[exit ' + code + ']\x1b[0m\r\n');
            sessionIndex.delete(panel.sessionId);
            panel.sessionId = null;
            const killBtn = document.getElementById('pty-' + panel.name + '-kill-btn');
            if (killBtn) killBtn.disabled = true;
            const idEl = document.getElementById('pty-' + panel.name + '-session-id');
            if (idEl) idEl.textContent = '';
        });
    }

    async function onSpawn(panel) {
        if (!tauri || !tauri.core || !tauri.core.invoke) {
            alert('Tauri ランタイムが利用できません');
            return;
        }
        if (panel.sessionId) {
            alert('既に ' + panel.command + ' セッションが起動中です。停止してから再起動してください。');
            return;
        }
        const cwdEl = document.getElementById('pty-' + panel.name + '-cwd');
        const cwd = (cwdEl && cwdEl.value || '').trim();
        if (!cwd) {
            alert('作業ディレクトリを入力してください');
            return;
        }
        const t = ensureTerm(panel);
        if (!t) return;
        let cols = 100, rows = 30;
        try {
            if (panel.fitAddon) panel.fitAddon.fit();
            cols = t.cols;
            rows = t.rows;
        } catch (e) { /* ignore */ }

        try {
            const res = await tauri.core.invoke('external_cli_pty_spawn', {
                req: {
                    command: panel.command,
                    args: [],
                    cwd: cwd,
                    cols: cols,
                    rows: rows,
                    env_overrides: {},
                },
            });
            panel.sessionId = res.session_id;
            sessionIndex.set(panel.sessionId, panel.name);
            setStatus(panel, 'running');
            const killBtn = document.getElementById('pty-' + panel.name + '-kill-btn');
            if (killBtn) killBtn.disabled = false;
            const idEl = document.getElementById('pty-' + panel.name + '-session-id');
            if (idEl) idEl.textContent = 'session: ' + panel.sessionId.slice(0, 8);
            if (panel.term) panel.term.focus();
        } catch (e) {
            console.error(e);
            setStatus(panel, 'failed');
            if (panel.term) panel.term.write('\r\n\x1b[31m[spawn_error] ' + String(e) + '\x1b[0m\r\n');
        }
    }

    async function onKill(panel) {
        if (!panel.sessionId) return;
        try {
            await tauri.core.invoke('external_cli_pty_kill', {
                req: { session_id: panel.sessionId },
            });
        } catch (e) {
            console.error('kill', e);
        }
    }

    function registerPanel(name, command) {
        const panel = {
            name: name,
            command: command,
            term: null,
            fitAddon: null,
            sessionId: null,
            resizeObserver: null,
        };
        panels.set(name, panel);
        ensureTerm(panel);
        const spawnBtn = document.getElementById('pty-' + name + '-spawn-btn');
        if (spawnBtn) spawnBtn.addEventListener('click', function () { onSpawn(panel); });
        const killBtn = document.getElementById('pty-' + name + '-kill-btn');
        if (killBtn) killBtn.addEventListener('click', function () { onKill(panel); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        subscribe();
        if (document.getElementById('pty-claude-terminal-mount')) {
            registerPanel('claude', 'claude');
        }
        if (document.getElementById('pty-codex-terminal-mount')) {
            registerPanel('codex', 'codex');
        }
    });
})();
