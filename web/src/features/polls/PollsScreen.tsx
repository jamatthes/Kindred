/**
 * The polls screen: a poll list beside the selected poll's detail.
 *
 * Layout follows `design-preview/screen-polls.html` — a fixed list column and a scrolling
 * detail column — rather than `design.md`'s map-plus-panel. The mockup is right and the
 * design text predates it: a poll's centre of gravity is the matrix, which is wide, and
 * giving it 62% of the width while a map sits beside it showing five circles would be the
 * wrong trade. `plan/overview.md`'s UI-first rule says feature UI starts from the agreed
 * mockup. Recorded as a NOTE in `design.md`.
 *
 * The charts come from `web/src/charts/`; nothing here draws its own. Their honesty rules —
 * zero-baselined bars, a number in every cell, unscored cells hatched rather than pale — are
 * the reason this feature is worth building rather than a spreadsheet, so they are used as
 * given.
 */

import { useMemo, useState } from 'react'
import { useSession } from '../../app/session'
import { useNavigate } from '../../app/router'
import { useStage } from '../../app/useStage'
import { Banner, Button, Skeleton } from '../../app/ui/primitives'
import { AvgBar, HeatMatrix, SpreadDots, DistributionStrip } from '../../charts'
import type { PollResults, PollSummary } from '../../app/types'
import { usePollDetail, usePollList } from './usePolls'
import { VotingControl } from './VotingControl'
import { optionsByRank } from './ranking'
import { PollAdminBar } from './PollAdminBar'
import { NonResponders } from './NonResponders'
import { CommentThread } from './CommentThread'
import { CreatePollForm } from './CreatePollForm'
import './polls.css'

const COMPLETION_LABEL: Record<string, string> = {
  none: 'Not started',
  partial: 'Part done',
  complete: 'Done',
}

function PollListItem({
  poll,
  selected,
  onOpen,
}: {
  poll: PollSummary
  selected: boolean
  onOpen: () => void
}) {
  const done = poll.group_completion.complete
  const total = poll.group_completion.total
  const percent = total === 0 ? 0 : Math.round((done / total) * 100)

  return (
    <button
      type="button"
      className={`poll-card${selected ? ' is-on' : ''}`}
      onClick={onOpen}
      aria-current={selected ? 'true' : undefined}
    >
      <span className="poll-card__title">{poll.title}</span>
      <span className="poll-card__tags">
        <span className={`tag tag--${poll.status}`}>
          {poll.status === 'open' ? 'Open' : 'Closed'}
        </span>
        <span className="tag">
          {poll.kind === 'options' ? 'One choice' : 'Score 1–10'}
        </span>
        <span className="tag">{poll.option_count} options</span>
        {poll.status === 'open' && poll.my_completion !== 'complete' ? (
          // Icon plus words, never a bare colour dot.
          <span className="tag tag--todo">You: {COMPLETION_LABEL[poll.my_completion]}</span>
        ) : null}
      </span>
      <span className="poll-card__progress">
        <span className="poll-card__bar" aria-hidden="true">
          <i style={{ width: `${percent}%` }} />
        </span>
        <span className="poll-card__count tabular">
          {done} of {total} voted
        </span>
      </span>
      {poll.decision ? (
        <span className="poll-card__decision">✓ Decided: {poll.decision.label}</span>
      ) : null}
    </button>
  )
}

