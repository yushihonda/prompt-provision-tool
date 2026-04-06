import path from "node:path";
import process from "node:process";

import {
  normalizedPath,
  resolvePackagedExecutablePath,
  runCommand,
} from "./common.mjs";

const HEALTH_MODE = "health";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function isNonEmpty(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function expectedRuntimeTruth(contract) {
  return contract.expectedRuntimeTruth;
}

function expectedArtifacts(contract) {
  return contract.expectedPackagedArtifacts;
}

function contractForMode(contract, mode) {
  const modeContract = contract.supportedModes.find((entry) => entry.name === mode);
  assert(modeContract, `unsupported verification mode in Rust contract: ${mode}`);
  return modeContract;
}

function assertDetailFields(source, label, contract) {
  const expected = expectedRuntimeTruth(contract);
  assert(source, `${label} is missing`);
  assert(
    source.providerMode === expected.providerMode,
    `${label}.providerMode must be ${expected.providerMode}, got ${source.providerMode}`,
  );
  assert(
    source.providerTransport === expected.providerTransport,
    `${label}.providerTransport must be ${expected.providerTransport}, got ${source.providerTransport}`,
  );
  assert(
    source.providerRuntime === expected.providerRuntime,
    `${label}.providerRuntime must be ${expected.providerRuntime}, got ${source.providerRuntime}`,
  );
  assert(
    source.providerImpl === expected.providerImpl,
    `${label}.providerImpl must be ${expected.providerImpl}, got ${source.providerImpl}`,
  );
  assert(
    isNonEmpty(source.providerAdapter),
    `${label}.providerAdapter must be a non-empty string`,
  );
}

function assertResolvedBinaryPath(filePath, expectedBaseName, label) {
  assert(isNonEmpty(filePath), `${label} is missing`);
  assert(
    path.basename(filePath) === expectedBaseName,
    `${label} must end with ${expectedBaseName}, got ${filePath}`,
  );
}

function assertBundledSidecarPath(filePath, label, contract) {
  assertResolvedBinaryPath(
    filePath,
    expectedArtifacts(contract).sidecarBinaryName,
    label,
  );
  assert(
    !normalizedPath(filePath).includes("/sidecar/main.py"),
    `${label} must not fall back to repo sidecar/main.py: ${filePath}`,
  );
}

function parseJsonPayload(value) {
  if (!value) {
    return {};
  }
  if (typeof value === "string") {
    return JSON.parse(value);
  }
  return value;
}

function assertEventPayloadsWithContract(runEvents, contract) {
  assert(Array.isArray(runEvents), "runEvents must be an array");
  assert(runEvents.length > 0, "runEvents must not be empty for real run verification");
  const expected = expectedRuntimeTruth(contract);
  for (const event of runEvents) {
    const payload = parseJsonPayload(event.payloadJson);
    if ("provider_mode" in payload) {
      assert(
        payload.provider_mode === expected.providerMode,
        `event ${event.eventType} provider_mode mismatch: ${payload.provider_mode}`,
      );
    }
    if ("provider_transport" in payload) {
      assert(
        payload.provider_transport === expected.providerTransport,
        `event ${event.eventType} provider_transport mismatch: ${payload.provider_transport}`,
      );
    }
    if ("provider_runtime" in payload) {
      assert(
        payload.provider_runtime === expected.providerRuntime,
        `event ${event.eventType} provider_runtime mismatch: ${payload.provider_runtime}`,
      );
    }
    if ("provider_impl" in payload) {
      assert(
        payload.provider_impl === expected.providerImpl,
        `event ${event.eventType} provider_impl mismatch: ${payload.provider_impl}`,
      );
    }
  }
}

function assertCommonReportFields(report, mode) {
  assert(report.contract, "report.contract is missing");
  assert(report.mode === mode, `report.mode must be ${mode}, got ${report.mode}`);
  assertDetailFields(report.runtimeConfig, "runtimeConfig", report.contract);
  assertDetailFields(report.sidecarHealth, "sidecarHealth", report.contract);
  assertResolvedBinaryPath(
    report.resolvedCliProviderBinaryPath,
    expectedArtifacts(report.contract).cliProviderBinaryName,
    "resolvedCliProviderBinaryPath",
  );
  assertBundledSidecarPath(report.resolvedSidecarPath, "resolvedSidecarPath", report.contract);
  assertBundledSidecarPath(
    report.runtimeConfig.sidecarScriptPath,
    "runtimeConfig.sidecarScriptPath",
    report.contract,
  );
  assert(
    path.basename(report.currentExePath) === expectedArtifacts(report.contract).desktopExecutableName,
    `currentExePath must end with ${expectedArtifacts(report.contract).desktopExecutableName}, got ${report.currentExePath}`,
  );
}

function assertSkillReport(report) {
  assert(report.skillResult, "skillResult must be present");
  assert(report.skillResult.status === "success", "skillResult.status must be success");
  assertDetailFields(report.skillResult, "skillResult", report.contract);
  assert(report.skillResult.eventCount > 0, "skillResult.eventCount must be > 0");
  assertEventPayloadsWithContract(report.runEvents, report.contract);
}

function assertWorkflowReport(report) {
  assert(report.workflowResult, "workflowResult must be present");
  assert(
    report.workflowResult.status === "success",
    "workflowResult.status must be success",
  );
  assertDetailFields(report.workflowResult, "workflowResult", report.contract);
  assert(report.workflowResult.eventCount > 0, "workflowResult.eventCount must be > 0");
  assertEventPayloadsWithContract(report.runEvents, report.contract);
}

function assertSecureStorageReport(report, options = {}) {
  assert(report.secureStorageResult, "secureStorageResult must be present");
  assert(report.secureStorageResult.dbExists, "secureStorageResult.dbExists must be true");
  assert(
    report.secureStorageResult.authSessionWriteOk,
    "secureStorageResult.authSessionWriteOk must be true",
  );
  assert(
    report.secureStorageResult.clearedAfterVerification,
    "secureStorageResult.clearedAfterVerification must be true",
  );
  assert(
    !report.secureStorageResult.tokenFoundInDb,
    "secureStorageResult.tokenFoundInDb must be false",
  );
  assert(
    !report.secureStorageResult.usernameFoundInDb,
    "secureStorageResult.usernameFoundInDb must be false",
  );
  if (options.requireRoundTrip) {
    assert(
      report.secureStorageResult.authSessionRoundTripOk,
      "secureStorageResult.authSessionRoundTripOk must be true",
    );
  }
}

async function launchVerification(executablePath, mode) {
  const { stdout } = await runCommand(executablePath, [], {
    captureOutput: true,
    env: {
      NEXMAGI_VERIFY_MODE: mode,
      NEXMAGI_VERIFY_ENGINE_MODE: process.env.NEXMAGI_VERIFY_ENGINE_MODE || "cli",
    },
  });
  return JSON.parse(stdout.trim());
}

const args = process.argv.slice(2);
const modeArg = args.find((value) => !value.startsWith("--"));
const mode = modeArg || HEALTH_MODE;
const optional = args.includes("--optional");
const requireStorageRoundTrip = args.includes("--require-storage-round-trip");

// Do not reconstruct runtime truth here.
// This helper may resolve paths and assert returned JSON only.
const executablePath = await resolvePackagedExecutablePath();
const contractReport = await launchVerification(executablePath, HEALTH_MODE);
assertCommonReportFields(contractReport, HEALTH_MODE);

const modeContract = contractForMode(contractReport.contract, mode);
const missingEnv = modeContract.requiredEnv.filter(
  (name) => !isNonEmpty(process.env[name]),
);
if (missingEnv.length > 0) {
  if (optional) {
    console.log(
      JSON.stringify(
        {
          skipped: true,
          optional: true,
          mode,
          reason: "missing verification fixture env",
          missingEnv,
          truthOwner: contractReport.contract.truthOwner,
          helperPolicy: contractReport.contract.helperPolicy,
        },
        null,
        2,
      ),
    );
    process.exit(0);
  }

  throw new Error(
    `missing required environment variables for ${mode} verification: ${missingEnv.join(", ")}`,
  );
}

const report = mode === HEALTH_MODE ? contractReport : await launchVerification(executablePath, mode);
assertCommonReportFields(report, mode);

if (mode === "skill") {
  assertSkillReport(report);
} else if (mode === "storage") {
  assertSecureStorageReport(report, { requireRoundTrip: requireStorageRoundTrip });
} else if (mode === "workflow") {
  assertWorkflowReport(report);
}

console.log(
  JSON.stringify(
    {
      ok: true,
      mode,
      executablePath,
      truthOwner: report.contract.truthOwner,
      helperPolicy: report.contract.helperPolicy,
      resolvedCliProviderBinaryPath: report.resolvedCliProviderBinaryPath,
      resolvedSidecarPath: report.resolvedSidecarPath,
      providerAdapter: report.runtimeConfig.providerAdapter,
      secureStorageProof: report.secureStorageResult
        ? {
            dbPath: report.secureStorageResult.dbPath,
            authSessionWriteOk: report.secureStorageResult.authSessionWriteOk,
            authSessionRoundTripOk: report.secureStorageResult.authSessionRoundTripOk,
            clearedAfterVerification: report.secureStorageResult.clearedAfterVerification,
            tokenFoundInDb: report.secureStorageResult.tokenFoundInDb,
            usernameFoundInDb: report.secureStorageResult.usernameFoundInDb,
          }
        : null,
      eventCount:
        report.skillResult?.eventCount ??
        report.workflowResult?.eventCount ??
        0,
    },
    null,
    2,
  ),
);
