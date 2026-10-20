import { useEffect, useRef, useState } from 'react'
import { PageHead, Section } from '../components/ui'
import type { ActionResult, ExchangeApi } from '../data/api'
import { ALL_GUARDS, type Guards, type RaceResult } from '../data/engine'
import { useExchange } from '../data/store'
import { inr } from '../lib/format'

const LAYERS: { key: keyof Guards; name: string; where: string; what: string }[] = [
  { key: 'statusCheck', name: 'Layer 1', where: 'Inside fn_commit_funds',
    what: 'Refuses any project that is not approved. Once the first session commits, the project is matched, so the second is turned away here.' },
  { key: 'guardTrigger', name: 'Layer 2', where: 'BEFORE INSERT trigger on commitments',
    what: 'Looks for an active commitment on the same project and raises if one exists.' },
  { key: 'uniqueIndex', name: 'Layer 3', where: 'Partial unique index, WHERE status = active',
    what: 'The structural backstop. The table itself cannot hold two active commitments for one project.' },
]

export function Safeguards() {
  return (
    <>
      <PageHead
        title="The database says no, so the app does not have to."
        lead="Each of these is a way to misuse the money, and each is stopped inside Postgres. None of the defences live in the interface. Run them and read the answers."
      />
      <Race />
      <Refusals />
    </>
  )
}

// ---------------------------------------------------------------- the race

function Race() {
  const { api } = useExchange()
  const [guards, setGuards] = useState<Guards>(ALL_GUARDS)
  const [result, setResult] = useState<RaceResult | null>(null)
  const [shown, setShown] = useState(0)
  const timer = useRef<number>(undefined)

  useEffect(() => () => window.clearInterval(timer.current), [])

  async function run() {
    window.clearInterval(timer.current)
    const r = await api.runRace(guards)
    setResult(r)
    const instant = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (instant) { setShown(r.steps.length); return }
    setShown(0)
    let n = 0
    timer.current = window.setInterval(() => {
      n += 1
      setShown(n)
      if (n >= r.steps.length) window.clearInterval(timer.current)
    }, 420)
  }

  const finished = result && shown >= result.steps.length
  const off = LAYERS.filter(l => !guards[l.key]).length

  return (
    <Section id="race" title="Two sessions fund the same project at once"
      hint="Both sessions try to lock money for one project. Exactly one may win. Switch layers off to see which one catches it next.">
      <div className="race">
        <fieldset className="layers">
          <legend className="sr-only">Protection layers</legend>
          {LAYERS.map(l => (
            <label key={l.key} className="layer" data-off={!guards[l.key] || undefined}>
              <input type="checkbox" checked={guards[l.key]}
                onChange={e => { setGuards({ ...guards, [l.key]: e.target.checked }); setResult(null) }} />
              <span className="layer__box" aria-hidden="true" />
              <span>
                <strong>{l.name}. {l.where}</strong>
                <span className="small muted">{l.what}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <div className="race__run">
          <button className="btn btn--turmeric" onClick={run}>Race two sessions</button>
          <p className="small faint">
            Runs on a scratch company and project, the fixture from db/tests/06_concurrency.sh, so your demo data is untouched.
            {off > 0 && ` ${off} layer${off > 1 ? 's are' : ' is'} switched off.`}
          </p>
        </div>

        {result && (
          <>
            <ol className="lanes" aria-label="What each session did, in order">
              <li className="lane-head" style={{ gridColumn: 1, gridRow: 1 }}><h3>Session A</h3></li>
              <li className="lane-head" style={{ gridColumn: 2, gridRow: 1 }}><h3>Session B</h3></li>
              {result.steps.slice(0, shown).map((s, i) => (
                <li key={i} className="step" data-tone={s.tone}
                  style={{ gridColumn: s.who === 'A' ? 1 : 2, gridRow: i + 2 }}>
                  {s.text}
                </li>
              ))}
            </ol>

            {finished && (
              <div className="verdict-box" data-ok={result.activeCommitments === 1} role="status">
                {result.activeCommitments === 1 ? (
                  <>
                    <h3>Exactly one commitment exists.</h3>
                    <p>
                      Session B was stopped
                      {result.stoppedBy ? ` by layer ${result.stoppedBy}` : ''} and rolled back. The database said:
                    </p>
                    <p className="code">ERROR: {result.message}</p>
                  </>
                ) : (
                  <>
                    <h3>The project was funded twice.</h3>
                    <p>
                      {result.activeCommitments} active commitments now exist and {inr(result.committed)} is locked
                      against a {inr(100_000)} project. This is what the three layers prevent.
                    </p>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </Section>
  )
}

// ---------------------------------------------------------------- refusals

interface Attempt {
  id: string
  title: string
  detail: string
  run: (api: ExchangeApi) => Promise<ActionResult>
}

const ATTEMPTS: Attempt[] = [
  { id: 'flagged', title: 'Fund a flagged project',
    detail: 'Sundar Textiles tries to lock money for the sanitation project that failed the fraud screen.',
    run: api => api.commitFunds({ companyId: 3, projectId: 8 }) },
  { id: 'again', title: 'Fund a project that is already funded',
    detail: 'Kalpataru Motors tries to fund the Barmer attendance project that Meridian already funds.',
    run: api => api.commitFunds({ companyId: 2, projectId: 1 }) },
  { id: 'over', title: 'Commit more than the mandated budget',
    detail: 'Sundar Textiles, with ₹24 lakh to spend, tries to commit ₹28 lakh.',
    run: api => api.commitFunds({ companyId: 3, projectId: 5 }) },
  { id: 'update', title: 'Edit a row in the ledger',
    detail: 'Change the amount on ledger row 2, the first release.',
    run: api => api.tryLedgerMutation('UPDATE', 2) },
  { id: 'delete', title: 'Delete a row from the ledger',
    detail: 'Erase ledger row 1, the original lock.',
    run: api => api.tryLedgerMutation('DELETE', 1) },
]

function Refusals() {
  const { api, act } = useExchange()
  const [answers, setAnswers] = useState<Record<string, string>>({})

  async function attempt(a: Attempt) {
    const r = await act(a.title, () => a.run(api))
    setAnswers(prev => ({ ...prev, [a.id]: r.ok ? 'It went through. That should not happen.' : r.error }))
  }

  return (
    <Section id="refusals" title="Try to break the rules"
      hint="Each button sends a request the database should refuse. The answer is its own error message, and nothing changes.">
      <ul className="attempts">
        {ATTEMPTS.map(a => (
          <li key={a.id} className="attempt">
            <div className="attempt__ask">
              <div>
                <h3>{a.title}</h3>
                <p className="muted small">{a.detail}</p>
              </div>
              <button className="btn btn--quiet btn--small" onClick={() => attempt(a)}>Try it</button>
            </div>
            {answers[a.id] && <p className="attempt__answer code" role="status">ERROR: {answers[a.id]}</p>}
          </li>
        ))}
      </ul>
    </Section>
  )
}
