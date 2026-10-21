// In-browser port of the database rules in db/migrations/004 to 008.
// Every function takes a DbState and returns a new one (or throws), so a thrown
// SqlError leaves the caller's state untouched, which is what ROLLBACK means.
// Error messages are copied from the plpgsql so the UI can show the real text.

import { addDays, inr, toIsoDate } from '../lib/format'
import type {
  Commitment, DbState, LedgerEntry, Milestone, Project, ProjectStatus, Rulebook,
} from './types'

export class SqlError extends Error {
  constructor(message: string, public code = 'P0001', public layer?: 1 | 2 | 3) {
    super(message)
    this.name = 'SqlError'
  }
}

/** A rule the API layer enforces before the database is asked to do anything. */
export class RuleError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'RuleError'
  }
}

export interface Effect {
  /** The function, trigger or table that did the work. */
  by: string
  text: string
}

export interface Outcome<T = void> {
  state: DbState
  effects: Effect[]
  value: T
}

/** Switches for the three independent double-funding layers (race demo only). */
export interface Guards {
  statusCheck: boolean
  guardTrigger: boolean
  uniqueIndex: boolean
}
export const ALL_GUARDS: Guards = { statusCheck: true, guardTrigger: true, uniqueIndex: true }

const round2 = (n: number) => Math.round(n * 100) / 100
const round4 = (n: number) => Math.round(n * 1e4) / 1e4
const round5 = (n: number) => Math.round(n * 1e5) / 1e5
const num2 = (n: number) => n.toFixed(2)
const clone = <T>(v: T): T => structuredClone(v)

function nextId(s: DbState, table: string): number {
  s.seq[table] = (s.seq[table] ?? 0) + 1
  return s.seq[table]
}

function mustFind<T>(rows: T[], pred: (r: T) => boolean, message: string): T {
  const row = rows.find(pred)
  if (!row) throw new SqlError(message)
  return row
}

// ------------------------------------------------------------ fn_commit_funds

export interface CommitArgs {
  companyId: number
  projectId: number
  matchId?: number | null
  amount?: number | null
}

/**
 * fn_commit_funds plus the triggers it fires: guard (layer 2), unique index
 * (layer 3), phase schedule and the lock ledger row. Layer 1 is the status
 * check inside the function itself.
 */
export function commitFunds(
  prev: DbState, args: CommitArgs, now: Date, guards: Guards = ALL_GUARDS,
): Outcome<number> {
  const s = clone(prev)
  const fx: Effect[] = []

  const co = mustFind(s.companies, c => c.id === args.companyId, `company ${args.companyId} not found`)
  const pr = mustFind(s.projects, p => p.id === args.projectId, `project ${args.projectId} not found`)

  if (guards.statusCheck && pr.status !== 'approved') {
    throw new SqlError(`project ${pr.id} is ${pr.status}, only approved projects can be funded`, 'P0001', 1)
  }

  const amount = round2(args.amount ?? pr.requestedAmount)
  if (round2(co.committedBudget + amount) > co.mandatedBudget) {
    throw new SqlError(
      `company ${co.id} has ${num2(co.mandatedBudget - co.committedBudget)} remaining, cannot commit ${num2(amount)}`,
    )
  }

  const active = s.commitments.find(c => c.projectId === pr.id && c.status === 'active')
  if (active && guards.guardTrigger) {
    throw new SqlError(`project ${pr.id} already has active commitment ${active.id}`, '23505', 2)
  }
  if (active && guards.uniqueIndex) {
    throw new SqlError(
      'duplicate key value violates unique constraint "uniq_active_commitment_per_project"', '23505', 3,
    )
  }

  const cm: Commitment = {
    id: nextId(s, 'commitments'),
    matchId: args.matchId ?? null,
    companyId: co.id,
    projectId: pr.id,
    amount,
    numPhases: pr.numPhases,
    status: 'active',
    lockedAt: now.toISOString(),
  }
  s.commitments.push(cm)
  fx.push({ by: 'fn_commit_funds', text: `Inserted commitment ${cm.id} for ${inr(amount)}.` })

  // trg_generate_phase_schedule
  const per = round2(amount / cm.numPhases)
  for (let n = 1; n <= cm.numPhases; n++) {
    s.phases.push({
      id: nextId(s, 'phases'), commitmentId: cm.id, phaseNo: n,
      amount: n < cm.numPhases ? per : round2(amount - per * (cm.numPhases - 1)),
      status: 'locked', releasedAt: null,
    })
    s.milestones.push({
      id: nextId(s, 'milestones'), projectId: pr.id, commitmentId: cm.id, phaseNo: n,
      description: `Phase ${n} deliverable`, dueDate: toIsoDate(addDays(now, n * 90)),
      reportedAt: null, evidenceUri: null, reportedMetric: null,
      verification: 'pending', verifiedBy: null, verifiedAt: null,
    })
  }
  fx.push({
    by: 'trg_generate_phase_schedule',
    text: `Split the money into ${cm.numPhases} phases and created ${cm.numPhases} milestones, one gating each phase.`,
  })

  pushLedger(s, {
    commitmentId: cm.id, phaseId: null, amount, type: 'lock',
    note: 'funds locked on match confirmation',
  }, now)
  fx.push({ by: 'fund_transactions', text: `Ledger row appended: lock ${inr(amount)}.` })

  co.committedBudget = round2(co.committedBudget + amount)
  setProjectStatus(pr, 'matched')
  fx.push({ by: 'fn_commit_funds', text: `Company budget used is now ${inr(co.committedBudget)} of ${inr(co.mandatedBudget)}. Project moved to matched.` })

  pushAudit(s, 'commitment', cm.id, 'funds_locked', { company_id: co.id, project_id: pr.id, amount }, now)

  return { state: s, effects: fx, value: cm.id }
}

