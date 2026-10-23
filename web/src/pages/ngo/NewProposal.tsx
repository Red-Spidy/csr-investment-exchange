import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHead } from '../../components/ui'
import type { Sector } from '../../data/api'
import { usePortal } from '../../data/portal'
import { useExchange, useQuery } from '../../data/store'
import { sectorLabel } from '../../lib/labels'

const SECTORS: Sector[] = ['education', 'healthcare', 'water_sanitation', 'environment', 'livelihood']

const SAMPLE = (ngo: string) => ({
  title: 'After-school science clubs for girls, Gaya',
  sector: 'education' as Sector, state: 'Bihar', amount: '1200000', duration: '12', phases: '2',
  text: `${ngo} will run after-school science clubs for 2,400 adolescent girls in 30 government schools of Gaya `
    + 'district, Bihar. The average science score of these girls is 41% today; with weekly lab sessions, scholarships '
    + 'for science kits and teacher training, we aim to raise it from 41% to 55% within 12 months. We request Rs 12 lakh.',
})

export function NewProposal() {
  const { ngoId, to } = usePortal()
  const navigate = useNavigate()
  const { act, source } = useExchange()
  const { data: rows } = useQuery(api => api.scorecard())
  const ngoName = rows?.find(r => r.ngoId === ngoId)?.ngoName ?? 'Our organisation'
  const [busy, setBusy] = useState(false)
  const [f, setF] = useState({ title: '', sector: 'education' as Sector, state: '', amount: '', duration: '12', phases: '3', text: '' })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF(v => ({ ...v, [k]: e.target.value }))

  return (
    <>
      <PageHead title="New proposal" lead="Describe the project in your own words. It is scored as soon as you submit." />

      <div className="form-layout">
        <form className="proposal-form panel" aria-busy={busy || undefined} onSubmit={async e => {
          e.preventDefault()
          setBusy(true)
          const out = await act('Proposal submitted', api => api.submitProposal({
            ngoId: ngoId!, title: f.title.trim(), proposalText: f.text.trim(), sector: f.sector,
            state: f.state.trim() || null, requestedAmount: Number(f.amount),
            durationMonths: Number(f.duration), numPhases: Number(f.phases),
          }))
          setBusy(false)
          if (out.ok && out.projectId) navigate(to(`/projects/${out.projectId}`))
        }}>
          <div className="field proposal-form__text">
            <label htmlFor="sp-title">Project title</label>
            <input id="sp-title" className="input" required minLength={3} maxLength={200} value={f.title} onChange={set('title')} />
          </div>
          <div className="field">
            <label htmlFor="sp-sector">Sector</label>
            <select id="sp-sector" className="select" value={f.sector} onChange={set('sector')}>
              {SECTORS.map(s => <option key={s} value={s}>{sectorLabel(s)}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="sp-state">State</label>
            <input id="sp-state" className="input" maxLength={80} value={f.state} onChange={set('state')} />
          </div>
          <div className="field">
            <label htmlFor="sp-amount">Amount requested (₹)</label>
            <input id="sp-amount" className="input" type="number" required min={1} step={1000} inputMode="numeric"
              value={f.amount} onChange={set('amount')} />
          </div>
          <div className="field">
            <label htmlFor="sp-duration">Duration (months)</label>
            <input id="sp-duration" className="input" type="number" required min={1} max={120} value={f.duration} onChange={set('duration')} />
          </div>
          <div className="field">
            <label htmlFor="sp-phases">Paid in phases</label>
            <input id="sp-phases" className="input" type="number" required min={1} max={12} value={f.phases} onChange={set('phases')} />
          </div>
          <div className="field proposal-form__text">
            <label htmlFor="sp-text">Proposal</label>
            <textarea id="sp-text" className="input" required minLength={50} maxLength={8000} rows={8}
              placeholder="What you will do, where, for whom, what will change and by how much, how long it takes and what it costs."
              value={f.text} onChange={set('text')} />
          </div>
          <div className="proposal-form__actions">
            <button className="btn" type="submit" disabled={busy || source !== 'live'}>
              {busy ? 'Scoring…' : 'Submit proposal'}
            </button>
            {source !== 'live' && <span className="small bad">Submitting needs the server, which is not reachable.</span>}
            {busy && <span className="small muted">Reading the proposal and checking it. This takes a few seconds.</span>}
          </div>
        </form>

        <aside className="side-card tips" aria-labelledby="tips-h">
          <h2 id="tips-h">What gets a proposal approved</h2>
          <ul className="plain">
            <li>A measurable target with its starting value, such as <em>from 41% to 55%</em>.</li>
            <li>How many people benefit, and who they are.</li>
            <li>The district and state.</li>
            <li>How long it takes and what it costs.</li>
          </ul>
          <p className="small muted">
            Proposals are scored for expected impact, your spending record and the goals they serve. Strong ones are
            approved straight away; the rest go to an exchange reviewer.
          </p>
          <button type="button" className="link-btn small" onClick={() => setF(SAMPLE(ngoName))}>Fill in a sample proposal</button>
        </aside>
      </div>
    </>
  )
}
