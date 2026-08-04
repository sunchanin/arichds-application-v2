---
description: Take a GitHub issue and run it through the full implement → scrutinize → review → fix loop autonomously until review approves.
argument-hint: <issue-number>
allowed-tools: Bash, Read, Write, Glob, Grep, Task, SendMessage
---

You are the **orchestrator** for issue **#$1**. Drive the entire pipeline yourself by delegating to subagents. The human does not want to be involved until review passes — only stop early for the hard limits below.

**Keep an audit trail as you go.** From every subagent reply, capture the TDD decision, the scrutinize/code-review findings and how they were resolved, and the verdict.

**Record which skills each subagent actually invoked — from its transcript, not its words.** Each `Task` call returns the path to that subagent's transcript (its `output_file`, a `.jsonl` or `.output` under the session's `tasks/` dir); a `SendMessage` reply continues the same agent and appends to that same file. **Capture each subagent's `output_file` path verbatim from the tool result the moment it is returned — that exact path is the only reliable handle.** After every subagent reply (Task or SendMessage), grep that exact file — this is the tamper-proof source of truth for whether the required skills actually ran:
```
grep -o '"skill":"[a-z-]*"' <that-agent's-output_file> | sort | uniq -c   # which skills
grep -c '"name":"Skill"' <that-agent's-output_file>                        # how many Skill calls
```
Verify BOTH sets: the four pipeline skills (`/draft-delegation-prompt`, `/tdd` when required, `/scrutinize`, `/code-review`) **and** every domain skill the reviewer mandated in the delegation prompt's Workflow-discipline section (e.g. `antd-ui`, `frontend-design`, `dataviz`). A mandated domain skill that never appears in the implementer's transcript is a process miss — note it in the audit log and, if it plausibly changed the outcome (wrong-convention UI, stale API), feed it back as a fix-pass item rather than approving around it. You will write the verified result into a Thai-language audit log in Step 5. The final report to the human must also be **in Thai (ภาษาไทย)**.

## Step 0 — Fetch the issue
Run: `gh issue view $1 --json number,title,body,labels,comments`
If it fails, stop and report. Read the issue carefully and extract acceptance criteria.

**Label sanity check:** if the issue carries `needs-info`, `needs-triage`, or `wontfix`, do not run it blind — tell the human it isn't marked ready and ask whether to proceed (a human explicitly running a single issue may override; unlike a batch, this is one deliberate pick). `ready-for-human` means a human must implement it — stop and say so.

**Fold in the project's definition-of-done gate.** The issue's acceptance criteria are the primary standard, but this project also gates every module on things an issue body may not restate — read the "Workflow / เทสผ่าน" gate in `CLAUDE.md` and `SPEC.md` §5 (e.g. Output Parity vs v1 for LP/Billing/Energy, a real-meter read for acquisition work) and treat any that apply to this issue as additional acceptance criteria the reviewer must judge against. `/to-issues` should have written these into the issue already; if they're missing, add them to the criteria you pass downstream rather than letting the gap through.

## Step 1 — Reviewer authors the delegation prompt (Job A)
Spawn **one reviewer agent for this issue** (Task tool), passing the issue text, and ask it for **Job A**. You will continue this **same** agent via SendMessage for Job B and any fix prompts (if SendMessage is a deferred tool in your session, load it via ToolSearch first) — do not spawn a fresh reviewer per step; the context it builds here (issue, code, tests) is reused across the whole issue. It invokes `/draft-delegation-prompt` and returns a `## DELEGATION PROMPT` (including a "TDD required" decision). Do not write the build prompt yourself — the reviewer owns prompt authoring.

## Step 2 — Implement
Delegate to the `implementer` subagent, passing the reviewer's DELEGATION PROMPT verbatim. It implements (using `/tdd` iff the prompt requires it), runs its built-in self-check (exception-handler audit + None/edge-case trace — no skill call), fixes everything above nit, and returns IMPLEMENTATION + TDD RESULT + SELF-CHECK REPORT.

If its self-assessment is NEEDS_MORE_WORK, feed its own findings back to it and re-run until it reports READY_FOR_REVIEW (max 3 internal passes, then proceed to review regardless and let the reviewer judge).

## Step 3 — Review (Job B)
**Continue the same reviewer agent** (SendMessage) for **Job B**, passing the implementer's full report. It already holds the issue and code context from Job A — remind it that the standard is the **issue's acceptance criteria**, not its own delegation prompt. It invokes `/scrutinize` + `/code-review` and returns CODE REVIEW (verdict + problems).

## Step 4 — Loop
- If **APPROVED** → go to Step 5.
- If **CHANGES_REQUESTED** → message the **same reviewer** (SendMessage) in **Job A**, passing its own CODE REVIEW problems, to author a fix `## DELEGATION PROMPT`; send that to the `implementer` (fix → re-run self-check → self-fix above-nit), then back to Step 3.
- Track an iteration counter. **After 5 full review cycles without approval, STOP** — but still go to Step 5 to **write the audit log** (recording how far it got and the outstanding problems) before reporting to the human. Do not loop forever, and do not skip the log.

