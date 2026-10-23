import '@fontsource-variable/bricolage-grotesque/wdth.css'
import '@fontsource-variable/instrument-sans/index.css'
import './styles/base.css'
import './styles/shell.css'
import './styles/cloth.css'
import './styles/pages.css'
import './styles/portal.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import { ExchangeProvider } from './data/store'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ExchangeProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ExchangeProvider>
  </StrictMode>,
)
