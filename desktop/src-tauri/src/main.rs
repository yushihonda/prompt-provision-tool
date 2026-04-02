use keyring::Entry;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager, State, Url};
use tauri_plugin_updater::UpdaterExt;
use thiserror::Error;

static EVENT_SEQUENCE: AtomicU64 = AtomicU64::new(1);
const PACKAGED_CLI_PROVIDER_BINARY_ID: &str = "ppt-provider-adapter";
const PACKAGED_SIDECAR_BINARY_ID: &str = "ppt-sidecar";
const PACKAGED_CLI_PROVIDER_ADAPTER: &str = "local_worker";
const PACKAGED_CLI_PROVIDER_TRANSPORT: &str = "subprocess";
const DESKTOP_KEYCHAIN_SERVICE: &str = "com.poifull.promptprovisiontool.desktop";
const DESKTOP_AUTH_SESSION_ACCOUNT: &str = "auth-session";

#[derive(Default)]
struct DesktopState {
    sidecar: Mutex<SidecarRuntime>,
}

#[derive(Default)]
struct SidecarRuntime {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    stdout: Option<BufReader<ChildStdout>>,
    next_request_id: u64,
}

#[derive(Debug, Error)]
enum DesktopError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("keyring error: {0}")]
    Keyring(#[from] keyring::Error),
    #[error("{0}")]
    Message(String),
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct AppInfo {
    name: String,
    version: String,
    identifier: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopEnv {
    platform: String,
    arch: String,
    debug: bool,
    tauri_runtime: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeConfig {
    desktop: bool,
    api_base: String,
    worker_script_path: String,
    sidecar_script_path: String,
    engine_event_mode: String,
    local_execution_mode: String,
    configured_engine_mode: String,
    effective_engine_mode: String,
    provider_mode: String,
    provider_transport: String,
    provider_adapter: String,
    provider_runtime: String,
    provider_impl: String,
    auth_key_source: String,
    observation_source: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct StorageSummary {
    db_path: String,
    migrations_applied: usize,
    engine_mode: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct EngineModeConfig {
    engine_mode: String,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AuthSession {
    token: String,
    username: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct WorkflowRunRow {
    id: i64,
    workflow_name: String,
    status: String,
    engine_mode: Option<String>,
    created_at: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct WorkflowRunEventRow {
    event_id: String,
    event_type: String,
    run_id: i64,
    node_id: Option<String>,
    attempt_no: i64,
    occurred_at: String,
    correlation_id: String,
    causation_id: Option<String>,
    root_event_id: String,
    trigger_event_id: String,
    origin_layer: String,
    idempotency_key: String,
    schema_version: i64,
    payload_json: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SidecarStatus {
    running: bool,
    pid: Option<u32>,
    mode: &'static str,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SidecarHealth {
    status: String,
    pid: Option<u32>,
    commands: Vec<String>,
    configured_engine_mode: String,
    effective_engine_mode: String,
    provider_mode: String,
    provider_transport: String,
    provider_adapter: String,
    provider_runtime: String,
    provider_impl: String,
    auth_key_source: String,
    observation_source: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DemoWorkflowResult {
    status: String,
    summary: String,
    engine_mode_hint: String,
    run_id: i64,
    event_count: usize,
    configured_engine_mode: String,
    effective_engine_mode: String,
    provider_mode: String,
    provider_transport: String,
    provider_adapter: String,
    provider_runtime: String,
    provider_impl: String,
    auth_key_source: String,
    observation_source: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct AppUpdateStatus {
    configured: bool,
    current_version: String,
    endpoints: Vec<String>,
    update_available: bool,
    version: Option<String>,
    body: Option<String>,
    pub_date: Option<String>,
    download_url: Option<String>,
    target: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SecureStorageVerificationResult {
    keychain_service: String,
    account_name: String,
    db_path: String,
    db_exists: bool,
    auth_session_write_ok: bool,
    auth_session_round_trip_ok: bool,
    cleared_after_verification: bool,
    retrieved_username: Option<String>,
    token_found_in_db: bool,
    username_found_in_db: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LocalSkillExecutionResult {
    status: String,
    execution_id: i64,
    output: String,
    model_used: String,
    tokens_used: i64,
    execution_time_ms: i64,
    output_format: String,
    error_message: Option<String>,
    run_id: i64,
    event_count: usize,
    configured_engine_mode: String,
    effective_engine_mode: String,
    provider_mode: String,
    provider_transport: String,
    provider_adapter: String,
    provider_runtime: String,
    provider_impl: String,
    auth_key_source: String,
    observation_source: String,
    token_accounting_source: String,
    provider_error_code: Option<String>,
    provider_error_message: Option<String>,
    retry_reason: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LocalWorkflowExecutionResult {
    status: String,
    workflow_execution_id: i64,
    execution_ids: Vec<i64>,
    leader_execution_id: Option<i64>,
    output: String,
    error_message: Option<String>,
    run_id: i64,
    event_count: usize,
    configured_engine_mode: String,
    effective_engine_mode: String,
    provider_mode: String,
    provider_transport: String,
    provider_adapter: String,
    provider_runtime: String,
    provider_impl: String,
    auth_key_source: String,
    observation_source: String,
    token_accounting_source: String,
    provider_error_code: Option<String>,
    provider_error_message: Option<String>,
    retry_reason: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopVerificationReport {
    contract: DesktopVerificationContract,
    mode: String,
    runtime_config: RuntimeConfig,
    sidecar_health: SidecarHealth,
    current_exe_path: String,
    resolved_cli_provider_binary_path: Option<String>,
    resolved_sidecar_path: String,
    secure_storage_result: Option<SecureStorageVerificationResult>,
    skill_result: Option<LocalSkillExecutionResult>,
    workflow_result: Option<LocalWorkflowExecutionResult>,
    run_events: Vec<WorkflowRunEventRow>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopVerificationContract {
    truth_owner: String,
    helper_policy: String,
    supported_modes: Vec<VerificationModeContract>,
    expected_runtime_truth: VerificationExpectedRuntimeTruth,
    expected_packaged_artifacts: VerificationExpectedPackagedArtifacts,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct VerificationModeContract {
    name: String,
    required_env: Vec<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct VerificationExpectedRuntimeTruth {
    provider_mode: String,
    provider_transport: String,
    provider_runtime: String,
    provider_impl: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct VerificationExpectedPackagedArtifacts {
    desktop_executable_name: String,
    cli_provider_binary_name: String,
    sidecar_binary_name: String,
}

#[derive(serde::Deserialize)]
struct SidecarResponse {
    id: u64,
    ok: bool,
    #[serde(default)]
    result: Value,
    #[serde(default)]
    error: Option<String>,
}

#[derive(Deserialize)]
struct SidecarEventDraft {
    event_key: String,
    event_type: String,
    node_id: Option<String>,
    attempt_no: i64,
    correlation_id: String,
    #[serde(default)]
    causation_key: Option<String>,
    #[serde(default)]
    root_event_key: Option<String>,
    #[serde(default)]
    trigger_event_key: Option<String>,
    origin_layer: String,
    event_idempotency_key: String,
    #[serde(default)]
    payload_json: Value,
}

#[derive(Deserialize)]
struct SidecarWorkflowResult {
    status: String,
    summary: String,
    engine_mode_hint: String,
    #[serde(default)]
    provider_output: String,
    #[serde(default)]
    configured_engine_mode: String,
    #[serde(default)]
    effective_engine_mode: String,
    #[serde(default)]
    provider_mode: String,
    #[serde(default)]
    provider_transport: String,
    #[serde(default)]
    provider_adapter: String,
    #[serde(default)]
    provider_runtime: String,
    #[serde(default)]
    provider_impl: String,
    #[serde(default)]
    auth_key_source: String,
    #[serde(default)]
    observation_source: String,
    #[serde(default)]
    events: Vec<SidecarEventDraft>,
}

#[derive(Deserialize)]
struct SidecarSkillExecutionResult {
    status: String,
    execution_id: i64,
    #[serde(default)]
    output: String,
    #[serde(default)]
    model_used: String,
    #[serde(default)]
    tokens_used: i64,
    #[serde(default)]
    execution_time_ms: i64,
    #[serde(default)]
    output_format: String,
    #[serde(default)]
    error_message: Option<String>,
    #[serde(default)]
    configured_engine_mode: String,
    #[serde(default)]
    effective_engine_mode: String,
    #[serde(default)]
    provider_mode: String,
    #[serde(default)]
    provider_transport: String,
    #[serde(default)]
    provider_adapter: String,
    #[serde(default)]
    provider_runtime: String,
    #[serde(default)]
    provider_impl: String,
    #[serde(default)]
    auth_key_source: String,
    #[serde(default)]
    observation_source: String,
    #[serde(default)]
    token_accounting_source: String,
    #[serde(default)]
    provider_error_code: Option<String>,
    #[serde(default)]
    provider_error_message: Option<String>,
    #[serde(default)]
    retry_reason: Option<String>,
    #[serde(default)]
    events: Vec<SidecarEventDraft>,
}

#[derive(Deserialize)]
struct SidecarRealWorkflowResult {
    status: String,
    workflow_execution_id: i64,
    #[serde(default)]
    execution_ids: Vec<i64>,
    #[serde(default)]
    leader_execution_id: Option<i64>,
    #[serde(default)]
    output: String,
    #[serde(default)]
    error_message: Option<String>,
    #[serde(default)]
    configured_engine_mode: String,
    #[serde(default)]
    effective_engine_mode: String,
    #[serde(default)]
    provider_mode: String,
    #[serde(default)]
    provider_transport: String,
    #[serde(default)]
    provider_adapter: String,
    #[serde(default)]
    provider_runtime: String,
    #[serde(default)]
    provider_impl: String,
    #[serde(default)]
    auth_key_source: String,
    #[serde(default)]
    observation_source: String,
    #[serde(default)]
    token_accounting_source: String,
    #[serde(default)]
    provider_error_code: Option<String>,
    #[serde(default)]
    provider_error_message: Option<String>,
    #[serde(default)]
    retry_reason: Option<String>,
    #[serde(default)]
    events: Vec<SidecarEventDraft>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CreateWorkflowRunInput {
    workflow_name: String,
    status: Option<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct AppendWorkflowRunEventInput {
    event_type: String,
    run_id: i64,
    node_id: Option<String>,
    attempt_no: Option<i64>,
    occurred_at: Option<String>,
    correlation_id: String,
    causation_id: Option<String>,
    root_event_id: Option<String>,
    trigger_event_id: Option<String>,
    origin_layer: Option<String>,
    idempotency_key: String,
    schema_version: Option<i64>,
    payload_json: Value,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct UpdateWorkflowRunStatusInput {
    run_id: i64,
    status: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct LocalSkillExecutionInput {
    auth_token: String,
    skill_id: i64,
    skill_name: Option<String>,
    input_data: Value,
    output_format: Option<String>,
    enable_deep_think: Option<bool>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct LocalWorkflowExecutionInput {
    auth_token: String,
    workflow_id: i64,
    workflow_name: Option<String>,
    global_input_data: Value,
    per_skill_input: Option<Value>,
    output_format: Option<String>,
}

impl SidecarRuntime {
    fn cleanup(&mut self) {
        self.stdin = None;
        self.stdout = None;

        if let Some(child) = self.child.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }

        self.child = None;
    }
}

#[derive(Clone)]
struct ResolvedSidecarTarget {
    executable_path: PathBuf,
    args: Vec<String>,
    display_path: PathBuf,
}

fn repo_sidecar_script_path() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../sidecar/main.py")
        .to_path_buf()
}

fn python_executable() -> String {
    env::var("PPT_SIDECAR_PYTHON").unwrap_or_else(|_| "python3".to_string())
}

fn desktop_api_base() -> String {
    env::var("PPT_DESKTOP_API_BASE")
        .or_else(|_| env::var("WORKER_SERVER_URL"))
        .unwrap_or_else(|_| "http://127.0.0.1:8000".to_string())
}

fn packaged_cli_provider_binary_name() -> String {
    if cfg!(target_os = "windows") {
        format!("{PACKAGED_CLI_PROVIDER_BINARY_ID}.exe")
    } else {
        PACKAGED_CLI_PROVIDER_BINARY_ID.to_string()
    }
}

fn packaged_sidecar_binary_name() -> String {
    if cfg!(target_os = "windows") {
        format!("{PACKAGED_SIDECAR_BINARY_ID}.exe")
    } else {
        PACKAGED_SIDECAR_BINARY_ID.to_string()
    }
}

fn packaged_resource_binary_path(
    app: &AppHandle,
    override_env_var: &str,
    binary_name: &str,
) -> Option<PathBuf> {
    if let Ok(value) = env::var(override_env_var) {
        let path = PathBuf::from(value);
        if path.exists() {
            return Some(path);
        }
    }

    if let Ok(resource_dir) = app.path().resource_dir() {
        for candidate in [
            resource_dir.join("bin").join(binary_name),
            resource_dir.join("resources").join("bin").join(binary_name),
        ] {
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }

    if let Ok(current_exe) = env::current_exe() {
        if let Some(contents_dir) = current_exe.parent().and_then(|path| path.parent()) {
            let candidate = contents_dir
                .join("Resources")
                .join("resources")
                .join("bin")
                .join(binary_name);
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }

    None
}

fn packaged_cli_provider_binary_path(app: &AppHandle) -> Option<PathBuf> {
    let binary_name = packaged_cli_provider_binary_name();
    packaged_resource_binary_path(app, "PPT_CLI_PROVIDER_BINARY_PATH", &binary_name)
}

fn packaged_sidecar_binary_path(app: &AppHandle) -> Option<PathBuf> {
    let binary_name = packaged_sidecar_binary_name();
    packaged_resource_binary_path(app, "PPT_SIDECAR_BINARY_PATH", &binary_name)
}

fn resolve_sidecar_target(app: &AppHandle) -> ResolvedSidecarTarget {
    if let Some(binary_path) = packaged_sidecar_binary_path(app) {
        return ResolvedSidecarTarget {
            executable_path: binary_path.clone(),
            args: Vec::new(),
            display_path: binary_path,
        };
    }

    let script_path = repo_sidecar_script_path();
    ResolvedSidecarTarget {
        executable_path: PathBuf::from(python_executable()),
        args: vec![script_path.display().to_string()],
        display_path: script_path,
    }
}

fn cli_provider_adapter() -> String {
    env::var("PPT_CLI_PROVIDER_ADAPTER")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| PACKAGED_CLI_PROVIDER_ADAPTER.to_string())
}

fn cli_provider_transport() -> String {
    env::var("PPT_CLI_PROVIDER_TRANSPORT")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| PACKAGED_CLI_PROVIDER_TRANSPORT.to_string())
}

fn cli_provider_detail_fields(app: &AppHandle) -> (String, String, String, String) {
    // Keep `provider_mode=cli` stable and derive only implementation-detail fields here.
    // This mirrors the Python-side command resolution contract for preview diagnostics.
    if packaged_cli_provider_binary_path(app).is_some() {
        let provider_runtime = env::var("PPT_CLI_PROVIDER_RUNTIME")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| "binary".to_string());
        let provider_impl = env::var("PPT_CLI_PROVIDER_IMPL")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| PACKAGED_CLI_PROVIDER_BINARY_ID.to_string());
        return (
            cli_provider_transport(),
            cli_provider_adapter(),
            provider_runtime,
            provider_impl,
        );
    }

    (
        cli_provider_transport(),
        cli_provider_adapter(),
        "python".to_string(),
        "local_worker.provider_adapter".to_string(),
    )
}

fn preview_runtime_diagnostics(
    app: &AppHandle,
    configured_engine_mode: &str,
) -> (String, String, String, String, String, String, String, String, String) {
    if configured_engine_mode == "cli" {
        let (provider_transport, provider_adapter, provider_runtime, provider_impl) =
            cli_provider_detail_fields(app);
        (
            configured_engine_mode.to_string(),
            "cli".to_string(),
            "cli".to_string(),
            provider_transport,
            provider_adapter,
            provider_runtime,
            provider_impl,
            "bundle_or_local_env".to_string(),
            "engine_origin_batch".to_string(),
        )
    } else {
        (
            configured_engine_mode.to_string(),
            "api_key".to_string(),
            "api_key".to_string(),
            "sdk".to_string(),
            "none".to_string(),
            "python".to_string(),
            "sdk_execute_bundle".to_string(),
            "bundle_or_local_env".to_string(),
            "engine_origin_batch".to_string(),
        )
    }
}

fn runtime_config_internal(app: &AppHandle) -> RuntimeConfig {
    let configured_engine_mode = get_engine_mode_internal(app)
        .map(|config| config.engine_mode)
        .unwrap_or_else(|_| "api_key".to_string());
    let (
        configured_engine_mode,
        effective_engine_mode,
        provider_mode,
        provider_transport,
        provider_adapter,
        provider_runtime,
        provider_impl,
        auth_key_source,
        observation_source,
    ) = preview_runtime_diagnostics(app, &configured_engine_mode);
    RuntimeConfig {
        desktop: true,
        api_base: desktop_api_base(),
        worker_script_path: "js/execution-worker.js".to_string(),
        sidecar_script_path: resolve_sidecar_target(app).display_path.display().to_string(),
        engine_event_mode: "sidecar-batch".to_string(),
        local_execution_mode: "sidecar".to_string(),
        configured_engine_mode,
        effective_engine_mode,
        provider_mode,
        provider_transport,
        provider_adapter,
        provider_runtime,
        provider_impl,
        auth_key_source,
        observation_source,
    }
}

fn verification_mode_contracts() -> Vec<VerificationModeContract> {
    vec![
        VerificationModeContract {
            name: "health".to_string(),
            required_env: Vec::new(),
        },
        VerificationModeContract {
            name: "skill".to_string(),
            required_env: vec![
                "PPT_VERIFY_AUTH_TOKEN".to_string(),
                "PPT_VERIFY_SKILL_ID".to_string(),
            ],
        },
        VerificationModeContract {
            name: "workflow".to_string(),
            required_env: vec![
                "PPT_VERIFY_AUTH_TOKEN".to_string(),
                "PPT_VERIFY_WORKFLOW_ID".to_string(),
            ],
        },
        VerificationModeContract {
            name: "storage".to_string(),
            required_env: Vec::new(),
        },
    ]
}

fn current_desktop_executable_name() -> String {
    env::current_exe()
        .ok()
        .and_then(|path| path.file_name().map(|name| name.to_string_lossy().to_string()))
        .unwrap_or_else(|| {
            if cfg!(target_os = "windows") {
                "prompt-provision-tool-desktop.exe".to_string()
            } else {
                "prompt-provision-tool-desktop".to_string()
            }
        })
}

fn desktop_verification_contract() -> DesktopVerificationContract {
    DesktopVerificationContract {
        // `PPT_VERIFY_MODE` semantics are owned here; helpers must not reinterpret them.
        truth_owner: "rust_tauri".to_string(),
        // This layer is the canonical source of runtime truth for packaged verification.
        helper_policy: "discover_launch_read_assert_only".to_string(),
        supported_modes: verification_mode_contracts(),
        // Provider field transitions are decided here, not in external verification scripts.
        expected_runtime_truth: VerificationExpectedRuntimeTruth {
            provider_mode: "cli".to_string(),
            provider_transport: PACKAGED_CLI_PROVIDER_TRANSPORT.to_string(),
            provider_runtime: "binary".to_string(),
            provider_impl: PACKAGED_CLI_PROVIDER_BINARY_ID.to_string(),
        },
        expected_packaged_artifacts: VerificationExpectedPackagedArtifacts {
            desktop_executable_name: current_desktop_executable_name(),
            cli_provider_binary_name: packaged_cli_provider_binary_name(),
            sidecar_binary_name: packaged_sidecar_binary_name(),
        },
    }
}

fn env_nonempty(name: &str) -> Option<String> {
    env::var(name).ok().and_then(|value| {
        let trimmed = value.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    })
}

fn required_env(name: &str) -> Result<String, DesktopError> {
    env_nonempty(name).ok_or_else(|| {
        DesktopError::Message(format!(
            "missing required verification environment variable: {name}"
        ))
    })
}

fn required_i64_env(name: &str) -> Result<i64, DesktopError> {
    let value = required_env(name)?;
    value.parse::<i64>().map_err(|err| {
        DesktopError::Message(format!(
            "{name} must be a valid integer, got `{value}`: {err}"
        ))
    })
}

fn env_json(name: &str, default: Value) -> Result<Value, DesktopError> {
    match env_nonempty(name) {
        Some(value) => serde_json::from_str(&value).map_err(|err| {
            DesktopError::Message(format!(
                "{name} must be valid JSON when provided: {err}"
            ))
        }),
        None => Ok(default),
    }
}

fn secure_auth_session_entry() -> Result<Entry, DesktopError> {
    Entry::new(DESKTOP_KEYCHAIN_SERVICE, DESKTOP_AUTH_SESSION_ACCOUNT).map_err(DesktopError::from)
}

fn get_auth_session_internal() -> Result<Option<AuthSession>, DesktopError> {
    let entry = secure_auth_session_entry()?;
    match entry.get_password() {
        Ok(value) => Ok(Some(serde_json::from_str(&value)?)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(DesktopError::Keyring(err)),
    }
}

fn set_auth_session_internal(auth_session: AuthSession) -> Result<AuthSession, DesktopError> {
    let entry = secure_auth_session_entry()?;
    let serialized = serde_json::to_string(&auth_session)?;
    entry.set_password(&serialized)?;
    Ok(auth_session)
}

fn clear_auth_session_internal() -> Result<(), DesktopError> {
    let entry = secure_auth_session_entry()?;
    match entry.delete_credential() {
        Ok(_) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(DesktopError::Keyring(err)),
    }
}

fn verify_secure_storage_contract_internal(
    app: &AppHandle,
) -> Result<SecureStorageVerificationResult, DesktopError> {
    // Prompt contents stay memory-only; this proof only covers auth session persistence.
    clear_auth_session_internal()?;

    let expected_session = AuthSession {
        token: env_nonempty("PPT_VERIFY_STORAGE_TOKEN").unwrap_or_else(|| unique_token("verify-token")),
        username: env_nonempty("PPT_VERIFY_STORAGE_USERNAME")
            .unwrap_or_else(|| "desktop-storage-proof".to_string()),
    };

    set_auth_session_internal(AuthSession {
        token: expected_session.token.clone(),
        username: expected_session.username.clone(),
    })?;
    let retrieved = get_auth_session_internal()?;

    let db_path = desktop_db_path(app)?;
    let db_exists = db_path.exists();
    let db_text = if db_exists {
        String::from_utf8_lossy(&fs::read(&db_path)?).to_string()
    } else {
        String::new()
    };

    clear_auth_session_internal()?;
    let cleared_after_verification = get_auth_session_internal()?.is_none();

    Ok(SecureStorageVerificationResult {
        keychain_service: DESKTOP_KEYCHAIN_SERVICE.to_string(),
        account_name: DESKTOP_AUTH_SESSION_ACCOUNT.to_string(),
        db_path: db_path.display().to_string(),
        db_exists,
        auth_session_write_ok: true,
        auth_session_round_trip_ok: retrieved
            .as_ref()
            .map(|session| {
                session.token == expected_session.token && session.username == expected_session.username
            })
            .unwrap_or(false),
        cleared_after_verification,
        retrieved_username: retrieved.map(|session| session.username),
        token_found_in_db: db_text.contains(&expected_session.token),
        username_found_in_db: db_text.contains(&expected_session.username),
    })
}

fn embedded_updater_endpoints() -> Result<Vec<Url>, DesktopError> {
    let Some(raw) = option_env!("PPT_UPDATER_ENDPOINTS_JSON") else {
        return Ok(Vec::new());
    };
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Ok(Vec::new());
    }

    let raw_endpoints = serde_json::from_str::<Vec<String>>(trimmed).map_err(|err| {
        DesktopError::Message(format!(
            "PPT_UPDATER_ENDPOINTS_JSON must be a JSON array of strings at build time: {err}"
        ))
    })?;

    raw_endpoints
        .into_iter()
        .map(|value| {
            Url::parse(&value).map_err(|err| {
                DesktopError::Message(format!(
                    "PPT_UPDATER_ENDPOINTS_JSON contains an invalid URL `{value}`: {err}"
                ))
            })
        })
        .collect()
}

fn embedded_updater_pubkey() -> Option<String> {
    option_env!("PPT_UPDATER_PUBLIC_KEY")
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn updater_is_configured() -> bool {
    embedded_updater_pubkey().is_some()
        && embedded_updater_endpoints()
            .map(|endpoints| !endpoints.is_empty())
            .unwrap_or(false)
}

fn app_data_dir(app: &AppHandle) -> Result<PathBuf, DesktopError> {
    let base = match app.path().app_data_dir() {
        Ok(path) => path,
        Err(_) => env::current_dir()?.join(".ppt-desktop"),
    };

    fs::create_dir_all(&base)?;
    Ok(base)
}

fn desktop_db_path(app: &AppHandle) -> Result<PathBuf, DesktopError> {
    Ok(app_data_dir(app)?.join("prompt_provision_tool.db"))
}

fn unique_token(prefix: &str) -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    let sequence = EVENT_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("{prefix}-{millis}-{sequence}")
}

fn table_columns(conn: &Connection, table_name: &str) -> Result<HashSet<String>, DesktopError> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info({table_name})"))?;
    let rows = stmt.query_map([], |row| row.get::<_, String>(1))?;
    let mut columns = HashSet::new();

    for row in rows {
        columns.insert(row?);
    }

    Ok(columns)
}

fn migrate_workflow_run_events_table(conn: &Connection) -> Result<(), DesktopError> {
    let columns = table_columns(conn, "workflow_run_events")?;

    if !columns.contains("event_id") {
        conn.execute("ALTER TABLE workflow_run_events ADD COLUMN event_id TEXT", [])?;
    }
    if !columns.contains("run_id") {
        conn.execute("ALTER TABLE workflow_run_events ADD COLUMN run_id INTEGER", [])?;
    }
    if !columns.contains("node_id") {
        conn.execute("ALTER TABLE workflow_run_events ADD COLUMN node_id TEXT", [])?;
    }
    if !columns.contains("attempt_no") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 0",
            [],
        )?;
    }
    if !columns.contains("occurred_at") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN occurred_at TEXT",
            [],
        )?;
    }
    if !columns.contains("correlation_id") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN correlation_id TEXT",
            [],
        )?;
    }
    if !columns.contains("causation_id") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN causation_id TEXT",
            [],
        )?;
    }
    if !columns.contains("root_event_id") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN root_event_id TEXT",
            [],
        )?;
    }
    if !columns.contains("trigger_event_id") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN trigger_event_id TEXT",
            [],
        )?;
    }
    if !columns.contains("origin_layer") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN origin_layer TEXT",
            [],
        )?;
    }
    if !columns.contains("idempotency_key") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN idempotency_key TEXT",
            [],
        )?;
    }
    if !columns.contains("schema_version") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1",
            [],
        )?;
    }
    if !columns.contains("payload_json") {
        conn.execute(
            "ALTER TABLE workflow_run_events ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'",
            [],
        )?;
    }

    if columns.contains("workflow_run_id") {
        conn.execute(
            "UPDATE workflow_run_events SET run_id = COALESCE(run_id, workflow_run_id) WHERE run_id IS NULL",
            [],
        )?;
    }

    if columns.contains("created_at") {
        conn.execute(
            "UPDATE workflow_run_events SET occurred_at = COALESCE(occurred_at, created_at, CURRENT_TIMESTAMP) WHERE occurred_at IS NULL",
            [],
        )?;
    } else {
        conn.execute(
            "UPDATE workflow_run_events SET occurred_at = COALESCE(occurred_at, CURRENT_TIMESTAMP) WHERE occurred_at IS NULL",
            [],
        )?;
    }

    conn.execute(
        "UPDATE workflow_run_events SET event_id = COALESCE(event_id, 'legacy-' || id) WHERE event_id IS NULL OR event_id = ''",
        [],
    )?;
    conn.execute(
        "UPDATE workflow_run_events SET correlation_id = COALESCE(correlation_id, 'legacy-run-' || COALESCE(run_id, id)) WHERE correlation_id IS NULL OR correlation_id = ''",
        [],
    )?;
    conn.execute(
        "UPDATE workflow_run_events SET root_event_id = COALESCE(root_event_id, event_id) WHERE root_event_id IS NULL OR root_event_id = ''",
        [],
    )?;
    conn.execute(
        "UPDATE workflow_run_events SET trigger_event_id = COALESCE(trigger_event_id, causation_id, event_id) WHERE trigger_event_id IS NULL OR trigger_event_id = ''",
        [],
    )?;
    conn.execute(
        "UPDATE workflow_run_events SET origin_layer = COALESCE(origin_layer, 'engine') WHERE origin_layer IS NULL OR origin_layer = ''",
        [],
    )?;
    conn.execute(
        "UPDATE workflow_run_events SET idempotency_key = COALESCE(idempotency_key, 'legacy-idem-' || id) WHERE idempotency_key IS NULL OR idempotency_key = ''",
        [],
    )?;
    conn.execute(
        "UPDATE workflow_run_events SET payload_json = COALESCE(payload_json, '{}') WHERE payload_json IS NULL OR payload_json = ''",
        [],
    )?;

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_run_events_event_id ON workflow_run_events(event_id)",
        [],
    )?;
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_run_events_idempotency_key ON workflow_run_events(idempotency_key)",
        [],
    )?;
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_run_events_run_time ON workflow_run_events(run_id, occurred_at)",
        [],
    )?;
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_run_events_run_type_time ON workflow_run_events(run_id, event_type, occurred_at)",
        [],
    )?;
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_run_events_correlation_time ON workflow_run_events(correlation_id, occurred_at)",
        [],
    )?;
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_run_events_run_node_attempt ON workflow_run_events(run_id, node_id, attempt_no)",
        [],
    )?;

    Ok(())
}

