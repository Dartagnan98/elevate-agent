import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { delimiter, dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { afterEach, describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const backendDir = dirname(dirname(fileURLToPath(import.meta.url)));
const runner = join(
  backendDir,
  "scripts",
  "apply-hq-migrations-0011-0020.sh",
);
const checksDir = join(backendDir, "scripts", "hq-migrations");
const projectRef = "gpmzkdjxfwbryculteee";
const confirmation = "APPLY-ELEVATE-HQ-PRODUCTION-0011-0020";
const secretMarker = "never-record-this-password";
const productionUrl =
  `postgresql://postgres.${projectRef}:${secretMarker}` +
  "@aws-0-ca-central-1.pooler.supabase.com:5432/postgres?sslmode=verify-full";

const temporaryDirectories: string[] = [];

afterEach(() => {
  while (temporaryDirectories.length > 0) {
    rmSync(temporaryDirectories.pop()!, { recursive: true, force: true });
  }
});

function makeHarness(): {
  root: string;
  evidenceDir: string;
  captureDir: string;
  binDir: string;
  caPath: string;
} {
  const root = mkdtempSync(join(tmpdir(), "elevate-hq-migration-test-"));
  temporaryDirectories.push(root);
  const evidenceDir = join(root, "evidence");
  const captureDir = join(root, "capture");
  const binDir = join(root, "bin");
  for (const directory of [evidenceDir, captureDir, binDir]) {
    mkdirSync(directory, { recursive: true });
  }
  const caPath = join(root, "prod-supabase.cer");
  writeFileSync(
    caPath,
    "-----BEGIN CERTIFICATE-----\nTEST-ONLY-CA\n-----END CERTIFICATE-----\n",
    { mode: 0o600 },
  );

  const mockPsql = join(binDir, "psql");
  writeFileSync(
    mockPsql,
    `#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const args = process.argv.slice(2);
const fileFlag = args.indexOf("--file");
if (fileFlag < 0 || !args[fileFlag + 1]) process.exit(91);
const plan = fs.readFileSync(args[fileFlag + 1], "utf8");
fs.writeFileSync(path.join(process.env.MOCK_PSQL_CAPTURE_DIR, "plan.sql"), plan);
fs.writeFileSync(
  path.join(process.env.MOCK_PSQL_CAPTURE_DIR, "argv.txt"),
  args.join("\\n"),
);
fs.writeFileSync(
  path.join(process.env.MOCK_PSQL_CAPTURE_DIR, "connection-env.json"),
  JSON.stringify({
    host: process.env.PGHOST,
    port: process.env.PGPORT,
    database: process.env.PGDATABASE,
    user: process.env.PGUSER,
    sslmode: process.env.PGSSLMODE,
    sslrootcert: process.env.PGSSLROOTCERT ?? null,
    passwordPresent: Boolean(process.env.PGPASSWORD),
    sourceUrlPresent: Boolean(process.env.TEST_HQ_DATABASE_URL),
    launcherUrlPresent: Boolean(process.env.ELEVATE_HQ_PSQL_URL),
    inheritedOverridesPresent: [
      "PGHOSTADDR",
      "PGSERVICE",
      "PGSERVICEFILE",
      "PGPASSFILE",
      "PGOPTIONS",
      "PGSSLCERT",
      "PGSSLKEY",
      "PGSSLCRL",
      "PGSSLCRLDIR",
      "PGSSLNEGOTIATION",
      "PGTARGETSESSIONATTRS",
    ].filter((name) => Boolean(process.env[name])),
  }),
);
for (const line of plan.split(/\\r?\\n/)) {
  if (!line.startsWith("\\\\echo ELEVATE_AUDIT ")) continue;
  const output = line.slice("\\\\echo ".length);
  process.stdout.write(output + "\\n");
  const match = output.match(/event=migration state=started migration=(\\d{4})/);
  if (match && match[1] === process.env.MOCK_PSQL_FAIL_MIGRATION) {
    process.stderr.write("mock migration failure " + match[1] + "\\n");
    process.exit(44);
  }
}
process.exit(0);
`,
  );
  chmodSync(mockPsql, 0o755);
  return { root, evidenceDir, captureDir, binDir, caPath };
}

function runMigration(
  harness: ReturnType<typeof makeHarness>,
  options: {
    confirmation?: string;
    url?: string;
    failMigration?: string;
    extraArgs?: string[];
    extraEnv?: Record<string, string>;
  } = {},
) {
  return spawnSync(
    runner,
    [
      "--database-url-env",
      "TEST_HQ_DATABASE_URL",
      "--confirm",
      options.confirmation ?? confirmation,
      "--evidence-dir",
      harness.evidenceDir,
      ...(options.extraArgs ?? []),
    ],
    {
      cwd: backendDir,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${harness.binDir}${delimiter}${process.env.PATH ?? ""}`,
        TEST_HQ_DATABASE_URL: options.url ?? productionUrl,
        MOCK_PSQL_CAPTURE_DIR: harness.captureDir,
        ELEVATE_HQ_DB_SSLROOTCERT: harness.caPath,
        PGHOSTADDR: "203.0.113.99",
        PGSERVICE: "hostile-service",
        PGSERVICEFILE: "/tmp/hostile-service-file",
        PGPASSFILE: "/tmp/hostile-password-file",
        PGOPTIONS: "-c search_path=hostile",
        PGSSLROOTCERT: "/tmp/hostile-root.pem",
        PGSSLCERT: "/tmp/hostile-client.pem",
        PGSSLKEY: "/tmp/hostile-client.key",
        PGSSLCRL: "/tmp/hostile-crl.pem",
        PGSSLCRLDIR: "/tmp/hostile-crl-dir",
        PGSSLNEGOTIATION: "direct",
        PGTARGETSESSIONATTRS: "read-write",
        ...(options.failMigration
          ? { MOCK_PSQL_FAIL_MIGRATION: options.failMigration }
          : {}),
        ...(options.extraEnv ?? {}),
      },
    },
  );
}

function onlyEvidence(evidenceDir: string): string {
  const entries = readdirSync(evidenceDir).filter((entry) =>
    entry.endsWith(".audit.log"),
  );
  assert.equal(entries.length, 1);
  return readFileSync(join(evidenceDir, entries[0]), "utf8");
}

describe("HQ 0011-0020 migration runner", () => {
  it("keeps reserved PostgreSQL words out of migration aliases", () => {
    const migrationsDir = join(backendDir, "supabase", "migrations");
    const migrations = readdirSync(migrationsDir)
      .filter((entry) => /^(001[1-9]|0020)_.*\.sql$/.test(entry))
      .sort();
    assert.equal(migrations.length, 10);
    for (const migration of migrations) {
      const sql = readFileSync(join(migrationsDir, migration), "utf8")
        .split(/\r?\n/)
        .filter((line) => !/^\s*--/.test(line))
        .join("\n");
      assert.doesNotMatch(sql, /\bas\s+grant\b/i, migration);
      assert.doesNotMatch(sql, /\bgrant\./i, migration);
    }
  });

  it("pins explicit least-privilege diagnostic table grants", () => {
    for (const [migration, table] of [
      ["0011_session_diagnostic_events.sql", "session_diagnostic_events"],
      ["0013_app_crash_reports.sql", "app_crash_reports"],
    ] as const) {
      const sql = readFileSync(
        join(backendDir, "supabase", "migrations", migration),
        "utf8",
      );
      assert.match(
        sql,
        new RegExp(
          `revoke all on table public\\.${table}\\s+` +
            "from public, anon, authenticated, service_role;",
          "i",
        ),
      );
      assert.match(
        sql,
        new RegExp(
          `grant select, insert on table public\\.${table}\\s+to service_role;`,
          "i",
        ),
      );
    }

    const lockdown = readFileSync(
      join(
        backendDir,
        "supabase",
        "migrations",
        "0012_lock_down_public_privileges.sql",
      ),
      "utf8",
    );
    const revokeStatements = lockdown
      .split(";")
      .filter((statement) => /\brevoke\b/i.test(statement));
    for (const statement of revokeStatements) {
      assert.doesNotMatch(statement, /\bservice_role\b/i);
    }
  });

  it("builds one fail-closed psql session with exact ordered transactions", () => {
    const harness = makeHarness();
    const result = runMigration(harness);
    assert.equal(result.status, 0, result.stderr || result.stdout);

    const plan = readFileSync(join(harness.captureDir, "plan.sql"), "utf8");
    const expectedFiles = [
      "0011_session_diagnostic_events.sql",
      "0012_lock_down_public_privileges.sql",
      "0013_app_crash_reports.sql",
      "0014_atomic_device_approval.sql",
      "0015_atomic_login_codes.sql",
      "0016_atomic_membership_allocation.sql",
      "0017_refresh_v2_response_recovery.sql",
      "0018_device_v2_response_recovery.sql",
      "0019_initial_issuance_v2.sql",
      "0020_device_start_v3_idempotency.sql",
    ];

    let previous = -1;
    for (const migrationFile of expectedFiles) {
      const migrationNumber = migrationFile.slice(0, 4);
      const started = plan.indexOf(
        `event=migration state=started migration=${migrationNumber}`,
      );
      const current = plan.indexOf(migrationFile);
      const committed = plan.indexOf(
        `event=migration state=committed migration=${migrationNumber}`,
      );
      assert.ok(started > previous, `${migrationNumber} start is out of order`);
      assert.ok(current > previous, `${migrationFile} is missing or out of order`);
      assert.ok(current > started, `${migrationFile} is outside its transaction`);
      assert.ok(committed > current, `${migrationNumber} has no commit marker`);
      const transaction = plan.slice(started, committed);
      assert.equal((transaction.match(/^begin;$/gm) ?? []).length, 1);
      assert.equal((transaction.match(/^commit;$/gm) ?? []).length, 1);
      assert.match(transaction, /^set local lock_timeout = '5s';$/m);
      assert.match(transaction, /^set local statement_timeout = '5min';$/m);
      assert.match(transaction, /^set local search_path = public, pg_temp;$/m);
      assert.match(transaction, /pg_advisory_xact_lock/);
      previous = committed;
    }

    assert.equal((plan.match(/^begin;$/gm) ?? []).length, 10);
    assert.equal((plan.match(/^commit;$/gm) ?? []).length, 10);
    assert.equal((plan.match(/^set local lock_timeout = '5s';$/gm) ?? []).length, 10);
    assert.equal(
      (plan.match(/^set local statement_timeout = '5min';$/gm) ?? []).length,
      10,
    );
    assert.equal(
      (plan.match(/^set local search_path = public, pg_temp;$/gm) ?? []).length,
      10,
    );
    assert.equal(
      (
        plan.match(
          /pg_advisory_xact_lock\(pg_catalog\.hashtextextended\('elevate-hq-schema-migration', 0\)\)/g,
        ) ?? []
      ).length,
      10,
    );

    const pre0020 = plan.indexOf("verify-0020-topology.sql");
    const start0020 = plan.indexOf(
      "event=migration state=started migration=0020",
    );
    assert.ok(pre0020 > plan.indexOf("state=committed migration=0019"));
    assert.ok(start0020 > pre0020);
    assert.ok(plan.indexOf("verify-final-readiness.sql") > start0020);
    assert.ok(plan.indexOf("notify pgrst, 'reload schema';") > start0020);

    const argv = readFileSync(join(harness.captureDir, "argv.txt"), "utf8");
    assert.match(argv, /^-X$/m);
    assert.match(argv, /^--no-psqlrc$/m);
    assert.match(argv, /^--no-password$/m);
    assert.match(argv, /^--set=ON_ERROR_STOP=1$/m);
    assert.equal(argv.includes(secretMarker), false);
    assert.deepEqual(
      JSON.parse(
        readFileSync(
          join(harness.captureDir, "connection-env.json"),
          "utf8",
        ),
      ),
      {
        host: "aws-0-ca-central-1.pooler.supabase.com",
        port: "5432",
        database: "postgres",
        user: `postgres.${projectRef}`,
        sslmode: "verify-full",
        sslrootcert: harness.caPath,
        passwordPresent: true,
        sourceUrlPresent: false,
        launcherUrlPresent: false,
        inheritedOverridesPresent: [],
      },
    );

    const evidence = onlyEvidence(harness.evidenceDir);
    assert.match(evidence, /event=run_finished state=succeeded schema=0020/);
    assert.match(
      evidence,
      /event=runner_identity runner_sha256=[0-9a-f]{64} initial_check_sha256=[0-9a-f]{64} pre_0020_check_sha256=[0-9a-f]{64} final_check_sha256=[0-9a-f]{64}/,
    );
    assert.match(evidence, /event=migration_planned migration=0011 sha256=[0-9a-f]{64}/);
    assert.match(evidence, /event=migration state=committed migration=0020/);
    assert.equal(evidence.includes(secretMarker), false);
  });

  it("rejects wrong confirmation and wrong project before invoking psql", () => {
    for (const options of [
      { confirmation: "yes" },
      { url: "postgresql://postgres:secret@localhost/postgres" },
      {
        url:
          `postgresql://postgres:${projectRef}` +
          "@wrong-project.pooler.supabase.com/postgres?sslmode=verify-full",
      },
      {
        url:
          `postgresql://postgres.${projectRef}:secret` +
          "@evil.example/postgres?sslmode=verify-full",
      },
      {
        url:
          `postgresql://postgres.${projectRef}:secret` +
          "@aws-0-ca-central-1.pooler.supabase.com:6543/postgres?sslmode=verify-full",
      },
    ]) {
      const harness = makeHarness();
      const result = runMigration(harness, options);
      assert.notEqual(result.status, 0);
      assert.equal(readdirSync(harness.captureDir).length, 0);
      assert.equal(readdirSync(harness.evidenceDir).length, 0);
    }
  });

  it("requires a separately named, regular production Supabase CA file", () => {
    for (const explicitRoot of ["", "relative-ca.pem", "/does/not/exist.cer"]) {
      const harness = makeHarness();
      const result = runMigration(harness, {
        extraEnv: { ELEVATE_HQ_DB_SSLROOTCERT: explicitRoot },
      });
      assert.notEqual(result.status, 0);
      assert.equal(readdirSync(harness.captureDir).length, 0);
    }

    const symlinkHarness = makeHarness();
    const symlinkPath = join(symlinkHarness.root, "linked-ca.cer");
    const linked = spawnSync("ln", ["-s", symlinkHarness.caPath, symlinkPath]);
    assert.equal(linked.status, 0);
    const symlinkResult = runMigration(symlinkHarness, {
      extraEnv: { ELEVATE_HQ_DB_SSLROOTCERT: symlinkPath },
    });
    assert.notEqual(symlinkResult.status, 0);
    assert.equal(readdirSync(symlinkHarness.captureDir).length, 0);
  });

  it("allows only an explicitly attested loopback ephemeral test target", () => {
    const harness = makeHarness();
    const database = "elevate_hq_migration_test_mock";
    const result = runMigration(harness, {
      confirmation: "TEST-ONLY-APPLY-ELEVATE-HQ-0011-0020",
      url:
        `postgresql://postgres:test@127.0.0.1:55432/${database}` +
        "?sslmode=disable",
      extraArgs: ["--local-test-database", database],
      extraEnv: {
        ELEVATE_HQ_MIGRATION_TEST_ONLY: "LOCAL-EPHEMERAL-POSTGRES",
      },
    });
    assert.equal(result.status, 0, result.stderr || result.stdout);
    const planPath = join(harness.captureDir, "plan.sql");
    assert.ok(
      existsSync(planPath),
      `${result.stdout}\n${result.stderr}\ncapture=${readdirSync(harness.captureDir)}`,
    );
    const plan = readFileSync(planPath, "utf8");
    assert.match(plan, /local test target identity check failed/);
    assert.match(plan, /event=local_target_identity state=pass/);
    assert.deepEqual(
      JSON.parse(
        readFileSync(
          join(harness.captureDir, "connection-env.json"),
          "utf8",
        ),
      ),
      {
        host: "127.0.0.1",
        port: "55432",
        database,
        user: "postgres",
        sslmode: "disable",
        sslrootcert: null,
        passwordPresent: true,
        sourceUrlPresent: false,
        launcherUrlPresent: false,
        inheritedOverridesPresent: [],
      },
    );

    const unattested = makeHarness();
    const rejected = runMigration(unattested, {
      confirmation: "TEST-ONLY-APPLY-ELEVATE-HQ-0011-0020",
      url:
        `postgresql://postgres:test@127.0.0.1:55432/${database}` +
        "?sslmode=disable",
      extraArgs: ["--local-test-database", database],
    });
    assert.notEqual(rejected.status, 0);
    assert.equal(readdirSync(unattested.captureDir).length, 0);
  });

  it("stops on the first psql error and records failure without success", () => {
    const harness = makeHarness();
    const result = runMigration(harness, { failMigration: "0015" });
    assert.equal(result.status, 44, result.stderr || result.stdout);

    const evidence = onlyEvidence(harness.evidenceDir);
    assert.match(evidence, /event=migration state=started migration=0015/);
    assert.doesNotMatch(evidence, /event=migration state=committed migration=0015/);
    assert.doesNotMatch(evidence, /event=migration state=started migration=0016/);
    assert.match(evidence, /event=run_finished state=failed exit_code=44/);
    assert.doesNotMatch(evidence, /event=run_finished state=succeeded/);
  });

  it("pins non-retry baseline, 0020 topology, and final readiness invariants", () => {
    const migration0020 = readFileSync(
      join(
        backendDir,
        "supabase",
        "migrations",
        "0020_device_start_v3_idempotency.sql",
      ),
      "utf8",
    );
    assert.match(
      migration0020,
      /create or replace function public\.elevate_hq_schema_readiness_v1\(\)[\s\S]*?returns jsonb[\s\S]*?language plpgsql[\s\S]*?stable[\s\S]*?security invoker[\s\S]*?set search_path = pg_catalog, public, pg_temp/,
    );
    assert.match(
      migration0020,
      /revoke execute on function public\.elevate_hq_schema_readiness_v1\(\)[\s\S]*?from public, anon, authenticated;/,
    );
    assert.match(
      migration0020,
      /grant execute on function public\.elevate_hq_schema_readiness_v1\(\)[\s\S]*?to service_role;/,
    );

    const baseline = readFileSync(
      join(checksDir, "verify-0010-baseline.sql"),
      "utf8",
    );
    assert.match(baseline, /HQ migration baseline is not pristine 0010/);
    assert.match(baseline, /Do not retry/);
    assert.match(baseline, /session_diagnostic_events/);
    assert.match(baseline, /start_device_grant_atomic_v3/);
    assert.match(baseline, /elevate_hq_schema_readiness_v1/);

    const pre0020 = readFileSync(
      join(checksDir, "verify-0020-topology.sql"),
      "utf8",
    );
    assert.match(pre0020, /elevate_internal already exists/);
    assert.match(pre0020, /required 0017-0019 public functions are incomplete/);
    assert.match(pre0020, /expected six 0017-0019 columns/);
    assert.match(pre0020, /public v3\/readiness function already exists/);
    assert.match(pre0020, /v3 trigger already exists/);

    const finalReadiness = readFileSync(
      join(checksDir, "verify-final-readiness.sql"),
      "utf8",
    );
    assert.match(finalReadiness, /null refresh family expiry remains/);
    assert.match(finalReadiness, /duplicate unconsumed login codes remain/);
    assert.match(finalReadiness, /public\/internal function pair absent/);
    assert.match(finalReadiness, /function grants are unsafe/);
    assert.match(finalReadiness, /v3 capability trigger is absent/);
    assert.match(finalReadiness, /index_metadata\.indisvalid/);
    assert.match(finalReadiness, /index_metadata\.indisready/);
    assert.match(finalReadiness, /and convalidated/);
    assert.match(finalReadiness, /tgenabled in \('O', 'A'\)/);
    assert.match(finalReadiness, /tgfoid = to_regprocedure/);
    assert.match(finalReadiness, /public\.elevate_hq_schema_readiness_v1\(\)/);
    assert.match(finalReadiness, /proc\.provolatile = 's'/);
    assert.match(finalReadiness, /and not proc\.prosecdef/);
    assert.match(
      finalReadiness,
      /search_path=pg_catalog, public, pg_temp/,
    );
    assert.match(
      finalReadiness,
      /readiness RPC did not return exact success contract/,
    );
    for (const key of [
      "contract",
      "schema_version",
      "ready",
      "tables_ready",
      "columns_ready",
      "constraints_ready",
      "indexes_ready",
      "rpcs_ready",
      "triggers_ready",
      "privileges_ready",
      "data_invariants_ready",
      "initial_issuance_v2_ready",
    ]) {
      assert.ok(finalReadiness.includes(`'${key}'`), `missing ${key}`);
    }
  });
});
