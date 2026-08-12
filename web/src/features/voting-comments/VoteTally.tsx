/**
 * VoteTally — the tally at the three densities `design.md` specifies: compact (list row),
 * medium (popover card), full (side panel with voter attribution).
 *
 * Compact is a plain number-plus-minimal-bar, matching the existing `poll-card__bar`
 * pattern (`polls/polls.css`) rather than a `web/src/charts/` widget — the chart widgets
 * carry their own insight caption, accessible table fallback and legend, which is exactly
 * right for the panel's full density and too much chrome for a table cell. Medium and full
 * both go through the real chart widgets (`AvgBar`/`DistributionStrip`/`SpreadDots`), so
 * their honesty rules (zero-baseline, no invented "not voted" folded into a denominator)
 * apply everywhere a tally actually renders as a chart.
 *
 * "Not yet voted" is always shown as its own figure, never folded into a percentage of
 * "count" — `design.md`: "A 10/10 average from one voter must not look like consensus."
 */

import { AvgBar, DistributionStrip, SpreadDots } from '../../charts'
import type { SuggestionVoteSummary, VoteTally as VoteTallyData } from '../../app/types'
import './voting.css'

export type VoteTallyDensity = 'compact' | 'medium' | 'full'

export type VoteTallyProps = {
  tally: VoteTallyData | null
  density: VoteTallyDensity
  title: string
}

function insightFor(tally: VoteTallyData, title: string): string {
  if (tally.count === 0) return `${title} — no votes yet`
  if (tally.mode === 'score') {
    return `${title} averages ${tally.average?.toFixed(1) ?? '—'} across ${tally.count} vote${tally.count === 1 ? '' : 's'}`
  }
  return `${title} — ${tally.up ?? 0} for, ${tally.down ?? 0} against`
}

function CompactTally({ tally }: { tally: VoteTallyData | null }) {
  if (!tally || tally.count === 0) {
    return <span className="vt-compact vt-compact--empty">No votes</span>
  }
  if (tally.mode === 'score') {
    const percent = ((tally.average ?? 0) / 10) * 100
    return (
      <span className="vt-compact">
        <span className="vt-compact__value tabular">{tally.average?.toFixed(1) ?? '—'}</span>
        <span className="vt-compact__bar" aria-hidden="true">
          <i style={{ width: `${percent}%` }} />
        </span>
      </span>
    )
  }
  const total = (tally.up ?? 0) + (tally.down ?? 0)
  const upPercent = total > 0 ? ((tally.up ?? 0) / total) * 100 : 0
  return (
    <span className="vt-compact">
      <span className="vt-compact__value tabular">
        {tally.up ?? 0}↑ {tally.down ?? 0}↓
      </span>
      <span className="vt-compact__bar" aria-hidden="true">
        <i style={{ width: `${upPercent}%` }} />
      </span>
    </span>
  )
}

/**
 * The list row's compact tally, built from `Suggestion.vote_summary` — the field
 * `map-suggestions/design.md`'s `GET /suggestions` response denormalises directly, rather
 * than this feature's own richer `VoteTally` shape (`GET /suggestions/{id}/votes`). Firing
 * one vote-tally request per row to populate a table would be exactly the N+1 pattern
 * `map-suggestions/design.md` calls out avoiding; this reuses the list response's own
 * summary instead, at the cost of not having `eligible_count`/voter attribution here — the
 * compact density never shows those anyway.
 */
export function CompactVoteTally({ summary }: { summary: SuggestionVoteSummary | null }) {
  if (!summary) return <CompactTally tally={null} />
  return (
    <CompactTally
      tally={{
        mode: summary.mode,
        count: summary.count,
        eligible_count: 0,
        average: summary.average,
        distribution: null,
        up: summary.up,
        down: summary.down,
        none: null,
        my_vote: null,
        voters: [],
        not_voted: [],
      }}
    />
  )
}

export function VoteTally({ tally, density, title }: VoteTallyProps) {
  if (density === 'compact') return <CompactTally tally={tally} />

  if (!tally || tally.count === 0) {
    return tally?.mode === 'thumbs' ? (
      <DistributionStrip insight={`${title} — no votes yet`} up={0} down={0} none={tally?.eligible_count ?? 0} />
    ) : (
      <AvgBar insight={`${title} — no votes yet`} items={[]} />
    )
  }

  const insight = insightFor(tally, title)

  if (tally.mode === 'thumbs') {
    return (
      <div className="vt-medium">
        <DistributionStrip insight={insight} up={tally.up ?? 0} down={tally.down ?? 0} none={tally.none ?? 0} />
        {density === 'full' ? <VoterAttribution tally={tally} /> : null}
      </div>
    )
  }

  return (
    <div className="vt-medium">
      <AvgBar insight={insight} items={[{ label: title, value: tally.average ?? 0, count: tally.count }]} />
      {density === 'full' ? (
        <>
          <SpreadDots
            insight="Where the group agrees, and where it does not"
            options={[{ label: title, scores: tally.voters.map((v) => v.score).filter((s): s is number => s != null) }]}
          />
          <VoterAttribution tally={tally} />
        </>
      ) : null}
    </div>
  )
}

function VoterAttribution({ tally }: { tally: VoteTallyData }) {
  return (
    <div className="vt-attribution">
      {tally.voters.length > 0 ? (
        <ul className="vt-attribution__list">
          {tally.voters.map((voter) => (
            <li key={voter.user_id}>
              <span>{voter.display_name}</span>
              <span className="tabular">{voter.score ?? (voter.thumb === 'up' ? '👍' : voter.thumb === 'down' ? '👎' : '—')}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {tally.not_voted.length > 0 ? (
        <p className="vt-attribution__outstanding">
          Not yet voted: {tally.not_voted.map((m) => m.display_name).join(', ')}
        </p>
      ) : null}
    </div>
  )
}