function setProjectStatus(p: Project, status: ProjectStatus) {
  p.status = status
}

/** The commitment a project's page shows: the active one, else a completed one, else a cancelled one. */
export function latestCommitment(s: DbState, projectId: number): Commitment | undefined {
  const rank = (c: Commitment) => (c.status === 'active' ? 0 : c.status !== 'cancelled' ? 1 : 2)
  return s.commitments
    .filter(c => c.projectId === projectId)
    .sort((a, b) => rank(a) - rank(b) || a.id - b.id)[0]
}

function pushLedger(s: DbState, e: Omit<LedgerEntry, 'id' | 'createdAt'>, now: Date) {
  s.ledger.push({ ...e, id: nextId(s, 'ledger'), createdAt: now.toISOString() })
}

function pushAudit(
  s: DbState, entity: string, entityId: number, action: string,
  detail: Record<string, unknown>, now: Date,
) {
  s.audit.push({ id: nextId(s, 'audit'), entity, entityId, action, detail, createdAt: now.toISOString() })
}

// ------------------------------------------------------------ milestones

/** trg_guard_closed_commitment: a cancelled or completed commitment's milestones are history. */
function guardClosedCommitment(s: DbState, ms: Milestone) {
  const cm = s.commitments.find(c => c.id === ms.commitmentId)!
  if (cm.status !== 'active') {
    throw new SqlError(`commitment ${cm.id} is ${cm.status}, its milestones can no longer change`)
  }
}

export function submitEvidence(
  prev: DbState, milestoneId: number, metric: number, now: Date,
): Outcome {
  const s = clone(prev)
  const ms = mustFind(s.milestones, m => m.id === milestoneId, `milestone ${milestoneId} not found`)
  if (ms.verification !== 'pending') {
    throw new RuleError(`Milestone ${ms.id} is already ${ms.verification}; evidence can only be submitted once.`)
  }
  guardClosedCommitment(s, ms)
  ms.verification = 'submitted'
  ms.reportedAt = now.toISOString()
  ms.reportedMetric = metric
  ms.evidenceUri = `evidence/commitment-${ms.commitmentId}-phase-${ms.phaseNo}.pdf`
  return {
    state: s, value: undefined,
    effects: [
      { by: 'milestones', text: `Phase ${ms.phaseNo} evidence recorded, reported metric ${metric}.` },
      { by: 'trg_release_next_phase', text: 'Did not fire. It only fires when a reviewer marks a milestone verified, so no money moved.' },
    ],
  }
}

export function verifyMilestone(
  prev: DbState, milestoneId: number, by: string, now: Date,
): Outcome {
  const s = clone(prev)
  const ms = mustFind(s.milestones, m => m.id === milestoneId, `milestone ${milestoneId} not found`)
  if (ms.verification !== 'submitted') {
    throw new RuleError(`Milestone ${ms.id} has no submitted evidence to verify.`)
  }
  guardClosedCommitment(s, ms)
  ms.verification = 'verified'
  ms.verifiedBy = by
  ms.verifiedAt = now.toISOString()
  const fx: Effect[] = [{ by: 'milestones', text: `Phase ${ms.phaseNo} marked verified by ${by}.` }]
  releaseNextPhase(s, ms, now, fx)
  return { state: s, effects: fx, value: undefined }
}

