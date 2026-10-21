// Opt-in contract test: the browser demo is a port of the database rules, and this
// checks the port has not drifted from the real thing. It compares what the FastAPI
// service returns for a freshly seeded database with what the demo engine returns.
//
//   make reset seed && make api            (in the repo root)
//   VITE_PARITY_API_URL=http://127.0.0.1:8000 npm test
//
// It is skipped unless that variable is set, because it needs a running API.
//
// VITE_PARITY_WRITES=1 also replays a write scenario on both sides and compares the
// receipts and the resulting state. It resets the live database before and after, so
// it needs CSR_ALLOW_RESET=1 (make api sets it) and it discards whatever was there.

import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { ActionResult, ExchangeApi } from './api'
import { createDemoApi } from './demoApi'
import { createHttpApi } from './httpApi'

const base = import.meta.env.VITE_PARITY_API_URL as string | undefined
const writes = import.meta.env.VITE_PARITY_WRITES === '1'

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

describe.skipIf(!base || !writes)('the live API equals the browser demo after the same writes', () => {
  const live = createHttpApi(`${base}/api`)
  const demo = createDemoApi()

  beforeAll(() => live.reset())
  afterAll(() => live.reset())

  it('fail a milestone, release the next one, then terminate the commitment', async () => {
    const steps: [string, (api: ExchangeApi) => Promise<ActionResult>][] = [
      ['evidence 2', api => api.submitEvidence(2, 0.5)],
      ['fail 2', api => api.failMilestone(2)],
      ['evidence 3', api => api.submitEvidence(3, 5)],
      ['verify 3', api => api.verifyMilestone(3)],
      ['blank reason', api => api.terminateCommitment(1, '   ')],
      ['terminate', api => api.terminateCommitment(1, 'Phase 2 failed verification')],
      ['terminate again', api => api.terminateCommitment(1, 'again')],
      ['milestone after', api => api.failMilestone(3)],
      ['report after', api => api.reportImpact(1, 3)],
    ]
    // The reviewer's name comes from CSR_REVIEWER on the server and is fixed in the demo,
    // so each side's name is read off its first receipt and masked everywhere.
    const names = { live: '', demo: '' }
    const signer = (r: ActionResult) => (r.ok ? r.effects[0].text.match(/marked \w+ by (.+)\.$/)?.[1] : undefined)
    const mask = <T>(v: T, name: string): T =>
      (name ? JSON.parse(JSON.stringify(v).split(name).join('<reviewer>')) : v)
    const same = async <T>(read: (api: ExchangeApi) => Promise<T>, label: string) =>
      expect(mask(stripClock(await read(live)), names.live), label)
        .toEqual(mask(stripClock(await read(demo)), names.demo))

    for (const [name, step] of steps) {
      const [a, b] = [await step(live), await step(demo)]
      names.live ||= signer(a) ?? ''
      names.demo ||= signer(b) ?? ''
      expect(mask(a, names.live), name).toEqual(mask(b, names.demo))
    }
    expect([names.live, names.demo].every(Boolean), 'a receipt named each reviewer').toBe(true)
    await same(api => api.commitments(), 'commitments')
    await same(api => api.ledger(), 'ledger')
    await same(api => api.audit(), 'audit')
    await same(api => api.companies(), 'companies')
    await same(api => api.scorecard(), 'scorecard')
    await same(api => api.leaderboard(), 'leaderboard')
    await same(api => api.esgTimeline(), 'esg timeline')
    await same(async api => (await api.projectDetail(1)).commitment, 'project 1 funding')
  })
})
