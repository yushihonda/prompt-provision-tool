use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

use crate::{
    app_data_dir, desktop_api_base, get_engine_mode_internal, packaged_cli_provider_binary_path,
    resolve_sidecar_target, DesktopError, PACKAGED_CLI_PROVIDER_BINARY_ID,
    PACKAGED_CLI_PROVIDER_TRANSPORT,
};

const DEFAULT_MAX_WORKERS: usize = 4;
const WORKER_TIMEOUT_SECS: u64 = 600;

enum WorkerStatus {
    Idle,
    Busy {
        task_id: u64,
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

struct BackgroundSkillTask {
    task_id: u64,
    execution_id: i64,
    skill_id: i64,
    skill_name: String,
    auth_token: String,
    api_base: String,
    engine_mode: String,
    status: String,
    output_format: String,
    result: Option<Value>,
    error_message: Option<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EnqueueBackgroundSkillInput {
    pub auth_token: String,
    pub skill_id: i64,
    pub skill_name: Option<String>,
    pub input_data: Value,
    pub output_format: Option<String>,
    pub enable_deep_think: Option<bool>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct BackgroundSkillStatus {
    pub task_id: u64,
    pub execution_id: i64,
    pub skill_id: i64,
    pub skill_name: String,
    pub status: String,
    pub output_format: String,
    pub error_message: Option<String>,
    pub worker_id: Option<usize>,
    pub result: Option<Value>,
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct BackgroundSkillProgressEvent {
    pub event_type: String,
    pub task_id: u64,
    pub execution_id: i64,
    pub skill_id: i64,
    pub skill_name: String,
    pub status: String,
    pub worker_id: Option<usize>,
    pub error_message: Option<String>,
    pub result: Option<Value>,
}

pub struct BackgroundSkillManager {
    workers: Vec<WorkerSlot>,
    next_task_id: u64,
    pending_queue: VecDeque<u64>,
    tasks: HashMap<u64, BackgroundSkillTask>,
}

impl Default for BackgroundSkillManager {
    fn default() -> Self {
        let max_workers = DEFAULT_MAX_WORKERS;
        let workers = (0..max_workers)
            .map(|id| WorkerSlot {
                id,
                status: WorkerStatus::Idle,
            })
            .collect();
        Self {
            workers,
            next_task_id: 1,
            pending_queue: VecDeque::new(),
            tasks: HashMap::new(),
        }
    }
}

impl BackgroundSkillManager {
    pub fn enqueue(
        &mut self,
        app: &AppHandle,
        input: EnqueueBackgroundSkillInput,
    ) -> Result<BackgroundSkillStatus, DesktopError> {
        let api_base = desktop_api_base();
        let engine_mode = get_engine_mode_internal(app)
            .map(|c| c.engine_mode)
            .unwrap_or_else(|_| "api_key".to_string());
        let output_format = input.output_format.clone().unwrap_or_else(|| "txt".to_string());

        let client = reqwest::blocking::Client::new();
        let mut body = json!({
            "skill_id": input.skill_id,
            "input_data": input.input_data,
            "output_format": output_format,
        });
        if let Some(enable_deep_think) = input.enable_deep_think {
            body["enable_deep_think"] = json!(enable_deep_think);
        }

        let resp = client
            .post(format!("{}/api/execute", api_base))
            .header("Authorization", format!("Bearer {}", input.auth_token))
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .map_err(|e| DesktopError::Message(format!("Failed to enqueue skill execution: {}", e)))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().unwrap_or_default();
            return Err(DesktopError::Message(format!(
                "Failed to enqueue skill execution: HTTP {} — {}",
                status, text
            )));
        }

        let resp_json: Value = resp
            .json()
            .map_err(|e| DesktopError::Message(format!("Invalid enqueue response: {}", e)))?;

        let execution_id = resp_json["execution_id"]
            .as_i64()
            .ok_or_else(|| DesktopError::Message("Missing execution_id".into()))?;

        let task_id = self.next_task_id;
        self.next_task_id += 1;

        let task = BackgroundSkillTask {
            task_id,
            execution_id,
            skill_id: input.skill_id,
            skill_name: input
                .skill_name
                .clone()
                .unwrap_or_else(|| format!("Skill {}", input.skill_id)),
            auth_token: input.auth_token,
            api_base,
            engine_mode,
            status: "queued".to_string(),
            output_format: input.output_format.unwrap_or_else(|| "txt".to_string()),
            result: None,
            error_message: None,
        };

        self.pending_queue.push_back(task_id);
        self.tasks.insert(task_id, task);

        let status = self.get_status(task_id).ok_or_else(|| {
            DesktopError::Message("Failed to build background task status".into())
        })?;
        self.emit_progress(app, "queued", &status);
        Ok(status)
    }

    pub fn get_status(&self, task_id: u64) -> Option<BackgroundSkillStatus> {
        let task = self.tasks.get(&task_id)?;
        let worker_id = self.workers.iter().find_map(|worker| match &worker.status {
            WorkerStatus::Busy { task_id: busy_task_id, .. } if *busy_task_id == task_id => Some(worker.id),
            _ => None,
        });
        Some(BackgroundSkillStatus {
            task_id: task.task_id,
            execution_id: task.execution_id,
            skill_id: task.skill_id,
            skill_name: task.skill_name.clone(),
            status: task.status.clone(),
            output_format: task.output_format.clone(),
            error_message: task.error_message.clone(),
            worker_id,
            result: task.result.clone(),
        })
    }

    pub fn has_active_tasks(&self) -> bool {
        !self.pending_queue.is_empty()
            || self
                .tasks
                .values()
                .any(|task| matches!(task.status.as_str(), "queued" | "processing" | "pending_local" | "pending"))
    }

    pub fn active_task_count(&self) -> usize {
        self.tasks
            .values()
            .filter(|task| matches!(task.status.as_str(), "queued" | "processing" | "pending_local" | "pending"))
            .count()
    }

    pub fn tick(&mut self, app: &AppHandle) {
        self.collect_completed_workers(app);

        while self.idle_worker_count() > 0 {
            let Some(task_id) = self.pending_queue.pop_front() else {
                break;
            };

            let Some(task) = self.tasks.get_mut(&task_id) else {
                continue;
            };
            if task.status != "queued" {
                continue;
            }

            task.status = "processing".to_string();
            let auth_token = task.auth_token.clone();
            let api_base = task.api_base.clone();
            let engine_mode = task.engine_mode.clone();
            let execution_id = task.execution_id;

            match self.dispatch_to_worker(app, task_id, execution_id, &auth_token, &api_base, &engine_mode) {
                Ok(worker_id) => {
                    if let Some(status) = self.get_status(task_id) {
                        self.emit_progress(app, "worker_dispatched", &BackgroundSkillStatus {
                            worker_id: Some(worker_id),
                            ..status
                        });
                    }
                }
                Err(err) => {
                    if let Some(task) = self.tasks.get_mut(&task_id) {
                        task.status = "error".to_string();
                        task.error_message = Some(err.to_string());
                    }
                    if let Some(status) = self.get_status(task_id) {
                        self.emit_progress(app, "worker_error", &status);
                    }
                }
            }
        }
    }

    fn idle_worker_count(&self) -> usize {
        self.workers.iter().filter(|worker| worker.is_idle()).count()
    }

    fn dispatch_to_worker(
        &mut self,
        app: &AppHandle,
        task_id: u64,
        execution_id: i64,
        auth_token: &str,
        api_base: &str,
        engine_mode: &str,
    ) -> Result<usize, DesktopError> {
        let worker_idx = self
            .workers
            .iter()
            .position(|worker| worker.is_idle())
            .ok_or_else(|| DesktopError::Message("No idle workers available".into()))?;

        let (child, stdout) = self.spawn_worker_process(app, execution_id, auth_token, api_base, engine_mode)?;
        let worker_id = self.workers[worker_idx].id;
        self.workers[worker_idx].status = WorkerStatus::Busy {
            task_id,
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
            .map(|dir| dir.join(format!("background_skill_{}_stderr.log", execution_id)))
            .unwrap_or_else(|_| PathBuf::from(format!("/tmp/nexmagi_background_skill_{}_stderr.log", execution_id)));

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

        for arg in &sidecar_target.args {
            cmd.arg(arg);
        }
        cmd.arg("--execute-single");

        if let Some(binary_path) = packaged_cli_provider_binary_path(app) {
            cmd.env("NEXMAGI_CLI_PROVIDER_BINARY_PATH", binary_path)
                .env("NEXMAGI_CLI_PROVIDER_RUNTIME", "binary")
                .env("NEXMAGI_CLI_PROVIDER_IMPL", PACKAGED_CLI_PROVIDER_BINARY_ID)
                .env("NEXMAGI_CLI_PROVIDER_TRANSPORT", PACKAGED_CLI_PROVIDER_TRANSPORT)
                .env("NEXMAGI_CLI_PROVIDER_ADAPTER", crate::cli_provider_adapter());
        }

        let mut child = cmd.spawn().map_err(|e| {
            DesktopError::Message(format!("Failed to spawn background skill worker for exec {}: {}", execution_id, e))
        })?;

        let payload = json!({
            "api_base": api_base,
            "auth_token": auth_token,
            "execution_id": execution_id,
            "configured_engine_mode": engine_mode,
        });

        if let Some(stdin) = child.stdin.as_mut() {
            writeln!(stdin, "{}", payload).map_err(|e| {
                DesktopError::Message(format!("Failed to write background worker stdin: {}", e))
            })?;
            stdin.flush().map_err(|e| {
                DesktopError::Message(format!("Failed to flush background worker stdin: {}", e))
            })?;
        }
        drop(child.stdin.take());

        let stdout = child
            .stdout
            .take()
            .map(BufReader::new)
            .ok_or_else(|| DesktopError::Message("Failed to capture background worker stdout".into()))?;

        Ok((child, stdout))
    }

    fn collect_completed_workers(&mut self, app: &AppHandle) {
        let mut completed_results: Vec<(usize, u64, Result<Value, String>)> = Vec::new();

        for worker in &mut self.workers {
            let (task_id, is_done, result) = match &mut worker.status {
                WorkerStatus::Busy {
                    task_id,
                    execution_id,
                    started_at,
                    child,
                    stdout,
                } => match child.try_wait() {
                    Ok(Some(_)) => {
                        let result = if let Some(reader) = stdout.take() {
                            Self::read_worker_result(reader)
                        } else {
                            Err("No stdout available".to_string())
                        };
                        (*task_id, true, result)
                    }
                    Ok(None) => {
                        if started_at.elapsed() > Duration::from_secs(WORKER_TIMEOUT_SECS) {
                            let _ = child.kill();
                            let _ = child.wait();
                            (
                                *task_id,
                                true,
                                Err(format!("Worker timed out for execution {}", execution_id)),
                            )
                        } else {
                            continue;
                        }
                    }
                    Err(err) => (*task_id, true, Err(format!("try_wait error: {}", err))),
                },
                WorkerStatus::Idle => continue,
            };

            if is_done {
                completed_results.push((worker.id, task_id, result));
                worker.status = WorkerStatus::Idle;
            }
        }

        for (worker_id, task_id, result) in completed_results {
            if let Some(task) = self.tasks.get_mut(&task_id) {
                match result {
                    Ok(value) => {
                        let status = value
                            .get("status")
                            .and_then(Value::as_str)
                            .unwrap_or("success")
                            .to_string();
                        task.status = status.clone();
                        task.error_message = value
                            .get("error_message")
                            .and_then(Value::as_str)
                            .map(|value| value.to_string());
                        task.result = Some(value);
                    }
                    Err(err) => {
                        task.status = "error".to_string();
                        task.error_message = Some(err);
                        task.result = None;
                    }
                }

                if let Some(status) = self.get_status(task_id) {
                    let event_type = if status.status == "error" {
                        "worker_error"
                    } else {
                        "worker_completed"
                    };
                    self.emit_progress(
                        app,
                        event_type,
                        &BackgroundSkillStatus {
                            worker_id: Some(worker_id),
                            ..status
                        },
                    );
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
            return Err("Worker produced no output".into());
        }
        let envelope: Value = serde_json::from_str(&line)
            .map_err(|e| format!("Invalid worker JSON: {}", e))?;
        if envelope.get("ok").and_then(Value::as_bool).unwrap_or(false) {
            Ok(envelope.get("result").cloned().unwrap_or_else(|| json!({})))
        } else {
            Err(envelope
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("Worker failed")
                .to_string())
        }
    }

    fn emit_progress(&self, app: &AppHandle, event_type: &str, status: &BackgroundSkillStatus) {
        let payload = BackgroundSkillProgressEvent {
            event_type: event_type.to_string(),
            task_id: status.task_id,
            execution_id: status.execution_id,
            skill_id: status.skill_id,
            skill_name: status.skill_name.clone(),
            status: status.status.clone(),
            worker_id: status.worker_id,
            error_message: status.error_message.clone(),
            result: status.result.clone(),
        };
        let _ = app.emit("background-skill-progress", &payload);
    }
}
