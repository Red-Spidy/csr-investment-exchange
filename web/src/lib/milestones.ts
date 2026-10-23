import type { CommitmentView } from '../data/api'

/** The milestone an NGO can act on now: the first phase still locked, with every earlier one paid. */
export function openMilestone(v: CommitmentView) {
  if (v.commitment.status !== 'active') return null
  const phases = [...v.phases].sort((a, b) => a.phaseNo - b.phaseNo)
  const next = phases.find(p => p.status !== 'released')
  if (!next || next.status !== 'locked') return null
  return v.milestones.find(m => m.phaseNo === next.phaseNo) ?? null
}
