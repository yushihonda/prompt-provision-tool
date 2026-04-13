//! ワークスペースライフサイクル — Tauri ファイルシステム側。
//!
//! バックエンドの `CoordinatorWorkspace` テーブルはワークスペースメタデータ
//! （id、plan、task、mode、status）を保持するが、実際のディレクトリは
//! デスクトップユーザーのホームツリーに存在する。このモジュールは
//! 両者を同期させる 3 つの Tauri コマンドを提供する:
//!
//! 1. `workspace_ensure_dir` — 絶対パスを mkdir し、バックエンドに
//!    パスを POST して行を `reserved -> active` に遷移させる
//! 2. `workspace_promote` — バックエンドのみのステータス変更（ファイルは保持）
//! 3. `workspace_cleanup` — オプションでディレクトリを rm -rf し、
//!    バックエンドに `cleanup` を POST して行を `cleaned` にマークする
//!
//! 安全性: ワークスペースルートのベースは `~/.nexmagi/workspaces/`。
//! このモジュールが算出するすべてのパスはそのルート内に強制され、
//! `workspace_cleanup` はその外部にあるものの削除を拒否する。

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
    // 英数字 / _ / - 以外のすべての文字を _ に置換する。
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
            // ここでは workspace_id のみが判明しており、plan/task パスは
            // 不明。バックエンドがパスの信頼できる情報源だが、盲目的な
            // rm -rf はできない。妥協案: ワークスペースルートを走査して
            // 名前が `-{workspace_id}` で終わるディレクトリを削除する。
            // これは O(plans * tasks) だが workspace_id は UUID なので
            // 衝突は不可能。
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
                                    // 安全性: 対象がワークスペースルート配下であることを再確認する。
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

// ───────────────────────────────────────────────
// ワークスペースからファイルの全内容を読み取る
// ───────────────────────────────────────────────

#[derive(Debug, Clone, Deserialize)]
pub struct ReadWorkspaceFileRequest {
    pub workspace_id: String,
    pub relative_path: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReadWorkspaceFileResponse {
    pub workspace_id: String,
    pub relative_path: String,
    pub size: u64,
    pub content: String,
    pub is_binary: bool,
    pub truncated: bool,
}

const READ_FILE_MAX_BYTES: usize = 5 * 1024 * 1024;
const READ_FILE_ALLOWED_EXTENSIONS: &[&str] = &[
    "html", "htm", "css", "js", "mjs", "cjs", "ts", "tsx", "jsx",
    "json", "yaml", "yml", "toml", "md", "txt", "py", "rb", "rs",
    "go", "java", "kt", "swift", "c", "cc", "cpp", "h", "hpp", "sh",
    "bash", "zsh", "sql", "xml", "csv", "ini", "conf", "env",
    "gitignore", "dockerfile",
];

fn locate_workspace_dir(workspace_id: &str) -> Result<PathBuf, String> {
    // ワークスペースルートを走査し、名前が `-{workspace_id}` で終わる
    // 最初のディレクトリを見つける。workspace_cleanup と同じ検索パターンを
    // 使用して両者の一貫性を保つ。
    let root = workspaces_root()?;
    if !root.exists() {
        return Err("workspaces root does not exist".into());
    }
    let suffix = format!("-{}", workspace_id);
    let plan_dirs = fs::read_dir(&root)
        .map_err(|e| format!("read_workspaces_root_failed: {e}"))?;
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
                    .map(|n| n.ends_with(&suffix))
                    .unwrap_or(false);
                if matches && leaf_path.is_dir() {
                    return Ok(leaf_path);
                }
            }
        }
    }
    Err(format!("workspace_not_found: {}", workspace_id))
}

