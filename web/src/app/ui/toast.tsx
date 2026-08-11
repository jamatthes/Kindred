/**
 * Toasts: transient confirmation of the user's *own* action, and nothing else. Anything
 * the user must be able to come back to is a persistent element, per the notification
 * rules in `plan/design-system.md`.
 */

import { useCallback, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ToastContext } from './toastContext'
import './ui.css'

type Toast = { id: number; message: string }

const TOAST_MS = 4000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const show = useCallback((message: string) => {
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, message }])
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), TOAST_MS)
  }, [])

  const value = useMemo(() => show, [show])

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Polite: a confirmation should not interrupt what a screen reader is saying. */}
      <div className="k-toast-region" aria-live="polite">
        {toasts.map((toast) => (
          <div className="k-toast" key={toast.id}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" aria-hidden="true">
              <path d="M5 12l4 4 10-10" />
            </svg>
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