fn initialize_continuation_locks(conn: &Connection) -> Result<(), DesktopError> {
    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS continuation_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            node_id TEXT NOT NULL,
            attempt_no INTEGER NOT NULL DEFAULT 0,
            dedupe_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            owner_event_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            released_at TEXT,
            FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_continuation_locks_active
        ON continuation_locks(dedupe_key)
        WHERE status = 'active';
        "#
    )?;

    Ok(())
}

fn initialize_storage_internal(app: &AppHandle) -> Result<StorageSummary, DesktopError> {
    let db_path = desktop_db_path(app)?;
    let conn = Connection::open(&db_path)?;

    conn.execute_batch(
        r#"
        PRAGMA foreign_keys = ON;
        PRAGMA journal_mode = WAL;

        CREATE TABLE IF NOT EXISTS workflow_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            engine_mode TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS workflow_run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            event_type TEXT NOT NULL,
            run_id INTEGER,
            node_id TEXT,
            attempt_no INTEGER NOT NULL DEFAULT 0,
            occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            correlation_id TEXT,
            causation_id TEXT,
            root_event_id TEXT,
            trigger_event_id TEXT,
            origin_layer TEXT NOT NULL DEFAULT 'engine',
            idempotency_key TEXT,
            schema_version INTEGER NOT NULL DEFAULT 1,
            payload_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remote_skill_id INTEGER,
            name TEXT NOT NULL,
            version TEXT,
            bundle_hash TEXT,
            policy_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS skill_bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_id INTEGER NOT NULL,
            manifest_version TEXT,
            encryption_scheme TEXT,
            ciphertext BLOB NOT NULL,
            signature TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS provider_configs (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            engine_mode TEXT NOT NULL DEFAULT 'api_key',
            preferred_provider TEXT,
            preferred_model TEXT,
            cli_path TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        "#,
    )?;

    conn.execute(
        r#"
        INSERT INTO provider_configs (id, engine_mode)
        VALUES (1, 'api_key')
        ON CONFLICT(id) DO NOTHING
        "#,
        [],
    )?;

    migrate_workflow_run_events_table(&conn)?;
    initialize_continuation_locks(&conn)?;

    let engine_mode: String = conn.query_row(
        "SELECT engine_mode FROM provider_configs WHERE id = 1",
        [],
        |row| row.get(0),
    )?;

    Ok(StorageSummary {
        db_path: db_path.display().to_string(),
        migrations_applied: 7,
        engine_mode,
    })
}

fn get_engine_mode_internal(app: &AppHandle) -> Result<EngineModeConfig, DesktopError> {
    initialize_storage_internal(app)?;
    let conn = Connection::open(desktop_db_path(app)?)?;
    let engine_mode = conn.query_row(
        "SELECT engine_mode FROM provider_configs WHERE id = 1",
        [],
        |row| row.get(0),
    )?;

    Ok(EngineModeConfig { engine_mode })
}

fn set_engine_mode_internal(
    app: &AppHandle,
    engine_mode: String,
) -> Result<EngineModeConfig, DesktopError> {
    if engine_mode != "api_key" && engine_mode != "cli" {
        return Err(DesktopError::Message(
            "engine_mode must be 'api_key' or 'cli'".to_string(),
        ));
    }

    initialize_storage_internal(app)?;
    let conn = Connection::open(desktop_db_path(app)?)?;
    conn.execute(
        r#"
        UPDATE provider_configs
        SET engine_mode = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        "#,
        params![engine_mode],
    )?;

    get_engine_mode_internal(app)
}

fn list_workflow_runs_internal(app: &AppHandle) -> Result<Vec<WorkflowRunRow>, DesktopError> {
    initialize_storage_internal(app)?;
    let conn = Connection::open(desktop_db_path(app)?)?;
    let mut stmt = conn.prepare(
        r#"
        SELECT id, workflow_name, status, engine_mode, created_at
        FROM workflow_runs
        ORDER BY id DESC
        LIMIT 25
        "#,
    )?;

    let rows = stmt.query_map([], |row| {
        Ok(WorkflowRunRow {
            id: row.get(0)?,
            workflow_name: row.get(1)?,
            status: row.get(2)?,
            engine_mode: row.get(3)?,
            created_at: row.get(4)?,
        })
    })?;

    let mut items = Vec::new();
    for row in rows {
        items.push(row?);
    }

    Ok(items)
}

fn create_workflow_run_internal(
    conn: &Connection,
    workflow_name: &str,
    status: &str,
    engine_mode: Option<&str>,
) -> Result<WorkflowRunRow, DesktopError> {
    conn.execute(
        r#"
        INSERT INTO workflow_runs (workflow_name, status, engine_mode)
        VALUES (?, ?, ?)
        "#,
        params![workflow_name, status, engine_mode],
    )?;

    let run_id = conn.last_insert_rowid();
    conn.query_row(
        r#"
        SELECT id, workflow_name, status, engine_mode, created_at
        FROM workflow_runs
        WHERE id = ?
        "#,
        params![run_id],
        |row| {
            Ok(WorkflowRunRow {
                id: row.get(0)?,
                workflow_name: row.get(1)?,
                status: row.get(2)?,
                engine_mode: row.get(3)?,
                created_at: row.get(4)?,
            })
        },
    )
    .map_err(DesktopError::from)
}

fn append_workflow_run_event_internal(
    conn: &Connection,
    input: &AppendWorkflowRunEventInput,
) -> Result<WorkflowRunEventRow, DesktopError> {
    let event_id = unique_token("evt");
    let occurred_at = input.occurred_at.clone();
    let attempt_no = input.attempt_no.unwrap_or(0);
    let schema_version = input.schema_version.unwrap_or(1);
    let origin_layer = input
        .origin_layer
        .clone()
        .unwrap_or_else(|| "engine".to_string());
    let root_event_id = input
        .root_event_id
        .clone()
        .unwrap_or_else(|| event_id.clone());
    let trigger_event_id = input
        .trigger_event_id
        .clone()
        .unwrap_or_else(|| input.causation_id.clone().unwrap_or_else(|| event_id.clone()));
    let payload_json = input.payload_json.to_string();

    conn.execute(
        r#"
        INSERT OR IGNORE INTO workflow_run_events (
            event_id,
            event_type,
            run_id,
            node_id,
            attempt_no,
            occurred_at,
            correlation_id,
            causation_id,
            root_event_id,
            trigger_event_id,
            origin_layer,
            idempotency_key,
            schema_version,
            payload_json
        )
        VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?, ?, ?, ?, ?, ?, ?)
        "#,
        params![
            event_id,
            input.event_type,
            input.run_id,
            input.node_id,
            attempt_no,
            occurred_at,
            input.correlation_id,
            input.causation_id,
            root_event_id,
            trigger_event_id,
            origin_layer,
            input.idempotency_key,
            schema_version,
            payload_json,
        ],
    )?;

    conn.query_row(
        r#"
        SELECT event_id, event_type, run_id, node_id, attempt_no, occurred_at,
               correlation_id, causation_id, root_event_id, trigger_event_id, origin_layer,
               idempotency_key, schema_version, payload_json
        FROM workflow_run_events
        WHERE idempotency_key = ?
        "#,
        params![input.idempotency_key],
        |row| {
            Ok(WorkflowRunEventRow {
                event_id: row.get(0)?,
                event_type: row.get(1)?,
                run_id: row.get(2)?,
                node_id: row.get(3)?,
                attempt_no: row.get(4)?,
                occurred_at: row.get(5)?,
                correlation_id: row.get(6)?,
                causation_id: row.get(7)?,
                root_event_id: row.get(8)?,
                trigger_event_id: row.get(9)?,
                origin_layer: row.get(10)?,
                idempotency_key: row.get(11)?,
                schema_version: row.get(12)?,
                payload_json: row.get(13)?,
            })
        },
    )
    .map_err(DesktopError::from)
}

