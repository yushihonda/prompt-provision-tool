(function () {
    const tauriInvoke = window.__TAURI__?.core?.invoke;
    // NexMAGI Desktop — Tauri前提の設定（WEB版フォールバック削除済み）
    const fallbackConfig = {
        desktop: true,
        apiBase: 'http://127.0.0.1:8000',
        workerScriptPath: 'js/execution-worker.js',
        sidecarScriptPath: '',
        engineEventMode: 'sidecar-batch',
        localExecutionMode: 'sidecar',
        configuredEngineMode: 'api_key',
        effectiveEngineMode: 'api_key',
        providerMode: 'api_key',
        providerTransport: 'sdk',
        providerAdapter: 'none',
        providerRuntime: 'python',
        providerImpl: 'sdk_execute_bundle',
        authKeySource: 'bundle_or_local_env',
        observationSource: 'engine_origin_batch',
        configSource: 'desktop-fallback',
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

    function normalizeHeaders(headersInit) {
        const normalized = {};
        if (!headersInit) {
            return normalized;
        }

        if (headersInit instanceof Headers) {
            headersInit.forEach((value, key) => {
                normalized[key] = value;
            });
            return normalized;
        }

        if (Array.isArray(headersInit)) {
            headersInit.forEach(([key, value]) => {
                normalized[String(key)] = String(value);
            });
            return normalized;
        }

        Object.entries(headersInit).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
                normalized[key] = String(value);
            }
        });
        return normalized;
    }

    function ensureHeader(headers, key, value) {
        const existingKey = Object.keys(headers).find((headerName) => headerName.toLowerCase() === key.toLowerCase());
        if (!existingKey) {
            headers[key] = value;
        }
    }

    function base64ToUint8Array(base64) {
        const binary = window.atob(base64 || '');
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
            bytes[index] = binary.charCodeAt(index);
        }
        return bytes;
    }

    async function normalizeDesktopRequest(url, options = {}) {
        const method = String(options.method || 'GET').toUpperCase();
        const headers = normalizeHeaders(options.headers);
        const body = options.body;
        const request = {
            url,
            method,
            headers,
            bodyText: null,
            bodyBase64: null,
        };

        if (body === undefined || body === null) {
            return request;
        }

        if (body instanceof FormData) {
            const formPairs = [];
            for (const [key, value] of body.entries()) {
                if (typeof value !== 'string') {
                    throw new Error('desktop native HTTP does not support file FormData bodies');
                }
                formPairs.push([key, value]);
            }
            request.bodyText = new URLSearchParams(formPairs).toString();
            ensureHeader(request.headers, 'Content-Type', 'application/x-www-form-urlencoded;charset=UTF-8');
            return request;
        }

        if (body instanceof URLSearchParams) {
            request.bodyText = body.toString();
            ensureHeader(request.headers, 'Content-Type', 'application/x-www-form-urlencoded;charset=UTF-8');
            return request;
        }

        if (typeof body === 'string') {
            request.bodyText = body;
            return request;
        }

        if (body instanceof Blob) {
            const buffer = await body.arrayBuffer();
            const bytes = new Uint8Array(buffer);
            let binary = '';
            bytes.forEach((byte) => {
                binary += String.fromCharCode(byte);
            });
            request.bodyBase64 = window.btoa(binary);
            ensureHeader(request.headers, 'Content-Type', body.type || 'application/octet-stream');
            return request;
        }

        if (body instanceof ArrayBuffer) {
            const bytes = new Uint8Array(body);
            let binary = '';
            bytes.forEach((byte) => {
                binary += String.fromCharCode(byte);
            });
            request.bodyBase64 = window.btoa(binary);
            ensureHeader(request.headers, 'Content-Type', 'application/octet-stream');
            return request;
        }

        if (ArrayBuffer.isView(body)) {
            const bytes = new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
            let binary = '';
            bytes.forEach((byte) => {
                binary += String.fromCharCode(byte);
            });
            request.bodyBase64 = window.btoa(binary);
            ensureHeader(request.headers, 'Content-Type', 'application/octet-stream');
            return request;
        }

        throw new Error(`unsupported desktop request body: ${Object.prototype.toString.call(body)}`);
    }

    async function fetchWithDesktopNativeHttp(url, options = {}) {
        const request = await normalizeDesktopRequest(url, options);
        const response = await invokeDesktop('native_http_request', { request });
        return new Response(base64ToUint8Array(response.bodyBase64), {
            status: Number(response.status || 0),
            statusText: response.statusText || '',
            headers: response.headers || {},
        });
    }

    async function fetchWithRuntime(path, options = {}) {
        const url = buildApiUrl(path);
        const mergedOptions = {
            credentials: 'include',
            ...options,
        };
        if (tauriInvoke && isDesktopRuntime()) {
            return fetchWithDesktopNativeHttp(url, mergedOptions);
        }
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
        // デスクトップ専用: sessionStorage不要（Keychain/ファイルで管理）
        return getCachedAuthSession();
    }

    function getCachedAuthSession() {
        return authSession ? { ...authSession } : null;
    }

    async function ensureAuthSession() {
        if (authSessionLoaded) {
            return getCachedAuthSession();
        }

        if (authSessionPromise) {
            return authSessionPromise;
        }

        // デスクトップ: Tauriのget_auth_sessionでKeychain/ファイルから取得
        if (tauriInvoke) {
            authSessionPromise = invokeDesktop('get_auth_session')
                .then((session) => commitAuthSession(session || null))
                .finally(() => {
                    authSessionPromise = null;
                });
            return authSessionPromise;
        }

        // フォールバック（Tauriが初期化前の場合）
        return getCachedAuthSession();
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
        return session?.username || '';
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

    // -----------------------------------------------------------------------
    // Orchestration API (multi-terminal workflow execution)
    // -----------------------------------------------------------------------

    async function startOrchestratedWorkflow(input) {
        if (!tauriInvoke) throw new Error('Orchestration requires desktop runtime');
        return tauriInvoke('start_orchestrated_workflow', { input });
    }

    async function getOrchestrationStatus(workflowExecutionId) {
        if (!tauriInvoke) return null;
        return tauriInvoke('get_orchestration_status', { workflowExecutionId });
    }

    async function cancelOrchestration(workflowExecutionId) {
        if (!tauriInvoke) return;
        return tauriInvoke('cancel_orchestration', { workflowExecutionId });
    }

    let orchestrationProgressUnlisten = null;

    function onOrchestrationProgress(callback) {
        if (!window.__TAURI__?.event?.listen) return () => {};
        if (orchestrationProgressUnlisten) {
            orchestrationProgressUnlisten();
        }
        const promise = window.__TAURI__.event.listen('orchestration-progress', (event) => {
            callback(event.payload);
        });
        promise.then(unlisten => { orchestrationProgressUnlisten = unlisten; });
        return () => {
            if (orchestrationProgressUnlisten) {
                orchestrationProgressUnlisten();
                orchestrationProgressUnlisten = null;
            }
        };
    }

    function shouldUseOrchestratedExecution() {
        return Boolean(tauriInvoke) && isDesktopRuntime();
    }

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
        startOrchestratedWorkflow,
        getOrchestrationStatus,
        cancelOrchestration,
        onOrchestrationProgress,
        shouldUseOrchestratedExecution,
        invoke: tauriInvoke,
    };
})();
