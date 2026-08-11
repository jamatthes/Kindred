/**
 * `/styleguide` — chart widget gallery.
 *
 * Renders every widget in `web/src/charts/` with realistic sample data (a York/Cornwall
 * poll, matching `design-preview/charts.html` and `design-preview/screen-polls.html`),
 * plus each widget's empty and single-point states. A plain, unlinked, authenticated
 * route (DS-13) — no Storybook dependency, page-scoped theme toggle so both themes can be
 * compared without touching the account preference.
 *
 * This page covers the *chart* portion of the design-system styleguide only; the token,
 * primitive, and form-state sections are a separate track's Phase 8 work.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { AvgBar } from './AvgBar'
import { SpreadDots } from './SpreadDots'
import { HeatMatrix } from './HeatMatrix'
import { DistributionStrip } from './DistributionStrip'
import { MiniBar, Sparkline } from './MiniBar'
import type { ChartMember, ChartOption } from './types'
import './Styleguide.css'

const members: ChartMember[] = [
  { id: 'm1', label: 'Ana R.' },
  { id: 'm2', label: 'Tom P.' },
  { id: 'm3', label: 'Mei J.' },
  { id: 'm4', label: 'Sam K.' },
]

const options: ChartOption[] = [
  { id: 'o1', label: 'Cornwall' },
  { id: 'o2', label: 'Somerset' },
  { id: 'o3', label: 'Lakes' },
  { id: 'o4', label: 'York' },
]

const heatValues: (number | null)[][] = [
  [9, 6, 2, 7],
  [10, 7, 9, 5],
  [5, 5, 3, 8],
  [8, null, 6, 9],
]

function Card({
  tag,
  sub,
  children,
}: {
  tag: string
  sub: string
  children: ReactNode
}) {
  return (
    <div className="k-styleguide__card">
      <span className="k-styleguide__tag">{tag}</span>
      <p className="k-styleguide__card-sub">{sub}</p>
      {children}
    </div>
  )
}

export function Styleguide() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light')

  return (
    <div className="k-styleguide" data-theme={theme}>
      <div className="k-styleguide__head">
        <div>
          <h1>Chart widgets</h1>
          <p>
            Small token-aware SVG components, no chart library. Bars always start at zero,
            one accent per key series, no gridline noise — titles state the finding, not
            the metric name.
          </p>
        </div>
        <div className="k-styleguide__toggle" role="group" aria-label="Theme">
          <button type="button" aria-pressed={theme === 'light'} onClick={() => setTheme('light')}>
            Light
          </button>
          <button type="button" aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')}>
            Dark
          </button>
        </div>
      </div>

      <p className="k-styleguide__section-title">Realistic data — York/Cornwall poll</p>
      <div className="k-styleguide__grid">
        <Card tag="AvgBar" sub="Average score per destination, 11 members · scale 0–10">
          <AvgBar
            insight="Cornwall leads by two full points"
            items={[
              { label: 'Cornwall', value: 8.0, count: 11 },
              { label: 'Somerset', value: 6.0, count: 10 },
              { label: 'Lake District', value: 5.0, count: 9 },
              { label: 'York', value: 7.2, count: 11 },
            ]}
          />
        </Card>

        <Card tag="SpreadDots" sub="One dot per member, 0–10">
          <SpreadDots
            insight="Everyone likes Cornwall; the Lake District splits the group"
            options={[
              { label: 'Cornwall', scores: [7, 8, 8, 9, 9, 10, 10, 8] },
              { label: 'Lake District', scores: [1, 1, 2, 2, 3, 5, 8, 9, 10] },
            ]}
          />
        </Card>

        <Card tag="HeatMatrix" sub="Members × options — the spreadsheet this replaces">
          <HeatMatrix
            insight="Mei is the only one cool on Cornwall"
            rows={members}
            cols={options}
            values={heatValues}
          />
        </Card>

        <Card tag="DistributionStrip" sub="Thumbs vote · 11 members, 2 not voted">
          <DistributionStrip insight="Two Guys Pizza: 7 in favour, 2 against" up={7} down={2} none={2} />
        </Card>

        <Card tag="MiniBar" sub="Compact side-panel stat, zero-based">
          <MiniBar insight="Suggestions added this week" values={[2, 5, 1, 4, 6, 3, 4]} />
        </Card>

        <Card tag="Sparkline" sub="Aspect ratio targets a ~45° average trend slope">
          <Sparkline insight="Votes climbed steadily through the week" values={[3, 4, 4, 6, 9, 10, 14]} />
        </Card>
      </div>

      <p className="k-styleguide__section-title">Empty states</p>
      <div className="k-styleguide__grid">
        <Card tag="AvgBar" sub="No votes yet">
          <AvgBar insight="No scores yet" items={[]} />
        </Card>
        <Card tag="SpreadDots" sub="No votes yet">
          <SpreadDots insight="No scores yet" options={[]} />
        </Card>
        <Card tag="HeatMatrix" sub="No votes yet">
          <HeatMatrix insight="No scores yet" rows={[]} cols={[]} values={[]} />
        </Card>
        <Card tag="DistributionStrip" sub="No votes yet">
          <DistributionStrip insight="No votes yet" up={0} down={0} none={0} />
        </Card>
        <Card tag="Sparkline" sub="Single point — refuses to fake a trend line">
          <Sparkline insight="First data point only" values={[6]} />
        </Card>
      </div>
    </div>
  )
}
