/**
 * CommentThread — the undo-restores-position guarantee (V8), the mention token rendering
 * (V7), and edit/delete gated by `can_edit`/`can_delete` from the API (never re-derived
 * client-side).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Comment } from '../../app/types'

const list = vi.fn()
const create = vi.fn()
const removeApi = vi.fn()
const undoDelete = vi.fn()
vi.mock('./api', () => ({
  commentsApi: {
    list: (...args: unknown[]) => list(...args),
    create: (...args: unknown[]) => create(...args),
    update: vi.fn(),
    remove: (...args: unknown[]) => removeApi(...args),
    undoDelete: (...args: unknown[]) => undoDelete(...args),
  },
}))

vi.mock('./useTripMembers', () => ({ useTripMembers: () => [] }))

let mockUser: { id: string } | null = { id: 'me' }
vi.mock('../../app/session', () => ({ useSession: () => ({ user: mockUser }) }))

let mockStage = { canMutate: true }
vi.mock('../../app/useStage', () => ({ useStage: () => mockStage }))

type Handler = (envelope: { type: string; payload: unknown }) => void
const handlers = new Map<string, Set<Handler>>()
vi.mock('../../app/socket', () => ({
  socket: {
    subscribe: (type: string, handler: Handler) => {
      const set = handlers.get(type) ?? new Set<Handler>()
      set.add(handler)
      handlers.set(type, set)
      return () => set.delete(handler)
    },
  },
}))
function emit(type: string, payload: unknown) {
  for (const handler of handlers.get(type) ?? []) handler({ type, payload })
}

const { CommentThread } = await import('./CommentThread')

function comment(overrides: Partial<Comment> = {}): Comment {
  return {
    id: 'c1',
    subject_type: 'suggestion',
    subject_id: 's1',
    // Flat, matching the real `CommentOut` wire shape (`server/app/schemas/comment.py`) —
    // not a nested `author` object. See the M3 integration pass's fix note on `Comment` in
    // app/types.ts.
    author_id: 'me',
    author_name: 'Me',
    family_id: null,
    family_color: null,
    body: 'First comment',
    mentions: [],
    edited_at: null,
    created_at: '2027-01-01T00:00:00Z',
    can_edit: true,
    can_delete: true,
    ...overrides,
  }
}

beforeEach(() => {
  list.mockReset()
  create.mockReset()
  removeApi.mockReset()
  undoDelete.mockReset()
  handlers.clear()
  mockUser = { id: 'me' }
  mockStage = { canMutate: true }
})

describe('CommentThread — empty state', () => {
  it('shows the inline empty state with the composer', async () => {
    list.mockResolvedValueOnce([])
    render(<CommentThread subjectType="suggestion" subjectId="s1" />)
    expect(await screen.findByText('No comments yet — start the discussion.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Post' })).toBeInTheDocument()
  })
})

describe('CommentThread — mentions render as tokens', () => {
  it('renders @[Name](user:uuid) markup as a distinct token, not raw markup', async () => {
    list.mockResolvedValueOnce([
      comment({ body: 'Hey @[Jibby](user:11111111-1111-1111-1111-111111111111) look at this' }),
    ])
    render(<CommentThread subjectType="suggestion" subjectId="s1" />)
    await screen.findByText('First comment', { exact: false }).catch(() => {}) // no-op guard
    expect(await screen.findByText('@Jibby')).toBeInTheDocument()
    expect(screen.queryByText(/user:11111111/)).not.toBeInTheDocument()
  })
})

describe('CommentThread — delete → undo (own comment)', () => {
  it('collapses the comment in place with an inline undo affordance, no confirm dialog', async () => {
    list.mockResolvedValueOnce([comment()])
    removeApi.mockResolvedValueOnce(undefined)
    render(<CommentThread subjectType="suggestion" subjectId="s1" />)
    await screen.findByText('First comment')

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument() // own delete: no confirm
    await waitFor(() => expect(screen.getByText('Comment deleted.')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
  })

  it('undo restores the comment to its original position in the thread', async () => {
    list.mockResolvedValueOnce([comment({ id: 'c1', body: 'First' }), comment({ id: 'c2', body: 'Second' })])
    removeApi.mockResolvedValueOnce(undefined)
    render(<CommentThread subjectType="suggestion" subjectId="s1" />)
    await screen.findByText('First')

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete' })
    fireEvent.click(deleteButtons[0]) // delete "First"
    await waitFor(() => expect(screen.getByText('Comment deleted.')).toBeInTheDocument())

    undoDelete.mockResolvedValueOnce(comment({ id: 'c1', body: 'First' }))
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))

    await waitFor(() => expect(screen.getAllByText(/First|Second/)).toHaveLength(2))
    const items = screen.getAllByRole('listitem')
    // "First" is back in position 0, ahead of "Second".
    expect(items[0]).toHaveTextContent('First')
    expect(items[1]).toHaveTextContent('Second')
  })
})

describe('CommentThread — moderation delete (someone else\'s comment)', () => {
  it('opens a confirm dialog and leaves a tombstone rather than reflowing', async () => {
    list.mockResolvedValueOnce([
      comment({ can_edit: false, can_delete: true, author_id: 'other', author_name: 'Alex', family_id: null, family_color: null }),
    ])
    removeApi.mockResolvedValueOnce(undefined)
    render(<CommentThread subjectType="suggestion" subjectId="s1" />)
    await screen.findByText('First comment')

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('alertdialog')).toBeInTheDocument() // moderation: real confirm
    expect(removeApi).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Delete comment' }))
    await waitFor(() => expect(screen.getByText('Comment removed.')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument() // no undo for a moderation delete
  })
})

describe('CommentThread — permission-gated edit/delete', () => {
  it('shows neither edit nor delete when can_edit and can_delete are both false', async () => {
    list.mockResolvedValueOnce([comment({ can_edit: false, can_delete: false })])
    render(<CommentThread subjectType="suggestion" subjectId="s1" />)
    await screen.findByText('First comment')
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('the composer and delete/edit controls are absent once the stage is frozen', async () => {
    mockStage = { canMutate: false }
    list.mockResolvedValueOnce([comment()])
    render(<CommentThread subjectType="suggestion" subjectId="s1" />)
    await screen.findByText('First comment')
    expect(screen.queryByRole('button', { name: 'Post' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    expect(screen.getByText('This trip is frozen — comments are read-only.')).toBeInTheDocument()
  })
})

describe('CommentThread — live comment.created for the open subject', () => {
  it('appends a comment created elsewhere without a manual reload', async () => {
    list.mockResolvedValueOnce([])
    render(<CommentThread subjectType="suggestion" subjectId="s1" />)
    await screen.findByText('No comments yet — start the discussion.')

    // The real broadcast nests the comment under `comment` alongside the subject fields
    // (`server/app/routers/comments.py`'s `_broadcast` calls) — a flattened mock here is
    // exactly the mismatch the M3 integration pass's live Playwright smoke found (the
    // handler read `id`/`body`/`author` straight off the envelope and got `undefined` for
    // all of them).
    const created = comment({ id: 'live-1', body: 'From another tab' })
    emit('comment.created', { subject_type: 'suggestion', subject_id: 's1', comment: created })
    expect(await screen.findByText('From another tab')).toBeInTheDocument()
  })
})
