/**
 * The toast context and its hook, split from the provider component so the module exports
 * only one kind of thing — which is what keeps React Fast Refresh working.
 */

import { createContext, useContext } from 'react'

export type ShowToast = (message: string) => void

export const ToastContext = createContext<ShowToast | null>(null)

export function useToast(): ShowToast {
  const show = useContext(ToastContext)
  if (show === null) throw new Error('useToast must be used inside <ToastProvider>')
  return show
}
