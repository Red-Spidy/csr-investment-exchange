import type { ImpactReport } from '../data/types'

/** What an NGO has reported for one project: each report is that month's gain, so they add up. */
export function progressSoFar(reports: ImpactReport[], projectId: number): { total: number; months: number } {
  const mine = reports.filter(r => r.projectId === projectId)
  const total = Math.round(mine.reduce((t, r) => t + r.metricValue, 0) * 100) / 100
  return { total, months: mine.length }
}

/** The share of the promised gain reported so far, or null when the proposal promised nothing measurable. */
export function shareOfPromise(total: number, promised: number | null): number | null {
  return promised && promised > 0 ? total / promised : null
}
