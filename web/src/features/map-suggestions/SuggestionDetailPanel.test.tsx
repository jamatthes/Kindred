/**
 * Permission-gated UI (`requirements.md` > Permissions): status controls render only for the
 * owner/organiser, and edit/delete only for the author, their family's head/spouse, or the
 * owner/organiser. Also covers grouped children rendering inside the parent's detail panel
 * (`design.md` S8) and the open-in-maps deep link's region-vs-point branch.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Suggestion, User } from '../../app/types'

vi.mock('../../app/ui/toastContext', () => ({ useToast: () => vi.fn() }))
vi.mock('./placesClient', () => ({ placesAvailable: () => false, getPlaceDetails: vi.fn() }))
vi.mock('./api', () => ({
  suggestionsApi: { linkPreview: vi.fn(), setStatus: vi.fn(), remove: vi.fn() },
}))

let mockUser: Partial<User> | null = null
vi.mock('../../app/session', () => ({ useSession: () => ({ user: mockUser }) }))

let mockStage = { canMutate: true, stage: 'planning', isPlanning: true, isHoliday: false, isEnd: false }
vi.mock('../../app/useStage', () => ({ useStage: () => mockStage }))

const { SuggestionDetailPanel } = await import('./SuggestionDetailPanel')

function suggestion(overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id: 's1',
    type: 'accommodation',
    title: 'Harbour House',
    notes: null,
    status: 'proposed',
    created_by: { user_id: 'author-1', display_name: 'Alex', family_id: 'fam-1', family_color: 3 },
    lat: 50.4,
    lng: -4.7,
    geometry_geojson: null,
    place_id: null,
    place_snapshot: null,
    external_url: null,
    vote_summary: null,
    comment_count: 0,
    distances: [],
    children: [],
    created_at: '2027-01-01T00:00:00Z',
    updated_at: '2027-01-01T00:00:00Z',
    ...overrides,
  }
}

function renderPanel(suggestionOverrides: Partial<Suggestion> = {}) {
  render(
    <SuggestionDetailPanel
      suggestion={suggestion(suggestionOverrides)}
      onChanged={vi.fn()}
      onDeleted={vi.fn()}
    />,
  )
}

describe('SuggestionDetailPanel — permission-gated controls', () => {
  it('shows no status or delete controls for a plain member viewing someone else\'s suggestion', () => {
    mockUser = { id: 'someone-else', is_owner: false, is_organiser: false, family: null }
    renderPanel()
    expect(screen.queryByRole('button', { name: /Shortlist|Approve|Reject/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('shows delete (but not status) for the suggestion\'s own author', () => {
    mockUser = { id: 'author-1', is_owner: false, is_organiser: false, family: null }
    renderPanel()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Shortlist|Approve|Reject/ })).not.toBeInTheDocument()
  })

  it('shows delete for the head of the author\'s own family', () => {
    mockUser = { id: 'head-1', is_owner: false, is_organiser: false, family: { id: 'fam-1', role: 'head', name: 'Smiths', color: 1, color_custom: null } }
    renderPanel()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('hides delete for the head of a different family', () => {
    mockUser = { id: 'outsider', is_owner: false, is_organiser: false, family: { id: 'fam-2', role: 'head', name: 'Others', color: 2, color_custom: null } }
    renderPanel()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('shows status controls and delete for an organiser regardless of family', () => {
    mockUser = { id: 'org-1', is_owner: false, is_organiser: true, family: null }
    renderPanel({ status: 'proposed' })
    expect(screen.getByRole('button', { name: 'Shortlist' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('offers "Reopen" only from the rejected status, not a forward transition (AdminStatusControls, voting-comments)', () => {
    mockUser = { id: 'org-1', is_owner: false, is_organiser: true, family: null }
    renderPanel({ status: 'rejected' })
    expect(screen.getByRole('button', { name: 'Reopen' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('hides mutating controls entirely when the stage is frozen (End), even for an organiser', () => {
    mockUser = { id: 'org-1', is_owner: false, is_organiser: true, family: null }
    mockStage = { canMutate: false, stage: 'end', isPlanning: false, isHoliday: false, isEnd: true }
    renderPanel()
    expect(screen.queryByRole('button', { name: /Shortlist|Approve|Reject/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    mockStage = { canMutate: true, stage: 'planning', isPlanning: true, isHoliday: false, isEnd: false }
  })
})

describe('SuggestionDetailPanel — grouped children (S8)', () => {
  it('lists grouped children inside the parent\'s panel, each individually selectable', () => {
    mockUser = { id: 'viewer', is_owner: false, is_organiser: false, family: null }
    renderPanel({
      children: [
        suggestion({ id: 'child-1', type: 'meal', title: 'Breakfast at the hotel' }),
        suggestion({ id: 'child-2', type: 'activity', title: 'Guided walk' }),
      ],
    })
    expect(screen.getByText('2 things here')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Breakfast at the hotel/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Guided walk/ })).toBeInTheDocument()
  })
})

describe('SuggestionDetailPanel — open in Google Maps', () => {
  it('uses a search deep link for a region and a directions link with place_id for a point', () => {
    mockUser = { id: 'viewer', is_owner: false, is_organiser: false, family: null }
    renderPanel({ type: 'region', lat: 50.1, lng: -4.2 })
    expect(screen.getByRole('link', { name: 'Open in Google Maps' })).toHaveAttribute(
      'href',
      'https://www.google.com/maps/search/?api=1&query=50.1,-4.2',
    )
  })

  it('carries destination_place_id for a suggestion with a place_id', () => {
    mockUser = { id: 'viewer', is_owner: false, is_organiser: false, family: null }
    renderPanel({ place_id: 'ChIJabc', lat: 50.1, lng: -4.2 })
    expect(screen.getByRole('link', { name: 'Open in Google Maps' })).toHaveAttribute(
      'href',
      'https://www.google.com/maps/dir/?api=1&destination=50.1,-4.2&destination_place_id=ChIJabc',
    )
  })
})
