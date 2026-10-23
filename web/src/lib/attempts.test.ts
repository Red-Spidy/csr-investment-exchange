import { describe, expect, it } from 'vitest'
import { createDemoApi } from '../data/demoApi'
import { overBudget } from './attempts'

describe('overBudget: the "commit more than the mandated budget" safeguard', () => {
  it('is refused by the budget check, not by a project status that happens to have changed', async () => {
    const out = await overBudget(createDemoApi())
    expect(out).toMatchObject({ ok: false, kind: 'sql' })
    expect(!out.ok && out.error).toMatch(/remaining, cannot commit/)
  })

  it('says so when there is no approved project to try it on', async () => {
    const api = createDemoApi()
    const noneApproved = { ...api, scorecard: async () => (await api.scorecard()).map(r => ({ ...r, status: 'flagged' as const })) }
    expect(await overBudget(noneApproved)).toMatchObject({ ok: false, kind: 'rule' })
  })
})

describe('overBudget follows the live grades', () => {
  it('tries it on a project that is approved now, not the one the seed approved', async () => {
    const api = createDemoApi()
    const tried: number[] = []
    const graded = {
      ...api,
      // As after make score: the reforestation project (5) went to review, Gaya (2) is approved.
      scorecard: async () => (await api.scorecard()).map(r => ({ ...r, status: r.projectId === 2 ? 'approved' as const : 'flagged' as const })),
      commitFunds: async (args: Parameters<typeof api.commitFunds>[0]) => { tried.push(args.projectId); return api.commitFunds(args) },
    }
    await overBudget(graded)
    expect(tried).toEqual([2])
  })
})
