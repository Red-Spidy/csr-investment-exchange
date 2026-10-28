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

/**
 * The bar: how much of the promise a project should have reached by now, the promised
 * gain spread evenly over its months. The same rule the server's rater uses.
 */
export function expectedByNow(promised: number | null, monthsDone: number, durationMonths: number): number | null {
  return promised != null && durationMonths > 0 ? promised * monthsDone / durationMonths : null
}

/** A project's newest monthly report, or null before its first. */
export function latestReport(reports: ImpactReport[], projectId: number): ImpactReport | null {
  return reports.filter(r => r.projectId === projectId)
    .reduce<ImpactReport | null>((last, r) => (!last || r.periodMonth > last.periodMonth ? r : last), null)
}
