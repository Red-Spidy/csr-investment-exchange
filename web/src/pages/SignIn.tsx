import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Brand } from '../components/PortalShell'
import { useExchange, useQuery } from '../data/store'

/** Demo sign-in: choose an account and open its portal. There are no passwords yet. */
export function SignIn() {
  const navigate = useNavigate()
  const { source } = useExchange()
  const { data: rows } = useQuery(api => api.scorecard())
  const { data: companies } = useQuery(api => api.companies())
  const ngos = useMemo(() => [...new Map((rows ?? []).map(r => [r.ngoId, r.ngoName])).entries()]
    .map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name)), [rows])

  const [ngoId, setNgoId] = useState('')
  const [companyId, setCompanyId] = useState('')
  const go = (path: string) => (e: FormEvent) => { e.preventDefault(); navigate(path) }
  useEffect(() => { document.title = 'Sign in – CSR Exchange' }, [])

  return (
    <div className="signin">
      <main className="signin__main" id="main">
        <Brand />
        <div className="signin__intro">
          <h1>Sign in</h1>
          <p className="muted">CSR funding for social projects, released only as the work is proven.</p>
        </div>

        <form className="account" onSubmit={go(`/ngo/${ngoId || ngos[0]?.id}`)}>
          <div className="account__text">
            <h2>NGO</h2>
            <p className="muted small">Submit proposals, upload milestone evidence and track the money you receive.</p>
          </div>
          <div className="account__pick">
            <label className="sr-only" htmlFor="si-ngo">Organisation</label>
            <select id="si-ngo" className="select" value={ngoId || ngos[0]?.id || ''} onChange={e => setNgoId(e.target.value)}>
              {ngos.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
            <button className="btn" type="submit" disabled={!ngos.length}>Continue</button>
          </div>
        </form>

        <form className="account" onSubmit={go(`/company/${companyId || companies?.[0]?.id}`)}>
          <div className="account__text">
            <h2>Company CSR team</h2>
            <p className="muted small">Set what you want to fund, commit your mandated budget and follow its impact.</p>
          </div>
          <div className="account__pick">
            <label className="sr-only" htmlFor="si-company">Company</label>
            <select id="si-company" className="select" value={companyId || companies?.[0]?.id || ''}
              onChange={e => setCompanyId(e.target.value)}>
              {(companies ?? []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button className="btn" type="submit" disabled={!companies?.length}>Continue</button>
          </div>
        </form>

        <form className="account" onSubmit={go('/review')}>
          <div className="account__text">
            <h2>Exchange reviewer</h2>
            <p className="muted small">Decide on proposals the scoring held back and verify milestone evidence.</p>
          </div>
          <div className="account__pick">
            <button className="btn btn--quiet" type="submit">Continue</button>
          </div>
        </form>

        <p className="signin__note faint small">
          Demo accounts without passwords. The server has no authentication yet, so run it only on your own machine.
          {source === 'demo' && ' The server is not reachable, so this is offline demo data.'}
        </p>
      </main>

      <div className="signin__art" aria-hidden="true">
        {(['released', 'review', 'locked', 'held', 'released', 'locked', 'free', 'review'] as const).map((tone, i) => (
          <span key={i} className="weave signin__band" data-tone={tone} />
        ))}
      </div>
    </div>
  )
}
