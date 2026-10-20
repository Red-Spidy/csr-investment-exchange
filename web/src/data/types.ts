// Row types mirror db/migrations/002_core_tables.sql, camelCased.
// Money is a plain number of rupees; the engine rounds to 2dp like NUMERIC(16,2).

export type ProjectStatus =
  | 'pending' | 'scoring' | 'approved' | 'flagged' | 'rejected'
  | 'matched' | 'active' | 'closed' | 'terminated'
export type PhaseStatus = 'locked' | 'released' | 'held' | 'terminated'
export type Verification = 'pending' | 'submitted' | 'verified' | 'failed'
export type CommitmentStatus = 'active' | 'completed' | 'cancelled'
export type Grade = 'A' | 'B' | 'C' | 'D'
export type TxnType = 'lock' | 'release' | 'hold' | 'terminate' | 'refund'

export interface Ngo {
  id: number
  name: string
  registrationNo: string
  sector: string
  state: string | null
  establishedYear: number | null
}

export interface Company {
  id: number
  name: string
  cin: string
  fy: string
  avgNetProfit: number
  mandatedBudget: number
  committedBudget: number
}

export interface Project {
  id: number
  ngoId: number
  title: string
  proposalText: string
  sector: string
  state: string | null
  requestedAmount: number
  durationMonths: number
  numPhases: number
  status: ProjectStatus
}

export interface Extraction {
  projectId: number
  goals: string[]
  targetMetric: { name: string; unit: string; baseline: number; target: number } | null
  beneficiaries: { count: number | null; group: string } | null
  geography: { state: string; district: string | null; ruralUrban: string } | null
  sdgs: number[]
  sdgConfidence: Record<number, number>
  redFlags: string[]
  /** Synthetic topic vector parameters, see fn_topic_vector in db/seed.sql. */
  topic: number
  jitter: number
  modelVersion: string
  promptVersion: string
}

export interface ImpactPrediction {
  projectId: number
  metricName: string
  metricUnit: string
  predictedValue: number
  ciLow: number
  ciHigh: number
  impactNorm: number
  modelVersion: string
}

export interface FraudScore {
  projectId: number
  ngoId: number
  anomalyScore: number
  isAnomaly: boolean
  modelVersion: string
}

export interface RiskGrade {
  projectId: number
  impactNorm: number
  fraudScore: number
  sdgConfidence: number
  ngoTrackRecord: number
  compositeScore: number
  grade: Grade
  decision: ProjectStatus
}

export interface Rulebook {
  id: number
  companyId: number
  fy: string
  requirementText: string
  focusAreas: string[]
  preferredStates: string[]
  targetSdgs: number[]
  minBudget: number
  maxBudget: number
  topic: number
  jitter: number
}

export interface SpendingHistory {
  ngoId: number
  fy: string
  totalSpend: number
  adminExpenseRatio: number
  burnRateVsSchedule: number
  categoryMixDrift: number
  roundNumberFreq: number
  vendorConcentration: number
  reportLatencyDays: number
  costPerBeneficiary: number | null
}

export interface Commitment {
  id: number
  matchId: number | null
  companyId: number
  projectId: number
  amount: number
  numPhases: number
  status: CommitmentStatus
  lockedAt: string
}

export interface FundPhase {
  id: number
  commitmentId: number
  phaseNo: number
  amount: number
  status: PhaseStatus
  releasedAt: string | null
}

export interface Milestone {
  id: number
  projectId: number
  commitmentId: number
  phaseNo: number
  description: string
  dueDate: string
  reportedAt: string | null
  evidenceUri: string | null
  reportedMetric: number | null
  verification: Verification
  verifiedBy: string | null
  verifiedAt: string | null
}

export interface LedgerEntry {
  id: number
  commitmentId: number
  phaseId: number | null
  amount: number
  type: TxnType
  note: string
  createdAt: string
}

export interface AuditEntry {
  id: number
  entity: string
  entityId: number
  action: string
  detail: Record<string, unknown>
  createdAt: string
}

export interface ImpactReport {
  id: number
  projectId: number
  /** First day of the reported month, YYYY-MM-DD. */
  periodMonth: string
  metricValue: number
}

/** The whole database. The demo engine treats it as immutable and returns copies. */
export interface DbState {
  ngos: Ngo[]
  companies: Company[]
  projects: Project[]
  extractions: Extraction[]
  impactPredictions: ImpactPrediction[]
  fraudScores: FraudScore[]
  riskGrades: RiskGrade[]
  rulebooks: Rulebook[]
  spendingHistory: SpendingHistory[]
  commitments: Commitment[]
  phases: FundPhase[]
  milestones: Milestone[]
  ledger: LedgerEntry[]
  audit: AuditEntry[]
  impactReports: ImpactReport[]
  seq: Record<string, number>
}