#[tauri::command]
pub async fn read_workspace_file(
    req: ReadWorkspaceFileRequest,
) -> Result<ReadWorkspaceFileResponse, String> {
    let res = tokio::task::spawn_blocking(move || -> Result<ReadWorkspaceFileResponse, String> {
        // 1. ID からワークスペースディレクトリを解決
        let ws_dir = locate_workspace_dir(&req.workspace_id)?;

        // 2. 対象パスを解決する。絶対パスと `..` コンポーネントを禁止して
        //    呼び出し元がワークスペースから脱出できないようにする。
        let rel = Path::new(&req.relative_path);
        if rel.is_absolute() {
            return Err("absolute_path_not_allowed".into());
        }
        for comp in rel.components() {
            use std::path::Component;
            match comp {
                Component::Normal(_) => {}
                Component::CurDir => {}
                _ => return Err("path_component_not_allowed".into()),
            }
        }
        let target = ws_dir.join(rel);
        // 二重安全策: パス正規化後も解決されたパスが
        // ws_dir 内にあることを確認する。
        let canon_target = target
            .canonicalize()
            .map_err(|e| format!("canonicalize_failed: {e}"))?;
        let canon_ws_dir = ws_dir
            .canonicalize()
            .map_err(|e| format!("canonicalize_ws_failed: {e}"))?;
        if !canon_target.starts_with(&canon_ws_dir) {
            return Err("path_escape_blocked".into());
        }
        // ~/.nexmagi/workspaces の最上位に対するルート内チェック。
        assert_inside_root(&canon_target)?;

        // 3. 拡張子ホワイトリスト
        let ext_lower = canon_target
            .extension()
            .and_then(|e| e.to_str())
            .map(|s| s.to_ascii_lowercase())
            .unwrap_or_default();
        let file_name_lower = canon_target
            .file_name()
            .and_then(|n| n.to_str())
            .map(|s| s.to_ascii_lowercase())
            .unwrap_or_default();
        let extension_ok = READ_FILE_ALLOWED_EXTENSIONS.contains(&ext_lower.as_str())
            // 拡張子のないファイルは、小文字化した名前が "dockerfile" /
            // "makefile" のような既知の設定ファイルに一致する場合のみ許可する。
            || (ext_lower.is_empty() && matches!(
                file_name_lower.as_str(),
                "dockerfile" | "makefile" | "readme" | "license"
            ));
        if !extension_ok {
            return Err(format!("extension_not_allowed: {}", ext_lower));
        }

        // 4. サイズ上限付きでファイルを読み取る
        let meta = fs::metadata(&canon_target)
            .map_err(|e| format!("stat_failed: {e}"))?;
        if !meta.is_file() {
            return Err("not_a_regular_file".into());
        }
        let size = meta.len();
        let take = (size as usize).min(READ_FILE_MAX_BYTES);
        let truncated = size as usize > READ_FILE_MAX_BYTES;

        let mut buf = vec![0u8; take];
        use std::io::Read;
        let mut f = fs::File::open(&canon_target)
            .map_err(|e| format!("open_failed: {e}"))?;
        f.read_exact(&mut buf)
            .map_err(|e| format!("read_failed: {e}"))?;

        let (content, is_binary) = match std::str::from_utf8(&buf) {
            Ok(s) => (s.to_string(), false),
            Err(_) => (String::new(), true),
        };

        Ok(ReadWorkspaceFileResponse {
            workspace_id: req.workspace_id,
            relative_path: req.relative_path,
            size,
            content,
            is_binary,
            truncated,
        })
    })
    .await
    .map_err(|e| format!("join_read_file: {e}"))??;
    Ok(res)
}

// ── プランのアクティブなワークスペースを一覧表示 ──

#[derive(Debug, Serialize)]
pub struct ActiveWorkspaceEntry {
    pub workspace_dir_name: String,
    pub absolute_path: String,
    pub size_bytes: u64,
}

#[tauri::command]
pub async fn workspace_list_active(
    plan_id: String,
) -> Result<Vec<ActiveWorkspaceEntry>, String> {
    tokio::task::spawn_blocking(move || -> Result<Vec<ActiveWorkspaceEntry>, String> {
        let root = workspaces_root()?;
        let plan_dir = root.join(sanitize_segment(&plan_id));
        if !plan_dir.exists() || !plan_dir.is_dir() {
            return Ok(vec![]);
        }
        let mut entries = vec![];
        let rd = fs::read_dir(&plan_dir).map_err(|e| format!("read_dir: {e}"))?;
        for entry in rd.flatten() {
            let path = entry.path();
            if !path.is_dir() {
                continue;
            }
            let size = dir_size_quick(&path);
            entries.push(ActiveWorkspaceEntry {
                workspace_dir_name: entry.file_name().to_string_lossy().into_owned(),
                absolute_path: path.to_string_lossy().into_owned(),
                size_bytes: size,
            });
        }
        Ok(entries)
    })
    .await
    .map_err(|e| format!("join_list_active: {e}"))?
}

fn dir_size_quick(dir: &std::path::Path) -> u64 {
    let mut total: u64 = 0;
    if let Ok(rd) = fs::read_dir(dir) {
        for entry in rd.flatten() {
            let meta = entry.metadata();
            if let Ok(m) = meta {
                if m.is_file() {
                    total += m.len();
                } else if m.is_dir() {
                    total += dir_size_quick(&entry.path());
                }
            }
        }
    }
    total
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
        // ドット、スラッシュ、スペースはそれぞれ個別に置換される。
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
        // パスが存在しない場合でも、フォールバックブランチは
        // 文字列比較で通過する。
        assert!(assert_inside_root(&path).is_ok());
    }

    #[test]
    fn assert_inside_root_rejects_sibling() {
        let home = std::env::var_os("HOME").map(PathBuf::from).unwrap();
        let outside = home.join("somewhere-else");
        assert!(assert_inside_root(&outside).is_err());
    }
}
