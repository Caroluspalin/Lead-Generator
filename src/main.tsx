import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'
import './index.css'
import App from './App.tsx'
import { PipelineProvider } from './context/PipelineContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PipelineProvider>
      <App />
      <Toaster position="bottom-right" richColors closeButton duration={3000} />
    </PipelineProvider>
  </StrictMode>,
)
