// Expected numbers below were read from the live Postgres container
// (fn_match_projects, company_esg_timeline, project_scorecard, fund_transactions)
// after `make demo`, so these tests pin the TypeScript port to the real SQL.

import { describe, expect, it } from 'vitest'
import { createDemoState } from './demo'
import {
  ALL_GUARDS, RuleError, SqlError, commitFunds, esgTimeline, failMilestone, latestCommitment, matchReport,
  ngoLeaderboard, projectScorecard, reportImpact, runRace, submitEvidence, terminateCommitment,
  tryLedgerMutation, verifyMilestone,
} from './engine'

const NOW = new Date('2026-10-19T10:00:00Z')
const demo = () => createDemoState(NOW)

describe('demo state matches `make demo`', () => {
  const s = demo()

  it('has one active commitment with the first phase released', () => {
    expect(s.commitments).toHaveLength(1)
    expect(s.phases.map(p => [p.phaseNo, p.amount, p.status])).toEqual([
      [1, 800_000, 'released'], [2, 800_000, 'locked'], [3, 800_000, 'locked'],
    ])
    expect(s.companies[0].committedBudget).toBe(2_400_000)
    expect(s.projects[0].status).toBe('active')
  })

  it('wrote the same two ledger rows and two audit rows', () => {
    expect(s.ledger.map(l => [l.type, l.amount, l.note])).toEqual([
      ['lock', 2_400_000, 'funds locked on match confirmation'],
      ['release', 800_000, 'phase 1 released on verified milestone 1'],
    ])
    expect(s.audit.map(a => a.action)).toEqual(['funds_locked', 'phase_released'])
  })

  it('dates the milestones 90 days apart from commit time', () => {
    expect(s.milestones.map(m => m.dueDate)).toEqual(['2027-01-17', '2027-04-17', '2027-07-16'])
  })
})

describe('matchReport equals fn_match_projects', () => {
  const s = demo()

  it('Meridian: only the Gaya project qualifies', () => {
    const r = matchReport(s, 1).ranked
    expect(r.map(m => m.projectId)).toEqual([2])
    expect(r[0].similarity).toBeCloseTo(0.99679, 4)
    expect(r[0].matchScore).toBeCloseTo(0.88108, 4)
  })

  it('Kalpataru: the handpump project squeaks in on SDG 3 with ~0 similarity', () => {
    const r = matchReport(s, 2).ranked
    expect(r.map(m => m.projectId)).toEqual([3, 4])
    expect(r[0].matchScore).toBeCloseTo(0.9638, 4)
    expect(r[1].similarity).toBeCloseTo(-0.00067, 4)
    expect(r[1].matchScore).toBeCloseTo(0.2991, 4)
    expect(r[1].sharedSdgs).toEqual([3])
  })

  it('Sundar: the over-budget flagged sanitation project is excluded with reasons', () => {
    const rep = matchReport(s, 3)
    expect(rep.ranked.map(m => m.projectId)).toEqual([4])
    expect(rep.ranked[0].matchScore).toBeCloseTo(0.8993, 4)
    const flagged = rep.excluded.find(e => e.projectId === 8)!
    expect(flagged.reasons.some(r => r.includes('flagged'))).toBe(true)
    expect(flagged.reasons.some(r => r.includes('outside'))).toBe(true)
  })
})

describe('window views', () => {
  const s = demo()

  it('esgTimeline equals company_esg_timeline', () => {
    const rows = esgTimeline(s)
    expect(rows.map(r => r.cumulativeImpact)).toEqual([1.2, 3.25, 6.35, 10.75, 16.35, 23.25])
    expect(rows.map(r => r.momDelta)).toEqual([null, 0.85, 1.05, 1.3, 1.2, 1.3])
    expect(rows.map(r => r.rolling3mo)).toEqual([1.2, 1.625, 2.1167, 3.1833, 4.3667, 5.6333])
  })

  it('leaderboard ranks the only funded NGO first, without the join fan-out', () => {
    const rows = ngoLeaderboard(s)
    const vidya = rows.find(r => r.ngoId === 1)!
    expect(vidya.totalImpact).toBe(23.25)
    // The view reported 14,400,000 (6 reports x 2,400,000) until migration 006; the commitment is 2,400,000.
    expect(vidya.totalFunded).toBe(2_400_000)
    expect(vidya.impactPerMillion).toBe(9.6875)
    expect([vidya.sectorRank, vidya.overallPercentile]).toEqual([1, 1])
    expect(rows.find(r => r.ngoId === 2)!.sectorRank).toBe(2)
    expect(rows.find(r => r.ngoId === 3)!.overallPercentile).toBe(0)
  })

  it('scorecard splits the commitment into released and locked', () => {
    const row = projectScorecard(s).find(r => r.projectId === 1)!
    expect([row.committedAmount, row.releasedAmount, row.lockedAmount]).toEqual([2_400_000, 800_000, 1_600_000])
  })
})

