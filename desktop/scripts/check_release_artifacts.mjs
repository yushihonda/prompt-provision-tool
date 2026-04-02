import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { pathExists } from "./common.mjs";

function requireEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

async function walkForMetadata(rootDir, matches = []) {
  const entries = await readdir(rootDir, { withFileTypes: true });
  for (const entry of entries) {
    const entryPath = path.join(rootDir, entry.name);
    if (entry.isDirectory()) {
      await walkForMetadata(entryPath, matches);
      continue;
    }
    if (entry.name === "metadata.json") {
      matches.push(entryPath);
    }
  }
  return matches;
}

function parseExpectedTargetKeys() {
  const raw = process.env.PPT_RELEASE_EXPECTED_TARGET_KEYS_JSON?.trim();
  if (!raw) {
    return null;
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(`PPT_RELEASE_EXPECTED_TARGET_KEYS_JSON must be valid JSON: ${error.message}`);
  }

  if (!Array.isArray(parsed) || parsed.some((value) => typeof value !== "string" || !value.trim())) {
    throw new Error("PPT_RELEASE_EXPECTED_TARGET_KEYS_JSON must be a JSON array of non-empty strings");
  }

  return parsed.map((value) => value.trim()).sort();
}

const assetDir = path.resolve(requireEnv("PPT_RELEASE_ASSET_DIR"));
if (!(await pathExists(assetDir))) {
  throw new Error(`PPT_RELEASE_ASSET_DIR does not exist: ${assetDir}`);
}

const expectedCountRaw = process.env.PPT_RELEASE_EXPECTED_COUNT?.trim();
const expectedCount = expectedCountRaw ? Number.parseInt(expectedCountRaw, 10) : null;
if (expectedCountRaw && Number.isNaN(expectedCount)) {
  throw new Error(`PPT_RELEASE_EXPECTED_COUNT must be an integer, got ${expectedCountRaw}`);
}

const expectedTargetKeys = parseExpectedTargetKeys();
const metadataFiles = await walkForMetadata(assetDir);
if (metadataFiles.length === 0) {
  throw new Error(`No metadata.json files found under ${assetDir}`);
}
if (expectedCount !== null && metadataFiles.length !== expectedCount) {
  throw new Error(
    `Expected ${expectedCount} metadata.json files under ${assetDir}, found ${metadataFiles.length}`,
  );
}

const seenTargetKeys = new Set();
const summaries = [];

for (const metadataFile of metadataFiles) {
  const metadataDir = path.dirname(metadataFile);
  const metadata = JSON.parse(await readFile(metadataFile, "utf8"));
  const { targetKey, assetName, signatureName, bundleKind } = metadata;

  if (!targetKey || !assetName || !signatureName || !bundleKind) {
    throw new Error(`metadata.json is missing required fields: ${metadataFile}`);
  }
  if (seenTargetKeys.has(targetKey)) {
    throw new Error(`Duplicate targetKey in release artifacts: ${targetKey}`);
  }
  seenTargetKeys.add(targetKey);

  const assetPath = path.join(metadataDir, assetName);
  const signaturePath = path.join(metadataDir, signatureName);
  if (!(await pathExists(assetPath))) {
    throw new Error(`Release asset is missing: ${assetPath}`);
  }
  if (!(await pathExists(signaturePath))) {
    throw new Error(`Release signature is missing: ${signaturePath}`);
  }

  const signature = (await readFile(signaturePath, "utf8")).trim();
  if (!signature) {
    throw new Error(`Release signature is empty: ${signaturePath}`);
  }

  summaries.push({
    targetKey,
    bundleKind,
    assetName,
    signatureName,
  });
}

if (expectedTargetKeys) {
  const actual = [...seenTargetKeys].sort();
  if (
    actual.length !== expectedTargetKeys.length ||
    actual.some((value, index) => value !== expectedTargetKeys[index])
  ) {
    throw new Error(
      `Release target keys mismatch. Expected ${expectedTargetKeys.join(", ")}, got ${actual.join(", ")}`,
    );
  }
}

console.log(
  JSON.stringify(
    {
      ok: true,
      assetDir,
      metadataCount: metadataFiles.length,
      targetKeys: [...seenTargetKeys].sort(),
      artifacts: summaries.sort((left, right) => left.targetKey.localeCompare(right.targetKey)),
    },
    null,
    2,
  ),
);
