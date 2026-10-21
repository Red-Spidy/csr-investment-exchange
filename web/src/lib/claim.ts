import type { Extraction } from '../data/types'

type Target = NonNullable<Extraction['targetMetric']>

/** Metrics that start from nothing ("add 320 hectares"): the target is the whole claim. */
const FROM_ZERO = new Set(['hectares', 'tonnes_per_month', 'percent_increase'])

/**
 * How much a proposal promises, in its own units, or null when that cannot be
 * known: a reader that found the target but not the baseline cannot say how
 * far the project means to move, and guessing a baseline of zero would invent
 * a promise the proposal never made.
 */
export function promisedChange(t: Target | null | undefined): number | null {
  if (!t || t.target == null) return null
  if (t.baseline != null) return Math.abs(t.target - t.baseline)
  return FROM_ZERO.has(t.unit) ? t.target : null
}
