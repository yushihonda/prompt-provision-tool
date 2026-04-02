use std::env;
use std::path::Path;

fn main() {
    println!("cargo:rerun-if-changed=../scripts/build_cli_provider_binary.py");
    println!("cargo:rerun-if-changed=../scripts/provider_adapter_entry.py");
    println!("cargo:rerun-if-changed=../scripts/build_sidecar_binary.py");
    println!("cargo:rerun-if-changed=../scripts/sidecar_entry.py");
    println!("cargo:rerun-if-changed=../../local_worker/provider_adapter.py");
    println!("cargo:rerun-if-changed=../../sidecar");
    println!("cargo:rerun-if-env-changed=PPT_CLI_PROVIDER_COMMAND");
    println!("cargo:rerun-if-env-changed=PPT_CLI_PROVIDER_BINARY_PATH");
    println!("cargo:rerun-if-env-changed=PPT_CLI_PROVIDER_RUNTIME");
    println!("cargo:rerun-if-env-changed=PPT_CLI_PROVIDER_IMPL");
    println!("cargo:rerun-if-env-changed=PPT_CLI_PROVIDER_ADAPTER");
    println!("cargo:rerun-if-env-changed=PPT_CLI_PROVIDER_TRANSPORT");
    println!("cargo:rerun-if-env-changed=PPT_REQUIRE_CLI_PROVIDER_BINARY");
    println!("cargo:rerun-if-env-changed=PPT_SIDECAR_BINARY_PATH");
    println!("cargo:rerun-if-env-changed=PPT_REQUIRE_SIDECAR_BINARY");

    let require_binary = env::var("PPT_REQUIRE_CLI_PROVIDER_BINARY")
        .ok()
        .map(|value| value == "1" || value.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    if require_binary {
        let unix_artifact = Path::new("resources/bin/ppt-provider-adapter");
        let windows_artifact = Path::new("resources/bin/ppt-provider-adapter.exe");
        if !unix_artifact.exists() && !windows_artifact.exists() {
            panic!(
                "required packaged CLI binary is missing. Run `npm run cli-provider:build` before building."
            );
        }
    }

    let require_sidecar_binary = env::var("PPT_REQUIRE_SIDECAR_BINARY")
        .ok()
        .map(|value| value == "1" || value.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    if require_sidecar_binary {
        let unix_artifact = Path::new("resources/bin/ppt-sidecar");
        let windows_artifact = Path::new("resources/bin/ppt-sidecar.exe");
        if !unix_artifact.exists() && !windows_artifact.exists() {
            panic!(
                "required packaged sidecar binary is missing. Run `npm run sidecar:build` before building."
            );
        }
    }

    tauri_build::build()
}
