//! Local LLM (Ollama / OpenAI-compatible) read-only probe commands.
//!
//! These Tauri commands are pure HTTP relays — they never mutate backend
//! state. The frontend uses them for instant feedback in the adapter
//! settings panel; persistent health updates go through the backend
//! `/api/adapters/{id}/health/refresh` endpoint.

use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};

const PROBE_TIMEOUT_SECS: u64 = 5;
const MAX_RESPONSE_BYTES: u64 = 1024 * 1024; // 1 MiB cap

#[derive(Debug, Clone, Deserialize)]
pub struct LocalLlmPingRequest {
    pub base_url: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct LocalLlmPingResponse {
    pub reachable: bool,
    pub latency_ms: Option<u64>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct LocalLlmModelsRequest {
    pub base_url: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct LocalLlmModelsResponse {
    pub reachable: bool,
    pub models: Vec<String>,
    pub latency_ms: Option<u64>,
    pub error: Option<String>,
}

fn validate_scheme(base_url: &str) -> Result<(), String> {
    if base_url.starts_with("http://") || base_url.starts_with("https://") {
        Ok(())
    } else {
        Err("invalid_scheme".into())
    }
}

fn models_url(base_url: &str) -> String {
    format!("{}/models", base_url.trim_end_matches('/'))
}

fn build_client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(PROBE_TIMEOUT_SECS))
        .build()
        .map_err(|e| format!("client_build_failed: {e}"))
}

#[tauri::command]
pub async fn local_llm_ping(req: LocalLlmPingRequest) -> Result<LocalLlmPingResponse, String> {
    validate_scheme(&req.base_url)?;
    let url = models_url(&req.base_url);

    let result = tokio::task::spawn_blocking(move || -> LocalLlmPingResponse {
        let client = match build_client() {
            Ok(c) => c,
            Err(e) => {
                return LocalLlmPingResponse {
                    reachable: false,
                    latency_ms: None,
                    error: Some(e),
                };
            }
        };
        let started = Instant::now();
        match client.get(&url).send() {
            Ok(resp) => {
                let latency = started.elapsed().as_millis() as u64;
                let status = resp.status();
                if status.is_success() {
                    LocalLlmPingResponse {
                        reachable: true,
                        latency_ms: Some(latency),
                        error: None,
                    }
                } else {
                    LocalLlmPingResponse {
                        reachable: false,
                        latency_ms: Some(latency),
                        error: Some(format!("http_{}", status.as_u16())),
                    }
                }
            }
            Err(e) => LocalLlmPingResponse {
                reachable: false,
                latency_ms: None,
                error: Some(format!("{e}")),
            },
        }
    })
    .await
    .map_err(|e| format!("task_join_failed: {e}"))?;

    Ok(result)
}

#[tauri::command]
pub async fn local_llm_list_models(
    req: LocalLlmModelsRequest,
) -> Result<LocalLlmModelsResponse, String> {
    validate_scheme(&req.base_url)?;
    let url = models_url(&req.base_url);

    let result = tokio::task::spawn_blocking(move || -> LocalLlmModelsResponse {
        let client = match build_client() {
            Ok(c) => c,
            Err(e) => {
                return LocalLlmModelsResponse {
                    reachable: false,
                    models: vec![],
                    latency_ms: None,
                    error: Some(e),
                };
            }
        };
        let started = Instant::now();
        let resp = match client.get(&url).send() {
            Ok(r) => r,
            Err(e) => {
                return LocalLlmModelsResponse {
                    reachable: false,
                    models: vec![],
                    latency_ms: None,
                    error: Some(format!("{e}")),
                };
            }
        };
        let latency = started.elapsed().as_millis() as u64;
        let status = resp.status();
        if !status.is_success() {
            return LocalLlmModelsResponse {
                reachable: false,
                models: vec![],
                latency_ms: Some(latency),
                error: Some(format!("http_{}", status.as_u16())),
            };
        }
        // Cap response size.
        let bytes = match resp.bytes() {
            Ok(b) => b,
            Err(e) => {
                return LocalLlmModelsResponse {
                    reachable: true,
                    models: vec![],
                    latency_ms: Some(latency),
                    error: Some(format!("read_failed: {e}")),
                };
            }
        };
        if bytes.len() as u64 > MAX_RESPONSE_BYTES {
            return LocalLlmModelsResponse {
                reachable: true,
                models: vec![],
                latency_ms: Some(latency),
                error: Some("response_too_large".into()),
            };
        }
        let value: serde_json::Value = match serde_json::from_slice(&bytes) {
            Ok(v) => v,
            Err(e) => {
                return LocalLlmModelsResponse {
                    reachable: true,
                    models: vec![],
                    latency_ms: Some(latency),
                    error: Some(format!("malformed_json: {e}")),
                };
            }
        };
        let mut models: Vec<String> = vec![];
        if let Some(arr) = value.get("data").and_then(|v| v.as_array()) {
            for item in arr {
                if let Some(id) = item.get("id").and_then(|v| v.as_str()) {
                    models.push(id.to_string());
                }
            }
        } else {
            return LocalLlmModelsResponse {
                reachable: true,
                models: vec![],
                latency_ms: Some(latency),
                error: Some("malformed_response".into()),
            };
        }
        LocalLlmModelsResponse {
            reachable: true,
            models,
            latency_ms: Some(latency),
            error: None,
        }
    })
    .await
    .map_err(|e| format!("task_join_failed: {e}"))?;

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_scheme_rejected() {
        assert!(validate_scheme("file:///etc/passwd").is_err());
        assert!(validate_scheme("ftp://example.com").is_err());
        assert!(validate_scheme("http://localhost:11434/v1").is_ok());
        assert!(validate_scheme("https://api.example.com/v1").is_ok());
    }

    #[test]
    fn models_url_strips_trailing_slash() {
        assert_eq!(
            models_url("http://localhost:11434/v1/"),
            "http://localhost:11434/v1/models"
        );
        assert_eq!(
            models_url("http://localhost:11434/v1"),
            "http://localhost:11434/v1/models"
        );
    }
}
