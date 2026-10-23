import type { ActionResult, ExchangeApi } from '../data/api'

/**
 * Ask fn_commit_funds for 4 lakh more than a company has left. It picks whichever
 * project is approved right now: once the models grade the projects, a fixed choice
 * may be flagged, and the database would then refuse on status instead of budget,
 * which shows the wrong safeguard.
 */
export async function overBudget(api: ExchangeApi, companyId = 3): Promise<ActionResult> {
  const [companies, board] = await Promise.all([api.companies(), api.scorecard()])
  const company = companies.find(c => c.id === companyId)
  const project = board.find(r => r.status === 'approved')
  if (!company || !project) {
    return { ok: false, kind: 'rule', error: 'No approved project to try this on. Approve one on the Projects page first.' }
  }
  const left = company.mandatedBudget - company.committedBudget
  return api.commitFunds({ companyId, projectId: project.projectId, amount: left + 400_000 })
}
