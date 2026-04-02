import process from "node:process";

process.env.PPT_TAURI_CONFIG_PATH = "src-tauri/tauri.release.conf.json";

await import("./check_release_prereqs.mjs");
await import("./build_tauri_bundle.mjs");
