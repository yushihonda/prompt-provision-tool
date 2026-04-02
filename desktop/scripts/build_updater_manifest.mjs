import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";

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

const assetDir = path.resolve(process.env.PPT_RELEASE_ASSET_DIR || process.cwd());
const releaseTag = requireEnv("PPT_RELEASE_TAG").replace(/^refs\/tags\//, "");
const releaseVersion = requireEnv("PPT_RELEASE_VERSION").replace(/^v/, "");
const releaseRepository = requireEnv("PPT_RELEASE_REPOSITORY");
const manifestPath = path.resolve(
  process.env.PPT_RELEASE_MANIFEST_PATH || path.join(assetDir, "latest.json"),
);
const releaseNotes = process.env.PPT_RELEASE_NOTES?.trim() || "";

if (!(await pathExists(assetDir))) {
  throw new Error(`PPT_RELEASE_ASSET_DIR does not exist: ${assetDir}`);
}

const metadataFiles = await walkForMetadata(assetDir);
if (metadataFiles.length === 0) {
  throw new Error(`No metadata.json files found under ${assetDir}`);
}

const platforms = {};
for (const metadataFile of metadataFiles) {
  const metadataDir = path.dirname(metadataFile);
  const metadata = JSON.parse(await readFile(metadataFile, "utf8"));
  if (!metadata.targetKey || !metadata.assetName || !metadata.signatureName) {
    throw new Error(`metadata.json is missing required fields: ${metadataFile}`);
  }
  if (platforms[metadata.targetKey]) {
    throw new Error(`Duplicate targetKey in updater metadata: ${metadata.targetKey}`);
  }
  const signaturePath = path.join(metadataDir, metadata.signatureName);
  const signature = (await readFile(signaturePath, "utf8")).trim();
  if (!signature) {
    throw new Error(`Empty signature file: ${signaturePath}`);
  }
  platforms[metadata.targetKey] = {
    signature,
    url: `https://github.com/${releaseRepository}/releases/download/${releaseTag}/${metadata.assetName}`,
  };
}

const manifest = {
  version: releaseVersion,
  notes: releaseNotes || undefined,
  pub_date: new Date().toISOString(),
  platforms,
};

await writeFile(manifestPath, JSON.stringify(manifest, null, 2));

console.log(
  JSON.stringify(
    {
      ok: true,
      manifestPath,
      platformKeys: Object.keys(platforms),
      releaseTag,
      releaseVersion,
    },
    null,
    2,
  ),
);