/** trg_release_next_phase: the only code path that releases money. */
function releaseNextPhase(s: DbState, ms: Milestone, now: Date, fx: Effect[]) {
  const phase = s.phases.find(p => p.commitmentId === ms.commitmentId && p.phaseNo === ms.phaseNo)
  if (!phase) throw new SqlError(`no fund phase ${ms.phaseNo} for commitment ${ms.commitmentId}`)

  if (phase.status !== 'locked') {
    fx.push({ by: 'trg_release_next_phase', text: `Phase ${phase.phaseNo} is already ${phase.status}. Nothing paid twice.` })
    return
  }
  phase.status = 'released'
  phase.releasedAt = now.toISOString()
  pushLedger(s, {
    commitmentId: ms.commitmentId, phaseId: phase.id, amount: phase.amount, type: 'release',
    note: `phase ${ms.phaseNo} released on verified milestone ${ms.id}`,
  }, now)
  fx.push({ by: 'trg_release_next_phase', text: `Released phase ${phase.phaseNo}, ${inr(phase.amount)}. Ledger row appended.` })

  // A held phase is still owed, so it keeps the commitment open and the project flagged.
  const phases = s.phases.filter(p => p.commitmentId === ms.commitmentId)
  const outstanding = phases.filter(p => p.status === 'locked' || p.status === 'held').length
  const project = s.projects.find(p => p.id === ms.projectId)!
  if (outstanding === 0) {
    s.commitments.find(c => c.id === ms.commitmentId)!.status = 'completed'
    setProjectStatus(project, 'closed')
    fx.push({ by: 'trg_release_next_phase', text: 'No locked phases left. Commitment completed and project closed.' })
  } else if (project.status !== 'active' && !phases.some(p => p.status === 'held')) {
    setProjectStatus(project, 'active')
    fx.push({ by: 'trg_release_next_phase', text: 'First release made. Project is now active.' })
  }
  pushAudit(s, 'milestone', ms.id, 'phase_released', { phase_no: ms.phaseNo, amount: phase.amount }, now)
}

export function failMilestone(
  prev: DbState, milestoneId: number, by: string, now: Date,
): Outcome {
  const s = clone(prev)
  const ms = mustFind(s.milestones, m => m.id === milestoneId, `milestone ${milestoneId} not found`)
  if (ms.verification !== 'submitted') {
    throw new RuleError(`Milestone ${ms.id} has no submitted evidence to fail.`)
  }
  guardClosedCommitment(s, ms)
  ms.verification = 'failed'
  ms.verifiedBy = by
  ms.verifiedAt = now.toISOString()
  const fx: Effect[] = [{ by: 'milestones', text: `Phase ${ms.phaseNo} marked failed by ${by}.` }]

  // trg_hold_on_failed_verification
  const phase = s.phases.find(p => p.commitmentId === ms.commitmentId && p.phaseNo === ms.phaseNo)
  if (phase && phase.status === 'locked') {
    phase.status = 'held'
    pushLedger(s, {
      commitmentId: ms.commitmentId, phaseId: phase.id, amount: phase.amount, type: 'hold',
      note: `phase ${ms.phaseNo} held on failed verification of milestone ${ms.id}`,
    }, now)
    fx.push({ by: 'trg_hold_on_failed_verification', text: `Held phase ${phase.phaseNo}, ${inr(phase.amount)}. The money stays locked, it is not released.` })
  }
  setProjectStatus(s.projects.find(p => p.id === ms.projectId)!, 'flagged')
  fx.push({ by: 'trg_hold_on_failed_verification', text: 'Project flagged for review.' })
  pushAudit(s, 'milestone', ms.id, 'phase_held', { phase_no: ms.phaseNo }, now)
  return { state: s, effects: fx, value: undefined }
}

// ------------------------------------------------------------ fn_terminate_commitment

/**
 * fn_terminate_commitment: end an active commitment. Released phases stay paid; every
 * locked or held phase is terminated and its money goes back to the company budget.
 */
