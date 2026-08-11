/**
 * Section 6 — Google API status.
 *
 * The check runs only on the button, never on load: this is the one place the product
 * deliberately spends API calls, and a section that probed on render would spend them every
 * time anyone opened the console. The stored result is what makes the section useful without
 * spending anything.
 *
 * Status is icon plus word, never colour alone, and every failure carries the server's own
 * one-line hint so the explanation of a `denied` is the same wherever it appears.
 */

import { useEffect, useState } from 'react'
import { ApiError } from '../../app/apiClient'
import { Banner, Button } from '../../app/ui/primitives'
import type { GoogleApiStatus, GoogleStatus } from '../../app/types'
import { adminApi } from './api'

const STATUS_TEXT: Record<GoogleApiStatus, { icon: string; word: string }> = {
  ok: { icon: '✓', word: 'OK' },
  configured: { icon: '✓', word: 'Configured' },
  denied: { icon: '✕', word: 'Denied' },
  quota: { icon: '⚠', word: 'Quota' },
  unreachable: { icon: '⚠', word: 'Unreachable' },
  unchecked: { icon: '◌', word: 'Not checked' },
}

export type GoogleSectionProps = {
  status: GoogleStatus
  onChecked: (next: GoogleStatus) => void
}

export function GoogleSection({ status, onChecked }: GoogleSectionProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cooldown, setCooldown] = useState(0)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setTimeout(() => setCooldown((seconds) => seconds - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  async function run() {
    setBusy(true)
    setError(null)
    try {
      onChecked(await adminApi.runGoogleCheck())
      // The server's limit is one a minute; the countdown says so rather than letting the
      // next press fail.
      setCooldown(60)
    } catch (cause) {
      if (cause instanceof ApiError) {
        setError(cause.message)
        if (cause.code === 'rate_limited') setCooldown(cause.retryAfter ?? 60)
      } else {
        setError('The check did not run.')
      }
    } finally {
      setBusy(false)
    }
  }

  const neverChecked = status.checked_at === null

  return (
    <section className="admin__section" id="section-google" aria-labelledby="google-heading">
      <h2 className="admin__section-title" id="google-heading">
        Google APIs
      </h2>

      {error ? <Banner tone="error">{error}</Banner> : null}

      <div className="admin__actions">
        <Button
          variant="secondary"
          busy={busy}
          disabled={cooldown > 0}
          onClick={() => void run()}
        >
          {cooldown > 0 ? `Run check (${cooldown}s)` : 'Run check'}
        </Button>
        <span className="admin__hint">
          This makes a few real API calls.{' '}
          {status.checked_at
            ? `Last checked ${new Date(status.checked_at).toLocaleString()}.`
            : 'It has never been run.'}
        </span>
      </div>

      {neverChecked ? (
        <p className="admin__empty">
          Nothing has been checked yet. The table below shows what will be, and whether a key
          is configured for each.
        </p>
      ) : null}

      <table className="admin__mini-table admin__mini-table--roomy">
        <thead>
          <tr>
            <th scope="col">API</th>
            <th scope="col">Key</th>
            <th scope="col">Status</th>
            <th scope="col">Detail</th>
          </tr>
        </thead>
        <tbody>
          {status.apis.map((row) => {
            const text = STATUS_TEXT[row.status] ?? STATUS_TEXT.unchecked
            return (
              <tr key={row.name}>
                <td>
                  <strong>{row.name}</strong>
                </td>
                <td className="admin__muted">{row.key_type}</td>
                <td>
                  {/* Icon *and* word: colour is never the only carrier of meaning. */}
                  <span className={`status-chip status-chip--${row.status}`}>
                    <span aria-hidden="true">{text.icon}</span> {text.word}
                  </span>
                </td>
                <td className="admin__muted">
                  {row.name === 'Maps JavaScript' ? (
                    <>It cannot be verified from the server — it loads in the browser.</>
                  ) : (
                    <>
                      {row.hint ?? (row.detail ? `Reported ${row.detail}.` : '—')}
                    </>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}
