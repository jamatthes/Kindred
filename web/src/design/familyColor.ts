/**
 * The one function that resolves a family's colour to a CSS colour string.
 *
 * `plan/features/families/design.md` > "Family colour palette" (2026-08-11 ruling): a family
 * holds exactly one of a palette slot (`color`, 1-24) or an overflow custom hex
 * (`color_custom`, set only once every slot on the trip is taken). Every rendering call site —
 * `IdentityBadge`'s ring, map pins, family cards, the presence stack — goes through this
 * helper so nothing branches on slot-vs-custom itself; a new call site cannot forget the
 * distinction because it never has to know about it.
 */

export type FamilyColorish = {
  color: number | null
  color_custom: string | null
}

/** `var(--family-N)` for a palette slot, the raw hex for a custom colour, or `null` when the
 * family (or the caller) has neither — e.g. someone with no family yet. */
export function familyColor(family: FamilyColorish | null | undefined): string | null {
  if (!family) return null
  if (family.color != null) return `var(--family-${family.color})`
  if (family.color_custom) return family.color_custom
  return null
}