describe('fn_commit_funds', () => {
  const s = demo()

  it('commits an approved project and moves it to matched', () => {
    const out = commitFunds(s, { companyId: 1, projectId: 2 }, NOW)
    expect(out.state.projects.find(p => p.id === 2)!.status).toBe('matched')
    expect(out.state.companies[0].committedBudget).toBe(4_200_000)
    expect(out.state.phases.filter(p => p.commitmentId === out.value).map(p => p.amount)).toEqual([600_000, 600_000, 600_000])
    expect(out.state.ledger.at(-1)!.type).toBe('lock')
  })

  it('leaves the original state untouched when it throws', () => {
    expect(() => commitFunds(s, { companyId: 1, projectId: 1 }, NOW)).toThrow(
      'project 1 is active, only approved projects can be funded')
    expect(s.commitments).toHaveLength(1)
  })

  it('refuses a flagged project', () => {
    expect(() => commitFunds(s, { companyId: 3, projectId: 8 }, NOW)).toThrow('project 8 is flagged')
  })

  it('refuses to exceed the mandated budget', () => {
    expect(() => commitFunds(s, { companyId: 3, projectId: 3 }, NOW)).toThrow(
      'company 3 has 2400000.00 remaining, cannot commit 3200000.00')
  })

  it('puts the rounding remainder on the last phase', () => {
    const odd = structuredClone(s)
    odd.projects.find(p => p.id === 2)!.requestedAmount = 1_000_000
    const out = commitFunds(odd, { companyId: 1, projectId: 2 }, NOW)
    const amounts = out.state.phases.filter(p => p.commitmentId === out.value).map(p => p.amount)
    expect(amounts).toEqual([333_333.33, 333_333.33, 333_333.34])
    expect(amounts.reduce((a, b) => a + b, 0)).toBeCloseTo(1_000_000, 2)
  })
})

describe('milestone triggers', () => {
  const s = demo()

  it('releasing needs submitted evidence, then a verification', () => {
    expect(() => verifyMilestone(s, 2, 'reviewer', NOW)).toThrow(RuleError)
    const sub = submitEvidence(s, 2, 3.4, NOW)
    expect(sub.state.phases.find(p => p.id === 2)!.status).toBe('locked')
    expect(sub.state.ledger).toHaveLength(2)
    const ver = verifyMilestone(sub.state, 2, 'reviewer', NOW)
    expect(ver.state.phases.find(p => p.id === 2)!.status).toBe('released')
    expect(ver.state.ledger.at(-1)!.type).toBe('release')
  })

  it('closing out the last phase completes the commitment and closes the project', () => {
    let t = s
    for (const id of [2, 3]) {
      t = submitEvidence(t, id, 1, NOW).state
      t = verifyMilestone(t, id, 'reviewer', NOW).state
    }
    expect(t.commitments[0].status).toBe('completed')
    expect(t.projects[0].status).toBe('closed')
  })

  it('a failed verification holds the phase and flags the project, paying nothing', () => {
    const sub = submitEvidence(s, 2, 0.2, NOW).state
    const out = failMilestone(sub, 2, 'reviewer', NOW)
    expect(out.state.phases.find(p => p.id === 2)!.status).toBe('held')
    expect(out.state.projects[0].status).toBe('flagged')
    expect(out.state.ledger.at(-1)!.type).toBe('hold')
    expect(out.state.ledger.filter(l => l.type === 'release')).toHaveLength(1)
  })
})