function Results({ results }: { results: PollResults }) {
  const ranked = optionsByRank(results)
  const scored = ranked.filter((option) => option.response_count > 0)

  if (scored.length === 0) {
    return (
      <p className="polls-empty">No scores yet — be the first.</p>
    )
  }

  if (results.voting_mode === 'thumbs') {
    return (
      <div className="results">
        {ranked.map((option) => (
          <DistributionStrip
            key={option.option_id}
            insight={`${option.label} — ${option.up_count} for, ${option.down_count} against`}
            up={option.up_count}
            down={option.down_count}
            none={option.none_count}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="results">
      <AvgBar
        insight={results.insight}
        items={ranked
          .filter((option) => option.average !== null)
          .map((option) => ({
            label: option.label,
            value: option.average as number,
            count: option.response_count,
          }))}
      />
      <SpreadDots
        insight="Where we agree, and where we do not"
        options={scored
          .filter((option) => option.spread !== null)
          .map((option) => ({
            label: `${option.label} · spread ${option.spread}${option.is_split ? ' · split' : ''}`,
            scores: option.scores
              .map((s) => s.score)
              .filter((s): s is number => s !== null),
          }))}
      />
    </div>
  )
}

function Matrix({ results, userId }: { results: PollResults; userId: string }) {
  const ranked = optionsByRank(results)
  const rows = useMemo(
    () =>
      results.members.map((member) => ({
        id: member.user_id,
        // The caller's own row is marked, and family membership is legible, so patterns
        // along family lines are visible (PL-8).
        label: `${member.display_name}${member.user_id === userId ? ' (you)' : ''}`,
      })),
    [results.members, userId],
  )
  const cols = useMemo(
    () => ranked.map((option) => ({ id: option.option_id, label: option.label })),
    [ranked],
  )
  const values = useMemo(
    () =>
      results.members.map((member) =>
        ranked.map((option) => {
          const cell = option.scores.find((s) => s.user_id === member.user_id)
          // `null` renders hatched, never as a 0 — a silence is not a low score.
          return cell?.score ?? null
        }),
      ),
    [results.members, ranked],
  )

  if (rows.length === 0 || cols.length === 0) return null
  return <HeatMatrix insight={results.insight} rows={rows} cols={cols} values={values} />
}

export function PollsScreen({ selectedId }: { selectedId?: string }) {
  const { user } = useSession()
  const navigate = useNavigate()
  const stage = useStage()
  const { polls, loading, error } = usePollList()
  const detail = usePollDetail(selectedId ?? null)
  const [creating, setCreating] = useState(false)
  const [matrixOpen, setMatrixOpen] = useState(true)

  const isOrganiser = Boolean(user?.is_organiser)
  const poll = detail.poll
  const results = detail.results

  if (loading) {
    return (
      <div className="polls" aria-busy="true">
        <div className="poll-list">
          <Skeleton height="var(--space-5)" />
          <Skeleton height="var(--space-5)" />
        </div>
        <div className="poll-main">
          <Skeleton height="var(--text-sub)" width="50%" />
          <div style={{ height: 'var(--space-3)' }} />
          <Skeleton height="var(--space-6)" />
        </div>
      </div>
    )
  }

  return (
    <div className="polls">
      <aside className="poll-list" aria-label="Polls">
        <div className="poll-list__head">
          <span>Polls</span>
          <span className="tabular">{polls.length}</span>
        </div>

        {error ? <Banner tone="error">{error}</Banner> : null}

        {polls.length === 0 ? (
          <div className="polls-empty">
            <p>No polls yet — the first one usually decides where to go.</p>
            {isOrganiser && stage.canMutate ? (
              <Button onClick={() => setCreating(true)}>Create a poll</Button>
            ) : (
              <p className="muted">The trip organiser sets these up.</p>
            )}
          </div>
        ) : (
          <>
            {polls.map((item) => (
              <PollListItem
                key={item.id}
                poll={item}
                selected={item.id === selectedId}
                onOpen={() => navigate({ name: 'polls', pollId: item.id })}
              />
            ))}
            <p className="poll-list__foot">
              Open polls you haven&apos;t finished are listed first.
            </p>
            {isOrganiser && stage.canMutate ? (
              <Button variant="secondary" onClick={() => setCreating(true)}>
                Create a poll
              </Button>
            ) : null}
          </>
        )}
      </aside>

      <section className="poll-main">
        {!selectedId ? (
          <p className="polls-empty">Choose a poll to see how the group is scoring it.</p>
        ) : detail.loading || !poll || !results ? (
          <div aria-busy="true">
            <Skeleton height="var(--text-sub)" width="60%" />
            <div style={{ height: 'var(--space-3)' }} />
            <Skeleton height="var(--space-6)" />
          </div>
        ) : (
          <>
            <header className="poll-head">
              <div>
                <h1>{poll.title}</h1>
                {poll.description ? <p className="poll-head__sub">{poll.description}</p> : null}
              </div>
              <span className={`tag tag--${poll.status}`}>
                {poll.status === 'open' ? 'Open' : 'Closed'}
              </span>
            </header>

            {poll.decision ? (
              <div className="decision-banner" role="status">
                <strong>Decided: {poll.decision.label}</strong>
                {poll.can_seed_region ? null : null}
              </div>
            ) : null}

            <NonResponders
              results={results}
              poll={poll}
              canNudge={isOrganiser && stage.canMutate}
            />

            {/* Closed or ended: no control at all, not a disabled one (PL-17). */}
            {poll.status === 'open' && stage.canMutate && user ? (
              <VotingControl
                poll={poll}
                results={results}
                userId={user.id}
                onResults={detail.setResults}
              />
            ) : null}

            <p className="insight">{results.insight}</p>
            <p className="insight-sub">
              Averages count only cast scores — nobody is treated as a zero.
            </p>

            <Results results={results} />

            <div className="matrix-block">
              <button
                type="button"
                className="matrix-block__toggle"
                aria-expanded={matrixOpen}
                onClick={() => setMatrixOpen((open) => !open)}
              >
                {matrixOpen ? 'Hide' : 'Show'} everyone&apos;s scores
              </button>
              {matrixOpen && user ? <Matrix results={results} userId={user.id} /> : null}
            </div>

            <CommentThread pollId={poll.id} />

            {isOrganiser ? (
              <PollAdminBar
                poll={poll}
                results={results}
                onChanged={detail.setPoll}
                onGone={() => navigate({ name: 'polls' })}
              />
            ) : null}
          </>
        )}
      </section>

      {creating ? (
        <CreatePollForm
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setCreating(false)
            navigate({ name: 'polls', pollId: created.id })
          }}
        />
      ) : null}
    </div>
  )
}
