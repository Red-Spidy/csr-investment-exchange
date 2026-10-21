import type { ActionResult, CommitmentView, ExchangeApi, ProjectDetail } from './api'
import { createDemoState } from './demo'
import {
  RuleError, SqlError, commitFunds, esgTimeline, failMilestone, latestCommitment, matchReport,
  ngoLeaderboard, projectScorecard, reportImpact, runRace, submitEvidence, terminateCommitment,
  tryLedgerMutation, verifyMilestone, type Outcome,
} from './engine'
import type { DbState } from './types'

const REVIEWER = 'Reviewer (demo)'

/** The whole database lives in this closure; every write replaces it atomically. */
export function createDemoApi(): ExchangeApi {
  let db: DbState = createDemoState()

  const view = (commitmentId: number): CommitmentView => {
    const commitment = db.commitments.find(c => c.id === commitmentId)!
    return {
      commitment,
      project: db.projects.find(p => p.id === commitment.projectId)!,
      ngoName: db.ngos.find(n => n.id === db.projects.find(p => p.id === commitment.projectId)!.ngoId)!.name,
      companyName: db.companies.find(c => c.id === commitment.companyId)!.name,
      phases: db.phases.filter(p => p.commitmentId === commitmentId),
      milestones: db.milestones.filter(m => m.commitmentId === commitmentId),
    }
  }

  function write(fn: () => Outcome<number | void>): ActionResult {
    try {
      const out = fn()
      db = out.state
      return { ok: true, effects: out.effects, commitmentId: typeof out.value === 'number' ? out.value : undefined }
    } catch (err) {
      if (err instanceof SqlError) return { ok: false, error: err.message, kind: 'sql', code: err.code }
      if (err instanceof RuleError) return { ok: false, error: err.message, kind: 'rule' }
      throw err
    }
  }

  return {
    companies: async () => db.companies,
    rulebooks: async () => db.rulebooks,
    scorecard: async () => projectScorecard(db),

    projectDetail: async (projectId): Promise<ProjectDetail> => {
      const project = db.projects.find(p => p.id === projectId)!
      const cm = latestCommitment(db, projectId)
      return {
        project,
        ngo: db.ngos.find(n => n.id === project.ngoId)!,
        extraction: db.extractions.find(e => e.projectId === projectId) ?? null,
        prediction: db.impactPredictions.find(i => i.projectId === projectId) ?? null,
        fraud: db.fraudScores.find(f => f.projectId === projectId) ?? null,
        risk: db.riskGrades.find(r => r.projectId === projectId) ?? null,
        history: db.spendingHistory.filter(h => h.ngoId === project.ngoId),
        commitment: cm ? view(cm.id) : null,
      }
    },

    matches: async rulebookId => matchReport(db, rulebookId),
    commitments: async () => db.commitments.map(c => view(c.id)),
    ledger: async () => db.ledger,
    audit: async () => db.audit,
    esgTimeline: async () => esgTimeline(db),
    leaderboard: async () => ngoLeaderboard(db),

    commitFunds: async args => write(() => commitFunds(db, args, new Date())),
    submitEvidence: async (id, metric) => write(() => submitEvidence(db, id, metric, new Date())),
    verifyMilestone: async id => write(() => verifyMilestone(db, id, REVIEWER, new Date())),
    failMilestone: async id => write(() => failMilestone(db, id, REVIEWER, new Date())),
    terminateCommitment: async (id, reason) =>
      write(() => terminateCommitment(db, id, reason, REVIEWER, new Date())),

    reportImpact: async (projectId, value) => write(() => reportImpact(db, projectId, value, new Date())),

    tryLedgerMutation: async (op, id) => {
      try {
        tryLedgerMutation(db, op, id)
      } catch (err) {
        if (err instanceof SqlError) return { ok: false, error: err.message, kind: 'sql', code: err.code }
        if (err instanceof RuleError) return { ok: false, error: err.message, kind: 'rule' }
        throw err
      }
      return { ok: true, effects: [] }
    },

    runRace: async guards => runRace(guards, new Date()),
    reset: async () => { db = createDemoState() },
  }
}
