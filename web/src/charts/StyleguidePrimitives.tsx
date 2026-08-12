/**
 * `/styleguide` — primitives section.
 *
 * Renders the primitives that actually exist in `web/src/app/ui/` and `web/src/design/`
 * today. Two things design-system.md's Phase 5/6 wish list names are not implemented yet
 * — a dedicated `Chip` and a general-purpose `EmptyState` — and this page says so rather
 * than fabricating a component to fill the slot; `plan/features/design-system/tasks.md`
 * reflects the same gap (their checkboxes stay unticked).
 */

import { useState } from 'react'
import { Banner, Button, Skeleton, Spinner, TextField } from '../app/ui/primitives'
import { useToast } from '../app/ui/toastContext'
import { ToastProvider } from '../app/ui/toast'
import { BottomSheet } from '../app/BottomSheet'
import { IdentityBadge } from '../design/IdentityBadge'
import { ChartEmptyState } from './a11y'
import './StyleguidePrimitives.css'

function ButtonGallery() {
  return (
    <div className="k-sg-row">
      {(['primary', 'secondary', 'ghost'] as const).map((variant) => (
        <div key={variant} className="k-sg-button-col">
          <span className="k-sg-caption">{variant}</span>
          <Button variant={variant}>Default</Button>
          <Button variant={variant} busy>
            Loading
          </Button>
          <Button variant={variant} disabled>
            Disabled
          </Button>
        </div>
      ))}
    </div>
  )
}

function FieldGallery() {
  const [filled, setFilled] = useState('Cornwall, July 2027')
  return (
    <div className="k-sg-field-grid">
      <div>
        <span className="k-sg-caption">Default (empty)</span>
        <TextField label="Trip name" placeholder="e.g. Cornwall 2027" />
      </div>
      <div>
        <span className="k-sg-caption">Focus — this field has real DOM focus, not a simulated style</span>
        <TextField label="Trip name" autoFocus defaultValue="" />
      </div>
      <div>
        <span className="k-sg-caption">Filled</span>
        <TextField label="Trip name" value={filled} onChange={(e) => setFilled(e.target.value)} />
      </div>
      <div>
        <span className="k-sg-caption">Error</span>
        <TextField label="Trip name" defaultValue="" error="A trip needs a name." />
      </div>
      <div>
        <span className="k-sg-caption">Disabled</span>
        <TextField label="Trip name" defaultValue="Cornwall, July 2027" disabled />
      </div>
      <div>
        <span className="k-sg-caption">Hint</span>
        <TextField label="Trip name" defaultValue="" hint="Members will see this on every screen." />
      </div>
      <p className="k-sg-note">
        Hover has no static representation — tab or mouse over the fields above to verify
        it (and the focus ring) in both themes.
      </p>
    </div>
  )
}

function ToastDemo() {
  const showToast = useToast()
  return (
    <div className="k-sg-row">
      <Button variant="secondary" onClick={() => showToast('Suggestion added to the board.')}>
        Trigger a toast
      </Button>
      <p className="k-sg-note">
        Imperative, `aria-live="polite"`, auto-dismisses — never used for information that
        must persist (that's a notification, per design-system.md).
      </p>
    </div>
  )
}

function SkeletonGallery() {
  return (
    <div className="k-sg-skeleton-stack">
      <Skeleton height="var(--text-heading)" width="60%" />
      <Skeleton height="var(--text-body)" width="80%" />
      <Skeleton height="var(--space-6)" />
    </div>
  )
}

function BottomSheetDemo() {
  const [open, setOpen] = useState(false)
  return (
    <div className="k-sg-row">
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Open bottom sheet
      </Button>
      <BottomSheet open={open} title="Trip details" onClose={() => setOpen(false)}>
        <p>Focus-trapped, Escape closes, drag or the handle button changes snap point.</p>
      </BottomSheet>
    </div>
  )
}

function BadgeGallery() {
  return (
    <div className="k-sg-row">
      <IdentityBadge initials="AR" familyColor="var(--family-1)" name="Ana R." size={24} />
      <IdentityBadge initials="TP" familyColor="var(--family-4)" name="Tom P." size={32} />
      <IdentityBadge initials="MJ" familyColor="var(--family-7)" name="Mei J." size={40} offline />
      <IdentityBadge initials="SK" familyColor={null} name="Sam K. (no family yet)" size={32} />
    </div>
  )
}

export function StyleguidePrimitives() {
  return (
    // Self-contained: /styleguide is already mounted inside the app's own ToastProvider
    // (App.tsx) in production, but this section's own unit test renders it standalone,
    // and a gallery shouldn't assume it's wired into the app shell anyway. Nested
    // providers are harmless — `useToast` always resolves to the nearest one.
    <ToastProvider>
      <div className="k-sg-primitives">
        <p className="k-sg-subhead">Buttons</p>
        <ButtonGallery />

        <p className="k-sg-subhead">Fields</p>
        <FieldGallery />

        <p className="k-sg-subhead">Banners</p>
        <div className="k-sg-row">
          <Banner tone="error">Something needs your attention.</Banner>
          <Banner tone="info">Just so you know.</Banner>
        </div>

        <p className="k-sg-subhead">Spinner</p>
        <div className="k-sg-row">
          <Spinner />
        </div>

        <p className="k-sg-subhead">Toast</p>
        <ToastDemo />

        <p className="k-sg-subhead">Skeleton</p>
        <SkeletonGallery />

        <p className="k-sg-subhead">Bottom sheet</p>
        <BottomSheetDemo />

        <p className="k-sg-subhead">
          Identity badges (family colour + initials — the closest thing to a "chip" today)
        </p>
        <BadgeGallery />

        <p className="k-sg-subhead">Empty state</p>
        <p className="k-sg-note">
          There is no general-purpose `EmptyState` primitive in `web/src/app/ui/` yet
          (design-system tasks.md Phase 5 is unticked for it). The chart-specific version
          below is the only implementation that exists today:
        </p>
        <ChartEmptyState insight="No suggestions yet" message="No suggestions yet — drop the first pin." />
      </div>
    </ToastProvider>
  )
}
