/**
 * The client half of mention markup (`design.md` > "Mention markup"): `@[Display Name]
 * (user:<uuid>)`, stored inline in the comment body. The server is the parser of record for
 * notifications (`server/app/services/mentions.py`, not this feature's concern) — this file
 * only needs to (a) render the markup as a token and (b) insert well-formed markup from the
 * `@` picker. Both directions use the same regex so they can never disagree on the format.
 */

export type MentionToken = { name: string; userId: string }

const MENTION_RE = /@\[([^\]]+)\]\(user:([0-9a-fA-F-]{36})\)/g

/** Splits a comment body into plain-text and mention segments, in order, for rendering. */
export function splitMentions(body: string): (string | MentionToken)[] {
  const parts: (string | MentionToken)[] = []
  let lastIndex = 0
  for (const match of body.matchAll(MENTION_RE)) {
    const start = match.index ?? 0
    if (start > lastIndex) parts.push(body.slice(lastIndex, start))
    parts.push({ name: match[1], userId: match[2] })
    lastIndex = start + match[0].length
  }
  if (lastIndex < body.length) parts.push(body.slice(lastIndex))
  return parts
}

/** Every mentioned user id in a body, per the same regex — used only for display-side
 * bookkeeping; the server remains authoritative for who actually gets notified. */
export function extractMentionIds(body: string): string[] {
  return [...body.matchAll(MENTION_RE)].map((m) => m[2])
}

/**
 * While composing, the text right before the cursor may be an in-progress mention
 * (`@partial`). Returns the query text (without the `@`) and where it starts, or `null` when
 * the cursor is not inside one — used to decide whether to show the picker and what to
 * filter it by.
 */
export function activeMentionQuery(text: string, cursor: number): { query: string; start: number } | null {
  const upToCursor = text.slice(0, cursor)
  const at = upToCursor.lastIndexOf('@')
  if (at === -1) return null
  const between = upToCursor.slice(at + 1)
  // A space (or a newline) ends the mention attempt — "@" followed by ordinary prose is not
  // a mention in progress.
  if (/[\s]/.test(between)) return null
  return { query: between, start: at }
}

/** Replaces the in-progress `@query` at `start`..`cursor` with well-formed mention markup,
 * returning the new text and where the cursor should land (right after the inserted token). */
export function insertMention(
  text: string,
  start: number,
  cursor: number,
  member: MentionToken,
): { text: string; cursor: number } {
  const markup = `@[${member.name}](user:${member.userId}) `
  const next = text.slice(0, start) + markup + text.slice(cursor)
  return { text: next, cursor: start + markup.length }
}
