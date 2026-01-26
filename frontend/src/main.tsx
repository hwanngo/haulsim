import { ChakraProvider } from '@chakra-ui/react'
import React from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted CAT fonts (bundled, no external request; font-display: swap).
// Roboto Condensed 700 = headings; Noto Sans 400/600/700 = body + labels.
import '@fontsource/roboto-condensed/700.css'
import '@fontsource/noto-sans/400.css'
import '@fontsource/noto-sans/600.css'
import '@fontsource/noto-sans/700.css'
import App from './App'
import { system } from './system'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ChakraProvider value={system}>
      <App />
    </ChakraProvider>
  </React.StrictMode>,
)
