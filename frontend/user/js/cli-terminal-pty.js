// Phase 2: Claude Code in a real PTY (duplex xterm.js terminal).
// Calls Tauri commands external_cli_pty_{spawn,write,resize,kill}.

(function () {
    'use strict';

    const tauri = window.__TAURI__;
    if (!tauri) {
        console.warn('[cli-terminal-pty] Tauri runtime not available');
    }

    let term = null;
    let fitAddon = null;
    let sessionId = null;
    let unlistenStdout = null;
    let unlistenExit = null;
    let resizeObserver = null;

    function ensureTerm() {
        if (term) return term;
        if (typeof Terminal === 'undefined') {
            console.error('[cli-terminal-pty] xterm.js not loaded');
            return null;
        }
        term = new Terminal({
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
            fitAddon = new window.FitAddon.FitAddon();
            term.loadAddon(fitAddon);
        }
        const mount = document.getElementById('pty-terminal-mount');
        term.open(mount);
        if (fitAddon) {
            try { fitAddon.fit(); } catch (e) { /* ignore until visible */ }
        }
        // Send keystrokes to the child via the write command.
        term.onData(function (data) {
            if (!sessionId) return;
            tauri.core.invoke('external_cli_pty_write', {
                req: { session_id: sessionId, data: data },
            }).catch(function (e) { console.error('pty_write', e); });
        });
        // Watch container resize and propagate cols/rows to the child PTY.
        if (window.ResizeObserver) {
            resizeObserver = new ResizeObserver(function () {
                if (!fitAddon || !sessionId) return;
                try {
                    fitAddon.fit();
                    const cols = term.cols;
                    const rows = term.rows;
                    tauri.core.invoke('external_cli_pty_resize', {
                        req: { session_id: sessionId, cols: cols, rows: rows },
                    }).catch(function (e) { console.warn('pty_resize', e); });
                } catch (e) { /* ignore */ }
            });
            resizeObserver.observe(mount);
        }
        return term;
    }

    function setStatus(status) {
        const el = document.getElementById('pty-status');
        if (!el) return;
        el.textContent = status;
        el.className = 'cli-status-badge ' + status;
    }

    async function subscribe() {
        if (!tauri || !tauri.event || !tauri.event.listen) return;
        unlistenStdout = await tauri.event.listen('external_cli_pty:stdout', function (e) {
            const p = e.payload || {};
            if (p.session_id !== sessionId) return;
            if (term) term.write(p.chunk || '');
        });
        unlistenExit = await tauri.event.listen('external_cli_pty:exit', function (e) {
            const p = e.payload || {};
            if (p.session_id !== sessionId) return;
            const code = p.exit_code === null || p.exit_code === undefined ? '?' : p.exit_code;
            setStatus(p.exit_code === 0 ? 'succeeded' : 'failed');
            if (term) term.write('\r\n\x1b[36m[exit ' + code + ']\x1b[0m\r\n');
            sessionId = null;
            const killBtn = document.getElementById('pty-kill-btn');
            if (killBtn) killBtn.disabled = true;
            const idEl = document.getElementById('pty-session-id');
            if (idEl) idEl.textContent = '';
        });
    }

    async function onSpawn() {
        if (!tauri || !tauri.core || !tauri.core.invoke) {
            alert('Tauri ランタイムが利用できません');
            return;
        }
        if (sessionId) {
            alert('既にセッションが起動中です。停止してから再起動してください。');
            return;
        }
        const cwdEl = document.getElementById('pty-cwd');
        const cwd = (cwdEl && cwdEl.value || '').trim();
        if (!cwd) {
            alert('作業ディレクトリを入力してください');
            return;
        }
        const t = ensureTerm();
        if (!t) return;
        // Best-effort fit before sending initial size.
        let cols = 100, rows = 30;
        try {
            if (fitAddon) fitAddon.fit();
            cols = t.cols;
            rows = t.rows;
        } catch (e) { /* ignore */ }

        try {
            const res = await tauri.core.invoke('external_cli_pty_spawn', {
                req: {
                    command: 'claude',
                    args: [],
                    cwd: cwd,
                    cols: cols,
                    rows: rows,
                    env_overrides: {},
                },
            });
            sessionId = res.session_id;
            setStatus('running');
            const killBtn = document.getElementById('pty-kill-btn');
            if (killBtn) killBtn.disabled = false;
            const idEl = document.getElementById('pty-session-id');
            if (idEl) idEl.textContent = 'session: ' + sessionId.slice(0, 8);
            if (term) term.focus();
        } catch (e) {
            console.error(e);
            setStatus('failed');
            if (term) term.write('\r\n\x1b[31m[spawn_error] ' + String(e) + '\x1b[0m\r\n');
        }
    }

    async function onKill() {
        if (!sessionId) return;
        try {
            await tauri.core.invoke('external_cli_pty_kill', {
                req: { session_id: sessionId },
            });
        } catch (e) {
            console.error('kill', e);
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        ensureTerm();
        subscribe();
        const spawnBtn = document.getElementById('pty-spawn-btn');
        if (spawnBtn) spawnBtn.addEventListener('click', onSpawn);
        const killBtn = document.getElementById('pty-kill-btn');
        if (killBtn) killBtn.addEventListener('click', onKill);
    });
})();
