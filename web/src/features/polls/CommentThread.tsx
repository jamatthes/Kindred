/**
 * The poll's comment thread (PL-11).
 *
 * A **plain** thread: no @mention parsing. `voting-comments` (M3) upgrades this in place, and
 * building half a mention parser now would be something that feature then has to unpick.
 *
 * Deleting your own comment is low-stakes and reversible by retyping, so it uses an undo
 * toast rather than a confirm. An organiser deleting somebody else's is a real confirm —
 * it is not their content.
 */

import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { useSession } from '../../app/session'
import { useStage } from '../../app/useStage'
import { socket } from '../../app/socket'
import { Banner, Button, TextField } from '../../app/ui/primitives'
import { ConfirmDialog } from '../../app/ui/ConfirmDialog'
import { useToast } from '../../app/ui/toastContext'
import { IdentityBadge } from '../../design/IdentityBadge'
import { familyColor } from '../../design/familyColor'
import type { PollComment } from '../../app/types'
import { pollsApi } from './api'

export function CommentThread({ pollId }: { pollId: string }) {
  const { user } = useSession()
  const stage = useStage()
  const toast = useToast()
  const [comments, setComments] = useState<PollComment[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<PollComment | null>(null)

  const load = useCallback(async () => {
    try {
      setComments(await pollsApi.comments(pollId))
    } catch {
      setError('The comments could not be loaded.')
    }
  }, [pollId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(
    () => socket.subscribe('comment.created', () => void load()),
    [load],
  )

  async function post() {
    if (!draft.trim()) return
    setBusy(true)
    setError(null)
    try {
      await pollsApi.addComment(pollId, draft.trim())
      setDraft('')
      await load()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That could not be posted.')
    } finally {
      setBusy(false)
    }
  }

  async function saveEdit(comment: PollComment) {
    setBusy(true)
    try {
      await pollsApi.editComment(comment.id, editDraft.trim())
      setEditing(null)
      await load()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  async function remove(comment: PollComment) {
    const body = comment.body
    try {
      await pollsApi.deleteComment(comment.id)
      await load()
      // Undo by retyping — the toast carries what was said, so it is not lost.
      toast(`Comment deleted. It said: “${body.slice(0, 60)}”`)
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'That could not be deleted.')
    }
  }

  return (
    // Carries its own `.poll-block` panel rather than being wrapped in one by the screen,
    // so it stays a single <section> with a single heading.
    <section className="comments poll-block">
      <h2 className="poll-block__head">
        <span>Comments</span>
        <span className="tabular">{comments.length}</span>
      </h2>

      {error ? <Banner tone="error">{error}</Banner> : null}

      <ul className="comments__list">
        {comments.map((comment) => (
          <li key={comment.id} className="comment">
            <IdentityBadge
              initials={comment.author_name.slice(0, 2)}
              familyColor={familyColor({
                color: comment.family_color,
                color_custom: comment.family_color_custom,
              })}
              size={24}
              name={comment.author_name}
            />
            <div className="comment__body">
              <span className="comment__who">{comment.author_name}</span>
              <span className="comment__when">
                {new Date(comment.created_at).toLocaleString()}
                {/* An edit that left no trace would falsify the discussion record. */}
                {comment.edited_at ? ' · edited' : ''}
              </span>
              {editing === comment.id ? (
                <>
                  <TextField
                    label="Edit comment"
                    value={editDraft}
                    onChange={(event) => setEditDraft(event.target.value)}
                  />
                  <div className="comment__actions">
                    <Button busy={busy} onClick={() => void saveEdit(comment)}>
                      Save
                    </Button>
                    <Button variant="ghost" onClick={() => setEditing(null)}>
                      Cancel
                    </Button>
                  </div>
                </>
              ) : (
                <p>{comment.body}</p>
              )}
              {stage.canMutate && editing !== comment.id ? (
                <div className="comment__actions">
                  {comment.can_edit ? (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setEditing(comment.id)
                        setEditDraft(comment.body)
                      }}
                    >
                      Edit
                    </Button>
                  ) : null}
                  {comment.can_delete ? (
                    <Button
                      variant="ghost"
                      onClick={() =>
                        comment.author_id === user?.id
                          ? void remove(comment)
                          : setConfirmDelete(comment)
                      }
                    >
                      Delete
                    </Button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      {comments.length === 0 ? (
        <p className="muted">No comments yet.</p>
      ) : null}

      {stage.canMutate ? (
        <div className="comments__compose">
          <TextField
            label="Add a comment"
            value={draft}
            disabled={busy}
            onChange={(event) => setDraft(event.target.value)}
          />
          <Button busy={busy} onClick={() => void post()}>
            Post
          </Button>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Delete this comment?"
        body={confirmDelete ? `${confirmDelete.author_name} wrote it, not you.` : ''}
        consequences={['They will not be told.', 'This cannot be undone.']}
        confirmLabel="Delete comment"
        tone="danger"
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          const target = confirmDelete
          setConfirmDelete(null)
          if (target) void remove(target)
        }}
      />
    </section>
  )
}
