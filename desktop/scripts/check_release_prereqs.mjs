import path from "node:path";
import process from "node:process";

import { desktopDir, pathExists } from "./common.mjs";

function requireEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required for release builds`);
  }
  return value;
}

function optionalEnv(name) {
  return process.env[name]?.trim() || "";
}

function requireOneOf(names) {
  for (const name of names) {
    const value = optionalEnv(name);
    if (value) {
      return { name, value };
    }
  }
  throw new Error(`One of ${names.join(", ")} is required for release builds`);
}

function parseJsonArray(name, rawValue) {
  let parsed;
  try {
    parsed = JSON.parse(rawValue);
  } catch (error) {
    throw new Error(`${name} must be valid JSON: ${error.message}`);
  }

  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error(`${name} must be a non-empty JSON array`);
  }

  for (const value of parsed) {
    if (typeof value !== "string" || !value.trim()) {
      throw new Error(`${name} must contain only non-empty strings`);
    }
    try {
      new URL(value);
    } catch (error) {
      throw new Error(`${name} contains an invalid URL \`${value}\`: ${error.message}`);
    }
  }

  return parsed;
}

const configPath = path.resolve(
  desktopDir,
  process.env.PPT_TAURI_CONFIG_PATH?.trim() || "src-tauri/tauri.release.conf.json",
);

if (!(await pathExists(configPath))) {
  throw new Error(`Release config does not exist: ${configPath}`);
}

const updaterPublicKey = requireEnv("PPT_UPDATER_PUBLIC_KEY");
const updaterEndpoints = parseJsonArray(
  "PPT_UPDATER_ENDPOINTS_JSON",
  requireEnv("PPT_UPDATER_ENDPOINTS_JSON"),
);
const signingPrivateKey = requireEnv("TAURI_SIGNING_PRIVATE_KEY");
const signingPassword = optionalEnv("TAURI_SIGNING_PRIVATE_KEY_PASSWORD");

const requiredByPlatform = [];

if (process.platform === "darwin") {
  for (const name of [
    "APPLE_CERTIFICATE",
    "APPLE_CERTIFICATE_PASSWORD",
    "KEYCHAIN_PASSWORD",
    "APPLE_API_PRIVATE_KEY",
    "APPLE_API_ISSUER",
  ]) {
    requireEnv(name);
    requiredByPlatform.push(name);
  }
  const selected = requireOneOf(["APPLE_API_KEY", "APPLE_API_KEY_ID"]);
  requiredByPlatform.push(selected.name);
} else if (process.platform === "win32") {
  for (const name of ["WINDOWS_CERTIFICATE", "WINDOWS_CERTIFICATE_PASSWORD"]) {
    requireEnv(name);
    requiredByPlatform.push(name);
  }
}

console.log(
  JSON.stringify(
    {
      ok: true,
      platform: process.platform,
      configPath,
      updaterEndpointCount: updaterEndpoints.length,
      signingPrivateKeyPresent: Boolean(signingPrivateKey),
      signingPrivateKeyPasswordPresent: Boolean(signingPassword),
      updaterPublicKeyPresent: Boolean(updaterPublicKey),
      requiredByPlatform,
    },
    null,
    2,
  ),
);
