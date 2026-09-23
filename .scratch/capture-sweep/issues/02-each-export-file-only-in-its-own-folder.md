# 02: Each export file is written only into its own folder — no fallback

**What to build:** An empty folder turns that file off; nothing is ever written into another
file's folder. The Load Profile CSV writes only to the Load Profile page's Output folder, the
Billing Export File only to the Billing Folder, the Energy Export File only to the Energy file
folder. With its folder empty the 15-minute writer holds quietly, the File Upload Destination
lists nothing for that file, and the Save button on that page answers 422 naming *that* page's
empty folder ("Billing folder is empty — set it on this page", "Energy file folder is empty — set
it on this page"). The help texts on the Load Profile, Billing, Energy Summary and Export Format
pages all say "leave empty to turn this file off" and no longer promise a fallback. This withdraws
the fallback 0.8.2/0.8.3 introduced (`.scratch/export-folders/spec.md`), and an install that set
only the Load Profile folder stops getting a billing file and an Energy file until their folders
are set — the owner accepted this 2026-09-23.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The two fallback readers in the settings module return the folder as stored (empty stays
      empty); no writer, endpoint or the upload cycle reads another file's folder
- [ ] Tests (rewriting `test_export_folders_per_file.py`): each writer with only its own folder set
      lands only there; each writer with its own folder empty and the other two set writes nothing;
      *Save billing file now* / *Save to file* answer 422 naming that page's folder when it is empty
      even though the Load Profile folder is set; the upload cycle with the billing folder empty
      sends no billing file even when one sits in the Load Profile folder
- [ ] The four pages' help texts and the Export Format page's paragraph say each file goes only to
      its own folder; no page claims the Load Profile folder is used by another file
- [ ] ADR 0023's 2026-09-23 amendment gains a paragraph withdrawing the fallback; SPEC §3.6's note,
      CLAUDE.md's 0023 digest and `.scratch/export-folders/spec.md`'s status line follow
- [ ] Gate: `ruff format --check`, `ruff check`, `pytest -n auto` (app), `pnpm lint && pnpm build`
      (web)