fn resolve_sidecar_event_reference(
    event_ids_by_key: &HashMap<String, String>,
    event_key: &Option<String>,
) -> Result<Option<String>, DesktopError> {
    match event_key {
        Some(key) => event_ids_by_key.get(key).cloned().map(Some).ok_or_else(|| {
            DesktopError::Message(format!("unresolved sidecar event reference: {key}"))
        }),
        None => Ok(None),
    }
}

fn append_sidecar_event_batch(
    conn: &Connection,
    run_id: i64,
    drafts: &[SidecarEventDraft],
) -> Result<Vec<WorkflowRunEventRow>, DesktopError> {
    let mut event_ids_by_key: HashMap<String, String> = HashMap::new();
    let mut rows = Vec::with_capacity(drafts.len());

    for draft in drafts {
        let row = append_workflow_run_event_internal(
            conn,
            &AppendWorkflowRunEventInput {
                event_type: draft.event_type.clone(),
                run_id,
                node_id: draft.node_id.clone(),
                attempt_no: Some(draft.attempt_no),
                occurred_at: None,
                correlation_id: draft.correlation_id.clone(),
                causation_id: resolve_sidecar_event_reference(
                    &event_ids_by_key,
                    &draft.causation_key,
                )?,
                root_event_id: resolve_sidecar_event_reference(
                    &event_ids_by_key,
                    &draft.root_event_key,
                )?,
                trigger_event_id: resolve_sidecar_event_reference(
                    &event_ids_by_key,
                    &draft.trigger_event_key,
                )?,
                origin_layer: Some(draft.origin_layer.clone()),
                idempotency_key: draft.event_idempotency_key.clone(),
                schema_version: Some(1),
                payload_json: draft.payload_json.clone(),
            },
        )?;
        event_ids_by_key.insert(draft.event_key.clone(), row.event_id.clone());
        rows.push(row);
    }

    Ok(rows)
}

