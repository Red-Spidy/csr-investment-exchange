// Opt-in contract test: the browser demo is a port of the database rules, and this
// checks the port has not drifted from the real thing. It compares what the FastAPI
// service returns for a freshly seeded database with what the demo engine returns.
//
//   make reset seed && make api            (in the repo root)
//   VITE_PARITY_API_URL=http://127.0.0.1:8000 npm test
//
// It is skipped unless that variable is set, because it needs a running API.

import { describe, expect, it } from 'vitest'
import { createDemoApi } from './demoApi'
import { createHttpApi } from './httpApi'

const base = import.meta.env.VITE_PARITY_API_URL as string | undefined

/** Timestamps and due dates depend on when each side was seeded; everything else must match. */
const CLOCK = new Set(['lockedAt', 'releasedAt', 'reportedAt', 'verifiedAt', 'createdAt', 'dueDate'])

function stripClock<T>(value: T): T {
  return JSON.parse(JSON.stringify(value, (key, v) => (CLOCK.has(key) ? undefined : v)))
}

describe.skipIf(!base)('the live API equals the browser demo on the seeded database', () => {
  const live = createHttpApi(`${base}/api`)
  const demo = createDemoApi()

  it('companies', async () => {
    expect(await live.companies()).toEqual(await demo.companies())
  })

  it('rulebooks (the demo-only vector parameters aside)', async () => {
    const strip = (rows: Awaited<ReturnType<typeof live.rulebooks>>) =>
      rows.map(({ topic: _t, jitter: _j, ...rest }) => rest)
    expect(strip(await live.rulebooks())).toEqual(strip(await demo.rulebooks()))
  })

  it('project_scorecard', async () => {
    expect(await live.scorecard()).toEqual(await demo.scorecard())
  })

  it.each([1, 2, 3])('fn_match_projects for rulebook %i, with the reasons for every exclusion', async id => {
    const [a, b] = [await live.matches(id), await demo.matches(id)]
    const round = (n: number) => Math.round(n * 1e4) / 1e4
    expect(a.excluded).toEqual(b.excluded)
    expect(a.ranked.map(m => m.projectId)).toEqual(b.ranked.map(m => m.projectId))
    for (const [i, m] of a.ranked.entries()) {
      const want = b.ranked[i]
      expect(round(m.matchScore)).toBe(round(want.matchScore))
      expect(round(m.similarity)).toBe(round(want.similarity))
      expect(m.sharedSdgs).toEqual(want.sharedSdgs)
      expect(m.sdgs).toEqual(want.sdgs)
      expect(round(m.contributions.similarity)).toBe(round(want.contributions.similarity))
    }
  })

  it('commitments, phases and milestones', async () => {
    expect(stripClock(await live.commitments())).toEqual(stripClock(await demo.commitments()))
  })

  it('the ledger and audit log', async () => {
    expect(stripClock(await live.ledger())).toEqual(stripClock(await demo.ledger()))
    expect(stripClock(await live.audit())).toEqual(stripClock(await demo.audit()))
  })

  it('company_esg_timeline', async () => {
    expect(await live.esgTimeline()).toEqual(await demo.esgTimeline())
  })

  it('ngo_leaderboard', async () => {
    expect(await live.leaderboard()).toEqual(await demo.leaderboard())
  })

  it('project detail for a funded and an unfunded project', async () => {
    const strip = (d: Awaited<ReturnType<typeof live.projectDetail>>) =>
      stripClock({ ...d, extraction: d.extraction && { ...d.extraction, topic: 0, jitter: 0 } })
    for (const id of [1, 2, 8]) {
      expect(strip(await live.projectDetail(id))).toEqual(strip(await demo.projectDetail(id)))
    }
  })
})
