/**
 * The families view (FM-4).
 *
 * Family **cards**, not a data table. `design.md` describes a table with tri-state sort;
 * the agreed mockup (`design-preview/screen-families.html`) is a card grid, and
 * `plan/overview.md`'s UI-first rule says feature UI starts from the agreed mockup. The
 * reason the mockup is right here: a trip has at most eight families, each with a handful of
 * members, so the thing worth showing at a glance is *who is in each family* — which a card
 * can hold and a row cannot. Sorting eight rows is a solution to a problem this screen does
 * not have. Recorded as a NOTE in `design.md`.
 *
 * The card is the "table" half of the map/table pair. The map half — one home pin per placed
 * family — waits for the map shell (M2); until then a placed family says so in words and an
 * unplaced one is listed rather than silently missing, which is the rule that actually
 * mattered.
 */

import { useMemo, useState } from 'react'
import { useSession } from '../../app/session'
import { useNavigate } from '../../app/router'
import { Banner, Button, Skeleton } from '../../app/ui/primitives'
import { IdentityBadge } from '../../design/IdentityBadge'
import type { Family, FamilyDetail } from '../../app/types'
import { useFamilies, useFamilyDetail } from './useFamilies'
import { FamilyPanel } from './FamilyPanel'
import { NewFamilyInviteCard } from './InviteBlock'
import { CreateFamilyForm } from './CreateFamilyForm'
import { ROLE_LABEL } from './labels'
import './families.css'

function MemberLine({ family }: { family: FamilyDetail }) {
  return (
    <ul className="fcard__members">
      {family.members.map((member) => (
        <li key={member.user_id} className="mrow">
          <IdentityBadge
            initials={member.initials}
            familyColor={family.color}
            avatarThumbUrl={member.avatar_thumb_url}
            size={24}
            name={member.display_name}
          />
          <span className="mrow__name">{member.display_name}</span>
          {/* Role in words, never colour or an icon alone. */}
          <span className="mrow__role">{ROLE_LABEL[member.role]}</span>
        </li>
      ))}
    </ul>
  )
}

function FamilyCard({
  family,
  isMine,
  onOpen,
}: {
  family: Family
  isMine: boolean
  onOpen: () => void
}) {
  const detail = useFamilyDetail(family.id)

  return (
    <button
      type="button"
      className={`fcard${isMine ? ' fcard--mine' : ''}`}
      onClick={onOpen}
      aria-label={`Open ${family.name}`}
    >
      <span className="fcard__head">
        <span
          className="fcard__dot"
          style={{ background: `var(--family-${family.color})` }}
          aria-hidden="true"
        />
        <span className="fcard__name">{family.name}</span>
        <span className="fcard__count">
          {family.member_count} {family.member_count === 1 ? 'member' : 'members'}
        </span>
      </span>

      <span className="fcard__locality">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M12 21s7-6.3 7-11a7 7 0 1 0-14 0c0 4.7 7 11 7 11z" />
          <circle cx="12" cy="10" r="2.6" />
        </svg>
        {family.home_locality ?? (family.geocode_status === 'pending' ? 'No home set' : 'Not placed')}
        <span className="fcard__privacy">
          {/* Family names usually already carry an article ("The Parkers"), so the copy
              must not add a second one. */}
          {isMine ? 'your family' : 'home address visible to them only'}
        </span>
      </span>

      {detail.family ? <MemberLine family={detail.family} /> : null}
    </button>
  )
}

export function FamiliesScreen({ selectedId }: { selectedId?: string }) {
  const { user } = useSession()
  const navigate = useNavigate()
  const { families, loading, error } = useFamilies()
  const [creating, setCreating] = useState(false)

  // What to *render*. The server refuses regardless, so this is a courtesy — but a control
  // that is visible and always fails is worse than one that was never offered.
  const isOrganiser = Boolean(user?.is_organiser)

  const totalMembers = useMemo(
    () => families.reduce((sum, f) => sum + f.member_count, 0),
    [families],
  )

  if (loading) {
    return (
      <div className="families" aria-busy="true">
        <Skeleton height="var(--text-sub)" width="40%" />
        <div className="families__grid">
          <Skeleton height="var(--space-6)" />
          <Skeleton height="var(--space-6)" />
        </div>
      </div>
    )
  }

  return (
    <div className="families">
      <header className="families__head">
        <h1>Families</h1>
        <p className="families__sub">
          {families.length} {families.length === 1 ? 'family' : 'families'} · {totalMembers}{' '}
          {totalMembers === 1 ? 'member' : 'members'} · everyone belongs to exactly one family
        </p>
      </header>

      {error ? <Banner tone="error">{error}</Banner> : null}

      {families.length === 0 ? (
        <div className="families__empty">
          {isOrganiser ? (
            <>
              <p>No families yet — create the first one.</p>
              <Button onClick={() => setCreating(true)}>Create a family</Button>
            </>
          ) : (
            <p>The trip organiser hasn&apos;t added any families yet.</p>
          )}
        </div>
      ) : (
        <div className="families__grid">
          {families.map((family) => (
            <FamilyCard
              key={family.id}
              family={family}
              isMine={family.id === user?.family?.id}
              onOpen={() => navigate({ name: 'families', familyId: family.id })}
            />
          ))}
          {isOrganiser ? <NewFamilyInviteCard onCreateFamily={() => setCreating(true)} /> : null}
        </div>
      )}

      {creating ? (
        <CreateFamilyForm
          onClose={() => setCreating(false)}
          onCreated={(family) => {
            setCreating(false)
            navigate({ name: 'families', familyId: family.id })
          }}
        />
      ) : null}

      {selectedId ? (
        <FamilyPanel familyId={selectedId} onClose={() => navigate({ name: 'families' })} />
      ) : null}
    </div>
  )
}
