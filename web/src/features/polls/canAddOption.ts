/**
 * Whether the "Add an option" affordance renders at all (PL-5, `requirements.md` >
 * Permissions: "Add an option | yes | when `allow_member_options` | when
 * `allow_member_options`"). A pure predicate, split out from `PollsScreen.tsx` so the
 * role/flag/stage matrix is testable without rendering the whole screen — same pattern as
 * `map-suggestions/distanceOrder.ts`'s `distanceSortValue`.
 *
 * Absent, not disabled, when it would be refused: closed polls and the End stage both stop
 * scoring too (PL-17: "no disabled voting controls cluttering the screen"), and adding an
 * option is the same kind of write.
 */

export function canAddOption(
  poll: { status: 'open' | 'closed'; allow_member_options: boolean },
  isOrganiser: boolean,
  canMutate: boolean,
): boolean {
  if (!canMutate) return false // End stage — the server would refuse with 409 regardless
  if (poll.status !== 'open') return false
  return isOrganiser || poll.allow_member_options
}
