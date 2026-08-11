/**
 * `/styleguide` — the map shell (`plan/features/map-suggestions/design.md` pre-build,
 * `feat/m3-map-shell`): `FakeMapProvider` with sample pins of every category, a boundary
 * polygon at a few preference tints, and the popover card — in both themes, per the same
 * side-by-side convention as the tokens and pickers sections above.
 *
 * Everything here is `web/src/features/map/`'s real components, not a mockup: the pins
 * really are `MapCanvas` + `FakeMapProvider`, so a visual regression in the actual map
 * shell shows up on this page.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { MapCanvas } from '../features/map/MapCanvas'
import { createFakeMapProvider } from '../features/map/FakeMapProvider'
import { PopoverCard } from '../features/map/PopoverCard'
import { RegionPolygon } from '../features/map/RegionPolygon'
import type { MarkerSpec, PolygonSpec, SuggestionStatus } from '../features/map/types'
import './StyleguideMap.css'

function Panel({ theme, children }: { theme: 'light' | 'dark'; children: ReactNode }) {
  return (
    <div className="k-sg-panel" data-theme={theme}>
      <span className="k-sg-caption">{theme}</span>
      {children}
    </div>
  )
}

const CORNWALL = { lat: 50.4, lng: -4.7 }

const pinMarkers: MarkerSpec[] = [
  { id: 'p-accom', kind: 'suggestion', position: { lat: 50.42, lng: -4.74 }, category: 'accommodation', status: 'shortlisted', familyColor: 1 },
  { id: 'p-activity', kind: 'suggestion', position: { lat: 50.39, lng: -4.68 }, category: 'activity', status: 'approved', familyColor: 6, selected: true },
  { id: 'p-meal', kind: 'suggestion', position: { lat: 50.41, lng: -4.65 }, category: 'meal', status: 'proposed', familyColor: 5 },
  { id: 'p-region', kind: 'suggestion', position: { lat: 50.44, lng: -4.71 }, category: 'region', status: 'rejected', familyColor: 3 },
  { id: 'p-scheduled', kind: 'suggestion', position: { lat: 50.38, lng: -4.73 }, category: 'accommodation', status: 'scheduled', familyColor: 2 },
  { id: 'p-no-family', kind: 'suggestion', position: { lat: 50.4, lng: -4.62 }, category: 'meal', status: 'proposed', familyColor: null },
  { id: 'p-live', kind: 'live', position: { lat: 50.405, lng: -4.7 }, familyColor: 5, initials: 'Ji', name: 'Jibby (Jiangs)', online: true },
  { id: 'p-live-off', kind: 'live', position: { lat: 50.415, lng: -4.68 }, familyColor: 6, initials: 'St', name: 'Stu (Riveras)', online: false },
]

const boundaryPolygon: PolygonSpec[] = [
  {
    id: 'region-boundary',
    shape: 'polygon',
    path: [
      { lat: 50.46, lng: -4.85 },
      { lat: 50.46, lng: -4.55 },
      { lat: 50.32, lng: -4.55 },
      { lat: 50.32, lng: -4.85 },
    ],
    prefScore: 8,
    boundarySource: 'osm',
  },
]

function MapDemo() {
  return (
    <div className="k-sg-map__canvas">
      <MapCanvas
        createProvider={createFakeMapProvider}
        center={CORNWALL}
        zoom={13}
        markers={pinMarkers}
        polygons={boundaryPolygon}
      />
      <span className="k-sg-map__attr">Boundary © OpenStreetMap contributors</span>
    </div>
  )
}

/** Standalone (non-provider) region tints, laid out in a row, so every ramp step used by
 *  the map and the poll `HeatMatrix` can be eyeballed together without needing eight
 *  separate `MapCanvas` instances. */
function TintStrip() {
  const scores: (number | null)[] = [0, 3, 5, 7, 10, null]
  return (
    <div className="k-sg-map__tints">
      {scores.map((score, i) => (
        <div className="k-sg-map__tint-cell" key={i}>
          <RegionPolygon
            id={`tint-${i}`}
            shape="polygon"
            width={72}
            height={56}
            points={[
              { x: 6, y: 6 },
              { x: 66, y: 10 },
              { x: 60, y: 50 },
              { x: 10, y: 46 },
            ]}
            prefScore={score}
          />
          <span className="k-sg-map__tint-label">{score === null ? 'no score' : score}</span>
        </div>
      ))}
    </div>
  )
}

function PopoverDemo() {
  const [status] = useState<SuggestionStatus>('shortlisted')
  return (
    <div className="k-sg-map__popovers">
      <PopoverCard
        title="Harbour House Cottages"
        category="accommodation"
        status={status}
        voteSummary={
          <div className="k-sg-map__vote-demo">
            <span className="k-sg-map__vote-avg">8.2</span>
            <div className="k-sg-map__vote-bar">
              <i style={{ width: '82%' }} />
            </div>
            <span className="k-sg-map__vote-count">6 votes</span>
          </div>
        }
        commentCount={3}
        distanceChips={
          <div className="k-sg-map__dist-demo">
            <span className="k-sg-map__dchip">4h 05</span>
            <span className="k-sg-map__dchip">5h 20</span>
          </div>
        }
        onDetails={() => {}}
        onOpenInMaps={() => {}}
      />
      <PopoverCard title="Coasteering" category="activity" status="proposed" />
    </div>
  )
}

export function StyleguideMap() {
  return (
    <div className="k-sg-map">
      <p className="k-styleguide__section-title">Map shell — pins, regions, popover</p>
      <p className="k-sg-map__note">
        `FakeMapProvider` behind `MapCanvas`: category icons, per-family colour accents,
        status treatment (never colour alone — each status also carries a distinct glyph or
        muting), live-location markers reusing the identity badge, and a named-locality
        region boundary with OSM attribution.
      </p>
      <div className="k-sg-panels">
        {(['light', 'dark'] as const).map((theme) => (
          <Panel theme={theme} key={theme}>
            <MapDemo />
          </Panel>
        ))}
      </div>

      <p className="k-styleguide__section-title">Preference ramp — region tint by score</p>
      <div className="k-sg-panels">
        {(['light', 'dark'] as const).map((theme) => (
          <Panel theme={theme} key={theme}>
            <TintStrip />
          </Panel>
        ))}
      </div>

      <p className="k-styleguide__section-title">Popover card</p>
      <div className="k-sg-panels">
        {(['light', 'dark'] as const).map((theme) => (
          <Panel theme={theme} key={theme}>
            <PopoverDemo />
          </Panel>
        ))}
      </div>
    </div>
  )
}
