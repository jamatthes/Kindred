/**
 * RegionPolygon — a region: dashed `--color-*` boundary, translucent fill, tinted by the
 * preference ramp when a poll/vote score exists.
 *
 * Circle and polygon regions render identically per `plan/features/map-suggestions/
 * design.md` ("both render identically as a dashed outline with a tinted fill") — this
 * component takes already-projected pixel geometry (a provider projects lat/lng; this
 * component only draws), so the same SVG path logic serves both shapes: a circle is
 * expressed as an SVG `<circle>`, a polygon as a closed `<path>`.
 */

import { prefTintClass } from './prefTint'
import type { Point } from './projection'
import './RegionPolygon.css'

export type RegionPolygonProps = {
  id: string
  /** Container size in pixels — the SVG viewBox. */
  width: number
  height: number
  shape: 'polygon' | 'circle'
  /** Polygon vertices in pixel space. Required when `shape === 'polygon'`. */
  points?: Point[]
  /** Circle centre in pixel space. Required when `shape === 'circle'`. */
  center?: Point
  radiusPx?: number
  prefScore?: number | null
  boundarySource?: 'osm' | 'drawn'
  selected?: boolean
  onClick?: (id: string) => void
}

function polygonPath(points: Point[]): string {
  if (points.length === 0) return ''
  const [first, ...rest] = points
  return `M ${first.x} ${first.y} ` + rest.map((p) => `L ${p.x} ${p.y}`).join(' ') + ' Z'
}

export function RegionPolygon({
  id,
  width,
  height,
  shape,
  points,
  center,
  radiusPx,
  prefScore,
  boundarySource,
  selected,
  onClick,
}: RegionPolygonProps) {
  const tintClass = prefTintClass(prefScore)
  const className = ['k-region', tintClass, selected ? 'is-selected' : ''].filter(Boolean).join(' ')
  const shared = {
    className,
    onClick: () => onClick?.(id),
    'data-testid': 'region-polygon',
    'data-shape': shape,
    'data-boundary-source': boundarySource ?? 'drawn',
    'data-pref-score': prefScore ?? undefined,
  } as const

  return (
    <svg
      className="k-region-svg"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
    >
      {shape === 'circle' && center && radiusPx !== undefined ? (
        <circle cx={center.x} cy={center.y} r={radiusPx} {...shared} />
      ) : (
        <path d={polygonPath(points ?? [])} {...shared} />
      )}
    </svg>
  )
}
