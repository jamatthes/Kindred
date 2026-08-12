/**
 * DistanceChip — the five states, duration-first formatting, and the rule this feature's
 * own docblock names as the one worth enforcing mechanically: never the preference ramp.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DistanceChip } from './DistanceChip'
import { formatDistanceMeters, formatDuration } from './format'
import type { DistanceOut } from '../../app/types'
// Vite's `?raw` import (declared by `vite/client`, already in tsconfig's `types`) — reads
// this feature's own CSS as a plain string, no Node `fs` typings needed in a browser-target
// tsconfig.
import distancesCss from './distances.css?raw'

function distance(overrides: Partial<DistanceOut> = {}): DistanceOut {
  return {
    family_id: 'fam-1',
    family_name: 'Parkers',
    family_color: 2,
    status: 'ok',
    duration_s: 9600, // 2h 40m
    distance_m: 210_000,
    is_estimate: false,
    computed_at: '2027-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('DistanceChip — ok state', () => {
  it('reads duration first, then the family name', () => {
    render(<DistanceChip distance={distance()} />)
    expect(screen.getByText('2h 40m from Parkers')).toBeInTheDocument()
  })

  it('formats under an hour without the hours segment', () => {
    render(<DistanceChip distance={distance({ duration_s: 35 * 60 })} />)
    expect(screen.getByText('35m from Parkers')).toBeInTheDocument()
  })
})

describe('DistanceChip — estimate state', () => {
  it('shows distance only, muted, explicitly marked as pending', () => {
    const { container } = render(
      <DistanceChip distance={distance({ status: 'pending', duration_s: null, distance_m: 48_000, is_estimate: true })} />,
    )
    const text = container.querySelector('.dist-chip__text')?.textContent ?? ''
    expect(text).toContain('~48.0 km from Parkers')
    expect(text).toContain('· driving time pending')
    // No duration is ever shown for an estimate.
    expect(text).not.toMatch(/^\d+h|^\d+m/)
  })

  it('carries a tooltip explaining the fallback', () => {
    render(<DistanceChip distance={distance({ status: 'pending', duration_s: null, is_estimate: true })} />)
    expect(screen.getByTitle(/straight-line estimate/)).toBeInTheDocument()
  })
})

describe('DistanceChip — no_route state', () => {
  it('reads as information, not an error, and mentions ferries/flights in the tooltip', () => {
    render(<DistanceChip distance={distance({ status: 'no_route', duration_s: null, distance_m: null })} />)
    expect(screen.getByText('No driving route from Parkers')).toBeInTheDocument()
    expect(screen.getByTitle(/ferry or flight/)).toBeInTheDocument()
  })

  it('appends the region centroid note for a region destination', () => {
    render(<DistanceChip distance={distance({ status: 'no_route', duration_s: null, distance_m: null })} isRegion />)
    expect(screen.getByTitle(/to the centre of this region/)).toBeInTheDocument()
  })
})

describe('DistanceChip — failed state', () => {
  it('is quiet, with no retry for an ordinary member', () => {
    render(<DistanceChip distance={distance({ status: 'failed', duration_s: null, distance_m: null })} />)
    expect(screen.getByText('Distance unavailable')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })

  it('offers a retry to an organiser, calling the recompute handler', () => {
    const onRetry = vi.fn()
    render(<DistanceChip distance={distance({ status: 'failed', duration_s: null, distance_m: null })} canRetry onRetry={onRetry} />)
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalled()
  })
})

describe('DistanceChip — no_home state', () => {
  it('is actionable, offering a link to set the address', () => {
    const onSetHome = vi.fn()
    render(<DistanceChip distance={distance({ status: 'no_home', duration_s: null, distance_m: null })} onSetHome={onSetHome} />)
    expect(screen.getByText('Home address not set')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Set it' }))
    expect(onSetHome).toHaveBeenCalled()
  })
})

describe('DistanceChip — colour never carries meaning alone', () => {
  it('every state pairs its class with visible text (not an icon-only chip)', () => {
    const states: DistanceOut['status'][] = ['ok', 'pending', 'no_route', 'failed', 'no_home']
    for (const status of states) {
      const { unmount, container } = render(
        <DistanceChip distance={distance({ status, duration_s: status === 'ok' ? 60 : null, is_estimate: status === 'pending' })} />,
      )
      expect(container.querySelector('.dist-chip__text')?.textContent?.trim()).not.toBe('')
      unmount()
    }
  })
})

describe('DistanceChip — never the preference ramp', () => {
  it('renders with no --scale-pref custom property on any element', () => {
    const states: DistanceOut['status'][] = ['ok', 'pending', 'no_route', 'failed', 'no_home']
    for (const status of states) {
      const { container, unmount } = render(
        <DistanceChip distance={distance({ status, duration_s: status === 'ok' ? 60 : null, is_estimate: status === 'pending' })} />,
      )
      for (const el of container.querySelectorAll<HTMLElement>('*')) {
        expect(el.getAttribute('style') ?? '').not.toMatch(/scale-pref/)
        expect(el.getAttribute('class') ?? '').not.toMatch(/scale-pref|pref-ramp/)
      }
      unmount()
    }
  })

  it('the component\'s own CSS source never references --scale-pref (design.md\'s explicit rule)', () => {
    expect(distancesCss).not.toMatch(/--scale-pref/)
  })
})

describe('format helpers', () => {
  it('formatDuration matches the chip\'s own text', () => {
    expect(formatDuration(9600)).toBe('2h 40m')
    expect(formatDuration(35 * 60)).toBe('35m')
    expect(formatDuration(0)).toBe('0m')
  })

  it('formatDistanceMeters switches to km at 1000m', () => {
    expect(formatDistanceMeters(800)).toBe('800 m')
    expect(formatDistanceMeters(48_000)).toBe('48.0 km')
  })
})
