(function () {
    const tauriInvoke = window.__TAURI__?.core?.invoke;
    const fallbackConfig = {
        desktop: Boolean(tauriInvoke),
        apiBase: Boolean(tauriInvoke) ? 'http://127.0.0.1:8000' : window.location.origin,
        workerScriptPath: 'js/execution-worker.js',
        sidecarScriptPath: '',
        engineEventMode: Boolean(tauriInvoke) ? 'sidecar-batch' : 'browser',
        localExecutionMode: Boolean(tauriInvoke) ? 'sidecar' : 'browser',
        configuredEngineMode: Boolean(tauriInvoke) ? 'api_key' : 'browser',
        effectiveEngineMode: Boolean(tauriInvoke) ? 'api_key' : 'browser',
        providerMode: 'api_key',
        providerTransport: Boolean(tauriInvoke) ? 'sdk' : 'browser_http',
        providerAdapter: Boolean(tauriInvoke) ? 'none' : 'browser',
        providerRuntime: Boolean(tauriInvoke) ? 'python' : 'browser',
        providerImpl: Boolean(tauriInvoke) ? 'sdk_execute_bundle' : 'browser_fetch',
        authKeySource: Boolean(tauriInvoke) ? 'bundle_or_local_env' : 'browser_session',
        observationSource: Boolean(tauriInvoke) ? 'engine_origin_batch' : 'browser_http',
        configSource: Boolean(tauriInvoke) ? 'desktop-fallback' : 'browser-origin',
        lastRuntimeError: null,
    };
    let runtimeConfig = normalizeRuntimeConfig({
        ...fallbackConfig,
        ...(window.__PPT_RUNTIME || {}),
    });
    let runtimeConfigPromise = null;
    let authSession = null;
    let authSessionLoaded = !Boolean(tauriInvoke);
    let authSessionPromise = null;

    function normalizeRuntimeConfig(config) {
        return {
            desktop: Boolean(config.desktop),
            apiBase: String(config.apiBase || fallbackConfig.apiBase).replace(/\/$/, ''),
            workerScriptPath: String(config.workerScriptPath || fallbackConfig.workerScriptPath),
            sidecarScriptPath: String(config.sidecarScriptPath || ''),
            engineEventMode: String(config.engineEventMode || fallbackConfig.engineEventMode),
            localExecutionMode: String(config.localExecutionMode || fallbackConfig.localExecutionMode),
            configuredEngineMode: String(config.configuredEngineMode || fallbackConfig.configuredEngineMode),
            effectiveEngineMode: String(config.effectiveEngineMode || fallbackConfig.effectiveEngineMode),
            providerMode: String(config.providerMode || fallbackConfig.providerMode),
            providerTransport: String(config.providerTransport || fallbackConfig.providerTransport),
            providerAdapter: String(config.providerAdapter || fallbackConfig.providerAdapter),
            providerRuntime: String(config.providerRuntime || fallbackConfig.providerRuntime),
            providerImpl: String(config.providerImpl || fallbackConfig.providerImpl),
            authKeySource: String(config.authKeySource || fallbackConfig.authKeySource),
            observationSource: String(config.observationSource || fallbackConfig.observationSource),
            configSource: String(config.configSource || fallbackConfig.configSource),
            lastRuntimeError: config.lastRuntimeError || null,
        };
    }

    function commitRuntimeConfig(nextConfig) {
        runtimeConfig = normalizeRuntimeConfig(nextConfig);
        window.__PPT_RUNTIME = { ...runtimeConfig };
        window.dispatchEvent(new CustomEvent('ppt-runtime-config-ready', {
            detail: { ...runtimeConfig },
        }));
        return getRuntimeConfig();
    }

    function getRuntimeConfig() {
        return { ...runtimeConfig };
    }

    function isDesktopRuntime() {
        return Boolean(runtimeConfig.desktop);
    }

    function getApiBase() {
        return getRuntimeConfig().apiBase;
    }

    function getEngineEventMode() {
        return getRuntimeConfig().engineEventMode;
    }

    function getLocalExecutionMode() {
        return getRuntimeConfig().localExecutionMode;
    }

    function getConfiguredEngineMode() {
        return getRuntimeConfig().configuredEngineMode;
    }

    function getEffectiveEngineMode() {
        return getRuntimeConfig().effectiveEngineMode;
    }

    function getProviderMode() {
        return getRuntimeConfig().providerMode;
    }

    function getAuthKeySource() {
        return getRuntimeConfig().authKeySource;
    }

    function getProviderStableFields() {
        const config = getRuntimeConfig();
        return {
            configuredEngineMode: config.configuredEngineMode,
            effectiveEngineMode: config.effectiveEngineMode,
            providerMode: config.providerMode,
            authKeySource: config.authKeySource,
        };
    }

    function getProviderDetails() {
        const config = getRuntimeConfig();
        return {
            providerTransport: config.providerTransport,
            providerAdapter: config.providerAdapter,
            providerRuntime: config.providerRuntime,
            providerImpl: config.providerImpl,
        };
    }

    function buildApiUrl(path) {
        const apiBase = getApiBase();
        if (!path) {
            return apiBase;
        }
        if (/^https?:\/\//.test(path)) {
            return path;
        }
        return `${apiBase}${path.startsWith('/') ? path : `/${path}`}`;
    }

    function resolveWorkerUrl(relativePath) {
        const normalized = String(relativePath || runtimeConfig.workerScriptPath).replace(/^\.\//, '');
        return new URL(normalized, window.location.href).toString();
    }

    async function fetchWithRuntime(path, options = {}) {
        const url = buildApiUrl(path);
        const mergedOptions = {
            credentials: 'include',
            ...options,
        };
        return fetch(url, mergedOptions);
    }

    function normalizeAuthSession(session) {
        if (!session || typeof session !== 'object') {
            return null;
        }
        const token = String(session.token || '').trim();
        const username = String(session.username || '').trim();
        if (!token) {
            return null;
        }
        return { token, username };
    }

    function commitAuthSession(nextSession) {
        authSession = normalizeAuthSession(nextSession);
        authSessionLoaded = true;

        if (isDesktopRuntime()) {
            sessionStorage.removeItem('token');
        } else if (authSession?.token) {
            sessionStorage.setItem('token', authSession.token);
        } else {
            sessionStorage.removeItem('token');
        }

        if (authSession?.username) {
            sessionStorage.setItem('username', authSession.username);
        } else if (nextSession === null) {
            sessionStorage.removeItem('username');
        }

        return getCachedAuthSession();
    }

    function getCachedAuthSession() {
        return authSession ? { ...authSession } : null;
    }

    async function ensureAuthSession() {
        if (!tauriInvoke || !isDesktopRuntime()) {
            if (!authSessionLoaded) {
                commitAuthSession({
                    token: sessionStorage.getItem('token') || '',
                    username: sessionStorage.getItem('username') || '',
                });
            }
            return getCachedAuthSession();
        }

        if (authSessionLoaded) {
            return getCachedAuthSession();
        }

        if (authSessionPromise) {
            return authSessionPromise;
        }

        authSessionPromise = invokeDesktop('get_auth_session')
            .then((session) => commitAuthSession(session || null))
            .finally(() => {
                authSessionPromise = null;
            });

        return authSessionPromise;
    }

    async function getAuthSession() {
        return ensureAuthSession();
    }

    async function getAuthToken() {
        const session = await ensureAuthSession();
        return session?.token || '';
    }

    async function getAuthUsername() {
        const session = await ensureAuthSession();
        return session?.username || sessionStorage.getItem('username') || '';
    }

    async function saveAuthSession(session) {
        const normalized = normalizeAuthSession(session);
        if (!normalized) {
            throw new Error('auth session must include a non-empty token');
        }
        if (tauriInvoke && isDesktopRuntime()) {
            const stored = await invokeDesktop('set_auth_session', { authSession: normalized });
            return commitAuthSession(stored);
        }
        return commitAuthSession(normalized);
    }

    async function clearAuthSession() {
        if (tauriInvoke && isDesktopRuntime()) {
            await invokeDesktop('clear_auth_session');
        }
        return commitAuthSession(null);
    }

    async function ensureRuntimeConfig() {
        if (!tauriInvoke || runtimeConfigPromise) {
            return runtimeConfigPromise || Promise.resolve(getRuntimeConfig());
        }

        runtimeConfigPromise = tauriInvoke('runtime_config')
            .then((config) => commitRuntimeConfig({
                ...config,
                configSource: 'tauri-command',
            }))
            .catch((error) => {
                commitRuntimeConfig({
                    ...runtimeConfig,
                    lastRuntimeError: error instanceof Error ? error.message : String(error),
                });
                throw error;
            });

        return runtimeConfigPromise;
    }

    function createWorker(relativePath, opts = {}) {
        const workerUrl = resolveWorkerUrl(relativePath || opts.path);
        return new Worker(workerUrl, opts.options || undefined);
    }

    function navigate(path) {
        window.location.href = path;
    }

    function getDiagnosticsSnapshot() {
        return {
            ...getRuntimeConfig(),
            workerUrl: resolveWorkerUrl(runtimeConfig.workerScriptPath),
            hasTauriInvoke: Boolean(tauriInvoke),
        };
    }

    async function invokeDesktop(command, payload) {
        if (!tauriInvoke) {
            throw new Error('Tauri invoke is not available');
        }
        return tauriInvoke(command, payload);
    }

    function canRecordDesktopEvents() {
        return isDesktopRuntime() && Boolean(tauriInvoke);
    }

    function shouldUseDesktopLocalExecution() {
        return isDesktopRuntime() && getLocalExecutionMode() === 'sidecar';
    }

    async function createWorkflowRun(workflowName, status = 'running') {
        return invokeDesktop('create_workflow_run', {
            input: {
                workflowName,
                status,
            },
        });
    }

    async function appendWorkflowRunEvent(event) {
        return invokeDesktop('append_workflow_run_event', { input: event });
    }

    async function updateWorkflowRunStatus(runId, status) {
        return invokeDesktop('update_workflow_run_status', {
            input: {
                runId,
                status,
            },
        });
    }

    async function runLocalSkillExecution(input) {
        return invokeDesktop('run_local_skill_execution', { input });
    }

    async function runLocalWorkflowExecution(input) {
        return invokeDesktop('run_local_workflow_execution', { input });
    }

    function classifyRetryDecision(details = {}) {
        const status = String(details.status || '').toLowerCase();
        const errorCode = String(details.errorCode || '').toLowerCase();

        if (status === 'cancelled') {
            return {
                shouldRetry: false,
                layer: 'workflow',
                reason: 'cancelled_by_user',
                decisionSource: 'desktop_stream_observer',
            };
        }

        if (errorCode === 'runtime_config_missing' || errorCode === 'invalid_url') {
            return {
                shouldRetry: false,
                layer: 'transport',
                reason: 'local_environment_error',
                decisionSource: 'desktop_stream_observer',
            };
        }

        if (errorCode === 'non_200_response') {
            return {
                shouldRetry: false,
                layer: 'transport',
                reason: 'transport_error',
                decisionSource: 'desktop_stream_observer',
            };
        }

        if (errorCode === 'network_unreachable' || errorCode === 'sse_closed_unexpectedly') {
            return {
                shouldRetry: false,
                layer: 'transport',
                reason: 'transport_error',
                decisionSource: 'desktop_stream_observer',
            };
        }

        return {
            shouldRetry: false,
            layer: 'workflow',
            reason: status === 'success' ? null : 'local_environment_error',
            decisionSource: 'desktop_stream_observer',
        };
    }

    function shouldRecordProxyLifecycleEvents(flowKind = 'http-api') {
        if (!isDesktopRuntime() || flowKind !== 'http-api') {
            return false;
        }
        if (shouldUseDesktopLocalExecution()) {
            return false;
        }
        return getEngineEventMode() !== 'sidecar-batch';
    }

    function getObservationSource(kind = 'provider', flowKind = 'http-api') {
        if (!shouldRecordProxyLifecycleEvents(flowKind)) {
            return 'engine_origin_batch';
        }
        return kind === 'retry' ? 'desktop_stream_observer' : 'sse_stream_boundary';
    }

    function createDesktopEventRecorder({ runId, correlationId, schemaVersion = 1 }) {
        const state = {
            runId,
            correlationId,
            schemaVersion,
            rootEventId: null,
            lastEventId: null,
        };

        return {
            async append(eventType, options = {}) {
                const event = {
                    eventType,
                    runId: options.runId ?? state.runId,
                    nodeId: options.nodeId ?? null,
                    attemptNo: options.attemptNo ?? 0,
                    occurredAt: options.occurredAt,
                    correlationId: options.correlationId ?? state.correlationId,
                    causationId: options.causationId ?? state.lastEventId ?? null,
                    rootEventId: options.rootEventId ?? state.rootEventId ?? undefined,
                    triggerEventId: options.triggerEventId ?? options.causationId ?? state.lastEventId ?? undefined,
                    originLayer: options.originLayer ?? 'engine',
                    idempotencyKey: options.idempotencyKey,
                    schemaVersion: options.schemaVersion ?? state.schemaVersion,
                    payloadJson: options.payloadJson ?? {},
                };
                const row = await appendWorkflowRunEvent(event);

                state.rootEventId = row.rootEventId || state.rootEventId || row.eventId;
                state.lastEventId = row.eventId;
                return row;
            },
            getState() {
                return { ...state };
            },
            setLastEventId(eventId) {
                state.lastEventId = eventId;
            },
        };
    }

    commitRuntimeConfig(runtimeConfig);
    void ensureRuntimeConfig();

    window.PPTRuntime = {
        getRuntimeConfig,
        isDesktopRuntime,
        getApiBase,
        getEngineEventMode,
        getLocalExecutionMode,
        getConfiguredEngineMode,
        getEffectiveEngineMode,
        getProviderMode,
        getAuthKeySource,
        getProviderStableFields,
        getProviderDetails,
        buildApiUrl,
        fetchWithRuntime,
        ensureRuntimeConfig,
        getAuthSession,
        getAuthToken,
        getAuthUsername,
        saveAuthSession,
        clearAuthSession,
        createWorker,
        navigate,
        resolveWorkerUrl,
        getDiagnosticsSnapshot,
        invokeDesktop,
        canRecordDesktopEvents,
        shouldUseDesktopLocalExecution,
        createWorkflowRun,
        appendWorkflowRunEvent,
        updateWorkflowRunStatus,
        runLocalSkillExecution,
        runLocalWorkflowExecution,
        classifyRetryDecision,
        shouldRecordProxyLifecycleEvents,
        getObservationSource,
        createDesktopEventRecorder,
        invoke: tauriInvoke,
    };
})();
