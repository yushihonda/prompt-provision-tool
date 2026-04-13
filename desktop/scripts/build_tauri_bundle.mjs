import { desktopDir, npmCommand, runCommand } from "./common.mjs";

const npm = npmCommand();
const configPath = process.env.NEXMAGI_TAURI_CONFIG_PATH?.trim();
const tauriBuildArgs = ["exec", "--", "tauri", "build"];

if (configPath) {
  tauriBuildArgs.push("--config", configPath);
}

await runCommand(npm, ["run", "cli-provider:build"], { cwd: desktopDir });
await runCommand(npm, ["run", "sidecar:build"], { cwd: desktopDir });
await runCommand(npm, tauriBuildArgs, {
  cwd: desktopDir,
  env: {
    CI: "true",
    NEXMAGI_REQUIRE_CLI_PROVIDER_BINARY: "1",
    NEXMAGI_REQUIRE_SIDECAR_BINARY: "1",
  },
});