export function terminateCommitment(
  prev: DbState, commitmentId: number, reason: string, by: string, now: Date,
): Outcome<number> {
  const s = clone(prev)
  if (!reason.trim()) throw new SqlError('a reason is required to terminate a commitment')
  const cm = mustFind(s.commitments, c => c.id === commitmentId, `commitment ${commitmentId} not found`)
  if (cm.status !== 'active') {
    throw new SqlError(`commitment ${cm.id} is ${cm.status}, only active commitments can be terminated`)
  }

  let refunded = 0
  const ended = s.phases
    .filter(p => p.commitmentId === cm.id && (p.status === 'locked' || p.status === 'held'))
    .sort((a, b) => a.phaseNo - b.phaseNo)
  for (const phase of ended) {
    phase.status = 'terminated'
    pushLedger(s, {
      commitmentId: cm.id, phaseId: phase.id, amount: phase.amount, type: 'terminate',
      note: `phase ${phase.phaseNo} terminated: ${reason.trim()}`,
    }, now)
    refunded = round2(refunded + phase.amount)
  }

  const co = s.companies.find(c => c.id === cm.companyId)!
  if (refunded > 0) {
    pushLedger(s, {
      commitmentId: cm.id, phaseId: null, amount: refunded, type: 'refund',
      note: 'unreleased money returned to the company budget',
    }, now)
    co.committedBudget = round2(co.committedBudget - refunded)
  }
  cm.status = 'cancelled'
  setProjectStatus(s.projects.find(p => p.id === cm.projectId)!, 'terminated')
  const released = round2(cm.amount - refunded)
  pushAudit(s, 'commitment', cm.id, 'commitment_terminated',
    { reason: reason.trim(), by, released, refunded }, now)

  const n = ended.length
  return {
    state: s, value: cm.id,
    effects: [
      {
        by: 'fn_terminate_commitment',
        text: `Terminated ${n} unreleased phase${n === 1 ? '' : 's'}, ${inr(refunded)}.`
          + (released > 0 ? ` The ${inr(released)} already released stays paid.` : ''),
      },
      {
        by: 'fund_transactions',
        text: `Ledger rows appended: terminate for ${n === 1 ? 'the phase' : `each of the ${n} phases`}, then refund ${inr(refunded)}.`,
      },
      {
        by: 'fn_terminate_commitment',
        text: `Company budget used is now ${inr(co.committedBudget)} of ${inr(co.mandatedBudget)}. Commitment cancelled, project terminated.`,
      },
    ],
  }
}

// ------------------------------------------------------------ monthly progress

