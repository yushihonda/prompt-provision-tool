// orchestration.rs — Multi-terminal orchestration manager
//
// Manages a pool of sidecar worker processes that execute individual skills
// concurrently. The backend remains the orchestration brain; this module is
// a stateless dispatcher that:
//   1. Starts a workflow via POST /api/execute/workflow
//   2. Polls for pending_local executions
//   3. Dispatches each to an idle worker (sidecar --execute-single subprocess)
//   4. Collects results and emits Tauri events for frontend consumption
//   5. Detects terminal state via workflow status API

use std::collections::{HashMap, HashSet};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};

use crate::{
    desktop_api_base, get_engine_mode_internal, packaged_cli_provider_binary_path,
    resolve_sidecar_target, app_data_dir,
    DesktopError, DesktopState,
    PACKAGED_CLI_PROVIDER_BINARY_ID, PACKAGED_CLI_PROVIDER_TRANSPORT,
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_MAX_WORKERS: usize = 4;
const POLL_INTERVAL_MS: u64 = 500;
const WORKER_TIMEOUT_SECS: u64 = 600;

// ---------------------------------------------------------------------------
// Worker slot
// ---------------------------------------------------------------------------

enum WorkerStatus {
    Idle,
    Busy {
        execution_id: i64,
        started_at: Instant,
        child: Child,
        stdout: Option<BufReader<std::process::ChildStdout>>,
    },
}

struct WorkerSlot {
    id: usize,
    status: WorkerStatus,
}

impl WorkerSlot {
    fn is_idle(&self) -> bool {
        matches!(self.status, WorkerStatus::Idle)
    }
}

// ---------------------------------------------------------------------------
// Orchestration run (tracks one workflow execution)
// ---------------------------------------------------------------------------

struct OrchestrationRun {
    workflow_execution_id: i64,
    run_id: i64,
    auth_token: String,
    api_base: String,
    engine_mode: String,
    status: String,
    dispatched: HashSet<i64>,
    completed: HashSet<i64>,
    errors: HashMap<i64, String>,
    steps: Vec<Value>,
}

// ---------------------------------------------------------------------------
// Public types for Tauri commands
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StartOrchestrationInput {
    pub auth_token: String,
    pub workflow_id: i64,
    pub workflow_name: Option<String>,
    pub global_input_data: Value,
    pub per_skill_input: Option<Value>,
    pub output_format: Option<String>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct OrchestrationStatus {
    pub run_id: i64,
    pub workflow_execution_id: i64,
    pub status: String,
    pub total_dispatched: usize,
    pub total_completed: usize,
    pub total_errors: usize,
    pub workers: Vec<WorkerView>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct WorkerView {
    pub id: usize,
    pub status: String,
    pub execution_id: Option<i64>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct OrchestrationProgressEvent {
    pub workflow_execution_id: i64,
    pub event_type: String,
    pub execution_id: Option<i64>,
    pub worker_id: Option<usize>,
    pub total_dispatched: usize,
    pub total_completed: usize,
    pub total_errors: usize,
    pub status: String,
}

// ---------------------------------------------------------------------------
// OrchestrationManager
// ---------------------------------------------------------------------------

pub struct OrchestrationManager {
    max_workers: usize,
    workers: Vec<WorkerSlot>,
    active_runs: HashMap<i64, OrchestrationRun>,
}

impl Default for OrchestrationManager {
    fn default() -> Self {
        let max_workers = DEFAULT_MAX_WORKERS;
        let workers = (0..max_workers)
            .map(|id| WorkerSlot {
                id,
                status: WorkerStatus::Idle,
            })
            .collect();
        Self {
            max_workers,
            workers,
            active_runs: HashMap::new(),
        }
    }
}

impl OrchestrationManager {
    /// Start a new orchestrated workflow.
    /// POST /api/execute/workflow to backend, then track the run.
    pub fn start_workflow(
        &mut self,
        app: &AppHandle,
        input: StartOrchestrationInput,
    ) -> Result<OrchestrationStatus, DesktopError> {
        let api_base = desktop_api_base();
        let engine_mode = get_engine_mode_internal(app)
            .map(|c| c.engine_mode)
            .unwrap_or_else(|_| "api_key".to_string());

        // POST /api/execute/workflow
        let client = reqwest::blocking::Client::new();
        let body = json!({
            "workflow_id": input.workflow_id,
            "global_input_data": input.global_input_data,
            "per_skill_input": input.per_skill_input.unwrap_or(json!({})),
            "output_format": input.output_format.unwrap_or_else(|| "txt".to_string()),
        });

        let resp = client
            .post(format!("{}/api/execute/workflow", api_base))
            .header("Authorization", format!("Bearer {}", input.auth_token))
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .map_err(|e| DesktopError::Message(format!("Failed to start workflow: {}", e)))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().unwrap_or_default();
            return Err(DesktopError::Message(format!(
                "Failed to start workflow: HTTP {} — {}",
                status, text
            )));
        }

        let resp_json: Value = resp
            .json()
            .map_err(|e| DesktopError::Message(format!("Invalid response: {}", e)))?;

        let workflow_execution_id = resp_json["workflow_execution_id"]
            .as_i64()
            .ok_or_else(|| DesktopError::Message("Missing workflow_execution_id".into()))?;

        // Create local SQLite run record
        let run_id = self.create_local_run(app, workflow_execution_id)?;

        let run = OrchestrationRun {
            workflow_execution_id,
            run_id,
            auth_token: input.auth_token,
            api_base,
            engine_mode,
            status: "running".to_string(),
            dispatched: HashSet::new(),
            completed: HashSet::new(),
            errors: HashMap::new(),
            steps: Vec::new(),
        };

        let status = self.build_status(&run);
        self.active_runs.insert(workflow_execution_id, run);

        eprintln!(
            "[orchestration] started workflow_execution_id={}, run_id={}",
            workflow_execution_id, run_id
        );

        Ok(status)
    }

    /// Get status of a specific orchestration run.
    pub fn get_status(&self, workflow_execution_id: i64) -> Option<OrchestrationStatus> {
        self.active_runs
            .get(&workflow_execution_id)
            .map(|run| self.build_status(run))
    }

    /// Cancel a running orchestration.
    pub fn cancel(&mut self, workflow_execution_id: i64) {
        if let Some(run) = self.active_runs.get_mut(&workflow_execution_id) {
            run.status = "cancelled".to_string();
        }
        // Kill any busy workers for this run
        for worker in &mut self.workers {
            if let WorkerStatus::Busy {
                execution_id,
                ref mut child,
                ..
            } = worker.status
            {
                if self
                    .active_runs
                    .get(&workflow_execution_id)
                    .map_or(false, |r| r.dispatched.contains(&execution_id))
                {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        }
    }

    /// Has any active runs?
    pub fn has_active_runs(&self) -> bool {
        !self.active_runs.is_empty()
    }

    /// Main poll tick. Called periodically from background task.
    pub fn tick(&mut self, app: &AppHandle) {
        if self.active_runs.is_empty() {
            return;
        }

        // 1. Collect completed workers
        self.collect_completed_workers(app);

        // 2. For each active run, poll for pending executions and dispatch
        let wf_ids: Vec<i64> = self.active_runs.keys().cloned().collect();
        for wf_id in wf_ids {
            let run = match self.active_runs.get(&wf_id) {
                Some(r) if r.status == "running" => r,
                _ => continue,
            };

            // Poll backend for pending_local executions
            let pending = self.poll_pending_executions(
                &run.api_base,
                &run.auth_token,
                run.workflow_execution_id,
                &run.dispatched,
                &run.completed,
            );

            // Dispatch to idle workers
            for exec_id in pending {
                if self.idle_worker_count() == 0 {
                    break;
                }
                let run = self.active_runs.get_mut(&wf_id).unwrap();
                if run.dispatched.contains(&exec_id) {
                    continue;
                }
                run.dispatched.insert(exec_id);

                let auth_token = run.auth_token.clone();
                let api_base = run.api_base.clone();
                let engine_mode = run.engine_mode.clone();

                match self.dispatch_to_worker(app, exec_id, &auth_token, &api_base, &engine_mode) {
                    Ok(worker_id) => {
                        eprintln!(
                            "[orchestration] dispatched exec={} to worker={}",
                            exec_id, worker_id
                        );
                        self.emit_progress(app, wf_id, "worker_dispatched", Some(exec_id), Some(worker_id));
                    }
                    Err(e) => {
                        eprintln!("[orchestration] dispatch error: {}", e);
                        if let Some(run) = self.active_runs.get_mut(&wf_id) {
                            run.errors.insert(exec_id, e.to_string());
                        }
                    }
                }
            }

            // Check if workflow reached terminal state
            let run = self.active_runs.get(&wf_id).unwrap();
            if let Some(wf_status) = self.check_workflow_status(
                &run.api_base,
                &run.auth_token,
                run.workflow_execution_id,
            ) {
                if wf_status == "success" || wf_status == "error" || wf_status == "cancelled" {
                    if let Some(run) = self.active_runs.get_mut(&wf_id) {
                        run.status = wf_status.clone();
                    }
                    self.emit_progress(app, wf_id, "orchestration_completed", None, None);
                    eprintln!(
                        "[orchestration] workflow {} completed with status={}",
                        wf_id, wf_status
                    );
                }
            }
        }

        // 3. Remove completed runs
        self.active_runs.retain(|_, run| run.status == "running");
    }

    // -----------------------------------------------------------------------
    // Internal helpers
    // -----------------------------------------------------------------------

    fn idle_worker_count(&self) -> usize {
        self.workers.iter().filter(|w| w.is_idle()).count()
    }

    fn dispatch_to_worker(
        &mut self,
        app: &AppHandle,
        execution_id: i64,
        auth_token: &str,
        api_base: &str,
        engine_mode: &str,
    ) -> Result<usize, DesktopError> {
        let worker_idx = self
            .workers
            .iter()
            .position(|w| w.is_idle())
            .ok_or_else(|| DesktopError::Message("No idle workers available".into()))?;

        let (mut child, stdout) =
            self.spawn_worker_process(app, execution_id, auth_token, api_base, engine_mode)?;

        let worker_id = self.workers[worker_idx].id;
        self.workers[worker_idx].status = WorkerStatus::Busy {
            execution_id,
            started_at: Instant::now(),
            child,
            stdout: Some(stdout),
        };

        Ok(worker_id)
    }

    fn spawn_worker_process(
        &self,
        app: &AppHandle,
        execution_id: i64,
        auth_token: &str,
        api_base: &str,
        engine_mode: &str,
    ) -> Result<(Child, BufReader<std::process::ChildStdout>), DesktopError> {
        let sidecar_target = resolve_sidecar_target(app);

        if !sidecar_target.display_path.exists() {
            return Err(DesktopError::Message(format!(
                "sidecar entrypoint not found: {}",
                sidecar_target.display_path.display()
            )));
        }

        let stderr_path = app_data_dir(app)
            .map(|dir| dir.join(format!("worker_{}_stderr.log", execution_id)))
            .unwrap_or_else(|_| PathBuf::from(format!("/tmp/ppt_worker_{}_stderr.log", execution_id)));

        let stderr_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&stderr_path)
            .map(Stdio::from)
            .unwrap_or_else(|_| Stdio::inherit());

        let mut cmd = Command::new(&sidecar_target.executable_path);
        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(stderr_file);

        // Add sidecar script args + --execute-single flag
        for arg in &sidecar_target.args {
            cmd.arg(arg);
        }
        cmd.arg("--execute-single");

        // Packaged CLI provider env vars
        if let Some(binary_path) = packaged_cli_provider_binary_path(app) {
            cmd.env("PPT_CLI_PROVIDER_BINARY_PATH", binary_path)
                .env("PPT_CLI_PROVIDER_RUNTIME", "binary")
                .env("PPT_CLI_PROVIDER_IMPL", PACKAGED_CLI_PROVIDER_BINARY_ID)
                .env("PPT_CLI_PROVIDER_TRANSPORT", PACKAGED_CLI_PROVIDER_TRANSPORT)
                .env("PPT_CLI_PROVIDER_ADAPTER", crate::cli_provider_adapter());
        }

        let mut child = cmd.spawn().map_err(|e| {
            DesktopError::Message(format!("Failed to spawn worker for exec {}: {}", execution_id, e))
        })?;

        // Write payload to stdin
        let payload = json!({
            "api_base": api_base,
            "auth_token": auth_token,
            "execution_id": execution_id,
            "configured_engine_mode": engine_mode,
        });

        if let Some(stdin) = child.stdin.as_mut() {
            writeln!(stdin, "{}", payload).map_err(|e| {
                DesktopError::Message(format!("Failed to write to worker stdin: {}", e))
            })?;
            stdin.flush().map_err(|e| {
                DesktopError::Message(format!("Failed to flush worker stdin: {}", e))
            })?;
        }
        // Close stdin so the worker knows input is complete
        drop(child.stdin.take());

        let stdout = child
            .stdout
            .take()
            .map(BufReader::new)
            .ok_or_else(|| DesktopError::Message("Failed to capture worker stdout".into()))?;

        Ok((child, stdout))
    }

    fn collect_completed_workers(&mut self, app: &AppHandle) {
        // Phase 1: Collect results from completed workers (mutable borrow on workers)
        let mut completed_results: Vec<(usize, i64, Result<Value, String>)> = Vec::new();

        for worker in &mut self.workers {
            let (execution_id, is_done, result) = match &mut worker.status {
                WorkerStatus::Busy {
                    execution_id,
                    started_at,
                    child,
                    stdout,
                } => {
                    match child.try_wait() {
                        Ok(Some(_exit_status)) => {
                            let result = if let Some(reader) = stdout.take() {
                                Self::read_worker_result(reader)
                            } else {
                                Err("No stdout available".to_string())
                            };
                            (*execution_id, true, result)
                        }
                        Ok(None) => {
                            if started_at.elapsed() > Duration::from_secs(WORKER_TIMEOUT_SECS) {
                                eprintln!(
                                    "[orchestration] worker {} timed out for exec={}",
                                    worker.id, execution_id
                                );
                                let _ = child.kill();
                                let _ = child.wait();
                                (*execution_id, true, Err("Worker timed out".to_string()))
                            } else {
                                continue;
                            }
                        }
                        Err(e) => {
                            (*execution_id, true, Err(format!("try_wait error: {}", e)))
                        }
                    }
                }
                WorkerStatus::Idle => continue,
            };

            if is_done {
                completed_results.push((worker.id, execution_id, result));
                worker.status = WorkerStatus::Idle;
            }
        }

        // Phase 2: Record results and emit events (no mutable borrow on workers)
        for (worker_id, execution_id, result) in completed_results {
            for run in self.active_runs.values_mut() {
                if run.dispatched.contains(&execution_id) {
                    match &result {
                        Ok(value) => {
                            run.completed.insert(execution_id);
                            run.steps.push(value.clone());
                            eprintln!(
                                "[orchestration] worker={} completed exec={}",
                                worker_id, execution_id
                            );
                        }
                        Err(err) => {
                            run.errors.insert(execution_id, err.clone());
                            eprintln!(
                                "[orchestration] worker={} error exec={}: {}",
                                worker_id, execution_id, err
                            );
                        }
                    }
                    break;
                }
            }

            let event_type = if result.is_ok() {
                "worker_completed"
            } else {
                "worker_error"
            };

            // Find the wf_id for this execution
            for run in self.active_runs.values() {
                if run.dispatched.contains(&execution_id) {
                    self.emit_progress(
                        app,
                        run.workflow_execution_id,
                        event_type,
                        Some(execution_id),
                        Some(worker_id),
                    );
                    break;
                }
            }
        }
    }

    fn read_worker_result(reader: BufReader<std::process::ChildStdout>) -> Result<Value, String> {
        let mut line = String::new();
        let mut reader = reader;
        reader
            .read_line(&mut line)
            .map_err(|e| format!("Failed to read worker stdout: {}", e))?;

        if line.trim().is_empty() {
            return Err("Empty response from worker".to_string());
        }

        let response: Value =
            serde_json::from_str(&line).map_err(|e| format!("Invalid JSON from worker: {}", e))?;

        if response["ok"].as_bool() == Some(true) {
            Ok(response["result"].clone())
        } else {
            Err(response["error"]
                .as_str()
                .unwrap_or("unknown error")
                .to_string())
        }
    }

    fn poll_pending_executions(
        &self,
        api_base: &str,
        auth_token: &str,
        workflow_execution_id: i64,
        dispatched: &HashSet<i64>,
        completed: &HashSet<i64>,
    ) -> Vec<i64> {
        let client = reqwest::blocking::Client::new();
        let resp = client
            .get(format!("{}/api/user/executions", api_base))
            .header("Authorization", format!("Bearer {}", auth_token))
            .query(&[("limit", "500")])
            .send();

        let executions: Vec<Value> = match resp {
            Ok(r) if r.status().is_success() => r.json().unwrap_or_default(),
            _ => return Vec::new(),
        };

        // The endpoint may return {items: [...]} or [...] directly
        let items = if let Some(arr) = executions.first().and_then(|_| {
            // It's already a Vec<Value> if we got here
            None::<&Vec<Value>>
        }) {
            executions.clone()
        } else {
            executions
        };

        items
            .iter()
            .filter(|e| {
                e["workflow_execution_id"].as_i64() == Some(workflow_execution_id)
                    && e["status"].as_str() == Some("pending_local")
                    && e["id"]
                        .as_i64()
                        .map_or(true, |id| !dispatched.contains(&id) && !completed.contains(&id))
            })
            .filter_map(|e| e["id"].as_i64())
            .collect()
    }

    fn check_workflow_status(
        &self,
        api_base: &str,
        auth_token: &str,
        workflow_execution_id: i64,
    ) -> Option<String> {
        let client = reqwest::blocking::Client::new();
        let resp = client
            .get(format!(
                "{}/api/user/workflow-executions/{}/status",
                api_base, workflow_execution_id
            ))
            .header("Authorization", format!("Bearer {}", auth_token))
            .send();

        match resp {
            Ok(r) if r.status().is_success() => {
                let json: Value = r.json().ok()?;
                json["status"].as_str().map(String::from)
            }
            _ => None,
        }
    }

    fn create_local_run(
        &self,
        app: &AppHandle,
        workflow_execution_id: i64,
    ) -> Result<i64, DesktopError> {
        let db_path = app_data_dir(app)?.join("desktop_state.db");
        let conn = rusqlite::Connection::open(&db_path)
            .map_err(|e| DesktopError::Message(format!("SQLite open error: {}", e)))?;

        // Ensure orchestration tables exist (idempotent migration)
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS orchestration_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_execution_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                max_workers INTEGER NOT NULL DEFAULT 4,
                total_dispatched INTEGER NOT NULL DEFAULT 0,
                total_completed INTEGER NOT NULL DEFAULT 0,
                total_errors INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS orchestration_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                orchestration_run_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                execution_id INTEGER,
                worker_id INTEGER,
                payload_json TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );",
        )
        .map_err(|e| DesktopError::Message(format!("SQLite migration error: {}", e)))?;

        conn.execute(
            "INSERT INTO orchestration_runs (workflow_execution_id, max_workers) VALUES (?1, ?2)",
            rusqlite::params![workflow_execution_id, self.max_workers as i64],
        )
        .map_err(|e| DesktopError::Message(format!("SQLite insert error: {}", e)))?;

        Ok(conn.last_insert_rowid())
    }

    fn build_status(&self, run: &OrchestrationRun) -> OrchestrationStatus {
        OrchestrationStatus {
            run_id: run.run_id,
            workflow_execution_id: run.workflow_execution_id,
            status: run.status.clone(),
            total_dispatched: run.dispatched.len(),
            total_completed: run.completed.len(),
            total_errors: run.errors.len(),
            workers: self
                .workers
                .iter()
                .map(|w| match &w.status {
                    WorkerStatus::Idle => WorkerView {
                        id: w.id,
                        status: "idle".to_string(),
                        execution_id: None,
                    },
                    WorkerStatus::Busy { execution_id, .. } => WorkerView {
                        id: w.id,
                        status: "busy".to_string(),
                        execution_id: Some(*execution_id),
                    },
                })
                .collect(),
        }
    }

    fn emit_progress(
        &self,
        app: &AppHandle,
        workflow_execution_id: i64,
        event_type: &str,
        execution_id: Option<i64>,
        worker_id: Option<usize>,
    ) {
        if let Some(run) = self.active_runs.get(&workflow_execution_id) {
            let event = OrchestrationProgressEvent {
                workflow_execution_id,
                event_type: event_type.to_string(),
                execution_id,
                worker_id,
                total_dispatched: run.dispatched.len(),
                total_completed: run.completed.len(),
                total_errors: run.errors.len(),
                status: run.status.clone(),
            };
            let _ = app.emit("orchestration-progress", &event);
        }
    }
}
