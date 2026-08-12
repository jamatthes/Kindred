/**
 * ThumbsVoteControl — the up/down vote input for thumbs-mode categories.
 *
 * Two labelled buttons (icon *and* word — colour is never the sole carrier) plus a "clear"
 * affordance that only appears once a vote exists (`design.md`: "a third 'clear' affordance
 * once a vote exists").
 */

import './voting.css'

export type ThumbsVoteControlProps = {
  value: 'up' | 'down' | null
  onChange: (value: 'up' | 'down') => void
  onClear: () => void
  disabled?: boolean
  size?: 'compact' | 'full'
}

export function ThumbsVoteControl({ value, onChange, onClear, disabled = false, size = 'full' }: ThumbsVoteControlProps) {
  return (
    <div className={`vc-thumbs vc-thumbs--${size}`} role="group" aria-label="Your vote">
      <button
        type="button"
        className={`vc-thumbs__btn vc-thumbs__btn--up${value === 'up' ? ' is-on' : ''}`}
        aria-pressed={value === 'up'}
        disabled={disabled}
        onClick={() => onChange('up')}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3Zm0 0 4.5-8a2 2 0 0 1 3.5 1.3V9h4a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 18 20H9a2 2 0 0 1-2-2v-7Z" />
        </svg>
        <span>Yes</span>
      </button>
      <button
        type="button"
        className={`vc-thumbs__btn vc-thumbs__btn--down${value === 'down' ? ' is-on' : ''}`}
        aria-pressed={value === 'down'}
        disabled={disabled}
        onClick={() => onChange('down')}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path d="M17 13V4h3a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1h-3Zm0 0-4.5 8a2 2 0 0 1-3.5-1.3V15h-4a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6 4h9a2 2 0 0 1 2 2v7Z" />
        </svg>
        <span>No</span>
      </button>
      {value !== null ? (
        <button type="button" className="vc-thumbs__clear" disabled={disabled} onClick={onClear}>
          Clear
        </button>
      ) : null}
    </div>
  )
}
