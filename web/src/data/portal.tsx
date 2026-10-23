// Which portal a page is rendered in. Identity lives in the URL (/ngo/2/..., /company/1/...),
// so signing in only opens a portal, a link can be bookmarked, and pages need no session store.

import { createContext, useContext } from 'react'

export type Role = 'ngo' | 'company' | 'review'

export interface Portal {
  role: Role
  /** URL prefix of this portal, e.g. /company/1 */
  base: string
  ngoId: number | null
  companyId: number | null
}

const PortalContext = createContext<Portal>({ role: 'review', base: '/review', ngoId: null, companyId: null })

export const PortalProvider = PortalContext.Provider

export function usePortal() {
  const p = useContext(PortalContext)
  /** A path inside this portal: to('/projects/3') is /review/projects/3 in the reviewer console. */
  const to = (path = '') => (path === '' || path === '/' ? p.base : `${p.base}${path}`)
  return { ...p, to }
}
