# 01: Sign a full-version Activation Code and the machine stops asking for Meter Activation Codes

**What to build:** We sign an Activation Code that says nothing about meter activation, and
the operator on that machine adds a meter with a name, a transport and nothing else — the
Meter Activation Code field is not on the form, and the License card says the machine does
not need one. We sign an Activation Code that states the requirement, and that machine
behaves exactly as every machine does today: the field is there, required, and a create
without a valid code is refused.

Every Activation Code already issued keeps verifying, and reads as "not required".

Nothing about a meter already added changes, either way.

Source: `../spec.md`. Glossary terms **Meter Activation Requirement**, **Meter Activation
Code**, **Activation Code**, **Machine ID**, **Limited Mode** are in `CONTEXT.md`. The gate
this makes conditional is ADR 0019; the reason there is still no check at Update is
ADR 0005.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

## The shape

- [ ] The requirement is a **top-level field on the signed Activation Code payload**, beside
      the meter quota and the licensed model list — **never a feature key and never in the
      feature list**. The feature list names what the product may *do*; this names what the
      operator must *supply*, and the feature list carries a grandfathering rule this must
      not inherit
- [ ] **Unstated means not required.** An absent key and an explicit null are
      indistinguishable and both mean the same thing
- [ ] The **payload version is not bumped**. It is compared for exact equality, so a bump
      makes every Activation Code already signed fail as the wrong product
- [ ] The field is **not added to the required-field list**. That list is a membership test,
      and adding it there refuses every payload signed before today
- [ ] The payload builder in the **application** and the one in the **vendor CLI** both
      carry the field and stay byte-identical — the signature is taken over the canonical
      bytes, so a field in one and not the other makes nothing verify at all
- [ ] An Activation Code **signed before this change still verifies** and reads the field as
      absent, proven against the **real pre-change licence already pinned in the suite**,
      not a hand-built payload

## Reaching the request

- [ ] The verification result carries it, the license state carries it, and the license
      status endpoint exposes it — the path the licensed model list already takes
- [ ] The status endpoint exposes a **resolved boolean, never the raw value**. There is
      nothing for the browser to interpret here, only the rule "unstated means not
      required", and sending the raw value would put that rule in a second language
- [ ] The create-device handler reads the requirement from the **same license-state value**
      it already reads the meter quota and licensed models from — one evaluation per
      request, never cached (ADR 0001)

## The gate

- [ ] The Meter Activation Code check runs **only when the machine's requirement says so**
- [ ] It **keeps its position** — after the duplicate-serial check, before the device row is
      written, so a request that will be refused persists nothing
- [ ] The **request field becomes optional**. It is required today, so hiding it in the
      browser without this would make every full-version create fail validation
- [ ] A Meter Activation Code **supplied to a machine that does not demand one is still
      verified**, and stored when it verifies. A wrong Meter Serial, a wrong Machine ID and
      a tampered code are all still refused there. Ignoring a supplied code would write an
      unverified string into a column a later reader will assume was checked
- [ ] **No check is added at Update** — unlike the licensed model list, which needed one
      because a device could be created under a licensed model and edited onto an unlicensed
      one. No such bypass exists here: any Update whose probed Meter Serial differs from the
      stored one is already refused unconditionally (ADR 0005). **Write this reasoning into
      ADR 0019** — the two gates sit beside each other and the next reader will ask why one
      is enforced twice and the other once

## Devices already added

- [ ] **No new column and no migration.** A device row with no stored Meter Activation Code
      already means "this row needs none", and a machine whose requirement is switched on
      later must not reach back for a code its operator was never asked for
- [ ] A device added with no code **keeps working after the requirement is switched on**;
      a device added with one **keeps its stored code after the requirement is switched off**

## What the operator and the vendor see

- [ ] The Meter Activation Code field is **hidden** on a machine that does not require it —
      hidden, not disabled. A greyed control invites the question an absent one does not
- [ ] The **License card names the requirement**, beside the meter quota and the licensed
      models it already shows. The value has to reach the browser anyway for the form to
      hide the field, and this is the only place anyone can answer why two machines behave
      differently
- [ ] The **vendor CLI grows one flag** that states the requirement. Its absence is the full
      version, so the flag appears only on codes sold against a feature list

## The command a human actually signs through

The project's own **issue-an-Activation-Code command** is the one place a person decides
what a licence says. It passes extra flags through verbatim, so nothing in it becomes
false — but the omission it already had acquires a consequence it did not have before, and
this is the cheapest point to catch the mistake the whole risk rests on: **it catches it
before the code is generated, and it can ask a human, which the signing tool cannot.**

- [ ] Its **report step names the Meter Activation Requirement** of the code it just issued,
      beside the customer, machine, mode and expiry it already reports — so whoever signed
      it sees what they just sold rather than inferring it from what they typed
- [ ] When a **feature list is named and the requirement is not stated**, it **asks before
      signing** rather than proceeding. That single combination is the only way to give
      per-meter entitlement away by accident: a restricted licence signed the easy way
      silently stops demanding Meter Activation Codes, and nothing on the machine says so
- [ ] It **asks, it never refuses** — an Activation Code granting every feature while still
      demanding Meter Activation Codes is a licence we may genuinely want to sell
- [ ] It **stays silent when no feature list is named.** That is the full version, signed
      exactly as intended, and asking there would train the seller to click through the
      question

## Documents this change makes wrong

- [ ] **ADR 0019 is amended in place, keeping its title.** It is written as an unconditional
      rule and has an existing amendment section for exactly this. The amendment says who
      decides whether the gate applies, and why there is still no check at Update
- [ ] The **comment above the sellable feature keys** claims no licence has been issued and
      reasons from that. Two machines run on issued Activation Codes. Correct it to say
      codes are in the field, so a new key's absence must preserve today's behaviour
- [ ] The **record of a past signing** that calls a customer-site demo machine "this
      machine" is corrected

## Testing

- [ ] Tests sit at the **two existing seams — no new seam**: the application's HTTP seam
      through the shared test clients and the fixture that activates a fresh licence (which
      gains one keyword argument), and the vendor CLI seam where the feature-list and
      model-list flags are already tested
- [ ] **The existing test that proves a missing code is refused must be given a licence that
      states the requirement — never deleted.** It is the only proof the gate still works at
      all, and it is the one test this change breaks
- [ ] The license status endpoint is proven to report the resolved boolean **both ways**
- [ ] **Gate**: `ruff format --check .` + `ruff check .` + `python -m pytest -n auto` in
      `app/`; `pnpm lint` + `pnpm build` in `web/`. The **full** suite, never a subset
- [ ] **Output Parity vs v1**: not applicable — v1 has no Meter Activation Code at all. Say
      so in the report
- [ ] **Real-meter read**: not applicable — nothing here touches acquisition, though
      creating a device still probes the meter for its Meter Serial as it always has. Say so
