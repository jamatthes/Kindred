/**
 * canAddOption — the role/flag/stage matrix from `requirements.md`'s Permissions table:
 * "Add an option | yes | when allow_member_options | when allow_member_options", plus the
 * closed-poll and End-stage cases that are absent, not disabled (PL-17).
 */

import { describe, expect, it } from 'vitest'
import { canAddOption } from './canAddOption'

const OPEN = { status: 'open' as const, allow_member_options: false }
const OPEN_MEMBER_OPTIONS = { status: 'open' as const, allow_member_options: true }
const CLOSED = { status: 'closed' as const, allow_member_options: true }

describe('canAddOption', () => {
  it('the organiser can always add an option to an open poll, flag or no flag', () => {
    expect(canAddOption(OPEN, true, true)).toBe(true)
    expect(canAddOption(OPEN_MEMBER_OPTIONS, true, true)).toBe(true)
  })

  it('a member can add an option only when allow_member_options is true', () => {
    expect(canAddOption(OPEN, false, true)).toBe(false)
    expect(canAddOption(OPEN_MEMBER_OPTIONS, false, true)).toBe(true)
  })

  it('nobody can add an option to a closed poll, organiser included', () => {
    expect(canAddOption(CLOSED, true, true)).toBe(false)
    expect(canAddOption(CLOSED, false, true)).toBe(false)
  })

  it('nobody can add an option once the trip cannot mutate (End stage), organiser included', () => {
    expect(canAddOption(OPEN, true, false)).toBe(false)
    expect(canAddOption(OPEN_MEMBER_OPTIONS, false, false)).toBe(false)
  })
})
