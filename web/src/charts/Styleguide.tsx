/**
 * `/styleguide` — the design-system gallery (`plan/features/design-system/tasks.md`
 * Phase 8): token scales, primitives, and every chart widget, in one unlinked,
 * authenticated route (DS-13). No Storybook dependency; a page-scoped theme toggle so
 * both themes can be compared without touching the account preference.
 *
 * Four sections:
 *  - Tokens (`StyleguideTokens.tsx`) — colour scales in both themes at once, with a live
 *    contrast readout, the preference ramp shown three ways, type and spacing scales.
 *  - Primitives (`StyleguidePrimitives.tsx`) — every primitive that actually exists in
 *    `web/src/app/ui/` and `web/src/design/` today, in its documented states.
 *  - Dates and times (`StyleguidePickers.tsx`) — the three pickers of Phase 11, live in both
 *    themes, with their error, disabled and mid-range-hover states.
 *  - Charts — every widget in `web/src/charts/` with realistic sample data (a
 *    York/Cornwall poll, matching `design-preview/charts.html` and
 *    `design-preview/screen-polls.html`), plus each widget's empty and single-point
 *    states.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import { AvgBar } from './AvgBar'
import { SpreadDots } from './SpreadDots'
import { HeatMatrix } from './HeatMatrix'
import { DistributionStrip } from './DistributionStrip'
import { MiniBar, Sparkline } from './MiniBar'
import { StyleguideTokens } from './StyleguideTokens'
import { StyleguidePrimitives } from './StyleguidePrimitives'
import { StyleguidePickers } from './StyleguidePickers'
import { StyleguideMap } from './StyleguideMap'
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
          <h1>Design system</h1>
          <p>
            Tokens, primitives, and the chart widget library — reviewed here, in both
            themes, before and after any design-system change.
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

      <p className="k-styleguide__section-title">Tokens</p>
      <StyleguideTokens />

      <p className="k-styleguide__section-title">Primitives</p>
      <StyleguidePrimitives />

      <StyleguidePickers />

      <StyleguideMap />

      <p className="k-styleguide__section-title">Charts — realistic data (York/Cornwall poll)</p>
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

        <Card
          tag="SpreadDots"
          sub="Long labels ellipsize (with a title) — they never clip mid-glyph"
        >
          <SpreadDots
            insight="The polls page composes its labels; they must survive a narrow block"
            options={[
              { label: 'Cornwall · spread 0.7', scores: [7, 8, 8, 9, 9, 10] },
              { label: 'Lake District · spread 3.4 · split', scores: [1, 2, 3, 8, 9, 10] },
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

      <p className="k-styleguide__section-title">Charts — empty and single-point states</p>
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
