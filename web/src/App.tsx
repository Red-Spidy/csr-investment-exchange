import { useEffect } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { Shell } from './components/Shell'
import { Exchange } from './pages/Exchange'
import { Funds } from './pages/Funds'
import { Impact } from './pages/Impact'
import { Matching } from './pages/Matching'
import { Projects } from './pages/Projects'
import { Safeguards } from './pages/Safeguards'

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

export function App() {
  return (
    <>
      <ScrollTop />
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Exchange />} />
          <Route path="projects/:id?" element={<Projects />} />
          <Route path="matching" element={<Matching />} />
          <Route path="funds" element={<Funds />} />
          <Route path="impact" element={<Impact />} />
          <Route path="safeguards" element={<Safeguards />} />
          <Route path="*" element={<Exchange />} />
        </Route>
      </Routes>
    </>
  )
}
