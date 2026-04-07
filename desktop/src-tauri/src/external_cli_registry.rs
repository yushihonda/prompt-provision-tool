//! Registry of `ExternalCliAdapter` instances, keyed by adapter id.
//!
//! Tauri owns one `ExternalCliRegistry` as managed state. The generic
//! runner looks up the adapter by id and dispatches.

use parking_lot::RwLock;
use std::collections::HashMap;
use std::sync::Arc;

use crate::external_cli_traits::ExternalCliAdapter;

#[derive(Default)]
pub struct ExternalCliRegistry {
    inner: RwLock<HashMap<String, Arc<dyn ExternalCliAdapter>>>,
}

impl ExternalCliRegistry {
    pub fn register(&self, adapter: Arc<dyn ExternalCliAdapter>) {
        let id = adapter.adapter_config().adapter_id.clone();
        self.inner.write().insert(id, adapter);
    }

    pub fn get(&self, adapter_id: &str) -> Option<Arc<dyn ExternalCliAdapter>> {
        self.inner.read().get(adapter_id).cloned()
    }

    pub fn list(&self) -> Vec<Arc<dyn ExternalCliAdapter>> {
        self.inner.read().values().cloned().collect()
    }

    /// Build a registry pre-populated with the four built-in adapters.
    /// Concrete adapters live in `external_cli_adapters/`.
    pub fn with_defaults() -> Self {
        let r = Self::default();
        r.register(Arc::new(
            crate::external_cli_adapters::claude_code::ClaudeCodeAdapter::new(),
        ));
        r.register(Arc::new(
            crate::external_cli_adapters::codex::CodexAdapter::new(),
        ));
        r.register(Arc::new(
            crate::external_cli_adapters::generic::GenericAdapter::new(),
        ));
        r
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::external_cli_traits::*;
    use std::collections::HashMap;

    struct Stub {
        cfg: ExternalCliAdapterConfig,
    }
    impl ExternalCliAdapter for Stub {
        fn adapter_config(&self) -> &ExternalCliAdapterConfig {
            &self.cfg
        }
        fn validate_environment(&self) -> Result<(), String> {
            Ok(())
        }
        fn build_command(
            &self,
            _req: &ExternalCliExecutionRequest,
        ) -> Result<(String, Vec<String>), String> {
            Ok(("/bin/true".into(), vec![]))
        }
        fn classify_failure(
            &self,
            exit_code: Option<i32>,
            _stdout: &str,
            _stderr: &str,
            _kind: Option<std::io::ErrorKind>,
        ) -> ExternalCliExecutionStatus {
            if exit_code == Some(0) {
                ExternalCliExecutionStatus::Succeeded
            } else {
                ExternalCliExecutionStatus::Failed
            }
        }
    }

    fn stub(id: &str) -> Arc<dyn ExternalCliAdapter> {
        Arc::new(Stub {
            cfg: ExternalCliAdapterConfig {
                adapter_id: id.into(),
                adapter_name: id.into(),
                runtime: ExternalCliRuntimeKind::Generic,
                command: "/bin/true".into(),
                default_args: vec![],
                timeout_ms: Some(1000),
                requires_local_auth: false,
                capabilities: vec![],
                env_keys_passthrough: vec![],
                metadata: HashMap::new(),
            },
        })
    }

    #[test]
    fn register_and_get() {
        let r = ExternalCliRegistry::default();
        r.register(stub("a"));
        r.register(stub("b"));
        assert!(r.get("a").is_some());
        assert!(r.get("b").is_some());
        assert!(r.get("missing").is_none());
        assert_eq!(r.list().len(), 2);
    }
}
