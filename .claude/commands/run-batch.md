---
description: Run a contiguous range of GitHub issues through the full implement → scrutinize → review → fix pipeline, sequentially, committing each approved issue to a single working branch and skipping any that fail.
argument-hint: <start-issue> <end-issue> [branch-name]
allowed-tools: Bash, Read, Write, Glob, Grep, Task, SendMessage
---

You are the **batch orchestrator**. You will process GitHub issues **#$1 through #$2 inclusive, in ascending numeric order**, one at a time. The human is unattended — run autonomously and stop only for the hard limits below. Produce a final batch report at the end.

**Audit trail.** For each issue, capture from every subagent reply: the TDD decision, scrutinize/code-review findings and their resolution, and the verdict.

**Record which skills each subagent actually invoked — from its transcript, not its words.** Each `Task` call returns that subagent's transcript path (its `output_file`, a `.jsonl`); a `SendMessage` reply continues the same agent and appends to that same file. After every subagent reply (Task or SendMessage), grep that exact file — `grep -o '"skill":"[a-z-]*"' <output_file> | sort | uniq -c` and `grep -c '"name":"Skill"' <output_file>` — and record the verified result into the per-issue Thai audit log (Step 4b below). The final batch report must be **in Thai (ภาษาไทย)**.

## Setup (once, before the loop)

1. **Determine the working branch.** If `$3` is provided, use it; otherwise default to `batch/issues-$1-$2`.
   - Check current git state: `git status --porcelain` and `git branch --show-current`.
   - If the working tree is dirty, STOP and report — do not run a batch on a dirty tree.
   - Create and switch to the branch: `git switch -c <branch>` (or `git switch <branch>` if it already exists). All issues commit onto this same branch, in sequence.

2. **Initialize a batch ledger** (keep in your context, render in the final report):
   ```
   | Issue | Status | Cycles | Commit | Notes |
   ```
   Statuses: DONE, SKIPPED, BLOCKED_DEPENDENCY, ERROR.

## Per-issue loop  (for N = $1 … $2)

For each issue **#N**, run the same pipeline as `/run-issue` (do not re-derive it — follow these stages):

1. **Fetch:** `gh issue view N --json number,title,body,labels,comments`.
   - If the issue does not exist or is already closed, record SKIPPED with the reason, **write its audit log (Step 4b)**, and continue to N+1.
   - **Label gate:** if its labels include `needs-info`, `needs-triage`, `ready-for-human`, or `wontfix`, record **SKIPPED (label gate: <label>)**, write its audit log (Step 4b), and continue to N+1 — do not spend a single subagent on an issue that is not ready for an agent (`ready-for-human` means a human must do it — never implement it).

2. **Dependency awareness:** If any earlier issue in this batch was SKIPPED/BLOCKED/ERROR, and #N plausibly depends on it (references it, touches the same area), note the risk. Attempt #N anyway, but if it fails in a way that looks caused by the missing earlier work, record **BLOCKED_DEPENDENCY** rather than a generic failure.

3. **Author prompt → implement → review → fix loop:** Exactly as `/run-issue` Steps 1–4 — spawn **one reviewer agent for issue #N** (Task) and continue that same agent via SendMessage for every later reviewer step of this issue (Job B, fix prompts; if SendMessage is a deferred tool in your session, load it via ToolSearch first); spawn a fresh reviewer only when you move to the next issue. The reviewer's Job A authors the `DELEGATION PROMPT` (via `/draft-delegation-prompt`, deciding TDD), `implementer` builds it (`/tdd` iff required, then its built-in self-check + self-fix above-nit, max 3 internal passes), the same reviewer's Job B reviews (via `/scrutinize` + `/code-review`, judging against the issue — not its own prompt); on CHANGES_REQUESTED, the same reviewer authors the fix prompt and the loop repeats until APPROVED.
   - **Hard cap: 5 review cycles per issue.** If #N is not APPROVED within 5 cycles, **do NOT keep trying and do NOT commit it.** Revert this issue's own changes so they don't contaminate the next issue: `git restore --source=HEAD --staged --worktree .` to undo tracked edits, then remove only the untracked files this issue created — prefer `git clean -fd -- <paths>` scoped to the files the implementer reported, and run `git clean -nfd` (dry-run) first; never blanket-delete untracked files you can't attribute to this issue. Record **SKIPPED (review unmet after 5 cycles)** with the reviewer's outstanding problems, **write its audit log (Step 4b)**, and move to N+1.

