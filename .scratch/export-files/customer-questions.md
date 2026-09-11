# Four questions about the export files

Written 2026-09-11. These are the only things we need from you — none of them blocks the work,
and each one we get wrong costs more to change after your tooling is reading the files than
before.

Two of them change what we build. Two only change what we expect.

---

## 1. Does `Avg Phase Angle` need to work? — *changes nothing on our side either way*

Your sample asks for three phase angle columns and we have mapped them. On the Prometer 100 we
read them and get **0.000, 0.000 and -1.000**, on every interval.

That is the meter's own answer, not a gap in our software. We checked it against the meter's
instantaneous registers directly and got the same values, while the power factor register on the
same connection reads **0.076** — a power factor that low means an angle near 86 degrees. So the
registers exist, they answer, and what they answer is not a usable angle.

Our reading of this is that those registers are **not commissioned on that unit**, which is a
question for CEWE rather than for us. If you need the columns to carry real numbers, that is the
conversation to have; if you only need the columns present, they are present.

**What we need from you:** whether this matters to you, so we know whether to raise it with CEWE
or leave it.

---

## 2. What is `Setting : 1`? — *we reproduce it either way*

Every one of your sample files carries a line reading `Setting : 1` in the header block, with no
explanation anywhere in the workbook. We reproduce the line exactly, in the same position, so
your tooling's line offsets stay correct.

Nobody on either side appears to know what it means.

**What we need from you:** what the value is for, and whether it is ever anything other than `1`.
If it is a real setting, it should probably be reading something rather than being a constant we
copy.

---

## 3. Does anything read the closed, dated files? — **this one changes what we build**

When the columns in a file change, we do **not** rewrite the file you already have. We close it
under a name carrying the date — `<meter>.2026-09-15.csv` — and open a fresh file beside it under
the new header. Nothing is ever appended under a header that does not describe it.

This matters to you the first time you take an update, because the Load Profile file grows from
14 to 25 columns: your current file closes, a new one starts.

- If your tooling reads a **fixed filename**, it finds the new file and nothing changes for you.
- If your tooling **scans the folder**, it will now find two files with different column counts.

**What we need from you:** which of those it is. If it scans, we can put closed files in a
subfolder instead — that is a small change now and an awkward one later.

---

## 4. Is `M/D/YYYY HH:MM` actually required? — **this one changes a default**

Your billing sample shows dates as `5/1/2025 00:00`. Our default is `2025-05-01 00:00:00`.

It is a setting you control, and it applies to all three files at once. We would rather ship the
default you actually want than have you change it on first use.

**What we need from you:** either "the default is fine" or the exact format you need. If several
of your systems read these files and disagree about date format, tell us that too — it is the
kind of thing that is cheaper to know now.

---

Nothing here is urgent. Questions 3 and 4 are worth answering before the update reaches your
machine, because both are cheaper to act on now than after your files start filling.