fn update_workflow_run_status_internal(
    conn: &Connection,
    run_id: i64,
    status: &str,
) -> Result<(), DesktopError> {
    conn.execute(
        r#"
        UPDATE workflow_runs
        SET status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        "#,
        params![status, run_id],
    )?;
    Ok(())
}

fn list_workflow_run_events_internal(
    app: &AppHandle,
    run_id: i64,
) -> Result<Vec<WorkflowRunEventRow>, DesktopError> {
    initialize_storage_internal(app)?;
    let conn = Connection::open(desktop_db_path(app)?)?;
    let mut stmt = conn.prepare(
        r#"
        SELECT event_id, event_type, run_id, node_id, attempt_no, occurred_at,
               correlation_id, causation_id, root_event_id, trigger_event_id, origin_layer,
               idempotency_key, schema_version, payload_json
        FROM workflow_run_events
        WHERE run_id = ?
        ORDER BY occurred_at ASC, id ASC
        "#,
    )?;

    let rows = stmt.query_map(params![run_id], |row| {
        Ok(WorkflowRunEventRow {
            event_id: row.get(0)?,
            event_type: row.get(1)?,
            run_id: row.get(2)?,
            node_id: row.get(3)?,
            attempt_no: row.get(4)?,
            occurred_at: row.get(5)?,
            correlation_id: row.get(6)?,
            causation_id: row.get(7)?,
            root_event_id: row.get(8)?,
            trigger_event_id: row.get(9)?,
            origin_layer: row.get(10)?,
            idempotency_key: row.get(11)?,
            schema_version: row.get(12)?,
            payload_json: row.get(13)?,
        })
    })?;

    let mut items = Vec::new();
    for row in rows {
        items.push(row?);
    }
    Ok(items)
}