function nextMonth(iso: string): string {
  const [y, m] = iso.split('-').map(Number)
  return m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`
}

/**
 * INSERT INTO impact_reports for the month after the project's latest report
 * (or the current month for a first report). The window views read this table.
 */
export function reportImpact(prev: DbState, projectId: number, value: number, now: Date): Outcome {
  const s = clone(prev)
  const cm = latestCommitment(s, projectId)
  if (!cm) throw new RuleError(`Project ${projectId} has no commitment, so there is no funded work to report on.`)
  if (cm.status === 'cancelled') {
    throw new RuleError(`Project ${projectId} was terminated, so it has no funded work left to report on.`)
  }
  const months = s.impactReports.filter(r => r.projectId === projectId).map(r => r.periodMonth).sort()
  const month = months.length ? nextMonth(months[months.length - 1]) : `${toIsoDate(now).slice(0, 7)}-01`
  s.impactReports.push({ id: nextId(s, 'impactReports'), projectId, periodMonth: month, metricValue: value })

  const row = esgTimeline(s).find(r => r.companyId === cm.companyId && r.month === month)
  return {
    state: s, value: undefined,
    effects: [
      { by: 'impact_reports', text: `Recorded ${value} for ${month.slice(0, 7)}.` },
      ...(row ? [{
        by: 'company_esg_timeline',
        text: `The view recomputes on read. For that month the 3-month average is now ${row.rolling3mo.toFixed(2)} and the running total ${row.cumulativeImpact.toFixed(2)}.`,
      }] : []),
    ],
  }
}

// ------------------------------------------------------------ fn_review_project

/** fn_review_project (008_risk_grade.sql): a person settles what the grade sent to review. */
export function reviewProject(
  prev: DbState, projectId: number, approve: boolean, reviewer: string, note: string | null, now: Date,
): Outcome {
  const s = clone(prev)
  const p = mustFind(s.projects, x => x.id === projectId, `project ${projectId} not found`)
  if (p.status !== 'flagged' || s.commitments.some(c => c.projectId === projectId)) {
    throw new SqlError(`project ${projectId} is ${p.status}, only a flagged project with no commitment can be reviewed`)
  }
  if (!reviewer.trim()) throw new SqlError('a review needs a reviewer')
  const decision: ProjectStatus = approve ? 'approved' : 'rejected'
  setProjectStatus(p, decision)
  pushAudit(s, 'project', projectId, 'reviewed', { decision, reviewer, note }, now)
  return {
    state: s, value: undefined,
    effects: [
      { by: 'fn_review_project', text: `Project ${projectId} ${decision} by ${reviewer}${note ? `: ${note}` : ''}. Kept in project_reviews, so a later regrade will not overturn it.` },
      ...(approve ? [{ by: 'projects', text: `Project ${projectId} is now in the matching pool.` }] : []),
    ],
  }
}

/** trg_ledger_immutable: any UPDATE or DELETE on a ledger row raises. */
export function tryLedgerMutation(s: DbState, op: 'UPDATE' | 'DELETE', id: number): never {
  if (!s.ledger.some(l => l.id === id)) {
    throw new RuleError(`${op} 0: no ledger row with id ${id}, so the trigger never fires.`)
  }
  throw new SqlError(`fund_transactions is append-only (attempted ${op} on id ${id})`)
}

// ------------------------------------------------------------ pgvector matching

const DIM = 384
const roundHalfAway4 = (x: number) => Math.sign(x) * Math.round(Math.abs(x) * 1e4) / 1e4

/** fn_topic_vector from db/seed.sql. */
export function topicVector(topic: number, jitter = 0): number[] {
  return Array.from({ length: DIM }, (_, i) => {
    if (i === topic) return roundHalfAway4(1 - jitter)
    if (i === topic + 1) return roundHalfAway4(0.3 + jitter)
    if (i === topic + 2) return roundHalfAway4(0.15 + jitter / 2)
    return roundHalfAway4(Math.sin(i * 0.7 + topic) * 0.02)
  })
}

/** 1 - (a <=> b): pgvector cosine distance turned into similarity. */
export function cosineSimilarity(a: number[], b: number[]): number {
  let dot = 0, na = 0, nb = 0
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i] }
  return dot / (Math.sqrt(na) * Math.sqrt(nb))
}

export const MATCH_WEIGHTS = { similarity: 0.6, impact: 0.25, trust: 0.15 } as const

export interface MatchRow {
  projectId: number
  title: string
  ngoName: string
  state: string | null
  sdgs: number[]
  sharedSdgs: number[]
  requestedAmount: number
  similarity: number
  impactNorm: number
  fraudScore: number
  matchScore: number
  contributions: { similarity: number; impact: number; trust: number }
}

export interface Exclusion {
  projectId: number
  title: string
  ngoName: string
  status: ProjectStatus
  requestedAmount: number
  reasons: string[]
}

export interface MatchReport {
  rulebook: Rulebook
  ranked: MatchRow[]
  excluded: Exclusion[]
}

/**
 * fn_match_projects, plus the reason each project that did not make the list
 * was dropped. The ranked rows reproduce the SQL function's output exactly.
 */
export function matchReport(s: DbState, rulebookId: number, topK = 5): MatchReport {
  const rb = mustFind(s.rulebooks, r => r.id === rulebookId, `rulebook ${rulebookId} not found`)
  const rbVec = topicVector(rb.topic, rb.jitter)
  const candidates: MatchRow[] = []
  const excluded: Exclusion[] = []

  for (const p of s.projects) {
    const e = s.extractions.find(x => x.projectId === p.id)
    const ngo = s.ngos.find(n => n.id === p.ngoId)!
    const reasons: string[] = []
    if (p.status !== 'approved') reasons.push(`Status is ${p.status}; only approved projects can be matched.`)
    if (p.requestedAmount < rb.minBudget || p.requestedAmount > rb.maxBudget) {
      reasons.push(`Asks for ${inr(p.requestedAmount)}, outside the ${inr(rb.minBudget)} to ${inr(rb.maxBudget)} range.`)
    }
    if (rb.preferredStates.length > 0 && (!p.state || !rb.preferredStates.includes(p.state))) {
      reasons.push(`${p.state ?? 'Unknown state'} is not one of ${rb.preferredStates.join(' or ')}.`)
    }
    const shared = e ? e.sdgs.filter(g => rb.targetSdgs.includes(g)) : []
    if (rb.targetSdgs.length > 0 && shared.length === 0) {
      reasons.push(`No overlap with the target SDG${rb.targetSdgs.length > 1 ? 's' : ''} (${rb.targetSdgs.join(', ')}).`)
    }

    if (reasons.length > 0 || !e) {
      excluded.push({
        projectId: p.id, title: p.title, ngoName: ngo.name, status: p.status,
        requestedAmount: p.requestedAmount, reasons: reasons.length ? reasons : ['No extraction embedding yet.'],
      })
      continue
    }

    const sim = cosineSimilarity(topicVector(e.topic, e.jitter), rbVec)
    const ip = s.impactPredictions.find(x => x.projectId === p.id)
    const fs = s.fraudScores.find(x => x.projectId === p.id)
    const impact = ip?.impactNorm ?? 0
    const fraud = fs?.anomalyScore ?? 0
    const contributions = {
      similarity: MATCH_WEIGHTS.similarity * sim,
      impact: MATCH_WEIGHTS.impact * impact,
      trust: MATCH_WEIGHTS.trust * (1 - fraud),
    }
    candidates.push({
      projectId: p.id, title: p.title, ngoName: ngo.name, state: p.state, sdgs: e.sdgs, sharedSdgs: shared,
      requestedAmount: p.requestedAmount, similarity: round5(sim), impactNorm: impact, fraudScore: fraud,
      matchScore: round5(contributions.similarity + contributions.impact + contributions.trust),
      contributions,
    })
  }

  candidates.sort((a, b) => b.matchScore - a.matchScore)
  const ranked = candidates.slice(0, topK)
  for (const c of candidates.slice(topK)) {
    const p = s.projects.find(x => x.id === c.projectId)!
    excluded.push({
      projectId: c.projectId, title: c.title, ngoName: c.ngoName, status: p.status,
      requestedAmount: c.requestedAmount, reasons: [`Passed every filter but ranks below the top ${topK}.`],
    })
  }
  excluded.sort((a, b) => a.projectId - b.projectId)
  return { rulebook: rb, ranked, excluded }
}

// ------------------------------------------------------------ analytics views

export interface ScorecardRow {
  projectId: number
  title: string
  status: ProjectStatus
  sector: string
  state: string | null
  requestedAmount: number
  ngoId: number
  ngoName: string
  sdgs: number[]
  predictedValue: number | null
  ciLow: number | null
  ciHigh: number | null
  metricUnit: string | null
  anomalyScore: number | null
  isAnomaly: boolean | null
  compositeScore: number | null
  grade: string | null
  commitmentId: number | null
  committedAmount: number
  releasedAmount: number
  lockedAmount: number
  heldAmount: number
}

/** project_scorecard, with held money added so the funding position adds up. */
export function projectScorecard(s: DbState): ScorecardRow[] {
  return s.projects.map(p => {
    const e = s.extractions.find(x => x.projectId === p.id)
    const ip = s.impactPredictions.find(x => x.projectId === p.id)
    const fs = s.fraudScores.find(x => x.projectId === p.id)
    const rg = s.riskGrades.find(x => x.projectId === p.id)
    const cm = s.commitments.find(c => c.projectId === p.id && c.status === 'active')
    const phases = cm ? s.phases.filter(f => f.commitmentId === cm.id) : []
    const sum = (st: string) => phases.filter(f => f.status === st).reduce((t, f) => t + f.amount, 0)
    return {
      projectId: p.id, title: p.title, status: p.status, sector: p.sector, state: p.state,
      requestedAmount: p.requestedAmount, ngoId: p.ngoId,
      ngoName: s.ngos.find(n => n.id === p.ngoId)!.name,
      sdgs: e?.sdgs ?? [],
      predictedValue: ip?.predictedValue ?? null, ciLow: ip?.ciLow ?? null, ciHigh: ip?.ciHigh ?? null,
      metricUnit: ip?.metricUnit ?? null,
      anomalyScore: fs?.anomalyScore ?? null, isAnomaly: fs?.isAnomaly ?? null,
      compositeScore: rg?.compositeScore ?? null, grade: rg?.grade ?? null,
      commitmentId: cm?.id ?? null, committedAmount: cm?.amount ?? 0,
      releasedAmount: round2(sum('released')), lockedAmount: round2(sum('locked')), heldAmount: round2(sum('held')),
    }
  })
}

export interface EsgRow {
  companyId: number
  companyName: string
  month: string
  monthImpact: number
  activeProjects: number
  /** SUM() OVER (ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) */
  cumulativeImpact: number
  /** month_impact - LAG(month_impact) */
  momDelta: number | null
  prevMonthImpact: number | null
  /** AVG() OVER (ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) */
  rolling3mo: number
  /** PERCENT_RANK() OVER (PARTITION BY month ORDER BY month_impact) */
  peerPercentile: number
  peersInMonth: number
}

/** company_esg_timeline, window function for window function. */
export function esgTimeline(s: DbState): EsgRow[] {
  const monthly = new Map<string, { companyId: number; month: string; impact: number; projects: Set<number> }>()
  for (const cm of s.commitments) {
    for (const ir of s.impactReports.filter(r => r.projectId === cm.projectId)) {
      const key = `${cm.companyId}|${ir.periodMonth}`
      const cur = monthly.get(key) ?? { companyId: cm.companyId, month: ir.periodMonth, impact: 0, projects: new Set() }
      cur.impact += ir.metricValue
      cur.projects.add(cm.projectId)
      monthly.set(key, cur)
    }
  }
  const all = [...monthly.values()]
  const rows: EsgRow[] = []

  for (const company of s.companies) {
    const mine = all.filter(m => m.companyId === company.id).sort((a, b) => a.month.localeCompare(b.month))
    let running = 0
    mine.forEach((m, i) => {
      running += m.impact
      const prev = i > 0 ? mine[i - 1].impact : null
      const window = mine.slice(Math.max(0, i - 2), i + 1)
      const peers = all.filter(x => x.month === m.month)
      const below = peers.filter(x => x.impact < m.impact).length
      rows.push({
        companyId: company.id, companyName: company.name, month: m.month,
        monthImpact: round4(m.impact), activeProjects: m.projects.size,
        cumulativeImpact: round4(running),
        momDelta: prev === null ? null : round4(m.impact - prev),
        prevMonthImpact: prev === null ? null : round4(prev),
        rolling3mo: round4(window.reduce((t, x) => t + x.impact, 0) / window.length),
        peerPercentile: peers.length > 1 ? round4(below / (peers.length - 1)) : 0,
        peersInMonth: peers.length,
      })
    })
  }
  return rows.sort((a, b) => a.month.localeCompare(b.month) || a.companyId - b.companyId)
}

export interface LeaderRow {
  ngoId: number
  ngoName: string
  sector: string
  projectCount: number
  totalImpact: number
  totalFunded: number
  /** Impact per million rupees funded, or null if nothing is funded yet. */
  impactPerMillion: number | null
  /** DENSE_RANK() OVER (PARTITION BY sector ORDER BY impact per rupee DESC) */
  sectorRank: number
  /** PERCENT_RANK() OVER (ORDER BY impact per rupee) */
  overallPercentile: number
}

/** Money that reached the NGO: a cancelled commitment counts only its released phases (007). */
function fundedBy(s: DbState, c: Commitment): number {
  if (c.status !== 'cancelled') return c.amount
  return s.phases.filter(p => p.commitmentId === c.id && p.status === 'released').reduce((t, p) => t + p.amount, 0)
}

/**
 * ngo_leaderboard. Funding and impact are summed per project first, as the view does
 * since migration 006. Before it, the view joined commitments and impact_reports in
 * one go and counted each commitment once per report row (6x for the seeded project).
 */
export function ngoLeaderboard(s: DbState): LeaderRow[] {
  const base = s.ngos.map(n => {
    const projects = s.projects.filter(p => p.ngoId === n.id)
    const funded = projects.reduce(
      (t, p) => t + s.commitments.filter(c => c.projectId === p.id).reduce((a, c) => a + fundedBy(s, c), 0), 0)
    const impact = projects.reduce(
      (t, p) => t + s.impactReports.filter(r => r.projectId === p.id).reduce((a, r) => a + r.metricValue, 0), 0)
    return { n, projectCount: projects.length, funded, impact, ratio: funded > 0 ? impact / funded : 0 }
  })

  const ranks = (group: typeof base) => {
    const distinct = [...new Set(group.map(g => g.ratio))].sort((a, b) => b - a)
    return (ratio: number) => distinct.indexOf(ratio) + 1
  }
  const sectorRank = new Map<string, (r: number) => number>()
  for (const sector of new Set(base.map(b => b.n.sector))) {
    sectorRank.set(sector, ranks(base.filter(b => b.n.sector === sector)))
  }

  return base.map(b => {
    const below = base.filter(x => x.ratio < b.ratio).length
    return {
      ngoId: b.n.id, ngoName: b.n.name, sector: b.n.sector, projectCount: b.projectCount,
      totalImpact: round4(b.impact), totalFunded: round2(b.funded),
      impactPerMillion: b.funded > 0 ? round4(b.ratio * 1e6) : null,
      sectorRank: sectorRank.get(b.n.sector)!(b.ratio),
      overallPercentile: base.length > 1 ? round4(below / (base.length - 1)) : 0,
    }
  })
}

// ------------------------------------------------------------ double-funding race

export interface RaceStep {
  who: 'A' | 'B'
  text: string
  tone: 'ok' | 'wait' | 'stop' | 'bad'
}

export interface RaceResult {
  steps: RaceStep[]
  winner: 'A' | 'B' | null
  /** Which layer stopped the loser, or null if nothing did. */
  stoppedBy: 1 | 2 | 3 | null
  message: string | null
  activeCommitments: number
  committed: number
  mandated: number
}

/** Same fixture as db/tests/06_concurrency.sh: a company with room for exactly one commitment. */
function raceFixture(): DbState {
  return {
    ngos: [{ id: 1, name: 'Race NGO', registrationNo: 'T-RACE-NGO', sector: 'education', state: null, establishedYear: null }],
    companies: [{ id: 1, name: 'Race Co', cin: 'T-RACE-CIN', fy: 'FY24-25', avgNetProfit: 5_000_000, mandatedBudget: 500_000, committedBudget: 0 }],
    projects: [{
      id: 1, ngoId: 1, title: 'Race project', proposalText: 'text', sector: 'education', state: null,
      requestedAmount: 100_000, durationMonths: 6, numPhases: 2, status: 'approved',
    }],
    extractions: [], impactPredictions: [], fraudScores: [], riskGrades: [], rulebooks: [], spendingHistory: [],
    commitments: [], phases: [], milestones: [], ledger: [], audit: [], impactReports: [],
    seq: { commitments: 0, phases: 0, milestones: 0, ledger: 0, audit: 0, impactReports: 0 },
  }
}

/**
 * Two sessions race to commit the same project. Postgres serialises them on
 * the company row lock, so B always runs second and reads A's committed work.
 * `guards` lets the demo switch layers off to show what each one catches.
 */
export function runRace(guards: Guards, now: Date): RaceResult {
  const steps: RaceStep[] = []
  let s = raceFixture()
  const args = { companyId: 1, projectId: 1 }

  steps.push({ who: 'A', tone: 'ok', text: 'Takes the row lock on Race Co (SELECT ... FOR UPDATE).' })
  steps.push({ who: 'B', tone: 'wait', text: 'Asks for the same row lock. Postgres makes B wait.' })

  const a = commitFunds(s, args, now, guards)
  s = a.state
  steps.push({ who: 'A', tone: 'ok', text: 'Checks the project is approved and the budget has room.' })
  steps.push({ who: 'A', tone: 'ok', text: 'Inserts the commitment. No active one exists, so every guard passes.' })
  steps.push({ who: 'A', tone: 'ok', text: 'Commits. Phases, milestones and the lock ledger row land with it.' })
  steps.push({ who: 'B', tone: 'ok', text: 'Gets the lock after A commits and reads A’s committed rows.' })

  let winner: RaceResult['winner'] = 'A'
  let stoppedBy: RaceResult['stoppedBy'] = null
  let message: string | null = null
  try {
    const b = commitFunds(s, args, now, guards)
    s = b.state
    steps.push({ who: 'B', tone: 'bad', text: 'Inserts a second commitment for the same project. Nothing stopped it.' })
    winner = null
  } catch (err) {
    if (!(err instanceof SqlError)) throw err
    stoppedBy = err.layer ?? null
    message = err.message
    const where = err.layer === 1 ? 'Layer 1, the status check in fn_commit_funds'
      : err.layer === 2 ? 'Layer 2, the BEFORE INSERT guard trigger'
      : err.layer === 3 ? 'Layer 3, the partial unique index'
      : 'The budget check'
    steps.push({ who: 'B', tone: 'stop', text: `${where}, rejects it and rolls back.` })
  }

  return {
    steps, winner, stoppedBy, message,
    activeCommitments: s.commitments.filter(c => c.status === 'active').length,
    committed: s.companies[0].committedBudget,
    mandated: s.companies[0].mandatedBudget,
  }
}
