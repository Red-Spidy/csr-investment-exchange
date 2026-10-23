import type { PhaseStatus, ProjectStatus, TxnType, Verification } from '../data/types'

export const SDG_NAMES: Record<number, string> = {
  1: 'No poverty',
  2: 'Zero hunger',
  3: 'Good health and well-being',
  4: 'Quality education',
  5: 'Gender equality',
  6: 'Clean water and sanitation',
  7: 'Affordable and clean energy',
  8: 'Decent work and economic growth',
  9: 'Industry, innovation and infrastructure',
  10: 'Reduced inequalities',
  11: 'Sustainable cities and communities',
  12: 'Responsible consumption and production',
  13: 'Climate action',
  14: 'Life below water',
  15: 'Life on land',
  16: 'Peace, justice and strong institutions',
  17: 'Partnerships for the goals',
}

export const sdgName = (n: number) => SDG_NAMES[n] ?? `SDG ${n}`

export const SECTOR_LABEL: Record<string, string> = {
  education: 'Education',
  healthcare: 'Healthcare',
  water_sanitation: 'Water and sanitation',
  environment: 'Environment',
  livelihood: 'Livelihood',
}
export const sectorLabel = (s: string) => SECTOR_LABEL[s] ?? s

export const STATUS_LABEL: Record<ProjectStatus, string> = {
  pending: 'Submitted',
  scoring: 'Scoring',
  approved: 'Approved',
  flagged: 'In review',
  rejected: 'Rejected',
  matched: 'Matched',
  active: 'Funded',
  closed: 'Closed',
  terminated: 'Terminated',
}

export const PHASE_LABEL: Record<PhaseStatus, string> = {
  locked: 'Locked',
  released: 'Released',
  held: 'Held',
  terminated: 'Terminated',
}

export const VERIFICATION_LABEL: Record<Verification, string> = {
  pending: 'Waiting for NGO evidence',
  submitted: 'Evidence in, awaiting reviewer',
  verified: 'Verified',
  failed: 'Failed verification',
}

export const TXN_TONE: Record<TxnType, 'indigo' | 'madder' | 'linen' | 'neem'> = {
  lock: 'linen',
  release: 'indigo',
  hold: 'madder',
  terminate: 'madder',
  refund: 'neem',
}

export const TXN_LABEL: Record<TxnType, string> = {
  lock: 'Locked',
  release: 'Released',
  hold: 'Held',
  terminate: 'Terminated',
  refund: 'Refunded',
}

/** Short unit suffix for an impact metric. */
export function unitShort(unit: string): string {
  switch (unit) {
    case 'percentage_points': return 'pp'
    case 'percent_reduction': return '% fewer cases'
    case 'percent_increase': return '% higher'
    case 'hectares': return 'ha'
    case 'percent': return '%'
    case 'tonnes_per_month': return 'tonnes a month'
    case 'normalised_0_1': return 'share of the claim'
    default: return unit.replace(/_/g, ' ')
  }
}

export function metricLabel(name: string): string {
  const text = name.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}