## Step 5 — Audit log + report (ภาษาไทย)

First, **write a Thai-language audit log** to `.claude/run-logs/issue-$1.md` (create the `.claude/run-logs/` directory if needed) using the Write tool. Use this template — fill every field from what you actually captured, not from memory:

```markdown
# Audit log — Issue #$1: <หัวข้อ issue>
รัน: <วันเวลา> · branch: <ชื่อ branch> · ผลลัพธ์: <APPROVED / ค้าง> · รอบรีวิว: <n>

## ทำอะไรไปบ้าง (ทีละขั้น)
1. **reviewer (Job A) — สร้าง prompt** (`/draft-delegation-prompt`)
   - TDD required: <yes/no — เหตุผล>
2. **implementer — ลงมือ + ตรวจตัวเอง** (<`/tdd` หรือ "ไม่ใช้ TDD ตาม prompt">, self-check ในตัว — ไม่มี skill call)
   - ไฟล์ที่เปลี่ยน: <รายการ>
   - self-check เจออะไรเหนือ nit และแก้อย่างไร: <สรุป>
   - ผลรันเทสต์: <ผ่าน/ไม่ผ่าน + สรุป>
3. **reviewer (Job B, agent เดิมจาก Job A) — รีวิว** (`/scrutinize` + `/code-review`)
   - verdict: <APPROVED / CHANGES_REQUESTED> + problems ที่เจอ
4. **รอบแก้ (ถ้ามี):** <สรุปแต่ละรอบ: reviewer Job A สร้าง fix prompt → implementer แก้ → reviewer Job B รีวิวซ้ำ>

## ✅ skill ที่เรียกจริง — ยืนยันจาก transcript (tamper-proof)
<paste ผล grep ที่คุณรันบน transcript ของแต่ละ subagent ใน issue นี้ — ชื่อ skill + จำนวนครั้งจริง>

## Commit
<hash ถ้ามี> — <ข้อความ commit>  (ถ้ายังไม่ commit ให้ระบุว่ารอมนุษย์ตัดสินใจ)

## วิธีตรวจซ้ำด้วยตัวเอง (audit)
หลักฐานจริงอยู่ใน subagent transcript — **ระบุ path จริงของแต่ละ subagent (ค่า `output_file` ที่จับไว้ตอน spawn)** แล้ว grep ว่า skill ถูกเรียกจริงกี่ครั้ง / ชื่ออะไร. เก็บ path เหล่านั้นไว้ในบล็อกนี้ (อย่าใช้ glob สำเร็จรูป — โครงสร้าง path ของ transcript ต่างกันตาม harness และมักได้ผลศูนย์ทั้งที่ skill ถูกเรียกจริง):
    # แทน <path> ด้วย output_file จริงของแต่ละ subagent ใน issue นี้
    grep -o '"skill":"[a-z-]*"' <path> | sort | uniq -c
    grep -c '"name":"Skill"' <path>
```

**Then — learn & sync docs (do these two passes yourself as the orchestrator, before the final report):**

1. **Learn & record.** Reflect on what this run surfaced that a future session couldn't derive from the code — a root cause, a wrong assumption a doc encoded, a confirmed user decision, a meter/hardware behavior. Save each durable, non-obvious learning to the memory system (`MEMORY.md` index + one file per fact); skip anything an ADR, the code, or git history already records. Memory lives outside the repo, so this never touches git.
2. **Docs consistency sweep.** Beyond the per-issue `CONTEXT.md`/ADR the implementer already touched, verify the wider docs still match what shipped and update any that drifted: `CONTEXT-MAP.md`, the affected `README.md`(s), `CLAUDE.md`, and cross-referenced ADRs. A doc the change outdated is part of this run's unfinished work. Leave the edits **uncommitted** (the human commits — see below).

Then **report to the human in Thai**: ผลรีวิวสุดท้าย, สรุปสิ่งที่เปลี่ยน (ไฟล์ + แนวทาง), สถานะเทสต์, จำนวนรอบรีวิว, path ของ audit log ที่เพิ่งเขียน, **learnings ที่บันทึกลง memory + เอกสารที่อัปเดตในรอบ sweep**, แล้วถามว่าจะให้ commit / เปิด PR ไหม. **อย่า commit, push, หรือเปิด PR เอง** — เป็นการตัดสินใจของมนุษย์

## Hard limits (stop and ask the human immediately)
- Any need to change git history, force-push, or alter branch protections.
- Any destructive operation (deleting files/data not created in this task).
- The issue is ambiguous enough that you'd be guessing at core intent — ask one clarifying question rather than build the wrong thing.
- More than 5 review cycles.

Begin with Step 0 now.