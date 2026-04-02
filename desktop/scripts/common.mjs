import { spawn } from "node:child_process";
import { access, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));

export const desktopDir = path.resolve(scriptsDir, "..");
export const tauriDir = path.join(desktopDir, "src-tauri");
export const productName = "Prompt Provision Tool Desktop";
export const binaryName =
  process.platform === "win32"
    ? "prompt-provision-tool-desktop.exe"
    : "prompt-provision-tool-desktop";

export function npmCommand() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

export async function pathExists(targetPath) {
  try {
    await access(targetPath);
    return true;
  } catch {
    return false;
  }
}

export async function runCommand(command, args, options = {}) {
  const env = { ...process.env, ...(options.env || {}) };

  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd || desktopDir,
      env,
      shell: false,
      stdio: options.captureOutput ? ["ignore", "pipe", "pipe"] : "inherit",
    });

    let stdout = "";
    let stderr = "";

    if (options.captureOutput) {
      child.stdout.on("data", (chunk) => {
        stdout += chunk.toString();
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk.toString();
      });
    }

    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ code, stdout, stderr });
        return;
      }

      const error = new Error(
        `${command} ${args.join(" ")} exited with code ${code}`,
      );
      error.code = code;
      error.stdout = stdout;
      error.stderr = stderr;
      reject(error);
    });
  });
}

export async function detectPythonCommand() {
  const configured = process.env.PPT_PYTHON?.trim();
  const candidates = configured
    ? [configured]
    : process.platform === "win32"
      ? ["py", "python", "python3"]
      : ["python3", "python"];

  for (const candidate of candidates) {
    try {
      const versionArgs = candidate === "py" ? ["-3", "--version"] : ["--version"];
      await runCommand(candidate, versionArgs, { captureOutput: true });
      return candidate;
    } catch {
      // Try the next candidate.
    }
  }

  throw new Error(
    "Python executable not found. Set PPT_PYTHON, or install python3/python.",
  );
}

export function pythonScriptArgs(pythonCommandName, scriptPath, extraArgs = []) {
  if (pythonCommandName === "py") {
    return ["-3", scriptPath, ...extraArgs];
  }
  return [scriptPath, ...extraArgs];
}

export function targetDir() {
  return path.resolve(
    process.env.PPT_TAURI_TARGET_DIR ||
      process.env.CARGO_TARGET_DIR ||
      path.join(tauriDir, "target"),
  );
}

async function walkFiles(rootDir, predicate, matches = []) {
  if (!(await pathExists(rootDir))) {
    return matches;
  }

  const entries = await readdir(rootDir, { withFileTypes: true });
  for (const entry of entries) {
    const entryPath = path.join(rootDir, entry.name);
    if (entry.isDirectory()) {
      await walkFiles(entryPath, predicate, matches);
    } else if (predicate(entryPath)) {
      matches.push(entryPath);
    }
  }
  return matches;
}

export async function resolvePackagedExecutablePath() {
  const explicitPath = process.env.PPT_VERIFY_EXECUTABLE_PATH?.trim();
  if (explicitPath) {
    const resolved = path.resolve(explicitPath);
    if (await pathExists(resolved)) {
      return resolved;
    }
    throw new Error(`PPT_VERIFY_EXECUTABLE_PATH does not exist: ${resolved}`);
  }

  const releaseDir = path.join(targetDir(), "release");
  const candidates =
    process.platform === "darwin"
      ? [
          path.join(
            releaseDir,
            "bundle",
            "macos",
            `${productName}.app`,
            "Contents",
            "MacOS",
            "prompt-provision-tool-desktop",
          ),
          path.join(releaseDir, "prompt-provision-tool-desktop"),
        ]
      : process.platform === "win32"
        ? [path.join(releaseDir, "prompt-provision-tool-desktop.exe")]
        : [path.join(releaseDir, "prompt-provision-tool-desktop")];

  for (const candidate of candidates) {
    if (await pathExists(candidate)) {
      return candidate;
    }
  }

  const fallbackMatches = await walkFiles(releaseDir, (entryPath) => {
    const base = path.basename(entryPath);
    if (process.platform === "darwin") {
      return (
        base === "prompt-provision-tool-desktop" &&
        entryPath.includes(path.join(".app", "Contents", "MacOS"))
      );
    }
    return base === binaryName;
  });
  if (fallbackMatches.length > 0) {
    return fallbackMatches[0];
  }

  throw new Error(
    `Unable to find packaged executable under ${releaseDir}. Set PPT_VERIFY_EXECUTABLE_PATH if needed.`,
  );
}

export function normalizedPath(value) {
  return value.replaceAll("\\", "/");
}
