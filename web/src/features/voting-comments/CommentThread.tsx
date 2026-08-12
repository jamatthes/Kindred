/**
 * CommentThread — the full polymorphic thread (`design.md` S6/S7/S8/V10): flat, oldest
 * first, author + family colour + relative time, mentions rendered as tokens, edit/delete
 * gated by `can_edit`/`can_delete`, delete-as-undo for your own comment, a confirm dialog +
 * permanent tombstone for an admin deleting someone else's.
 *
 * A new, polymorphic component rather than an upgrade of `polls/CommentThread.tsx` — that
 * file's own docblock says `voting-comments` "upgrades this in place", but retrofitting a
 * different feature's already-shipped, already-tested component mid-build risked breaking
 * poll comments for a change out of this phase's scope. Recorded as a deviation in
 * `plan/features/voting-comments/design.md`; a follow-up can point `polls` at this
 * component (it only needs `subject_type: 'poll'`) once both are reviewed together.
 */

import { useState } from 'react'
import { useSession } from '../../app/session'
import { useStage } from '../../app/useStage'
import { Banner, Button } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import { IdentityBadge } from '../../design/IdentityBadge'
import { familyColor } from '../../design/familyColor'
import { splitMentions } from './mentions'
import { CommentComposer } from './CommentComposer'
import { useCommentThread } from './useComments'
import type { CommentSubjectType, Comment as CommentT } from '../../app/types'
import './voting.css'

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(diffMs / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return `${days}d ago`
}

function CommentBody({ body }: { body: string }) {
  return (
    <p className="comment__text">
      {splitMentions(body).map((part, index) =>
        typeof part === 'string' ? (
          <span key={index}>{part}</span>
        ) : (
          <span key={index} className="comment__mention">
            @{part.name}
          </span>
        ),
      )}
    </p>
  )
}

export function CommentThread({
  subjectType,
  subjectId,
}: {
  subjectType: CommentSubjectType
  subjectId: string
}) {
  const { user } = useSession()
  const stage = useStage()
  const { comments, removals, loading, error, post, edit, remove, undo } = useCommentThread(subjectType, subjectId)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  async function handleDelete(comment: CommentT) {
    if (comment.can_edit) {
      // Own comment: undo pattern, no confirm — low-stakes and reversible (design-system.md).
      await remove(comment.id)
    } else {
      setConfirmDeleteId(comment.id)
    }
  }

  return (
    <section className="comments" aria-label="Comments">
      <h3 className="panel-block__title">
        Comments <span className="tabular">{comments.length}</span>
      </h3>

      {error ? <Banner tone="error">{error}</Banner> : null}
      {loading ? <p className="muted">Loading…</p> : null}

      {!loading && comments.length === 0 ? (
        <p className="comments__empty">No comments yet — start the discussion.</p>
      ) : (
        <ul className="comments__list">
          {comments.map((comment) => {
            const removal = removals.get(comment.id)
            if (removal?.mode === 'tombstone') {
              return (
                <li key={comment.id} className="comment comment--tombstone">
                  <p>Comment removed.</p>
                </li>
              )
            }
            if (removal?.mode === 'undo') {
              return (
                <li key={comment.id} className="comment comment--undo">
                  <p>Comment deleted.</p>
                  <Button variant="ghost" onClick={() => void undo(comment.id)}>
                    Undo
                  </Button>
                </li>
              )
            }
            return (
              <li key={comment.id} className="comment">
                <IdentityBadge
                  initials={comment.author.display_name.slice(0, 2).toUpperCase()}
                  familyColor={familyColor({
                    color: comment.author.family_color,
                    color_custom: comment.author.family_color_custom ?? null,
                  })}
                  size={24}
                  name={comment.author.display_name}
                />
                <div className="comment__body">
                  <span className="comment__who">
                    {comment.author.display_name}
                    <span className="comment__when">
                      {' · '}
                      {relativeTime(comment.created_at)}
                      {comment.edited_at ? ' · edited' : ''}
                    </span>
                  </span>

                  {editingId === comment.id ? (
                    <CommentComposer
                      initialValue={comment.body}
                      submitLabel="Save"
                      autoFocus
                      onCancel={() => setEditingId(null)}
                      onSubmit={async (body) => {
                        const ok = await edit(comment.id, body)
                        if (ok) setEditingId(null)
                        return ok
                      }}
                    />
                  ) : (
                    <CommentBody body={comment.body} />
                  )}

                  {stage.canMutate && editingId !== comment.id ? (
                    <div className="comment__actions">
                      {comment.can_edit ? (
                        <Button variant="ghost" onClick={() => setEditingId(comment.id)}>
                          Edit
                        </Button>
                      ) : null}
                      {comment.can_delete ? (
                        <Button variant="ghost" onClick={() => void handleDelete(comment)}>
                          Delete
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {stage.canMutate && user ? (
        <CommentComposer placeholder="Add a comment" onSubmit={post} />
      ) : !stage.canMutate ? (
        <p className="muted">This trip is frozen — comments are read-only.</p>
      ) : null}

      <ConfirmDialog
        open={confirmDeleteId !== null}
        title="Delete this comment?"
        body="It was not written by you — this is a moderation action."
        consequences={['The author will not be notified.', 'A "comment removed" marker stays in its place.']}
        confirmLabel="Delete comment"
        tone="danger"
        onCancel={() => setConfirmDeleteId(null)}
        onConfirm={() => {
          const id = confirmDeleteId
          setConfirmDeleteId(null)
          if (id) void remove(id)
        }}
      />
    </section>
  )
}
