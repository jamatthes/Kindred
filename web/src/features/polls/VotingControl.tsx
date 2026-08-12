/**
 * The voting control (PL-3, PL-4, PL-2).
 *
 * Three shapes behind one component, because which one a member sees is the trip's decision
 * rather than theirs: a 1–10 scale, a three-state thumb, or a single-select list.
 *
 * **The ends of the scale are labelled in words.** "1" and "10" do not say which direction is
 * good, and a poll where half the family scored it backwards is worse than no poll. PL-3 asks
 * for this explicitly and it is the one piece of copy here that is not decoration.
 *
 * **Saving is optimistic with rollback.** The cell updates immediately, the PUT follows, and
 * a failure puts the old value back with an inline message — because a scale that lags by a
 * round trip gets pressed twice, and the second press is a different number.
 *
 * **Closed polls and the End stage render no control at all** — not a disabled one. PL-17
 * asks for a record, not a broken form.
 */

import { useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner } from '../../app/ui/primitives'
import type { Poll, PollResults, Thumb } from '../../app/types'
import { pollsApi } from './api'
import './polls.css'

/** PL-3: the meaning of the ends is shown, not left to guesswork. */
const SCALE_LOW = 'Really rather not'
const SCALE_HIGH = 'Yes please'
const SCALE = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

function myAnswer(results: PollResults | null, optionId: string, userId: string) {
  const option = results?.options.find((o) => o.option_id === optionId)
  return option?.scores.find((s) => s.user_id === userId) ?? null
}

export function VotingControl({
  poll,
  results,
  userId,
  onResults,
}: {
  poll: Poll
  results: PollResults | null
  userId: string
  onResults: (results: PollResults) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  /** Shown immediately, before the server answers. Cleared when the real results arrive. */
  const [optimistic, setOptimistic] = useState<Record<string, number | Thumb>>({})

  async function save(optionId: string, value: number | Thumb) {
    setError(null)
    setSaving(optionId)
    setOptimistic((current) => ({ ...current, [optionId]: value }))
    try {
      const entry =
        typeof value === 'number'
          ? { option_id: optionId, score: value }
          : { option_id: optionId, thumb: value }
      onResults(await pollsApi.putScores(poll.id, [entry]))
      setOptimistic((current) => {
        const next = { ...current }
        delete next[optionId]
        return next
      })
    } catch (cause) {
      // Roll back to whatever the server last told us, and say why.
      setOptimistic((current) => {
        const next = { ...current }
        delete next[optionId]
        return next
      })
      setError(
        cause instanceof ApiError ? cause.message : 'That score could not be saved.',
      )
    } finally {
      setSaving(null)
    }
  }

  const options = poll.options
  const singleChoice = poll.kind === 'options'

  return (
    <section className="vote">
      <h3 className="panel-block__title">Your answer</h3>
      {error ? <Banner tone="error">{error}</Banner> : null}

      {poll.voting_mode === 'score' && !singleChoice ? (
        <>
          <p className="vote__legend">
            <span>1 · {SCALE_LOW}</span>
            <span>10 · {SCALE_HIGH}</span>
          </p>
          <ul className="vote__list">
            {options.map((option) => {
              const answered = myAnswer(results, option.id, userId)
              const shown = optimistic[option.id] ?? answered?.score ?? null
              return (
                <li key={option.id} className="vote__row">
                  <span className="vote__label">
                    {option.label}
                    {shown === null ? (
                      // A partial response is visibly partial (PL-3).
                      <span className="vote__unscored">not scored yet</span>
                    ) : null}
                  </span>
                  <span className="vote__scale" role="group" aria-label={option.label}>
                    {SCALE.map((value) => (
                      <button
                        key={value}
                        type="button"
                        className={`vote__step${shown === value ? ' is-on' : ''}`}
                        aria-pressed={shown === value}
                        aria-label={`${option.label}: ${value}${
                          value === 1 ? ` (${SCALE_LOW})` : value === 10 ? ` (${SCALE_HIGH})` : ''
                        }`}
                        disabled={saving === option.id}
                        onClick={() => void save(option.id, value)}
                      >
                        {value}
                      </button>
                    ))}
                  </span>
                  {/* The value as a number as well as a position — never position alone. */}
                  <span className="vote__value tabular">{shown ?? '—'}</span>
                </li>
              )
            })}
          </ul>
        </>
      ) : null}

      {poll.voting_mode === 'thumbs' && !singleChoice ? (
        <ul className="vote__list">
          {options.map((option) => {
            const answered = myAnswer(results, option.id, userId)
            const shown = (optimistic[option.id] as Thumb) ?? answered?.thumb ?? null
            return (
              <li key={option.id} className="vote__row">
                <span className="vote__label">{option.label}</span>
                <span className="vote__thumbs" role="group" aria-label={option.label}>
                  {(['up', 'down'] as const).map((thumb) => (
                    <button
                      key={thumb}
                      type="button"
                      className={`vote__thumb${shown === thumb ? ' is-on' : ''}`}
                      aria-pressed={shown === thumb}
                      disabled={saving === option.id}
                      onClick={() => void save(option.id, thumb)}
                    >
                      {/* Icon *and* text — colour and glyph are never the only carrier. */}
                      {thumb === 'up' ? '👍' : '👎'}
                      <span>{thumb === 'up' ? 'Yes' : 'No'}</span>
                    </button>
                  ))}
                </span>
              </li>
            )
          })}
        </ul>
      ) : null}

      {singleChoice ? (
        <ul className="vote__list vote__list--single" role="radiogroup" aria-label={poll.title}>
          {options.map((option) => {
            const chosen = results?.options
              .find((o) => o.option_id === option.id)
              ?.scores.some((s) => s.user_id === userId)
            const shown = optimistic[option.id] !== undefined ? true : chosen
            return (
              <li key={option.id}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={Boolean(shown)}
                  className={`vote__choice${shown ? ' is-on' : ''}`}
                  disabled={saving === option.id}
                  // Choosing another replaces the previous choice with no extra
                  // interaction (PL-2) — the server deletes the old row.
                  onClick={() => void save(option.id, poll.voting_mode === 'score' ? 10 : 'up')}
                >
                  {option.label}
                </button>
              </li>
            )
          })}
        </ul>
      ) : null}
    </section>
  )
}
