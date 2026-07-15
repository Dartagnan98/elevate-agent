#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { lstatSync } from "node:fs";
import { isAbsolute } from "node:path";

function fail(message) {
  process.stderr.write(`ERROR: ${message}\n`);
  process.exit(1);
}

const [urlEnvironmentName, planFile] = process.argv.slice(2);
if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(urlEnvironmentName ?? "")) {
  fail("invalid database URL environment variable name");
}
if (!planFile) {
  fail("missing migration plan path");
}

const rawUrl = process.env[urlEnvironmentName];
if (!rawUrl) {
  fail("database URL environment variable is empty");
}

let parsed;
try {
  parsed = new URL(rawUrl);
} catch {
  fail("database URL is invalid");
}
if (!['postgresql:', 'postgres:'].includes(parsed.protocol)) {
  fail("database URL protocol is invalid");
}

let username;
let password;
let database;
try {
  username = decodeURIComponent(parsed.username);
  password = decodeURIComponent(parsed.password);
  database = decodeURIComponent(parsed.pathname.replace(/^\//, ""));
} catch {
  fail("database URL contains invalid percent encoding");
}
for (const value of [username, password, database]) {
  if (value.includes("\0") || value.includes("\n") || value.includes("\r")) {
    fail("database URL contains a forbidden control character");
  }
}
if (!parsed.hostname || !username || !database || database.includes("/")) {
  fail("database URL connection fields are incomplete");
}

const queryKeys = [...parsed.searchParams.keys()];
if (queryKeys.length !== 1 || queryKeys[0] !== "sslmode") {
  fail("database URL query parameters are not approved");
}
const sslmodes = parsed.searchParams.getAll("sslmode");
if (sslmodes.length !== 1) {
  fail("database URL must set sslmode exactly once");
}

const childEnvironment = { ...process.env };
const sslRootCert = process.env.ELEVATE_HQ_DB_SSLROOTCERT;
delete childEnvironment[urlEnvironmentName];
delete childEnvironment.ELEVATE_HQ_DB_SSLROOTCERT;
for (const inheritedOverride of [
  "PGHOST",
  "PGHOSTADDR",
  "PGPORT",
  "PGDATABASE",
  "PGUSER",
  "PGPASSWORD",
  "PGPASSFILE",
  "PGSERVICE",
  "PGSERVICEFILE",
  "PGOPTIONS",
  "PGSSLMODE",
  "PGSSLROOTCERT",
  "PGSSLCERT",
  "PGSSLKEY",
  "PGSSLCRL",
  "PGSSLCRLDIR",
  "PGSSLNEGOTIATION",
  "PGREQUIRESSL",
  "PGAPPNAME",
  "PGCONNECT_TIMEOUT",
  "PGTARGETSESSIONATTRS",
]) {
  delete childEnvironment[inheritedOverride];
}
Object.assign(childEnvironment, {
  PGHOST: parsed.hostname,
  PGPORT: parsed.port || "5432",
  PGDATABASE: database,
  PGUSER: username,
  PGPASSWORD: password,
  PGSSLMODE: sslmodes[0],
  PGAPPNAME: "elevate-hq-migration-0011-0020",
  PGCONNECT_TIMEOUT: "10",
});
if (sslmodes[0] === "verify-full") {
  if (
    !sslRootCert ||
    !isAbsolute(sslRootCert) ||
    sslRootCert.includes("\0") ||
    sslRootCert.includes("\n") ||
    sslRootCert.includes("\r")
  ) {
    fail("production TLS root certificate path is invalid");
  }
  let certificate;
  try {
    certificate = lstatSync(sslRootCert);
  } catch {
    fail("production TLS root certificate is unavailable");
  }
  if (
    !certificate.isFile() ||
    certificate.isSymbolicLink() ||
    certificate.size < 1 ||
    certificate.size > 1024 * 1024
  ) {
    fail("production TLS root certificate must be a regular CA file");
  }
  // This separately named, validated path is the only caller-controlled TLS
  // input. All ambient libpq overrides are removed before psql starts.
  childEnvironment.PGSSLROOTCERT = sslRootCert;
}

const result = spawnSync(
  "psql",
  [
    "-X",
    "--no-psqlrc",
    "--no-password",
    "--set=ON_ERROR_STOP=1",
    "--file",
    planFile,
  ],
  { env: childEnvironment, stdio: "inherit" },
);
if (result.error) {
  fail("could not execute psql");
}
if (result.signal) {
  process.stderr.write(`ERROR: psql terminated by signal ${result.signal}\n`);
  process.exit(1);
}
process.exit(result.status ?? 1);
