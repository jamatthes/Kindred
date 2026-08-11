/**
 * Composition root: the providers every screen depends on, then the route gate.
 */

import { SessionProvider } from './app/session'
import { ToastProvider } from './app/ui/toast'
import { Routes } from './app/routes'

export default function App() {
  return (
    <ToastProvider>
      <SessionProvider>
        <Routes />
      </SessionProvider>
    </ToastProvider>
  )
}
