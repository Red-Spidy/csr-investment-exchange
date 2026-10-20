import type { Band, Tone } from '../components/Cloth'
import type { CommitmentView } from '../data/api'

/** "Rural school attendance drive, Barmer" -> "Rural school attendance drive" */
export const shortTitle = (title: string) => title.split(',')[0]

/** "Meridian Industries Ltd" -> "Meridian" */
export const shortCompany = (name: string) => name.split(' ')[0]

/** One band per phase. A locked phase whose evidence is in shows as awaiting review. */
export function commitmentBands(v: CommitmentView): Band[] {
  return v.phases.map(p => {
    const ms = v.milestones.find(m => m.phaseNo === p.phaseNo)
    const tone: Tone =
      p.status === 'released' ? 'released'
      : p.status === 'held' ? 'held'
      : ms?.verification === 'submitted' ? 'review'
      : 'locked'
    return {
      key: `${v.commitment.id}-${p.phaseNo}`,
      amount: p.amount,
      tone,
      label: `Phase ${p.phaseNo}`,
      hint: `${shortTitle(v.project.title)}, phase ${p.phaseNo}`,
    }
  })
}

export function sumByTone(bands: Band[]): Record<Tone, number> {
  const out: Record<Tone, number> = { released: 0, locked: 0, review: 0, held: 0, free: 0 }
  for (const b of bands) out[b.tone] += b.amount
  return out
}
