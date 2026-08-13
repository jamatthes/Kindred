/**
 * Guessing our `SuggestionType` from Google's place categories.
 *
 * Google returns a `types[]` array — `['lodging', 'point_of_interest', 'establishment']` for
 * a hotel — where the useful category sits next to two near-universal filler entries. We map
 * the first entry we recognise to one of our four types (`design.md` > "Type inference from
 * Places"), which the create form then *preselects rather than imposes*: the user can change
 * it in the same dropdown they would have used anyway, so a wrong guess costs one click and a
 * right one costs nothing.
 *
 * Deliberately a plain lookup over a list, not a scoring model. The order the caller receives
 * from Google is already most-specific-first, so "first recognised wins" needs no tie-break,
 * and a table anyone can read and extend beats cleverness for something whose failure mode is
 * a preselected dropdown.
 *
 * Costs nothing: predictions already carry `types`, and `types` is a Basic-tier Place Details
 * field. No request exists because of this file.
 */

import type { SuggestionType } from '../../app/types'

const TYPE_BY_GOOGLE_CATEGORY: Record<string, SuggestionType> = {
  // Somewhere to sleep.
  lodging: 'accommodation',
  hotel: 'accommodation',
  motel: 'accommodation',
  resort_hotel: 'accommodation',
  guest_house: 'accommodation',
  bed_and_breakfast: 'accommodation',
  hostel: 'accommodation',
  campground: 'accommodation',
  camping_cabin: 'accommodation',
  rv_park: 'accommodation',
  cottage: 'accommodation',

  // Somewhere to eat.
  restaurant: 'meal',
  cafe: 'meal',
  coffee_shop: 'meal',
  bar: 'meal',
  pub: 'meal',
  bakery: 'meal',
  meal_takeaway: 'meal',
  meal_delivery: 'meal',
  food: 'meal',
  ice_cream_shop: 'meal',

  // Somewhere to go and do something.
  tourist_attraction: 'activity',
  museum: 'activity',
  art_gallery: 'activity',
  park: 'activity',
  national_park: 'activity',
  zoo: 'activity',
  aquarium: 'activity',
  amusement_park: 'activity',
  water_park: 'activity',
  stadium: 'activity',
  movie_theater: 'activity',
  spa: 'activity',
  beach: 'activity',
  hiking_area: 'activity',
  church: 'activity',
  castle: 'activity',

  // An area rather than a point.
  locality: 'region',
  sublocality: 'region',
  neighborhood: 'region',
  postal_town: 'region',
  administrative_area_level_1: 'region',
  administrative_area_level_2: 'region',
  country: 'region',
}

/** The fallback when nothing matches. Now that `other` exists, it is the honest answer: the
 *  guess previously defaulted to `activity`, which quietly asserted a category for every
 *  unrecognised place (a shop, a car park, a friend's house) and made `activity` mean
 *  "everything we could not identify". `other` says what is actually known — nothing — and
 *  the user can still change it in one click. */
export const DEFAULT_SUGGESTION_TYPE: SuggestionType = 'other'

/**
 * The best guess for `types`, or `DEFAULT_SUGGESTION_TYPE` when nothing is recognised.
 * Never throws and never returns null: the caller is filling in a required dropdown, and a
 * guess it can correct is more useful than an empty field it must fill.
 */
export function inferSuggestionType(types: readonly string[] | undefined | null): SuggestionType {
  for (const type of types ?? []) {
    const match = TYPE_BY_GOOGLE_CATEGORY[type]
    if (match) return match
  }
  return DEFAULT_SUGGESTION_TYPE
}
