# Spec — the full version adds meters without a Meter Activation Code

Grilled 2026-09-09, 16 questions over 6 rounds. Phase 2 of the requirements round
(`docs/REMAKE-PLAN.md` §7.4, requirement E1). Source brief:
`.scratch/arichds-full-version/requirements.md`.

## Problem Statement

On every machine we ship, adding a meter means typing a **Meter Activation Code** — a
signed string the vendor issues for that one Meter Serial on that one Machine ID. The
operator has to stop, send us the serial, wait for a code, paste it, and only then can
they create the device.

The customer buying the **full version** does not want that step. They are buying the
whole product for a site they run themselves, and the per-meter gate buys them nothing:
they are not being sold meters one at a time. On a site with twelve meters it is twelve
round trips to us before anyone can start reading anything.

There is no way to express this today. The gate is unconditional — it applies to every
machine, whatever its Activation Code says.

## Solution

The **Meter Activation Requirement** becomes a property of the machine's own
**Activation Code**, sitting beside the meter quota and the licensed model list.

When we sell the full version we sign an Activation Code that says nothing about it, and
that machine's operator adds meters by name and transport alone — no code, no round trip,
and no field on the form asking for one. When we sell a licence against a named feature
list we say so on the code, and that machine behaves exactly as every machine does today.

The operator can see which kind of machine they are on: the License card names it, beside
the meter quota and the licensed models it already shows.

Nothing about an already-added meter changes. A meter added without a code keeps working
if the requirement is later switched on; a meter added with one keeps its code if the
requirement is later switched off.

## User Stories

1. As an operator on a full-version machine, I want to add a meter without a Meter Activation Code, so that I can commission a site without a round trip to the vendor for every meter.
2. As an operator on a full-version machine, I want the Meter Activation Code field to be absent from the Add-device form, so that I am not left wondering whether I have skipped something required.
3. As an operator on a machine sold against a feature list, I want the Meter Activation Code to still be demanded, so that nothing about my install changes when I take the next update.
4. As an operator, I want the License card to tell me whether this machine needs Meter Activation Codes, so that I can answer "why does that machine ask and this one doesn't" without calling anyone.
5. As an operator, I want that answer to sit beside the meter quota and the licensed models on the same card, so that everything my Activation Code decides is readable in one place.
6. As a vendor, I want a machine's Meter Activation Requirement to be carried on the signed Activation Code, so that it cannot be changed on the machine by anyone holding it.
7. As a vendor, I want to sign a full-version Activation Code by leaving the requirement unstated, so that the simplest signing command produces the product I sell most.
8. As a vendor, I want to state the requirement explicitly when I sell against a feature list, so that a customer who bought a subset still buys meters one at a time.
9. As a vendor, I want to be asked before signing when I name a feature list and say nothing about the requirement, so that the one combination that gives entitlement away by accident is stopped while it is still a question rather than a code in someone's hands.
9a. As a vendor, I want the code I just issued to report its Meter Activation Requirement back to me, so that I can see what I sold rather than infer it from what I typed.
10. As a vendor, I want every Activation Code already issued to keep verifying after this change, so that shipping the next build does not strand a machine in Limited Mode.
11. As a vendor, I want an Activation Code issued before this change to read as "not required", so that the rule is one sentence rather than a special case about when the code was signed.
12. As an operator whose machine already has meters, I want those meters to keep working whichever way the requirement is set, so that a licence renewal never costs me data.
13. As an operator on a machine whose requirement is switched on later, I want the meters I already added to keep working, so that tightening the rule is not retroactive.
14. As an operator on a machine whose requirement is switched off later, I want the codes already stored to stay stored, so that nothing is quietly discarded.
15. As an operator who supplies a Meter Activation Code on a machine that does not demand one, I want it verified rather than ignored, so that a wrong code is refused instead of silently kept.
16. As a maintainer, I want the "absent means not required" rule to live in the backend only, so that the browser never carries a second copy of it that can drift.
17. As a maintainer, I want the requirement expressed as a constraint beside the meter quota rather than as a feature key, so that nobody later moves it into the feature list and inherits the grandfathering behaviour it must not have.
18. As a maintainer, I want ADR 0019 to say who decides whether the gate applies, so that a future reader is not told the gate is unconditional when it is not.
19. As a maintainer, I want the record that says no licence has been issued corrected, so that the next person weighing a licence change starts from what is actually true.
20. As a maintainer, I want the test that proves a missing code is refused to keep existing, so that removing the demand from one kind of machine does not remove the proof it still works on the other.
21. As a maintainer, I want a licence signed before this change pinned in the test suite, so that the compatibility promise is checked by a real artefact rather than asserted in prose.
22. As a customer buying the full version, I want to be told this is what "full" includes, so that the difference between the two products is something I can read rather than discover.

