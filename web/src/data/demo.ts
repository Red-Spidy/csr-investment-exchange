import { commitFunds, submitEvidence, verifyMilestone } from './engine'
import { SEED, SEED_IMPACT_REPORTS } from './seed'
import type { DbState } from './types'

/**
 * The state `make demo` leaves behind: Meridian funds the Barmer attendance
 * project through the commit function, phase 1 is verified (which releases the
 * first tranche through the trigger), and six months of progress are reported.
 */
export function createDemoState(now: Date = new Date()): DbState {
  let s: DbState = structuredClone(SEED)
  s = commitFunds(s, { companyId: 1, projectId: 1, amount: 2_400_000 }, now).state
  s = submitEvidence(s, 1, 3.1, now).state
  s = verifyMilestone(s, 1, 'seed', now).state
  for (const [month, value] of SEED_IMPACT_REPORTS) {
    s.seq.impactReports += 1
    s.impactReports.push({ id: s.seq.impactReports, projectId: 1, periodMonth: month, metricValue: value })
  }
  return s
}
