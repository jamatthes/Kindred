import { describe, expect, it } from 'vitest'
import { activeMentionQuery, extractMentionIds, insertMention, splitMentions } from './mentions'

const UUID = '11111111-1111-1111-1111-111111111111'

describe('splitMentions', () => {
  it('splits plain text around mention markup, preserving order', () => {
    const body = `Hey @[Jibby](user:${UUID}) can you check this?`
    const parts = splitMentions(body)
    expect(parts).toEqual(['Hey ', { name: 'Jibby', userId: UUID }, ' can you check this?'])
  })

  it('returns the whole string as one part when there is no mention', () => {
    expect(splitMentions('no mentions here')).toEqual(['no mentions here'])
  })

  it('handles multiple mentions', () => {
    const body = `@[A](user:${UUID}) and @[B](user:${UUID})`
    const parts = splitMentions(body)
    expect(parts).toHaveLength(3)
    expect(parts[0]).toEqual({ name: 'A', userId: UUID })
    expect(parts[2]).toEqual({ name: 'B', userId: UUID })
  })

  it('renders malformed mention markup as plain text', () => {
    const body = 'Hey @[Broken](user:not-a-uuid) nope'
    expect(splitMentions(body)).toEqual([body])
  })
})

describe('extractMentionIds', () => {
  it('extracts every well-formed mention uuid, including duplicates', () => {
    const body = `@[A](user:${UUID}) @[A again](user:${UUID})`
    expect(extractMentionIds(body)).toEqual([UUID, UUID])
  })

  it('returns nothing for a mention of a malformed uuid', () => {
    expect(extractMentionIds('@[X](user:nope)')).toEqual([])
  })
})

describe('activeMentionQuery', () => {
  it('detects an in-progress mention right before the cursor', () => {
    const text = 'Hey @jib'
    expect(activeMentionQuery(text, text.length)).toEqual({ query: 'jib', start: 4 })
  })

  it('returns null when there is no @ before the cursor', () => {
    expect(activeMentionQuery('just text', 5)).toBeNull()
  })

  it('returns null once a space ends the mention attempt', () => {
    expect(activeMentionQuery('Hey @jib ', 9)).toBeNull()
  })

  it('is scoped to the cursor position, not the whole string', () => {
    // Cursor sits right after "@a" — the "@later" after it is irrelevant.
    const text = '@a text @later'
    expect(activeMentionQuery(text, 2)).toEqual({ query: 'a', start: 0 })
  })
})

describe('insertMention', () => {
  it('replaces the in-progress @query with well-formed markup and returns the new cursor', () => {
    const text = 'Hey @jib, look at this'
    const start = 4
    const cursor = 8 // end of "@jib"
    const { text: next, cursor: nextCursor } = insertMention(text, start, cursor, {
      name: 'Jibby',
      userId: UUID,
    })
    expect(next).toBe(`Hey @[Jibby](user:${UUID}) , look at this`)
    expect(next.slice(0, nextCursor)).toBe(`Hey @[Jibby](user:${UUID}) `)
  })
})