## Implementation Decisions

**The shape: a constraint on the Activation Code, not a feature key**

- A new top-level field on the signed Activation Code payload, named for what it demands:
  **`require_meter_activation`**. It sits beside the meter quota, the feature list and the
  licensed model list.
- **It is deliberately not a feature key.** The feature list names what the product may
  *do*; this names what the operator must *supply*. Putting it in the feature list would
  also inherit that list's grandfathering rule, under which a licence signed without an
  explicit list picks up every key added later — which would decide this machine's gate by
  a mechanism nobody chose for it. The glossary entry for **Meter Activation Requirement**
  in `CONTEXT.md` says this out loud, because it is the mistake a future reader is most
  likely to make.
- **Absent means not required.** Every other constraint on a signed Activation Code already
  reads "unstated means unrestricted", and the full version is what we sell by stating
  nothing.

**The payload contract — the compatibility rules are load-bearing**

- **Do not bump the payload version.** The verifier compares it for exact equality, so a
  bump makes every Activation Code already signed fail as the wrong product.
- **Do not add the new field to the required-field list.** The licensed-model list was
  shipped the same way and for the same reason: a payload that predates the field must
  still verify, and the required-field list is a membership test that would refuse it.
- Read the field with a defaulting lookup plus a type check, exactly as the licensed-model
  list is read. An absent key and an explicit null are indistinguishable and both mean
  "not required" — that is the point, not an accident.
- The payload builder in the **application** and the one in the **vendor CLI** must stay
  byte-identical; the signature is taken over the canonical bytes, so a field added to one
  and not the other makes nothing verify. Both change together or neither does.

**Reaching the request**

- The verification result carries the new field; the license state carries it; the license
  status endpoint exposes it. This is the path the licensed-model list already takes.
- **The status endpoint exposes a resolved boolean, not the raw value.** The licensed-model
  list is exposed raw because the browser holds the catalog and can interpret "null means
  every model" itself. Here there is nothing to interpret — only the rule "unstated means
  not required" — and sending the raw value would put that rule in a second language. The
  raw value stays on the signed payload for anyone auditing it.
- The create-device handler reads the requirement off the same license-state value it
  already reads the meter quota and the licensed models from, in one evaluation per
  request. License state is never cached (ADR 0001).

**The gate**

- The Meter Activation Code check runs **only when the machine's requirement says so**. It
  keeps its position: after the duplicate-serial check, before the device row is written,
  so nothing is persisted by a request that will be refused.
- **The request field becomes optional.** It is required today, so hiding it in the browser
  without this change would make every full-version create fail validation.
- **A Meter Activation Code supplied to a machine that does not demand one is still
  verified**, and stored when it verifies. The requirement is "you need not supply one",
  never "you may not". Ignoring a supplied code would write an unverified string into the
  column a later reader will assume was checked.
- **No check is added at Update**, unlike the licensed-model list, which needed one because
  a device could be created under a licensed model and then edited onto an unlicensed one.
  No such bypass exists here: any Update whose probed Meter Serial differs from the stored
  one is already refused unconditionally (ADR 0005), so a device cannot be moved onto a
  different meter at all. **Write this reasoning into ADR 0019** — the two gates sit beside
  each other and the next reader will ask why one is enforced twice and the other once.
- **Limited Mode needs no design.** Device creation is under the guarded API prefix, so an
  invalid licence is refused before the handler runs; the gate is only ever reached from a
  license state already known valid.

**Devices already added**

- **No new column and no migration.** A device row with no stored Meter Activation Code
  already means "this row needs none" (ADR 0019 grandfathers rows that predate the gate),
  and a machine whose requirement is later switched on must not reach back for a code its
  operator was never asked for. The requirement is decided once, when the device is added.
