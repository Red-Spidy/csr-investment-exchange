import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { Exchange } from './pages/Exchange'
import { Funds } from './pages/Funds'
import { Impact } from './pages/Impact'
import { Matching } from './pages/Matching'
import { NewProposal } from './pages/ngo/NewProposal'
import { NgoHome } from './pages/ngo/NgoHome'
import { CompanyPortal, NgoPortal, ReviewPortal } from './pages/Portals'
import { ProjectPage, Projects } from './pages/Projects'
import { ReviewQueue } from './pages/ReviewQueue'
import { Safeguards } from './pages/Safeguards'
import { SignIn } from './pages/SignIn'

function ScrollTop() {
  const { pathname, hash } = useLocation()
  useEffect(() => {
    if (hash) {
      // The target renders after data loads, so give it a moment.
      const t = window.setTimeout(() => document.querySelector(hash)?.scrollIntoView(), 120)
      return () => window.clearTimeout(t)
    }
    window.scrollTo(0, 0)
  }, [pathname, hash])
  return null
}

/** Links from before the portals existed (/projects/3, /funds) open in the review console. */
function Legacy({ to }: { to: string }) {
  const { id } = useParams()
  return <Navigate to={id ? `${to}/${id}` : to} replace />
}

export function App() {
  return (
    <>
      <ScrollTop />
      <Routes>
        <Route path="/" element={<SignIn />} />

        <Route path="/ngo/:ngoId" element={<NgoPortal />}>
          <Route index element={<NgoHome />} />
          <Route path="new" element={<NewProposal />} />
          <Route path="projects/:id" element={<ProjectPage />} />
        </Route>

        <Route path="/company/:companyId" element={<CompanyPortal />}>
          <Route index element={<Exchange />} />
          <Route path="find" element={<Matching />} />
          <Route path="funding" element={<Funds />} />
          <Route path="impact" element={<Impact />} />
          <Route path="projects/:id" element={<ProjectPage />} />
        </Route>

        <Route path="/review" element={<ReviewPortal />}>
          <Route index element={<ReviewQueue />} />
          <Route path="projects/:id?" element={<Projects />} />
          <Route path="milestones" element={<Funds />} />
          <Route path="safeguards" element={<Safeguards />} />
        </Route>

        <Route path="/projects/:id?" element={<Legacy to="/review/projects" />} />
        <Route path="/funds" element={<Navigate to="/review/milestones" replace />} />
        <Route path="/safeguards" element={<Navigate to="/review/safeguards" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
