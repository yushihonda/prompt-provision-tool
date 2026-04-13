//! Thin Tauri-command shim for external CLI execution.
//!
//! The actual subprocess + capture + classification logic lives in
//! `external_cli_runner.rs`, and concrete adapters live in
//! `external_cli_adapters/`. This file only:
//!
//! - keeps the public Tauri command name `external_cli_run`
//! - re-exports the shared types so other modules can `use crate::external_cli::*`
//! - converts the incoming request into the registry-driven runner call

use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use tauri::{AppHandle, State};

pub use crate::external_cli_traits::{
    ExternalCliAdapterConfig, ExternalCliCapability, ExternalCliExecutionRequest,
    ExternalCliExecutionResult, ExternalCliExecutionStatus, ExternalCliRuntimeKind,
};

use crate::external_cli_approval::ApprovalGate;
use crate::external_cli_registry::ExternalCliRegistry;
use crate::external_cli_runner::run_external_cli_with_adapter;

#[tauri::command]
pub async fn external_cli_run(
    app: AppHandle,
    registry: State<'_, ExternalCliRegistry>,
    approval_gate: State<'_, ApprovalGate>,
    req: ExternalCliExecutionRequest,
) -> Result<ExternalCliExecutionResult, String> {
    let cancel = Arc::new(AtomicBool::new(false));
    Ok(run_external_cli_with_adapter(&registry, Some(&approval_gate), app, req, cancel).await)
}