- The consequence, accepted deliberately: nothing records *why* a given row has no code —
  whether it predates the gate or was added under the exemption. Distinguishing them would
  cost a column and a migration for an audit nobody has asked for.

**The vendor CLI**

- One flag that states the requirement. Its absence is the full version, so the flag is
  present only on the codes we sell against a feature list.
- **The signing tool itself gains no warning.** A warning there was considered and dropped
  in favour of the command below, which sits one layer above it — see Out of Scope.

**The command a human signs through**

- The project's own issue-an-Activation-Code command is **the one place a person decides
  what a licence says**. It passes extra flags through verbatim, so nothing in it becomes
  false — but the omission it already had now has a consequence, and this is where the
  mistake the whole risk rests on actually happens.
- Its **report names the Meter Activation Requirement** of the code just issued, beside the
  customer, machine, mode and expiry it already reports. Whoever signed it should see what
  they sold, not infer it from what they typed.
- When a **feature list is named and the requirement is not stated, it asks before
  signing.** It asks, it never refuses — an Activation Code granting every feature while
  still demanding Meter Activation Codes is a licence we may want to sell. And it stays
  silent when no feature list is named, because that is the full version signed exactly as
  intended; asking there would train the seller to click through the question.
- **This is strictly better than a warning inside the signing tool**, which is why that was
  dropped: it fires before the code exists rather than after, and it can put the question to
  a human, which a CLI printing to stderr cannot.

**The Add-device form and the License card**

- The Meter Activation Code field is **hidden** on machines that do not require it, not
  disabled. A greyed control invites the question an absent one does not.
- The resolved boolean reaches the Devices page as a prop threaded from wherever license
  status is already held, the way the licensed-model list already reaches the catalog
  dropdown.
- The License card gains a row naming the requirement, beside the meter quota and the
  licensed models. It costs nothing — the value has to reach the browser anyway for the
  form to hide the field — and it is the only place anyone can answer why two machines
  behave differently.

**Documents this change makes wrong**

- **ADR 0019** is amended in place, keeping its title. It is written as an unconditional
  rule and has an existing amendment section for exactly this. The amendment says who
  decides whether the gate applies, and why there is still no check at Update.
- **The comment above the sellable feature keys** claims no licence has been issued yet and
  reasons from that. Two machines are running on issued Activation Codes; the record that
  says one of them was "signed on this machine" describes a demo box at another site. Both
  are corrected, and the comment is rewritten to say what is now true: codes are in the
  field, so a new key's absence must preserve today's behaviour.
- **`CONTEXT.md`** already carries **Meter Activation Requirement** and the amended
  **Meter Activation Code** entry, written during the grill.

## Testing Decisions

A good test here asserts what an operator or a vendor can observe: whether creating a
device succeeds or is refused, what the license status says, what the signing tool prints.
None of them reach into how the payload is assembled or how the state is carried.

**Two existing seams, no new ones.**

- **The application's HTTP seam** — the shared test clients plus the fixture that activates
  a fresh licence on a running app. That fixture gains one keyword argument, and the seam
  then covers the whole path in one place: signing, verification, license state, the create
  gate, and the license status response. This is where the meter-activation tests already
  live, which is also where the one test that breaks lives.
- **The vendor CLI seam** — the fixture that drives the signing tool directly, where the
  feature-list and model-list flags are already tested. It covers the new flag, the payload
  it produces, and the warning.

**One reuse that is not a new seam:** the suite already pins a real Activation Code signed
before the licensed-model list existed, and asserts it still verifies. That same artefact
predates this field too, so one added assertion on the existing test proves the
compatibility promise against a real signed string rather than a hand-built payload. This
is the highest-value test in the change: it is the one that would catch a payload-version
bump or a required-field addition.

**What must be proven**

- A machine with the requirement unstated creates a device with no Meter Activation Code.
- A machine with the requirement stated refuses one — **this is the existing test that
  breaks.** It must be given a licence that states the requirement, never deleted. It is
  the only proof the gate still works at all.
- A supplied code is verified on both kinds of machine: a wrong serial, a wrong Machine ID
  and a tampered code are all still refused where the requirement is unstated.
- A verified code supplied to a machine that does not demand one is stored.
- A device added with no code keeps working after the requirement is switched on, and a
  device added with one keeps its stored code after the requirement is switched off.
