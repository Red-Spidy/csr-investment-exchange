import { describe, expect, it } from 'vitest'
import type { CommitmentView } from '../data/api'
import type { FundPhase, Milestone } from '../data/types'
import { openMilestone } from './milestones'

const phase = (phaseNo: number, status: FundPhase['status']): FundPhase =>
  ({ id: phaseNo, commitmentId: 1, phaseNo, amount: 100, status, releasedAt: null })
const milestone = (phaseNo: number, verification: Milestone['verification']): Milestone => ({
  id: 10 + phaseNo, projectId: 1, commitmentId: 1, phaseNo, description: `Phase ${phaseNo} deliverable`,
  dueDate: '2027-01-01', reportedAt: null, evidenceUri: null, reportedMetric: null, verification,
  verifiedBy: null, verifiedAt: null,
})
const view = (status: CommitmentView['commitment']['status'], phases: FundPhase[], milestones: Milestone[]) =>
  ({ commitment: { status }, phases, milestones } as unknown as CommitmentView)

describe('openMilestone: the milestone an NGO can report on now', () => {
  it('is the first phase not yet paid', () => {
    const v = view('active', [phase(2, 'locked'), phase(1, 'released'), phase(3, 'locked')],
      [milestone(1, 'verified'), milestone(2, 'pending'), milestone(3, 'pending')])
    expect(openMilestone(v)?.phaseNo).toBe(2)
  })
  it('stays open while its evidence waits for the reviewer', () => {
    const v = view('active', [phase(1, 'locked'), phase(2, 'locked')], [milestone(1, 'submitted'), milestone(2, 'pending')])
    expect(openMilestone(v)?.verification).toBe('submitted')
  })
  it('is none while an earlier phase is held', () => {
    const v = view('active', [phase(1, 'held'), phase(2, 'locked')], [milestone(1, 'failed'), milestone(2, 'pending')])
    expect(openMilestone(v)).toBeNull()
  })
  it('is none once every phase is paid, or the commitment has ended', () => {
    expect(openMilestone(view('active', [phase(1, 'released')], [milestone(1, 'verified')]))).toBeNull()
    expect(openMilestone(view('cancelled', [phase(1, 'locked')], [milestone(1, 'pending')]))).toBeNull()
  })
})
