//! Workspace lifecycle — Tauri filesystem side.
//!
//! The backend `CoordinatorWorkspace` table holds workspace metadata
//! (id, plan, task, mode, status) but the actual directories live on
//! the desktop user's home tree. This module provides the three
//! Tauri commands that keep the two in sync:
//!
//! 1. `workspace_ensure_dir` — mkdir the absolute path, POST the path
//!    back to backend so the row transitions `reserved -> active`
//! 2. `workspace_promote` — backend-only status flip (files kept)
//! 3. `workspace_cleanup` — optionally rm -rf the directory, then
//!    POST backend `cleanup` to mark the row `cleaned`
//!
//! Safety: the base workspace root is `~/.nexmagi/workspaces/`. All
//! paths computed by this module are forced to be inside that root
//! and `workspace_cleanup` refuses to delete anything outside of it.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

const WORKSPACES_DIRNAME: &str = ".nexmagi";
const WORKSPACES_SUBDIR: &str = "workspaces";

#[derive(Debug, Clone, Deserialize)]
pub struct WorkspaceEnsureRequest {
    pub api_base: String,
    pub auth_token: String,
    pub workspace_id: String,
    pub plan_id: String,
    pub task_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceEnsureResponse {
    pub workspace_id: String,
    pub workspace_path: String,
    pub status: String,
    pub created: bool,
}

#[derive(Debug, Clone, Deserialize)]
pub struct WorkspaceLifecycleRequest {
    pub api_base: String,
    pub auth_token: String,
    pub workspace_id: String,
    #[serde(default)]
    pub remove_files: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceLifecycleResponse {
    pub workspace_id: String,
    pub status: String,
    pub filesystem_removed: bool,
}

fn workspaces_root() -> Result<PathBuf, String> {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or_else(|| "HOME env var not set".to_string())?;
    Ok(home.join(WORKSPACES_DIRNAME).join(WORKSPACES_SUBDIR))
}

fn sanitize_segment(s: &str) -> String {
    // Replace anything that isn't alnum / _ / - with _.
    s.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

fn workspace_dir_for(plan_id: &str, task_id: &str, workspace_id: &str) -> Result<PathBuf, String> {
    let root = workspaces_root()?;
    let plan_dir = sanitize_segment(plan_id);
    let leaf = format!("{}-{}", sanitize_segment(task_id), sanitize_segment(workspace_id));
    if plan_dir.is_empty() || leaf == "-" {
        return Err("invalid workspace id components".into());
    }
    Ok(root.join(plan_dir).join(leaf))
}

fn assert_inside_root(path: &Path) -> Result<(), String> {
    let root = workspaces_root()?;
    let canon_root = root
        .canonicalize()
        .or_else(|_| Ok::<PathBuf, String>(root.clone()))?;
    let canon_path = path
        .canonicalize()
        .or_else(|_| Ok::<PathBuf, String>(path.to_path_buf()))?;
    if !canon_path.starts_with(&canon_root) {
        return Err(format!(
            "refusing to operate outside workspaces root: {}",
            canon_path.display()
        ));
    }
    Ok(())
}

fn build_client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| format!("client_build: {e}"))
}

fn post_workspace_path(
    api_base: &str,
    auth_token: &str,
    workspace_id: &str,
    workspace_path: &str,
) -> Result<(), String> {
    let client = build_client()?;
    let url = format!(
        "{}/api/worker/workspaces/{}/path",
        api_base.trim_end_matches('/'),
        workspace_id
    );
    let body = serde_json::json!({ "workspace_path": workspace_path });
    let resp = client
        .post(&url)
        .bearer_auth(auth_token)
        .json(&body)
        .send()
        .map_err(|e| format!("post_path_failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("post_path_http_{}", resp.status().as_u16()));
    }
    Ok(())
}

fn post_lifecycle(
    api_base: &str,
    auth_token: &str,
    workspace_id: &str,
    verb: &str,
) -> Result<(), String> {
    let client = build_client()?;
    let url = format!(
        "{}/api/worker/workspaces/{}/{}",
        api_base.trim_end_matches('/'),
        workspace_id,
        verb
    );
    let resp = client
        .post(&url)
        .bearer_auth(auth_token)
        .send()
        .map_err(|e| format!("post_lifecycle_failed: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("post_lifecycle_http_{}", resp.status().as_u16()));
    }
    Ok(())
}

#[tauri::command]
pub async fn workspace_ensure_dir(
    req: WorkspaceEnsureRequest,
) -> Result<WorkspaceEnsureResponse, String> {
    let res = tokio::task::spawn_blocking(move || -> Result<WorkspaceEnsureResponse, String> {
        let dir = workspace_dir_for(&req.plan_id, &req.task_id, &req.workspace_id)?;
        let created = !dir.exists();
        if created {
            fs::create_dir_all(&dir)
                .map_err(|e| format!("mkdir_failed: {e}"))?;
        }
        let dir_str = dir.to_string_lossy().into_owned();
        post_workspace_path(&req.api_base, &req.auth_token, &req.workspace_id, &dir_str)?;
        Ok(WorkspaceEnsureResponse {
            workspace_id: req.workspace_id,
            workspace_path: dir_str,
            status: "active".into(),
            created,
        })
    })
    .await
    .map_err(|e| format!("join_ensure: {e}"))??;
    Ok(res)
}

#[tauri::command]
pub async fn workspace_promote(
    req: WorkspaceLifecycleRequest,
) -> Result<WorkspaceLifecycleResponse, String> {
    let res = tokio::task::spawn_blocking(move || -> Result<WorkspaceLifecycleResponse, String> {
        post_lifecycle(&req.api_base, &req.auth_token, &req.workspace_id, "promote")?;
        Ok(WorkspaceLifecycleResponse {
            workspace_id: req.workspace_id,
            status: "promoted".into(),
            filesystem_removed: false,
        })
    })
    .await
    .map_err(|e| format!("join_promote: {e}"))??;
    Ok(res)
}

#[tauri::command]
pub async fn workspace_cleanup(
    req: WorkspaceLifecycleRequest,
) -> Result<WorkspaceLifecycleResponse, String> {
    let res = tokio::task::spawn_blocking(move || -> Result<WorkspaceLifecycleResponse, String> {
        let mut fs_removed = false;
        if req.remove_files {
            // We only know the workspace_id here, not the plan/task
            // path. The backend is the source of truth for the path,
            // but we cannot do a blind rm -rf. Compromise: walk the
            // workspaces root and remove any directory whose name
            // ends with `-{workspace_id}`. This is O(plans * tasks)
            // but workspace_id is a uuid so collisions are impossible.
            let root = workspaces_root()?;
            if root.exists() {
                if let Ok(plan_dirs) = fs::read_dir(&root) {
                    for plan_entry in plan_dirs.flatten() {
                        let plan_path = plan_entry.path();
                        if !plan_path.is_dir() {
                            continue;
                        }
                        if let Ok(leaf_dirs) = fs::read_dir(&plan_path) {
                            for leaf in leaf_dirs.flatten() {
                                let leaf_path = leaf.path();
                                let matches = leaf_path
                                    .file_name()
                                    .and_then(|n| n.to_str())
                                    .map(|n| n.ends_with(&format!("-{}", req.workspace_id)))
                                    .unwrap_or(false);
                                if matches && leaf_path.is_dir() {
                                    // Safety: re-assert that the target is under the workspaces root.
                                    assert_inside_root(&leaf_path)?;
                                    fs::remove_dir_all(&leaf_path)
                                        .map_err(|e| format!("rm_failed: {e}"))?;
                                    fs_removed = true;
                                }
                            }
                        }
                    }
                }
            }
        }
        post_lifecycle(&req.api_base, &req.auth_token, &req.workspace_id, "cleanup")?;
        Ok(WorkspaceLifecycleResponse {
            workspace_id: req.workspace_id,
            status: "cleaned".into(),
            filesystem_removed: fs_removed,
        })
    })
    .await
    .map_err(|e| format!("join_cleanup: {e}"))??;
    Ok(res)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workspace_dir_under_root() {
        let dir = workspace_dir_for("plan1", "task1", "ws1").unwrap();
        let root = workspaces_root().unwrap();
        assert!(dir.starts_with(&root));
        assert_eq!(dir.file_name().unwrap().to_string_lossy(), "task1-ws1");
    }

    #[test]
    fn sanitize_segment_replaces_bad_chars() {
        assert_eq!(sanitize_segment("foo/bar"), "foo_bar");
        // dots, slash, and space are all replaced individually.
        assert_eq!(sanitize_segment("../escape"), "___escape");
        assert_eq!(sanitize_segment("a b.c"), "a_b_c");
        assert_eq!(sanitize_segment("safe-id_42"), "safe-id_42");
    }

    #[test]
    fn workspace_dir_rejects_all_empty() {
        let r = workspace_dir_for("", "", "");
        assert!(r.is_err());
    }

    #[test]
    fn assert_inside_root_allows_subpath() {
        let root = workspaces_root().unwrap();
        let path = root.join("plan1").join("task1-ws1");
        // Even if the path does not exist, the fallback branch passes
        // it through string comparison.
        assert!(assert_inside_root(&path).is_ok());
    }

    #[test]
    fn assert_inside_root_rejects_sibling() {
        let home = std::env::var_os("HOME").map(PathBuf::from).unwrap();
        let outside = home.join("somewhere-else");
        assert!(assert_inside_root(&outside).is_err());
    }
}
