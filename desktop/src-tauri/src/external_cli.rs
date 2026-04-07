//! Phase 1 entry point for external CLI execution — now a thin shim.
//!
//! After Phase 3.2 the actual subprocess + capture + classification
//! logic lives in `external_cli_runner.rs`, and concrete adapters live
//! in `external_cli_adapters/`. This file only:
//!
//! - keeps the public Tauri command name `external_cli_run`
//! - re-exports the Phase 3 types so other modules can `use crate::external_cli::*`
//! - converts the incoming request into the registry-driven runner call

use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use tauri::{AppHandle, State};

pub use crate::external_cli_traits::{
    ExternalCliAdapterConfig, ExternalCliCapability, ExternalCliExecutionRequest,
    ExternalCliExecutionResult, ExternalCliExecutionStatus, ExternalCliRuntimeKind,
};

use crate::external_cli_registry::ExternalCliRegistry;
use crate::external_cli_runner::run_external_cli_with_adapter;

#[tauri::command]
pub async fn external_cli_run(
    app: AppHandle,
    registry: State<'_, ExternalCliRegistry>,
    req: ExternalCliExecutionRequest,
) -> Result<ExternalCliExecutionResult, String> {
    let cancel = Arc::new(AtomicBool::new(false));
    Ok(run_external_cli_with_adapter(&registry, app, req, cancel).await)
}
