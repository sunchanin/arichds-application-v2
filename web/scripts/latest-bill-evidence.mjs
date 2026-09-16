// Evidence for ui-audit ticket 09's tint rule (`src/billingHighlight.ts`).
//
// `web/` deliberately has no test runner; this repo proves page rules outside
// the browser instead (`renderToStaticMarkup` for markup, plain node for a pure
// helper). Run from `web/`:  node scripts/latest-bill-evidence.mjs
// It compiles the one helper with the pinned tsc into a temp dir and asserts
// the ticket's named cases plus the review's tie case. Exit code 1 on any FAIL.

import { execFileSync } from "node:child_process";
import { mkdtempSync, renameSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const out = mkdtempSync(join(tmpdir(), "latest-bill-"));
const tsc = join("node_modules", ".bin", process.platform === "win32" ? "tsc.cmd" : "tsc");
execFileSync(tsc, ["src/billingHighlight.ts", "--outDir", out, "--module", "esnext", "--target", "es2022", "--strict", "--skipLibCheck"], {
  stdio: "inherit",
  shell: process.platform === "win32",
});
renameSync(join(out, "billingHighlight.js"), join(out, "billingHighlight.mjs"));
const { latestBillRowId } = await import(pathToFileURL(join(out, "billingHighlight.mjs")).href);

let failed = 0;
const check = (ok, what) => {
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
  if (!ok) failed += 1;
};
const row = (id, billDate) => ({ id, bill_date: billDate });
const oldestFirst = [row(3, "2026-05-31T17:00:00+00:00"), row(2, "2026-06-30T17:00:00+00:00"), row(1, "2026-07-31T17:00:00+00:00")];

check(latestBillRowId(oldestFirst) === 1, "oldest-first order: the newest date wins, not row 0");
check(latestBillRowId([...oldestFirst].reverse()) === 1, "newest-first order: same row");
check(latestBillRowId([row(7, "2026-06-30T17:00:00+00:00"), row(8, "2026-05-31T17:00:00+00:00")]) === 7, "a filter hiding the newest tints the newest shown");
check(latestBillRowId([]) === null, "empty table tints nothing");
check(
  latestBillRowId([row(12, "2026-07-31T17:00:00+00:00"), row(11, "2026-07-31T17:00:00+00:00"), row(10, "2026-06-30T17:00:00+00:00")]) === 11,
  "two meters closing on the same instant (All devices): exactly one row, the lowest id",
);
// v1's literal rule, "first row of page one", disagrees with the helper on the oldest-first page.
check(oldestFirst[0].id !== latestBillRowId(oldestFirst), "mutation 'first row of page one' would tint a different row here");

process.exitCode = failed === 0 ? 0 : 1;