// Same scenarios and texts as api/tests/test_writes.py, so the demo says what Postgres says.
describe('fn_terminate_commitment', () => {
  const held = () => failMilestone(submitEvidence(demo(), 2, 0.5, NOW).state, 2, 'reviewer', NOW).state

  it('refunds the phases not yet released and keeps the released one paid', () => {
    const out = terminateCommitment(held(), 1, 'Phase 2 failed verification', 'reviewer', NOW)
    expect(out.value).toBe(1)
    expect(out.effects).toEqual([
      { by: 'fn_terminate_commitment', text: 'Terminated 2 unreleased phases, ₹16,00,000. The ₹8,00,000 already released stays paid.' },
      { by: 'fund_transactions', text: 'Ledger rows appended: terminate for each of the 2 phases, then refund ₹16,00,000.' },
      { by: 'fn_terminate_commitment', text: 'Company budget used is now ₹8,00,000 of ₹90,00,000. Commitment cancelled, project terminated.' },
    ])
    const s = out.state
    expect(s.commitments[0].status).toBe('cancelled')
    expect(s.phases.map(p => p.status)).toEqual(['released', 'terminated', 'terminated'])
    expect(s.projects[0].status).toBe('terminated')
    expect(s.companies[0].committedBudget).toBe(800_000)
    expect(s.ledger.slice(-3).map(l => [l.type, l.amount, l.phaseId])).toEqual([
      ['terminate', 800_000, 2], ['terminate', 800_000, 3], ['refund', 1_600_000, null],
    ])
    expect(s.ledger.at(-3)!.note).toBe('phase 2 terminated: Phase 2 failed verification')
    expect(s.audit.at(-1)).toMatchObject({
      entity: 'commitment', entityId: 1, action: 'commitment_terminated',
      detail: { reason: 'Phase 2 failed verification', by: 'reviewer', released: 800_000, refunded: 1_600_000 },
    })
  })

  it('refuses a blank reason, a second termination and a completed commitment', () => {
    expect(() => terminateCommitment(demo(), 1, '  ', 'r', NOW)).toThrow(
      new SqlError('a reason is required to terminate a commitment'))
    const once = terminateCommitment(demo(), 1, 'first', 'r', NOW).state
    expect(() => terminateCommitment(once, 1, 'second', 'r', NOW)).toThrow(
      new SqlError('commitment 1 is cancelled, only active commitments can be terminated'))
    let done = demo()
    for (const id of [2, 3]) done = verifyMilestone(submitEvidence(done, id, 5, NOW).state, id, 'r', NOW).state
    expect(() => terminateCommitment(done, 1, 'late', 'r', NOW)).toThrow('is completed, only active commitments')
  })

  it('freezes the milestones and progress reports of a terminated project', () => {
    const s = terminateCommitment(demo(), 1, 'NGO withdrew', 'r', NOW).state
    expect(() => submitEvidence(s, 2, 5, NOW)).toThrow(
      new SqlError('commitment 1 is cancelled, its milestones can no longer change'))
    expect(() => reportImpact(s, 1, 3, NOW)).toThrow(
      new RuleError('Project 1 was terminated, so it has no funded work left to report on.'))
    expect(latestCommitment(s, 1)!.status).toBe('cancelled')
  })

  it('frees the budget for another project, but not for the terminated one', () => {
    const s = terminateCommitment(demo(), 1, 'NGO withdrew', 'r', NOW).state
    expect(commitFunds(s, { companyId: 1, projectId: 2 }, NOW).state.companies[0].committedBudget).toBe(
      800_000 + s.projects.find(p => p.id === 2)!.requestedAmount)
    expect(() => commitFunds(s, { companyId: 1, projectId: 1 }, NOW)).toThrow(
      'project 1 is terminated, only approved projects can be funded')
  })

  it('counts only released money in the leaderboard and drops the commitment from the scorecard', () => {
    const s = terminateCommitment(demo(), 1, 'NGO withdrew', 'r', NOW).state
    expect(ngoLeaderboard(s).find(r => r.ngoId === 1)!.totalFunded).toBe(800_000)
    expect(projectScorecard(s).find(r => r.projectId === 1)).toMatchObject({
      status: 'terminated', commitmentId: null, committedAmount: 0,
    })
  })

  it('a later release does not complete a commitment while a phase is held', () => {
    const s = verifyMilestone(submitEvidence(held(), 3, 5, NOW).state, 3, 'r', NOW)
    expect(s.effects.some(e => e.text.includes('completed'))).toBe(false)
    expect(s.state.commitments[0].status).toBe('active')
    expect(s.state.phases.map(p => p.status)).toEqual(['released', 'held', 'released'])
    expect(s.state.projects[0].status).toBe('flagged')
  })
})

describe('append-only ledger', () => {
  it('rejects UPDATE and DELETE with the trigger message', () => {
    const s = demo()
    expect(() => tryLedgerMutation(s, 'UPDATE', 2)).toThrow(
      new SqlError('fund_transactions is append-only (attempted UPDATE on id 2)'))
    expect(() => tryLedgerMutation(s, 'DELETE', 1)).toThrow('attempted DELETE on id 1')
  })
})

describe('double-funding race', () => {
  const run = (g: Partial<typeof ALL_GUARDS>) => runRace({ ...ALL_GUARDS, ...g }, NOW)

  it('with every layer on, exactly one session wins and layer 1 stops the other', () => {
    const r = run({})
    expect([r.winner, r.stoppedBy, r.activeCommitments, r.committed]).toEqual(['A', 1, 1, 100_000])
    expect(r.message).toBe('project 1 is matched, only approved projects can be funded')
  })

  it('each layer catches it when the one before is removed', () => {
    expect(run({ statusCheck: false }).stoppedBy).toBe(2)
    expect(run({ statusCheck: false }).message).toBe('project 1 already has active commitment 1')
    expect(run({ statusCheck: false, guardTrigger: false }).stoppedBy).toBe(3)
    expect(run({ statusCheck: false, guardTrigger: false }).message).toContain('uniq_active_commitment_per_project')
  })

  it('with every layer off, the project is funded twice', () => {
    const r = run({ statusCheck: false, guardTrigger: false, uniqueIndex: false })
    expect([r.winner, r.stoppedBy, r.activeCommitments, r.committed]).toEqual([null, null, 2, 200_000])
  })
})

describe('monthly progress', () => {
  it('appends the next month and the timeline window functions recompute', () => {
    const out = reportImpact(demo(), 1, 8.2, NOW)
    const rows = esgTimeline(out.state)
    const last = rows.at(-1)!
    expect(last.month).toBe('2026-09-01')
    expect([last.monthImpact, last.momDelta, last.cumulativeImpact]).toEqual([8.2, 1.3, 31.45])
    expect(last.rolling3mo).toBeCloseTo((5.6 + 6.9 + 8.2) / 3, 4)
  })

  it('refuses to report progress on a project nobody funded', () => {
    expect(() => reportImpact(demo(), 2, 1, NOW)).toThrow(RuleError)
  })
})
