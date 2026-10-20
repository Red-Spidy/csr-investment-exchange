// The one boundary between the UI and the data. Every method maps to a table,
// view or function in db/migrations. httpApi.ts implements it over HTTP against the
// FastAPI service in api/ (Postgres does the work); demoApi.ts implements it in the
// browser with a port of the same rules, for when no API is running.

import type {
  CommitArgs, Effect, EsgRow, Guards, LeaderRow, MatchReport, RaceResult, ScorecardRow,
} from './engine'
import type {
  AuditEntry, Commitment, Company, Extraction, FraudScore, FundPhase, ImpactPrediction,
  LedgerEntry, Milestone, Ngo, Project, RiskGrade, Rulebook, SpendingHistory,
} from './types'

export type ActionResult =
  | { ok: true; effects: Effect[]; commitmentId?: number }
  | { ok: false; error: string; kind: 'sql' | 'rule'; code?: string }

export interface CommitmentView {
  commitment: Commitment
  project: Project
  ngoName: string
  companyName: string
  phases: FundPhase[]
  milestones: Milestone[]
}

export interface ProjectDetail {
  project: Project
  ngo: Ngo
  extraction: Extraction | null
  prediction: ImpactPrediction | null
  fraud: FraudScore | null
  risk: RiskGrade | null
  history: SpendingHistory[]
  commitment: CommitmentView | null
}

export interface ExchangeApi {
  // reads
  companies(): Promise<Company[]>
  rulebooks(): Promise<Rulebook[]>
  /** view project_scorecard */
  scorecard(): Promise<ScorecardRow[]>
  projectDetail(projectId: number): Promise<ProjectDetail>
  /** function fn_match_projects, plus why each other project was left out */
  matches(rulebookId: number): Promise<MatchReport>
  commitments(): Promise<CommitmentView[]>
  /** table fund_transactions */
  ledger(): Promise<LedgerEntry[]>
  audit(): Promise<AuditEntry[]>
  /** view company_esg_timeline */
  esgTimeline(): Promise<EsgRow[]>
  /** view ngo_leaderboard */
  leaderboard(): Promise<LeaderRow[]>

  // writes
  /** function fn_commit_funds */
  commitFunds(args: CommitArgs): Promise<ActionResult>
  submitEvidence(milestoneId: number, metric: number): Promise<ActionResult>
  /** UPDATE milestones SET verification_status = 'verified' */
  verifyMilestone(milestoneId: number): Promise<ActionResult>
  failMilestone(milestoneId: number): Promise<ActionResult>
  /** INSERT INTO impact_reports, the input to the window-function views. */
  reportImpact(projectId: number, value: number): Promise<ActionResult>
  /** Attempt to rewrite history in fund_transactions. */
  tryLedgerMutation(op: 'UPDATE' | 'DELETE', ledgerId: number): Promise<ActionResult>
  /** Two sessions, one project, on a scratch fixture. */
  runRace(guards: Guards): Promise<RaceResult>
  reset(): Promise<void>
}
