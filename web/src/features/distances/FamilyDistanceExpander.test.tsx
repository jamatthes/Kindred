/**
 * FamilyDistanceExpander — own family shown immediately (D1), every family reachable via
 * the expander (D3), families without a geocoded home listed rather than omitted.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FamilyDistanceExpander } from './FamilyDistanceExpander'
import type { DistanceOut } from '../../app/types'

function rows(): DistanceOut[] {
  return [
    { family_id: 'own', family_name: 'Us', family_color: 1, status: 'ok', duration_s: 1800, distance_m: 30_000, is_estimate: false, computed_at: null },
    { family_id: 'other-1', family_name: 'Parkers', family_color: 2, status: 'ok', duration_s: 3600, distance_m: 60_000, is_estimate: false, computed_at: null },
    { family_id: 'other-2', family_name: 'Hendersons', family_color: 3, status: 'no_home', duration_s: null, distance_m: null, is_estimate: false, computed_at: null },
  ]
}

describe('FamilyDistanceExpander', () => {
  it('shows the own-family chip immediately, without expanding', () => {
    render(<FamilyDistanceExpander distances={rows()} ownFamilyId="own" suggestionType="accommodation" />)
    expect(screen.getByText(/30m from Us/)).toBeInTheDocument()
    expect(screen.queryByText(/Parkers/)).not.toBeInTheDocument()
  })

  it('reveals every other family on expand, including one with no home set — never omitted', () => {
    render(<FamilyDistanceExpander distances={rows()} ownFamilyId="own" suggestionType="accommodation" />)
    fireEvent.click(screen.getByRole('button', { name: /Show all 3 families/ }))
    expect(screen.getByText(/from Parkers/)).toBeInTheDocument()
    expect(screen.getByText('Home address not set')).toBeInTheDocument()
  })

  it('falls back to the first row when the own family id is not found (defensive)', () => {
    render(<FamilyDistanceExpander distances={rows()} ownFamilyId={null} suggestionType="accommodation" />)
    expect(screen.getByText(/from Us/)).toBeInTheDocument()
  })
})
