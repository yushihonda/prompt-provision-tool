import { cp, mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { pathExists, targetDir } from "./common.mjs";

function requireEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

async function listFiles(dirPath) {
  if (!(await pathExists(dirPath))) {
    return [];
  }
  return await readdir(dirPath);
}

function singleMatch(entries, predicate, label) {
  const matches = entries.filter(predicate);
  if (matches.length === 0) {
    return null;
  }
  if (matches.length > 1) {
    throw new Error(`Expected exactly one ${label}, found ${matches.length}: ${matches.join(", ")}`);
  }
  return matches[0];
}

async function resolveReleasePair() {
  const bundleDir = path.join(targetDir(), "release", "bundle");

  if (process.platform === "darwin") {
    const macosDir = path.join(bundleDir, "macos");
    const entries = await listFiles(macosDir);
    const assetName = singleMatch(entries, (entry) => entry.endsWith(".app.tar.gz"), "macOS updater archive");
    if (!assetName) {
      throw new Error(`No macOS updater archive found under ${macosDir}`);
    }
    const signatureName = `${assetName}.sig`;
    return {
      assetPath: path.join(macosDir, assetName),
      assetName,
      signaturePath: path.join(macosDir, signatureName),
      signatureName,
      bundleKind: "macos-app-tar",
    };
  }

  if (process.platform === "win32") {
    const nsisDir = path.join(bundleDir, "nsis");
    const msiDir = path.join(bundleDir, "msi");
    const nsisEntries = await listFiles(nsisDir);
    const exeName = singleMatch(nsisEntries, (entry) => entry.endsWith(".exe"), "Windows NSIS installer");
    if (exeName) {
      return {
        assetPath: path.join(nsisDir, exeName),
        assetName: exeName,
        signaturePath: path.join(nsisDir, `${exeName}.sig`),
        signatureName: `${exeName}.sig`,
        bundleKind: "windows-nsis",
      };
    }

    const msiEntries = await listFiles(msiDir);
    const msiName = singleMatch(msiEntries, (entry) => entry.endsWith(".msi"), "Windows MSI installer");
    if (!msiName) {
      throw new Error(`No Windows updater installer found under ${nsisDir} or ${msiDir}`);
    }
    return {
      assetPath: path.join(msiDir, msiName),
      assetName: msiName,
      signaturePath: path.join(msiDir, `${msiName}.sig`),
      signatureName: `${msiName}.sig`,
      bundleKind: "windows-msi",
    };
  }

  throw new Error(`Unsupported platform for release artifact preparation: ${process.platform}`);
}

const outputDir = path.resolve(
  process.env.NEXMAGI_RELEASE_ASSET_DIR || path.join(targetDir(), "release", "updater-artifacts"),
);
const targetKey = requireEnv("NEXMAGI_RELEASE_TARGET_KEY");
const pair = await resolveReleasePair();

if (process.platform === "darwin" && !targetKey.startsWith("darwin-")) {
  throw new Error(`NEXMAGI_RELEASE_TARGET_KEY must start with darwin- on macOS, got ${targetKey}`);
}
if (process.platform === "win32" && !targetKey.startsWith("windows-")) {
  throw new Error(`NEXMAGI_RELEASE_TARGET_KEY must start with windows- on Windows, got ${targetKey}`);
}

if (!(await pathExists(pair.signaturePath))) {
  throw new Error(`Missing updater signature: ${pair.signaturePath}`);
}

await mkdir(outputDir, { recursive: true });
await cp(pair.assetPath, path.join(outputDir, pair.assetName));
await cp(pair.signaturePath, path.join(outputDir, pair.signatureName));
await writeFile(
  path.join(outputDir, "metadata.json"),
  JSON.stringify(
    {
      targetKey,
      assetName: pair.assetName,
      signatureName: pair.signatureName,
      bundleKind: pair.bundleKind,
    },
    null,
    2,
  ),
);

console.log(
  JSON.stringify(
    {
      ok: true,
      outputDir,
      targetKey,
      assetName: pair.assetName,
      signatureName: pair.signatureName,
      bundleKind: pair.bundleKind,
    },
    null,
    2,
  ),
);
