/**
 * Pure formatting helpers for distance text — duration first, per `design.md` D1: "duration
 * is what people actually care about on a drive." Kept separate from `DistanceChip` so the
 * sort comparator and any other consumer can format identically without importing a
 * component.
 */

/** "2h 40m" for an hour or more, "35m" under an hour. Never a bare number of seconds. */
export function formatDuration(seconds: number): string {
  const totalMinutes = Math.round(seconds / 60)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`
}

/** "48 km" or "800 m" — no unit invented, no fake precision past one decimal. */
export function formatDistanceMeters(metres: number): string {
  return metres >= 1000 ? `${(metres / 1000).toFixed(1)} km` : `${Math.round(metres)} m`
}