fn try_acquire_continuation_lock_internal(
    conn: &Connection,
    run_id: i64,
    node_id: &str,
    attempt_no: i64,
    dedupe_key: &str,
    owner_event_id: &str,
) -> Result<bool, DesktopError> {
    let affected = conn.execute(
        r#"
        INSERT OR IGNORE INTO continuation_locks (run_id, node_id, attempt_no, dedupe_key, status, owner_event_id)
        VALUES (?, ?, ?, ?, 'active', ?)
        "#,
        params![run_id, node_id, attempt_no, dedupe_key, owner_event_id],
    )?;
    Ok(affected > 0)
}

fn build_continuation_dedupe_key(
    run_id: i64,
    node_id: &str,
    continuation_reason: &str,
    failure_fingerprint: &str,
    delta_instruction_hash: &str,
) -> String {
    format!(
        "{run_id}:{node_id}:{continuation_reason}:{failure_fingerprint}:{delta_instruction_hash}"
    )
}

fn record_sidecar_run(
    app: &AppHandle,
    run_id: i64,
    status: &str,
    drafts: &[SidecarEventDraft],
) -> Result<usize, DesktopError> {
    let conn = Connection::open(desktop_db_path(app)?)?;
    append_sidecar_event_batch(&conn, run_id, drafts)?;
    update_workflow_run_status_internal(&conn, run_id, status)?;
    let events = list_workflow_run_events_internal(app, run_id)?;
    Ok(events.len())
}

fn ensure_sidecar_started(app: &AppHandle, runtime: &mut SidecarRuntime) -> Result<u32, DesktopError> {
    if let Some(child) = runtime.child.as_mut() {
        if child.try_wait()?.is_some() {
            runtime.cleanup();
        }
    }

    if let Some(child) = runtime.child.as_ref() {
        return Ok(child.id());
    }

    let sidecar_target = resolve_sidecar_target(app);
    if !sidecar_target.display_path.exists() {
        return Err(DesktopError::Message(format!(
            "sidecar entrypoint not found: {}",
            sidecar_target.display_path.display()
        )));
    }

    let mut child_command = Command::new(&sidecar_target.executable_path);
    child_command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    for arg in &sidecar_target.args {
        child_command.arg(arg);
    }

    if let Some(binary_path) = packaged_cli_provider_binary_path(app) {
        child_command
            .env("PPT_CLI_PROVIDER_BINARY_PATH", binary_path)
            .env("PPT_CLI_PROVIDER_RUNTIME", "binary")
            .env("PPT_CLI_PROVIDER_IMPL", PACKAGED_CLI_PROVIDER_BINARY_ID)
            .env("PPT_CLI_PROVIDER_TRANSPORT", PACKAGED_CLI_PROVIDER_TRANSPORT)
            .env("PPT_CLI_PROVIDER_ADAPTER", cli_provider_adapter());
    }

    let mut child = child_command.spawn()?;

    let pid = child.id();
    runtime.stdin = child.stdin.take();
    runtime.stdout = child.stdout.take().map(BufReader::new);
    runtime.child = Some(child);
    runtime.next_request_id = 0;

    Ok(pid)
}

