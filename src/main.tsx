import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Toaster } from 'sonner'
import './index.css'
import App from './App.tsx'
import { PipelineProvider } from './context/PipelineContext'
import { AuthProvider } from './context/AuthContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthProvider>
      <PipelineProvider>
        <App />
        <Toaster position="bottom-right" richColors closeButton duration={3000} />
      </PipelineProvider>
    </AuthProvider>
  </StrictMode>,
)