- The license status endpoint reports the resolved boolean both ways.
- A licence signed with the flag and one signed without produce the intended payload values,
  and naming a feature list without stating the requirement warns.

**Frontend: a recorded gap, not an oversight.** Hiding the form field and the new License
card row are covered only by the frontend lint and build. The repository has no frontend
test runner and adding one is not part of this work — the same gap recorded for the
All-Meters View.

**The gate**, in every ticket: format check, lint and the full backend suite in parallel —
never a subset — plus lint and build on the web app. Output Parity against v1 does not
apply: v1 has no Meter Activation Code at all. A real-meter read does not apply either;
nothing here touches acquisition, though creating a device still probes the meter for its
serial as it always has.

## Out of Scope

- **Unlimited meters and the full model list.** "Full version" in the customer's words
  bundles those, but the meter quota and the licensed model list are separate fields on the
  Activation Code and stay separate. A full-version code sets all three; that is a signing
  decision, not one key that unlocks three things without the licence saying so.
- **Recording why a device row has no Meter Activation Code** — grandfathered or exempt.
  Costs a column and a migration for an audit nobody has asked for.
- **Re-checking the requirement after a device exists.** Decided once, at Create, matching
  ADR 0019.
- **A check at Update.** Argued above; the changed-serial refusal already closes the bypass.
- **Fixing that a device row with no Meter Serial can have one filled in by Update without a
  code.** That behaviour exists today, is unchanged by this work, and is neither improved
  nor worsened by it. Recorded here because it was found while reading the gate, not
  because this change touches it.
- **A warning inside the signing tool** when a feature list is named without stating the
  requirement. It was specced, drafted as its own ticket, and dropped: the
  issue-an-Activation-Code command catches the same mistake one layer higher, before the
  code is generated, and can ask rather than only print. Two gates on one mistake is worth
  having only if the tool is driven directly by someone not using that command — nobody
  does today.
- **Warning when a Meter Activation Code is issued for a machine that does not demand one.**
  It would be useful and it is not possible: the signing tool works from a Machine ID alone
  and never reads that machine's own Activation Code, so it cannot know. It becomes possible
  only with the licence registry below, which is itself out of scope.
- **A licence registry in the repository.** Two rounds of this grill were spent on "which
  Activation Codes are in the field", answered from a screenshot in the end. Keeping a
  record would have answered it in seconds, and it will be asked again — but it is a
  process change, not this feature.
- **Reissuing Activation Codes to the two machines already running.** Both are demos,
  confirmed by the owner. Under the chosen polarity they stop requiring Meter Activation
  Codes when they next take a build, which is the intended behaviour for a demo opened as
  full.
- **The four un-driven meter models, the export files, and the Special Days import.** Later
  phases with their own grills.
- **A frontend test runner.**

## Further Notes

**One risk the owner accepted, recorded rather than argued again.** The chosen polarity
means a licence sold against a feature list needs the flag added by hand every time, and
forgetting it gives per-meter entitlement away **silently** — the machine simply stops
asking for codes and nobody is told. The opposite polarity would have failed loudly instead
(a customer calling to ask why they still have to type codes). The owner chose this
direction because unstated-means-unrestricted is how every other constraint on the
Activation Code already reads, and because nothing currently in the field is a paying
install. The question the issue-an-Activation-Code command now asks exists to give that
silent failure a voice at the one moment it can be caught — before the code exists, put to a
person rather than printed past them. If a future reader is weighing this again, the trade is: consistency of
the payload's own philosophy, against a default that is safe when someone forgets.

**Why the customer's own words are not the design.** The customer asked for a "full
version". That phrase bundles three separable things — every feature, every meter, every
model — plus a fourth that is not a feature at all, the per-meter gate. Enabling every
feature was already possible before this work and would not have removed the gate, because
the gate is not a feature. This spec builds only the fourth thing; the other three are
signing choices that already exist.

**Two records in the repository were wrong, and they cost this grill two rounds.** Every
place that discusses the sellable feature keys states that no licence has been issued, and
the one record of a signing calls a customer-site demo box "this machine". Working from
those, the grill concluded twice that the field was empty. The truth came from a screenshot
of a License card inside the customer's own requirements workbook. Correcting the records
is in scope above; the lesson worth carrying is that the licence question is the one the
repository is least equipped to answer about itself.