fn sidecar_health_internal(
    app: &AppHandle,
    state: &State<DesktopState>,
) -> Result<SidecarHealth, DesktopError> {
    initialize_storage_internal(app)?;
    let mut runtime = state
        .sidecar
        .lock()
        .map_err(|_| DesktopError::Message("sidecar lock poisoned".to_string()))?;
    let pid = ensure_sidecar_started(app, &mut runtime)?;
    let result = send_sidecar_command(app, &mut runtime, "health", json!({}))?;
    let configured_engine_mode = get_engine_mode_internal(app)?.engine_mode;
    let (
        configured_engine_mode,
        effective_engine_mode,
        provider_mode,
        provider_transport,
        provider_adapter,
        provider_runtime,
        provider_impl,
        auth_key_source,
        observation_source,
    ) = preview_runtime_diagnostics(app, &configured_engine_mode);

    let status = result
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("ok")
        .to_string();
    let commands = result
        .get("commands")
        .and_then(Value::as_array)
        .map(|items| {
            items.iter()
                .filter_map(|item| item.as_str().map(|value| value.to_string()))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();

    Ok(SidecarHealth {
        status,
        pid: Some(pid),
        commands,
        configured_engine_mode,
        effective_engine_mode,
        provider_mode,
        provider_transport,
        provider_adapter,
        provider_runtime,
        provider_impl,
        auth_key_source,
        observation_source,
    })
}

fn run_local_skill_execution_internal(
    app: &AppHandle,
    state: &State<DesktopState>,
    input: LocalSkillExecutionInput,
) -> Result<LocalSkillExecutionResult, DesktopError> {
    initialize_storage_internal(app)?;
    let mut runtime = state
        .sidecar
        .lock()
        .map_err(|_| DesktopError::Message("sidecar lock poisoned".to_string()))?;
    let engine_mode = get_engine_mode_internal(app)?.engine_mode;
    let conn = Connection::open(desktop_db_path(app)?)?;
    let run_name = input
        .skill_name
        .clone()
        .unwrap_or_else(|| format!("Skill {}", input.skill_id));
    let run = create_workflow_run_internal(&conn, &run_name, "running", Some(&engine_mode))?;
    let correlation_id = unique_token("corr");
    let command_id = unique_token("cmd");
    let result = match send_sidecar_command(
        app,
        &mut runtime,
        "run_skill_execution",
        json!({
            "api_base": runtime_config_internal(app).api_base,
            "auth_token": input.auth_token,
            "configured_engine_mode": engine_mode,
            "skill_id": input.skill_id,
            "skill_name": input.skill_name,
            "input_data": input.input_data,
            "output_format": input.output_format.unwrap_or_else(|| "txt".to_string()),
            "enable_deep_think": input.enable_deep_think,
            "correlation_id": correlation_id,
            "command_id": command_id,
        }),
    ) {
        Ok(value) => value,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err);
        }
    };
    let typed_result: SidecarSkillExecutionResult = match serde_json::from_value(result) {
        Ok(value) => value,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err.into());
        }
    };
    let event_count = match record_sidecar_run(app, run.id, &typed_result.status, &typed_result.events) {
        Ok(count) => count,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err);
        }
    };

    Ok(LocalSkillExecutionResult {
        status: typed_result.status,
        execution_id: typed_result.execution_id,
        output: typed_result.output,
        model_used: typed_result.model_used,
        tokens_used: typed_result.tokens_used,
        execution_time_ms: typed_result.execution_time_ms,
        output_format: typed_result.output_format,
        error_message: typed_result.error_message,
        run_id: run.id,
        event_count,
        configured_engine_mode: typed_result.configured_engine_mode,
        effective_engine_mode: typed_result.effective_engine_mode,
        provider_mode: typed_result.provider_mode,
        provider_transport: typed_result.provider_transport,
        provider_adapter: typed_result.provider_adapter,
        provider_runtime: typed_result.provider_runtime,
        provider_impl: typed_result.provider_impl,
        auth_key_source: typed_result.auth_key_source,
        observation_source: typed_result.observation_source,
        token_accounting_source: typed_result.token_accounting_source,
        provider_error_code: typed_result.provider_error_code,
        provider_error_message: typed_result.provider_error_message,
        retry_reason: typed_result.retry_reason,
    })
}

fn run_local_workflow_execution_internal(
    app: &AppHandle,
    state: &State<DesktopState>,
    input: LocalWorkflowExecutionInput,
) -> Result<LocalWorkflowExecutionResult, DesktopError> {
    initialize_storage_internal(app)?;
    let mut runtime = state
        .sidecar
        .lock()
        .map_err(|_| DesktopError::Message("sidecar lock poisoned".to_string()))?;
    let engine_mode = get_engine_mode_internal(app)?.engine_mode;
    let conn = Connection::open(desktop_db_path(app)?)?;
    let run_name = input
        .workflow_name
        .clone()
        .unwrap_or_else(|| format!("Workflow {}", input.workflow_id));
    let run = create_workflow_run_internal(&conn, &run_name, "running", Some(&engine_mode))?;
    let correlation_id = unique_token("corr");
    let command_id = unique_token("cmd");
    let result = match send_sidecar_command(
        app,
        &mut runtime,
        "run_workflow_execution",
        json!({
            "api_base": runtime_config_internal(app).api_base,
            "auth_token": input.auth_token,
            "configured_engine_mode": engine_mode,
            "workflow_id": input.workflow_id,
            "workflow_name": input.workflow_name,
            "global_input_data": input.global_input_data,
            "per_skill_input": input.per_skill_input.unwrap_or_else(|| json!({})),
            "output_format": input.output_format.unwrap_or_else(|| "txt".to_string()),
            "correlation_id": correlation_id,
            "command_id": command_id,
        }),
    ) {
        Ok(value) => value,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err);
        }
    };
    let typed_result: SidecarRealWorkflowResult = match serde_json::from_value(result) {
        Ok(value) => value,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err.into());
        }
    };
    let event_count = match record_sidecar_run(app, run.id, &typed_result.status, &typed_result.events) {
        Ok(count) => count,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err);
        }
    };

    Ok(LocalWorkflowExecutionResult {
        status: typed_result.status,
        workflow_execution_id: typed_result.workflow_execution_id,
        execution_ids: typed_result.execution_ids,
        leader_execution_id: typed_result.leader_execution_id,
        output: typed_result.output,
        error_message: typed_result.error_message,
        run_id: run.id,
        event_count,
        configured_engine_mode: typed_result.configured_engine_mode,
        effective_engine_mode: typed_result.effective_engine_mode,
        provider_mode: typed_result.provider_mode,
        provider_transport: typed_result.provider_transport,
        provider_adapter: typed_result.provider_adapter,
        provider_runtime: typed_result.provider_runtime,
        provider_impl: typed_result.provider_impl,
        auth_key_source: typed_result.auth_key_source,
        observation_source: typed_result.observation_source,
        token_accounting_source: typed_result.token_accounting_source,
        provider_error_code: typed_result.provider_error_code,
        provider_error_message: typed_result.provider_error_message,
        retry_reason: typed_result.retry_reason,
    })
}

fn run_packaged_verification(app: &AppHandle) -> Result<DesktopVerificationReport, DesktopError> {
    // `PPT_VERIFY_MODE` semantics are owned here; helpers must not reinterpret them.
    initialize_storage_internal(app)?;
    if let Some(engine_mode) = env_nonempty("PPT_VERIFY_ENGINE_MODE") {
        set_engine_mode_internal(app, engine_mode)?;
    }

    let mode = env_nonempty("PPT_VERIFY_MODE").unwrap_or_else(|| "health".to_string());
    let contract = desktop_verification_contract();
    let runtime_config = runtime_config_internal(app);
    let state = app.state::<DesktopState>();
    let sidecar_health = sidecar_health_internal(app, &state)?;
    let current_exe_path = env::current_exe()
        .map(|path| path.display().to_string())
        .unwrap_or_else(|_| "<unavailable>".to_string());
    let resolved_cli_provider_binary_path =
        packaged_cli_provider_binary_path(app).map(|path| path.display().to_string());
    let resolved_sidecar_path = resolve_sidecar_target(app).display_path.display().to_string();
    let mut secure_storage_result = None;
    let mut skill_result = None;
    let mut workflow_result = None;
    let mut run_events = Vec::new();

    match mode.as_str() {
        "health" => {}
        "storage" => {
            secure_storage_result = Some(verify_secure_storage_contract_internal(app)?);
        }
        "skill" => {
            let result = run_local_skill_execution_internal(
                app,
                &state,
                LocalSkillExecutionInput {
                    auth_token: required_env("PPT_VERIFY_AUTH_TOKEN")?,
                    skill_id: required_i64_env("PPT_VERIFY_SKILL_ID")?,
                    skill_name: env_nonempty("PPT_VERIFY_SKILL_NAME"),
                    input_data: env_json("PPT_VERIFY_INPUT_JSON", json!({}))?,
                    output_format: env_nonempty("PPT_VERIFY_OUTPUT_FORMAT"),
                    enable_deep_think: env_nonempty("PPT_VERIFY_ENABLE_DEEP_THINK")
                        .map(|value| value.eq_ignore_ascii_case("true") || value == "1"),
                },
            )?;
            run_events = list_workflow_run_events_internal(app, result.run_id)?;
            skill_result = Some(result);
        }
        "workflow" => {
            let result = run_local_workflow_execution_internal(
                app,
                &state,
                LocalWorkflowExecutionInput {
                    auth_token: required_env("PPT_VERIFY_AUTH_TOKEN")?,
                    workflow_id: required_i64_env("PPT_VERIFY_WORKFLOW_ID")?,
                    workflow_name: env_nonempty("PPT_VERIFY_WORKFLOW_NAME"),
                    global_input_data: env_json("PPT_VERIFY_GLOBAL_INPUT_JSON", json!({}))?,
                    per_skill_input: Some(env_json("PPT_VERIFY_PER_SKILL_INPUT_JSON", json!({}))?),
                    output_format: env_nonempty("PPT_VERIFY_OUTPUT_FORMAT"),
                },
            )?;
            run_events = list_workflow_run_events_internal(app, result.run_id)?;
            workflow_result = Some(result);
        }
        other => {
            return Err(DesktopError::Message(format!(
                "unsupported PPT_VERIFY_MODE `{other}`; expected `health`, `storage`, `skill`, or `workflow`"
            )));
        }
    }

    Ok(DesktopVerificationReport {
        contract,
        mode,
        runtime_config,
        sidecar_health,
        current_exe_path,
        resolved_cli_provider_binary_path,
        resolved_sidecar_path,
        secure_storage_result,
        skill_result,
        workflow_result,
        run_events,
    })
}

