/**
 * CommentComposer — the thread's compose box, with an `@` member picker (V7).
 *
 * Typing `@` followed by non-space characters opens a filtered picker
 * (`activeMentionQuery`/`mentions.ts`); choosing a member inserts well-formed
 * `@[Name](user:<uuid>)` markup and returns focus to the textarea right after the inserted
 * token. A character counter appears once the body nears the 4000-char cap
 * (`design.md`'s edge case). Field states follow the shared `useValidatedField`/`TextField`
 * conventions used by every other form in the app — this one only has a single field, so it
 * manages its own minimal validation (non-empty on submit) rather than pulling in the full
 * hook for one rule.
 */

import { useRef, useState } from 'react'
import { Button } from '../../app/ui/primitives'
import { VisuallyHidden } from '../../charts/a11y'
import { activeMentionQuery, insertMention } from './mentions'
import { useTripMembers } from './useTripMembers'
import type { TripMemberOption } from './useTripMembers'
import './voting.css'

const BODY_MAX = 4000
const COUNTER_THRESHOLD = BODY_MAX - 300

export type CommentComposerProps = {
  onSubmit: (body: string) => Promise<boolean>
  placeholder?: string
  submitLabel?: string
  initialValue?: string
  onCancel?: () => void
  autoFocus?: boolean
}

export function CommentComposer({
  onSubmit,
  placeholder = 'Add a comment',
  submitLabel = 'Post',
  initialValue = '',
  onCancel,
  autoFocus = false,
}: CommentComposerProps) {
  const [body, setBody] = useState(initialValue)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [picker, setPicker] = useState<{ query: string; start: number } | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const members = useTripMembers()

  const matches = picker
    ? members.filter((m) => m.displayName.toLowerCase().startsWith(picker.query.toLowerCase())).slice(0, 6)
    : []

  function onChange(next: string, cursor: number) {
    setBody(next)
    if (error) setError(next.trim() ? null : error) // re-validate after first error, on change
    setPicker(activeMentionQuery(next, cursor))
  }

  function pick(member: TripMemberOption) {
    if (!picker || !textareaRef.current) return
    const cursor = textareaRef.current.selectionStart ?? body.length
    const { text, cursor: nextCursor } = insertMention(body, picker.start, cursor, {
      name: member.displayName,
      userId: member.userId,
    })
    setBody(text)
    setPicker(null)
    // Restore focus + caret after the inserted token — a picker that steals focus
    // permanently would make mentioning someone and continuing to type two separate acts.
    requestAnimationFrame(() => {
      textareaRef.current?.focus()
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor)
    })
  }

  async function submit() {
    const trimmed = body.trim()
    if (!trimmed) {
      setError('Write something before posting.')
      return
    }
    if (trimmed.length > BODY_MAX) {
      setError(`Comments are limited to ${BODY_MAX} characters.`)
      return
    }
    setBusy(true)
    setError(null)
    const ok = await onSubmit(trimmed)
    setBusy(false)
    if (ok) setBody('')
    else setError('That could not be saved.')
  }

  return (
    <div className="comment-composer">
      <div className="comment-composer__field">
        <VisuallyHidden>
          <label htmlFor="comment-composer-body">{placeholder}</label>
        </VisuallyHidden>
        <textarea
          id="comment-composer-body"
          ref={textareaRef}
          className={`k-field__input${error ? ' k-field--error' : ''}`}
          value={body}
          placeholder={placeholder}
          rows={2}
          autoFocus={autoFocus}
          onChange={(event) => onChange(event.target.value, event.target.selectionStart ?? 0)}
          onBlur={() => {
            if (!body.trim() && !error) return
            setError(body.trim() ? null : error)
          }}
        />
        {picker && matches.length > 0 ? (
          <ul className="comment-composer__picker" role="listbox" aria-label="Mention a member">
            {matches.map((member) => (
              <li key={member.userId}>
                <button type="button" role="option" onClick={() => pick(member)}>
                  {member.displayName}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <div className="comment-composer__foot">
        {error ? (
          <span className="k-field__error" role="alert">
            {error}
          </span>
        ) : body.length > COUNTER_THRESHOLD ? (
          <span className="comment-composer__counter tabular">
            {body.length} / {BODY_MAX}
          </span>
        ) : (
          <span />
        )}
        <div className="comment-composer__actions">
          {onCancel ? (
            <Button variant="ghost" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
          ) : null}
          <Button busy={busy} onClick={() => void submit()}>
            {submitLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
