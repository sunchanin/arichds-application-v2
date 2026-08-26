/**
 * Why a license was refused, in words a site engineer can act on.
 *
 * Its own module rather than an export from `pages/Activation.tsx` because
 * **two surfaces take an Activation Code** and neither owns the other: the
 * first-run / Limited Mode gate (`pages/Activation.tsx`) and the License card
 * on Settings (`components/LicenseCard.tsx`, issue 011). A `components/` file
 * importing from `pages/` would be the only such import in the SPA, and
 * exporting a non-component from a page file costs a react-refresh warning on
 * a lint run the project treats as half its web gate.
 *
 * The keys are the API's own `error.reason` codes
 * (`app/src/arichds/licensing/activation_code.py`).
 *
 * **The map is shared; the fallbacks are not.** `Activation.tsx` wraps this
 * with Limited-Mode-flavoured fallbacks, which are true on the gate screen and
 * false on an active machine being told a *new* code was rejected — so the
 * License card supplies its own. Keep it that way.
 */
export const REASON_TEXT: Record<string, string> = {
  NO_LICENSE: "This machine has not been activated yet.",
  MALFORMED: "That code could not be read. Copy the whole line and try again.",
  INVALID_SIGNATURE: "That code failed its signature check. It may have been altered in transit.",
  WRONG_MACHINE: "That code was issued for a different machine. Check the Machine ID you sent the vendor.",
  EXPIRED: "That license has expired. Ask the vendor for a renewal.",
  WRONG_PRODUCT: "That code is not an ARICHDS Activation Code.",
  MACHINE_ID_UNAVAILABLE: "This machine's ID could not be read, so no license can be verified.",
};