fn send_sidecar_command(
    app: &AppHandle,
    runtime: &mut SidecarRuntime,
    command: &str,
    payload: Value,
) -> Result<Value, DesktopError> {
    ensure_sidecar_started(app, runtime)?;

    runtime.next_request_id += 1;
    let request_id = runtime.next_request_id;
    let request = json!({
        "id": request_id,
        "command": command,
        "payload": payload,
    });

    let stdin = runtime
        .stdin
        .as_mut()
        .ok_or_else(|| DesktopError::Message("sidecar stdin unavailable".to_string()))?;
    writeln!(stdin, "{}", request)?;
    stdin.flush()?;

    let stdout = runtime
        .stdout
        .as_mut()
        .ok_or_else(|| DesktopError::Message("sidecar stdout unavailable".to_string()))?;

    let mut line = String::new();
    stdout.read_line(&mut line)?;
    if line.trim().is_empty() {
        return Err(DesktopError::Message(
            "sidecar returned an empty response".to_string(),
        ));
    }

    let response: SidecarResponse = serde_json::from_str(&line)?;
    if response.id != request_id {
        return Err(DesktopError::Message(format!(
            "unexpected sidecar response id: expected {}, got {}",
            request_id, response.id
        )));
    }

    if response.ok {
        Ok(response.result)
    } else {
        Err(DesktopError::Message(
            response
                .error
                .unwrap_or_else(|| "sidecar returned an unknown error".to_string()),
        ))
    }
}

#[tauri::command]
fn ping() -> &'static str {
    "pong"
}

#[tauri::command]
fn app_info(app: AppHandle) -> AppInfo {
    AppInfo {
        name: app.package_info().name.clone(),
        version: app.package_info().version.to_string(),
        identifier: app.config().identifier.clone(),
    }
}

#[tauri::command]
fn desktop_env() -> DesktopEnv {
    DesktopEnv {
        platform: env::consts::OS.to_string(),
        arch: env::consts::ARCH.to_string(),
        debug: cfg!(debug_assertions),
        tauri_runtime: "tauri-v2".to_string(),
    }
}

#[tauri::command]
fn runtime_config(app: AppHandle) -> RuntimeConfig {
    let _ = initialize_storage_internal(&app);
    runtime_config_internal(&app)
}

#[tauri::command]
fn initialize_storage(app: AppHandle) -> Result<StorageSummary, String> {
    initialize_storage_internal(&app).map_err(|err| err.to_string())
}

#[tauri::command]
fn get_auth_session() -> Result<Option<AuthSession>, String> {
    get_auth_session_internal().map_err(|err| err.to_string())
}

#[tauri::command]
fn set_auth_session(auth_session: AuthSession) -> Result<AuthSession, String> {
    // Prompt contents stay memory-only; persistent auth session storage belongs here.
    set_auth_session_internal(auth_session).map_err(|err| err.to_string())
}

#[tauri::command]
fn clear_auth_session() -> Result<(), String> {
    clear_auth_session_internal().map_err(|err| err.to_string())
}

#[tauri::command]
fn get_engine_mode(app: AppHandle) -> Result<EngineModeConfig, String> {
    get_engine_mode_internal(&app).map_err(|err| err.to_string())
}

#[tauri::command]
fn set_engine_mode(app: AppHandle, engine_mode: String) -> Result<EngineModeConfig, String> {
    set_engine_mode_internal(&app, engine_mode).map_err(|err| err.to_string())
}

#[tauri::command]
fn list_workflow_runs(app: AppHandle) -> Result<Vec<WorkflowRunRow>, String> {
    list_workflow_runs_internal(&app).map_err(|err| err.to_string())
}

#[tauri::command]
fn create_workflow_run(
    app: AppHandle,
    input: CreateWorkflowRunInput,
) -> Result<WorkflowRunRow, String> {
    initialize_storage_internal(&app).map_err(|err| err.to_string())?;
    let conn = Connection::open(desktop_db_path(&app).map_err(|err| err.to_string())?)
        .map_err(|err| err.to_string())?;
    create_workflow_run_internal(
        &conn,
        &input.workflow_name,
        input.status.as_deref().unwrap_or("running"),
        None,
    )
    .map_err(|err| err.to_string())
}

#[tauri::command]
fn append_workflow_run_event(
    app: AppHandle,
    input: AppendWorkflowRunEventInput,
) -> Result<WorkflowRunEventRow, String> {
    initialize_storage_internal(&app).map_err(|err| err.to_string())?;
    let conn = Connection::open(desktop_db_path(&app).map_err(|err| err.to_string())?)
        .map_err(|err| err.to_string())?;
    append_workflow_run_event_internal(&conn, &input).map_err(|err| err.to_string())
}

#[tauri::command]
fn update_workflow_run_status(
    app: AppHandle,
    input: UpdateWorkflowRunStatusInput,
) -> Result<(), String> {
    initialize_storage_internal(&app).map_err(|err| err.to_string())?;
    let conn = Connection::open(desktop_db_path(&app).map_err(|err| err.to_string())?)
        .map_err(|err| err.to_string())?;
    update_workflow_run_status_internal(&conn, input.run_id, &input.status)
        .map_err(|err| err.to_string())
}

#[tauri::command]
fn list_workflow_run_events(app: AppHandle, run_id: i64) -> Result<Vec<WorkflowRunEventRow>, String> {
    list_workflow_run_events_internal(&app, run_id).map_err(|err| err.to_string())
}

#[tauri::command]
fn simulate_continuation(
    app: AppHandle,
    run_id: i64,
    node_id: String,
    attempt_no: i64,
    continuation_reason: String,
    failure_fingerprint: String,
    delta_instruction_hash: String,
) -> Result<Vec<WorkflowRunEventRow>, String> {
    initialize_storage_internal(&app).map_err(|err| err.to_string())?;
    let conn = Connection::open(desktop_db_path(&app).map_err(|err| err.to_string())?)
        .map_err(|err| err.to_string())?;

    let correlation_id = unique_token("corr");
    let continuation_dedupe_key = build_continuation_dedupe_key(
        run_id,
        &node_id,
        &continuation_reason,
        &failure_fingerprint,
        &delta_instruction_hash,
    );

    let candidate = append_workflow_run_event_internal(
        &conn,
        &AppendWorkflowRunEventInput {
            event_type: "continuation_candidate_detected".to_string(),
            run_id,
            node_id: Some(node_id.clone()),
            attempt_no: Some(attempt_no),
            occurred_at: None,
            correlation_id: correlation_id.clone(),
            causation_id: None,
            root_event_id: None,
            trigger_event_id: None,
            origin_layer: Some("continuation".to_string()),
            idempotency_key: format!("candidate:{continuation_dedupe_key}"),
            schema_version: Some(1),
            payload_json: json!({
                "continuation_reason": continuation_reason,
                "failure_fingerprint": failure_fingerprint,
                "delta_instruction_hash": delta_instruction_hash,
                "continuation_dedupe_key": continuation_dedupe_key,
            }),
        },
    )
    .map_err(|err| err.to_string())?;

    let acquired = try_acquire_continuation_lock_internal(
        &conn,
        run_id,
        &node_id,
        attempt_no,
        &continuation_dedupe_key,
        &candidate.event_id,
    )
    .map_err(|err| err.to_string())?;

    let lock_event_type = if acquired {
        "continuation_lock_acquired"
    } else {
        "continuation_lock_rejected"
    };
    let lock_event = append_workflow_run_event_internal(
        &conn,
        &AppendWorkflowRunEventInput {
            event_type: lock_event_type.to_string(),
            run_id,
            node_id: Some(node_id.clone()),
            attempt_no: Some(attempt_no),
            occurred_at: None,
            correlation_id: correlation_id.clone(),
            causation_id: Some(candidate.event_id.clone()),
            root_event_id: Some(candidate.event_id.clone()),
            trigger_event_id: Some(candidate.event_id.clone()),
            origin_layer: Some("continuation".to_string()),
            idempotency_key: format!("lock:{continuation_dedupe_key}:{lock_event_type}"),
            schema_version: Some(1),
            payload_json: json!({
                "continuation_dedupe_key": continuation_dedupe_key,
                "lock_acquired": acquired,
            }),
        },
    )
    .map_err(|err| err.to_string())?;

    let terminal_event_type = if acquired {
        "continuation_spawned"
    } else {
        "duplicate_suppressed"
    };
    let terminal_event = append_workflow_run_event_internal(
        &conn,
        &AppendWorkflowRunEventInput {
            event_type: terminal_event_type.to_string(),
            run_id,
            node_id: Some(node_id.clone()),
            attempt_no: Some(attempt_no),
            occurred_at: None,
            correlation_id,
            causation_id: Some(lock_event.event_id.clone()),
            root_event_id: Some(candidate.event_id.clone()),
            trigger_event_id: Some(lock_event.event_id.clone()),
            origin_layer: Some("continuation".to_string()),
            idempotency_key: format!("terminal:{continuation_dedupe_key}:{terminal_event_type}"),
            schema_version: Some(1),
            payload_json: json!({
                "continuation_dedupe_key": continuation_dedupe_key,
                "lock_event_id": lock_event.event_id,
            }),
        },
    )
    .map_err(|err| err.to_string())?;

    Ok(vec![candidate, lock_event, terminal_event])
}

