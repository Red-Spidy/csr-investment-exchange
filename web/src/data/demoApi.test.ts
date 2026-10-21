import { describe, expect, it } from 'vitest'
import { createDemoApi } from './demoApi'

describe('the browser demo', () => {
  it('says plainly that scoring a new proposal needs the API, where the models run', async () => {
    const out = await createDemoApi().submitProposal({
      ngoId: 1, title: 'T', proposalText: 'x'.repeat(60), sector: 'education', state: null,
      requestedAmount: 900_000, durationMonths: 12, numPhases: 2,
    })
    expect(out).toMatchObject({ ok: false, kind: 'rule' })
    expect(!out.ok && out.error).toMatch(/make api/)
  })

  it('says the same for a new rulebook, which needs the embedding model', async () => {
    const out = await createDemoApi().createRulebook({
      companyId: 1, requirementText: 'Fund girls education', focusAreas: ['education'], preferredStates: [],
      targetSdgs: [4], minBudget: 0, maxBudget: 1_000_000,
    })
    expect(out).toMatchObject({ ok: false, kind: 'rule' })
  })

  it('runs a review on its own copy of the rules', async () => {
    const api = createDemoApi()
    expect(await api.reviewProject(7, true, 'checked')).toMatchObject({ ok: true })
    expect((await api.projectDetail(7)).project.status).toBe('approved')
    expect(await api.reviewProject(7, true, null)).toMatchObject({ ok: false, kind: 'sql' })
  })
})