4. **Commit on success:** When #N is APPROVED:
   - `git add -A`
   - Commit with a message derived from the issue (e.g. `feat: add use-case presets (#3)`) and the required co-author trailer, using the name of the model you are actually running as (not a hardcoded one):
     ```
     git commit -m "<type>: <short summary> (#N)" -m "Co-Authored-By: <your-model-name> <noreply@anthropic.com>"
     ```
   - Record the commit hash (`git rev-parse --short HEAD`) in the ledger as DONE.
   - **Never push, never open a PR, never amend/rebase/force.** Commits stay local on the working branch.

4b. **Write the per-issue audit log (ภาษาไทย).** This step runs on **every** exit path for issue #N — DONE, SKIPPED, BLOCKED, or ERROR (the skip branches in steps 1 and 3 jump here first, never straight to N+1). Write `.claude/run-logs/issue-N.md` with the Write tool, using the **same Thai template as `/run-issue` Step 5**: steps taken, the **transcript-verified** skills actually invoked, TDD decision, scrutinize + code-review findings and resolution, cycle count, commit hash or skip reason, and the self-audit recipe. For a skipped issue, record how far it got and why it stopped.

5. Continue to the next issue. A skipped or errored issue must not halt the batch (except hard limits below).

## After the loop — Final batch report (ภาษาไทย)

**First, two closing passes over the WHOLE batch (once at the end, not per issue):**

1. **Learn & record.** Consolidate what the batch surfaced that a future session couldn't derive from the code — recurring root causes, wrong assumptions docs encoded, confirmed user decisions, meter/hardware behavior. Save each durable, non-obvious learning to the memory system (`MEMORY.md` index + one file per fact); skip anything an ADR, the code, or git history already records. Memory is outside the repo — no commit.
2. **Docs consistency sweep.** Beyond the per-issue `CONTEXT.md`/ADR the implementers touched, verify the wider docs still match everything the batch shipped and update any that drifted: `CONTEXT-MAP.md`, the affected `README.md`(s), `CLAUDE.md`, cross-referenced ADRs. Commit this sweep as a final `docs: sync docs & context after batch (#$1-#$2)` commit on the working branch (with the co-author trailer, as in Step 4), and add it to the ledger. Still **never** push / open a PR.

รายงานสรุปต่อมนุษย์ **เป็นภาษาไทย**:
- ชื่อ working branch และจำนวน commit บนนั้น (รวม commit `docs:` ปิดท้าย ถ้ามี)
- learnings ที่บันทึกลง memory + เอกสารที่อัปเดตในรอบ sweep
- ตาราง ledger เต็ม (ทุก issue #$1–#$2 พร้อม status, จำนวนรอบ, commit hash, หมายเหตุ)
- รายชื่อ audit log ที่เขียนไว้ (`.claude/run-logs/issue-*.md`) เพื่อให้มนุษย์เปิดดูทีละ issue ได้
- สำหรับทุก issue ที่ SKIPPED / BLOCKED / ERROR: ปัญหาที่ reviewer ยังค้าง หรือ error เพื่อให้มนุษย์ไปทำต่อเอง
- ความเสี่ยงเรื่อง dependency ที่ flag ไว้
- บรรทัดสรุปขั้นต่อไป: มนุษย์ยังต้องรีวิว branch แล้วตัดสินใจเรื่อง push / PR เอง — **คุณยังไม่ได้ push อะไรทั้งสิ้น**
- วิธีตรวจสอบหลักฐานจริง (transcript): `grep -ho '"skill":"[a-z-]*"' ~/.claude/projects/*/*/subagents/*.jsonl | sort | uniq -c`

## Hard limits (stop the WHOLE batch and ask the human)
- Dirty working tree at setup.
- Any need to push, open/modify a PR, change git history, force-push, rebase, or alter branch protections.
- Any destructive operation beyond reverting the current issue's own uncommitted changes (never delete pre-existing files/data, never `git reset --hard` past commits you didn't just make in this run, never empty stashes/trash).
- A single issue's intent is so ambiguous you'd be guessing at core behavior — record it as SKIPPED (ambiguous) and continue; do NOT halt the batch for one ambiguous issue.

Begin with Setup now, then process issues $1 through $2 in order.