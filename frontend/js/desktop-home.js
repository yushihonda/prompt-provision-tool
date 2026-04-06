(function () {
    const invoke = window.__TAURI__?.core?.invoke;
    const runtime = window.PPTRuntime;

    const appInfoEl = document.getElementById('app-info');
    const runtimeDiagnosticsInfoEl = document.getElementById('runtime-diagnostics-info');
    const runtimeDiagnosticsOutputEl = document.getElementById('runtime-diagnostics-output');
    const storageInfoEl = document.getElementById('storage-info');
    const runsOutputEl = document.getElementById('workflow-runs-output');
    const eventsOutputEl = document.getElementById('workflow-events-output');
    const sidecarInfoEl = document.getElementById('sidecar-info');
    const sidecarOutputEl = document.getElementById('sidecar-output');
    const engineModeSelect = document.getElementById('engine-mode-select');
    const engineModePill = document.getElementById('engine-mode-pill');
    let latestRunId = null;

    function renderRows(target, rows) {
        if (!rows || rows.length === 0) {
            target.textContent = 'まだ run はありません。';
            return;
        }

        target.textContent = rows
            .map((row) => `#${row.id} ${row.workflowName} [${row.status}] (${row.engineMode || 'n/a'})`)
            .join('\n');
    }

    function renderEvents(events) {
        if (!events || events.length === 0) {
            eventsOutputEl.textContent = 'event はまだありません。';
            return;
        }

        eventsOutputEl.textContent = events
            .map((event) => {
                let payloadSummary = '';
                try {
                    const payload = JSON.parse(event.payloadJson || '{}');
                    payloadSummary = Object.keys(payload).length === 0 ? '{}' : JSON.stringify(payload);
                } catch (error) {
                    payloadSummary = event.payloadJson || '{}';
                }

                return [
                    `${event.occurredAt} ${event.eventType}`,
                    `event_id=${event.eventId}`,
                    `attempt=${event.attemptNo} node=${event.nodeId || '-'}`,
                    `idem=${event.idempotencyKey}`,
                    payloadSummary,
                ].join('\n');
            })
            .join('\n\n');
    }

    function setAppInfo(text) {
        appInfoEl.textContent = text;
    }

    function setStorageInfo(text) {
        storageInfoEl.textContent = text;
    }

    function setRuntimeDiagnosticsInfo(text) {
        runtimeDiagnosticsInfoEl.textContent = text;
    }

    function setRuntimeDiagnosticsOutput(text) {
        runtimeDiagnosticsOutputEl.textContent = text;
    }

    function setSidecarInfo(text) {
        sidecarInfoEl.textContent = text;
    }

    function setSidecarOutput(text) {
        sidecarOutputEl.textContent = text;
    }

    async function safeInvoke(command, payload) {
        if (!invoke) {
            throw new Error('Tauri invoke is not available in this browser context.');
        }

        return invoke(command, payload);
    }

    async function loadAppInfo() {
        if (!invoke) {
            setAppInfo('ブラウザ表示です。Tauri 上で開くと app info を取得できます。');
            return;
        }

        const [info, env] = await Promise.all([
            safeInvoke('app_info'),
            safeInvoke('desktop_env'),
        ]);

        setAppInfo(
            [
                `name: ${info.name}`,
                `version: ${info.version}`,
                `identifier: ${info.identifier}`,
                `platform: ${env.platform}/${env.arch}`,
                `runtime: ${env.tauriRuntime}`,
            ].join('\n')
        );
    }

    async function refreshRuntimeDiagnostics() {
        const snapshot = runtime.getDiagnosticsSnapshot();
        const stable = runtime.getProviderStableFields();
        const detail = runtime.getProviderDetails();
        let backendStatus = 'browser mode';
        let sidecarStatus = 'browser mode';

        if (runtime.isDesktopRuntime()) {
            try {
                const healthResponse = await runtime.fetchWithRuntime('/health', { method: 'GET' });
                backendStatus = healthResponse.ok ? 'reachable' : `http ${healthResponse.status}`;
            } catch (error) {
                backendStatus = `unreachable: ${error instanceof Error ? error.message : String(error)}`;
            }

            // sidecar health は重い可能性があるため、ここでは既知の状態のみ表示
            // 詳細は「起動 / Health」ボタンで取得する
            sidecarStatus = 'click "起動 / Health" to check';
        }

        setRuntimeDiagnosticsInfo(
            [
                `desktop: ${snapshot.desktop}`,
                `configSource: ${snapshot.configSource}`,
                `configured_engine_mode: ${stable.configuredEngineMode}`,
                `effective_engine_mode: ${stable.effectiveEngineMode}`,
                `backend: ${backendStatus}`,
                `sidecar: ${sidecarStatus}`,
            ].join('\n')
        );
        setRuntimeDiagnosticsOutput(
            [
                `apiBase: ${snapshot.apiBase}`,
                `workerUrl: ${snapshot.workerUrl}`,
                `sidecarScript: ${snapshot.sidecarScriptPath || '-'}`,
                `providerMode: ${stable.providerMode}`,
                `providerTransport: ${detail.providerTransport}`,
                `providerAdapter: ${detail.providerAdapter}`,
                `providerRuntime: ${detail.providerRuntime}`,
                `providerImpl: ${detail.providerImpl}`,
                `authKeySource: ${stable.authKeySource}`,
                `observationSource: ${snapshot.observationSource}`,
                `hasTauriInvoke: ${snapshot.hasTauriInvoke}`,
                `lastRuntimeError: ${snapshot.lastRuntimeError || '-'}`,
            ].join('\n')
        );
    }

    async function initializeStorage() {
        const summary = await safeInvoke('initialize_storage');
        setStorageInfo(
            [
                `db: ${summary.dbPath}`,
                `migrations: ${summary.migrationsApplied}`,
                `engine_mode: ${summary.engineMode}`,
            ].join('\n')
        );
    }

    async function refreshRuns() {
        const rows = await safeInvoke('list_workflow_runs');
        renderRows(runsOutputEl, rows);
        latestRunId = rows[0]?.id || null;
        await refreshRunEvents();
    }

    async function refreshRunEvents() {
        if (!latestRunId) {
            renderEvents([]);
            return;
        }

        const events = await safeInvoke('list_workflow_run_events', { runId: latestRunId });
        renderEvents(events);
    }

    async function refreshEngineMode() {
        const config = await safeInvoke('get_engine_mode');
        engineModeSelect.value = config.engineMode;
        engineModePill.textContent = config.engineMode;
    }

    async function refreshSidecarHealth() {
        const health = await safeInvoke('sidecar_health');
        setSidecarInfo(
            [
                `status: ${health.status}`,
                `pid: ${health.pid || '-'}`,
                `mode: stdio`,
                `configured/effective: ${health.configuredEngineMode}/${health.effectiveEngineMode}`,
                `provider/auth: ${health.providerMode}/${health.authKeySource}`,
                `provider detail: ${health.providerTransport}/${health.providerAdapter}/${health.providerRuntime}`,
                `provider impl: ${health.providerImpl}`,
                `commands: ${health.commands.join(', ')}`,
            ].join('\n')
        );
    }

    async function startSidecar() {
        const status = await safeInvoke('start_sidecar');
        setSidecarOutput(`sidecar started: pid=${status.pid || '-'} mode=${status.mode}`);
        await refreshSidecarHealth();
    }

    async function stopSidecar() {
        const status = await safeInvoke('stop_sidecar');
        setSidecarInfo(`running: ${status.running}\npid: -\nmode: ${status.mode}`);
        setSidecarOutput('sidecar stopped');
    }

    async function runDemoWorkflow() {
        const result = await safeInvoke('run_demo_workflow', {
            topic: 'NexMAGI desktop bootstrap',
        });
        setSidecarOutput(
            [
                'demo_path: preview_only',
                `status: ${result.status}`,
                `engine_mode_hint: ${result.engineModeHint}`,
                `configured/effective: ${result.configuredEngineMode}/${result.effectiveEngineMode}`,
                `provider/auth: ${result.providerMode}/${result.authKeySource}`,
                `provider detail: ${result.providerTransport}/${result.providerAdapter}/${result.providerRuntime}`,
                `provider impl: ${result.providerImpl}`,
                `run_id: ${result.runId}`,
                `event_count: ${result.eventCount}`,
                '',
                result.summary,
            ].join('\n')
        );
        await refreshRuns();
    }

    async function simulateContinuation() {
        if (!latestRunId) {
            throw new Error('先に demo workflow を実行して run を作成してください。');
        }

        const payload = {
            runId: latestRunId,
            nodeId: 'demo-node',
            attemptNo: 1,
            continuationReason: 'verification_failed',
            failureFingerprint: 'demo-fingerprint',
            deltaInstructionHash: 'demo-delta-v1',
        };
        await safeInvoke('simulate_continuation', payload);
        const second = await safeInvoke('simulate_continuation', payload);
        setSidecarOutput(
            [
                `continuation run_id: ${latestRunId}`,
                `latest_event_types: ${second.map((event) => event.eventType).join(', ')}`,
            ].join('\n')
        );
        await refreshRunEvents();
    }

    async function bootstrap() {
        try {
            await runtime.ensureRuntimeConfig().catch(() => runtime.getRuntimeConfig());
        } catch (e) {
            // fallback config is fine
        }

        if (!invoke) {
            setAppInfo('ブラウザ表示です。Tauri 上で開くと app info を取得できます。');
            setStorageInfo('Tauri 上で開くと SQLite 初期化結果を表示します。');
            setSidecarInfo('Tauri 上で開くと sidecar を起動できます。');
            return;
        }

        // 各セクションを独立して非同期ロード（1つが遅くてもUIは操作可能）
        loadAppInfo().catch((err) => setAppInfo(`error: ${err}`));
        initializeStorage()
            .then(() => refreshEngineMode())
            .then(() => refreshRuns())
            .catch((err) => setStorageInfo(`error: ${err}`));
        refreshRuntimeDiagnostics().catch((err) => {
            setRuntimeDiagnosticsInfo(`error: ${err}`);
        });
        // sidecar は「起動 / Health」ボタンで手動起動（自動起動するとゾンビ化リスクあり）
        setSidecarInfo('「起動 / Health」ボタンで起動してください');
    }

    document.getElementById('init-storage-btn')?.addEventListener('click', async () => {
        await initializeStorage();
        await refreshEngineMode();
    });

    document.getElementById('refresh-runs-btn')?.addEventListener('click', async () => {
        await refreshRuns();
    });

    document.getElementById('start-sidecar-btn')?.addEventListener('click', async () => {
        await startSidecar();
        await refreshRuntimeDiagnostics();
    });

    document.getElementById('demo-workflow-btn')?.addEventListener('click', async () => {
        await runDemoWorkflow();
    });

    document.getElementById('simulate-continuation-btn')?.addEventListener('click', async () => {
        await simulateContinuation();
    });

    document.getElementById('stop-sidecar-btn')?.addEventListener('click', async () => {
        await stopSidecar();
        await refreshRuntimeDiagnostics();
    });

    engineModeSelect?.addEventListener('change', async (event) => {
        const engineMode = event.target.value;
        const config = await safeInvoke('set_engine_mode', { engineMode });
        engineModePill.textContent = config.engineMode;
        await initializeStorage();
    });

    window.addEventListener('ppt-runtime-config-ready', async () => {
        await refreshRuntimeDiagnostics();
    });

    bootstrap();
})();