#[tauri::command]
fn start_sidecar(app: AppHandle, state: State<DesktopState>) -> Result<SidecarStatus, String> {
    let mut runtime = state.sidecar.lock().map_err(|_| "sidecar lock poisoned")?;
    let pid = ensure_sidecar_started(&app, &mut runtime).map_err(|err| err.to_string())?;

    Ok(SidecarStatus {
        running: true,
        pid: Some(pid),
        mode: "stdio",
    })
}

#[tauri::command]
fn stop_sidecar(app: AppHandle, state: State<DesktopState>) -> Result<SidecarStatus, String> {
    let mut runtime = state.sidecar.lock().map_err(|_| "sidecar lock poisoned")?;

    if runtime.child.is_some() {
        let _ = send_sidecar_command(&app, &mut runtime, "shutdown", json!({}));
        runtime.cleanup();
    }

    Ok(SidecarStatus {
        running: false,
        pid: None,
        mode: "stdio",
    })
}

#[tauri::command]
fn sidecar_health(app: AppHandle, state: State<DesktopState>) -> Result<SidecarHealth, String> {
    sidecar_health_internal(&app, &state).map_err(|err| err.to_string())
}

#[tauri::command]
fn run_demo_workflow(
    app: AppHandle,
    state: State<DesktopState>,
    topic: Option<String>,
) -> Result<DemoWorkflowResult, String> {
    initialize_storage_internal(&app).map_err(|err| err.to_string())?;
    let mut runtime = state.sidecar.lock().map_err(|_| "sidecar lock poisoned")?;
    let engine_mode = get_engine_mode_internal(&app)
        .map_err(|err| err.to_string())?
        .engine_mode;
    let conn = Connection::open(desktop_db_path(&app).map_err(|err| err.to_string())?)
        .map_err(|err| err.to_string())?;
    let run = create_workflow_run_internal(
        &conn,
        "Desktop Demo Workflow",
        "running",
        Some(&engine_mode),
    )
    .map_err(|err| err.to_string())?;
    let correlation_id = unique_token("corr");
    let command_id = unique_token("cmd");
    let result = send_sidecar_command(
        &app,
        &mut runtime,
        "run_demo_workflow",
        json!({
            "topic": topic.unwrap_or_else(|| "Desktop orchestration bootstrap".to_string()),
            "engine_mode": engine_mode,
            "workflow_name": run.workflow_name,
            "correlation_id": correlation_id,
            "command_id": command_id,
            "node_id": "demo-node",
            "attempt_no": 1,
        }),
    );
    let result = match result {
        Ok(value) => value,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err.to_string());
        }
    };
    let typed_result: SidecarWorkflowResult = match serde_json::from_value(result) {
        Ok(value) => value,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err.to_string());
        }
    };
    let event_count = match record_sidecar_run(&app, run.id, &typed_result.status, &typed_result.events)
    {
        Ok(count) => count,
        Err(err) => {
            let _ = update_workflow_run_status_internal(&conn, run.id, "error");
            return Err(err.to_string());
        }
    };

    Ok(DemoWorkflowResult {
        status: typed_result.status,
        summary: typed_result.summary,
        engine_mode_hint: typed_result.engine_mode_hint,
        run_id: run.id,
        event_count,
        configured_engine_mode: typed_result.configured_engine_mode,
        effective_engine_mode: typed_result.effective_engine_mode,
        provider_mode: typed_result.provider_mode,
        provider_transport: typed_result.provider_transport,
        provider_adapter: typed_result.provider_adapter,
        provider_runtime: typed_result.provider_runtime,
        provider_impl: typed_result.provider_impl,
        auth_key_source: typed_result.auth_key_source,
        observation_source: typed_result.observation_source,
    })
}

#[tauri::command]
fn run_local_skill_execution(
    app: AppHandle,
    state: State<DesktopState>,
    input: LocalSkillExecutionInput,
) -> Result<LocalSkillExecutionResult, String> {
    run_local_skill_execution_internal(&app, &state, input).map_err(|err| err.to_string())
}

#[tauri::command]
fn run_local_workflow_execution(
    app: AppHandle,
    state: State<DesktopState>,
    input: LocalWorkflowExecutionInput,
) -> Result<LocalWorkflowExecutionResult, String> {
    run_local_workflow_execution_internal(&app, &state, input).map_err(|err| err.to_string())
}

#[tauri::command]
async fn check_for_app_update(app: AppHandle) -> Result<AppUpdateStatus, String> {
    let endpoints = embedded_updater_endpoints().map_err(|err| err.to_string())?;
    let endpoint_strings = endpoints.iter().map(|value| value.to_string()).collect::<Vec<_>>();
    let pubkey = embedded_updater_pubkey();
    let current_version = app.package_info().version.to_string();

    if endpoints.is_empty() || pubkey.is_none() {
        return Ok(AppUpdateStatus {
            configured: false,
            current_version,
            endpoints: endpoint_strings,
            update_available: false,
            version: None,
            body: None,
            pub_date: None,
            download_url: None,
            target: None,
        });
    }

    let update = app
        .updater_builder()
        .pubkey(pubkey.unwrap())
        .endpoints(endpoints.clone())
        .map_err(|err| err.to_string())?
        .build()
        .map_err(|err| err.to_string())?
        .check()
        .await
        .map_err(|err| err.to_string())?;

    if let Some(update) = update {
        Ok(AppUpdateStatus {
            configured: true,
            current_version,
            endpoints: endpoint_strings,
            update_available: true,
            version: Some(update.version.to_string()),
            body: update.body,
            pub_date: update.date.map(|value| value.to_string()),
            download_url: Some(update.download_url.to_string()),
            target: Some(update.target),
        })
    } else {
        Ok(AppUpdateStatus {
            configured: true,
            current_version,
            endpoints: endpoint_strings,
            update_available: false,
            version: None,
            body: None,
            pub_date: None,
            download_url: None,
            target: None,
        })
    }
}

fn main() {
    let builder = tauri::Builder::default();
    let builder = if updater_is_configured() {
        builder.plugin(tauri_plugin_updater::Builder::new().build())
    } else {
        builder
    };

    builder.manage(DesktopState::default()).setup(|app| {
            if env_nonempty("PPT_VERIFY_MODE").is_some() {
                let app_handle = app.handle().clone();
                let exit_code = match run_packaged_verification(&app_handle) {
                    Ok(report) => {
                        println!(
                            "{}",
                            serde_json::to_string_pretty(&report).unwrap_or_else(|_| "{}".to_string())
                        );
                        0
                    }
                    Err(err) => {
                        eprintln!(
                            "{}",
                            serde_json::to_string_pretty(&json!({
                                "mode": env_nonempty("PPT_VERIFY_MODE").unwrap_or_else(|| "health".to_string()),
                                "status": "error",
                                "message": err.to_string(),
                            }))
                            .unwrap_or_else(|_| "{\"status\":\"error\"}".to_string())
                        );
                        1
                    }
                };
                app_handle.exit(exit_code);
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ping,
            app_info,
            desktop_env,
            runtime_config,
            initialize_storage,
            get_auth_session,
            set_auth_session,
            clear_auth_session,
            get_engine_mode,
            set_engine_mode,
            list_workflow_runs,
            create_workflow_run,
            append_workflow_run_event,
            update_workflow_run_status,
            list_workflow_run_events,
            simulate_continuation,
            start_sidecar,
            stop_sidecar,
            sidecar_health,
            run_demo_workflow,
            run_local_skill_execution,
            run_local_workflow_execution,
            check_for_app_update
        ])
        .run(tauri::generate_context!())
        .expect("failed to run desktop app");
}
