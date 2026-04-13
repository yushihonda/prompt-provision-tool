import path from "node:path";
import process from "node:process";

import {
  desktopDir,
  detectPythonCommand,
  pythonScriptArgs,
  runCommand,
} from "./common.mjs";

const [, , scriptRelativePath, ...extraArgs] = process.argv;

if (!scriptRelativePath) {
  console.error("usage: node scripts/run_python_script.mjs <script> [args...]");
  process.exit(1);
}

const scriptPath = path.resolve(desktopDir, scriptRelativePath);
const pythonCommandName = await detectPythonCommand();
await runCommand(
  pythonCommandName,
  pythonScriptArgs(pythonCommandName, scriptPath, extraArgs),
  { cwd: desktopDir },
);
