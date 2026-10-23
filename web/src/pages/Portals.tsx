import { Navigate, useParams } from 'react-router-dom'
import { PortalShell } from '../components/PortalShell'
import { Loading } from '../components/ui'
import { useExchange, useQuery } from '../data/store'
import { openMilestone } from '../lib/milestones'

function useId(param: string | undefined) {
  const id = Number(param)
  return Number.isInteger(id) && id > 0 ? id : null
}

export function NgoPortal() {
  const id = useId(useParams().ngoId)
  const { data: rows } = useQuery(api => api.scorecard())
  const { data: commitments } = useQuery(api => api.commitments())
  if (id === null) return <Navigate to="/" replace />
  if (!rows) return <Loading>Opening your account</Loading>
  const name = rows.find(r => r.ngoId === id)?.ngoName
  if (!name) return <Navigate to="/" replace />

  const base = `/ngo/${id}`
  const evidenceDue = (commitments ?? [])
    .filter(c => c.project.ngoId === id && openMilestone(c)?.verification === 'pending').length

  return (
    <PortalShell portal={{ role: 'ngo', base, ngoId: id, companyId: null }} title="NGO portal" who={name}
      links={[
        { to: base, label: 'My projects', icon: 'projects', end: true, badge: evidenceDue },
        { to: `${base}/new`, label: 'New proposal', icon: 'plus' },
      ]} />
  )
}

export function CompanyPortal() {
  const id = useId(useParams().companyId)
  const { companyId } = useExchange()
  const { data: companies } = useQuery(api => api.companies())
  const { data: commitments } = useQuery(api => api.commitments())
  const { data: rulebooks } = useQuery(api => api.rulebooks())
  const rulebook = rulebooks?.filter(r => r.companyId === id).sort((a, b) => b.id - a.id)[0]
  const { data: report } = useQuery(
    api => (rulebook ? api.matches(rulebook.id) : Promise.resolve(undefined)), [rulebook?.id, companyId])
  if (id === null) return <Navigate to="/" replace />
  if (!companies) return <Loading>Opening your account</Loading>
  const company = companies.find(c => c.id === id)
  if (!company) return <Navigate to="/" replace />

  const base = `/company/${id}`
  const held = (commitments ?? []).filter(c => c.commitment.companyId === id && c.commitment.status === 'active')
    .filter(c => c.phases.some(p => p.status === 'held')).length

  return (
    <PortalShell portal={{ role: 'company', base, ngoId: null, companyId: id }} title="CSR portal" who={company.name}
      links={[
        { to: base, label: 'Overview', icon: 'home', end: true },
        { to: `${base}/find`, label: 'Find projects', icon: 'find', badge: report?.ranked.length ?? 0 },
        { to: `${base}/funding`, label: 'Funding', icon: 'funds', badge: held },
        { to: `${base}/impact`, label: 'Impact', icon: 'impact' },
      ]} />
  )
}

export function ReviewPortal() {
  const { data: rows } = useQuery(api => api.scorecard())
  const { data: commitments } = useQuery(api => api.commitments())
  const toReview = (rows ?? []).filter(r => r.status === 'flagged' && r.commitmentId === null).length
  const toVerify = (commitments ?? []).flatMap(c => c.milestones).filter(m => m.verification === 'submitted').length

  return (
    <PortalShell portal={{ role: 'review', base: '/review', ngoId: null, companyId: null }} title="Review console"
      who="Exchange reviewer"
      links={[
        { to: '/review', label: 'Queue', icon: 'queue', end: true, badge: toReview + toVerify },
        { to: '/review/projects', label: 'All projects', icon: 'projects' },
        { to: '/review/milestones', label: 'Milestones', icon: 'milestones', badge: toVerify },
        { to: '/review/safeguards', label: 'Safeguards', icon: 'safeguards' },
      ]} />
  )
}
