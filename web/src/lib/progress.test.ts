import { describe, expect, it } from 'vitest'
import type { ImpactReport } from '../data/types'
import { progressSoFar, shareOfPromise } from './progress'

const report = (id: number, projectId: number, periodMonth: string, metricValue: number): ImpactReport =>
  ({ id, projectId, periodMonth, metricValue })

const seeded = [1.2, 0.85, 1.05, 1.3, 1.2, 1.3].map((v, i) => report(i + 1, 1, `2026-0${i + 3}-01`, v))

describe('progressSoFar: what an NGO has reported for one project', () => {
  it('adds the monthly gains, rounded to two decimals', () => {
    expect(progressSoFar(seeded, 1)).toEqual({ total: 6.9, months: 6 })
  })
  it('counts only that project', () => {
    expect(progressSoFar([...seeded, report(7, 2, '2026-03-01', 4)], 2)).toEqual({ total: 4, months: 1 })
  })
  it('is zero over zero months before the first report', () => {
    expect(progressSoFar(seeded, 3)).toEqual({ total: 0, months: 0 })
  })
})

describe('shareOfPromise: how much of the promised gain is reported', () => {
  it('is the reported total over the promised change', () => {
    expect(shareOfPromise(6.9, 8)).toBeCloseTo(0.8625, 6)
  })
  it('is unknown when nothing measurable was promised', () => {
    expect(shareOfPromise(6.9, null)).toBeNull()
    expect(shareOfPromise(6.9, 0)).toBeNull()
  })
})
