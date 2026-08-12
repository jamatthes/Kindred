/**
 * A suggestion's voting mode, resolved from `trip_category_settings` by its `type`
 * (`design.md`: "A suggestion's mode is determined by its `type`... never denormalise the
 * mode onto a vote row"). Reuses `polls/api.ts`'s `categoryApi` — see the note in
 * `./api.ts` on why this feature does not define a second client for the same read.
 *
 * Re-read on a `422` mode-mismatch (`design.md`'s edge case: "the client refetches settings
 * in case it was stale") and on `category_settings.updated`, so the control switches shape
 * live if the admin changes the mode mid-session.
 */

import { useCallback, useEffect, useState } from 'react'
import { socket } from '../../app/socket'
import { categoryApi } from '../polls/api'
import type { SuggestionType, VotingMode } from '../../app/types'

export function useCategoryMode(suggestionType: SuggestionType): { mode: VotingMode; refetch: () => Promise<void> } {
  const [mode, setMode] = useState<VotingMode>('score')

  const load = useCallback(async () => {
    try {
      const rows = await categoryApi.read()
      // `SuggestionType` (region/accommodation/activity/meal) is a subset of
      // `VotingCategory`, which also has `poll` — the suggestion's own `type` string is the
      // category key directly, no translation table needed.
      const row = rows.find((r) => r.category === suggestionType)
      if (row) setMode(row.voting_mode)
    } catch {
      // A failure here must not break the vote control; it keeps whatever mode it last knew.
    }
  }, [suggestionType])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => socket.subscribe('category_settings.updated', () => void load()), [load])

  return { mode, refetch: load }
}
