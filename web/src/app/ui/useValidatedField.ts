/**
 * The validation behaviour `plan/design-system.md` specifies, in one place:
 * validate on blur, and once a field has shown an error, re-validate on every change so
 * the message disappears the moment the input becomes valid. Never validate on the first
 * keystroke — telling someone their half-typed password is too short is nagging, not help.
 */

import { useCallback, useState } from 'react'
import type { ChangeEvent, FocusEvent } from 'react'

export type Validator = (value: string) => string | null

export type ValidatedField = {
  value: string
  error: string | null
  setValue: (value: string) => void
  /** Force the error state, e.g. from a server response about this field. */
  setError: (error: string | null) => void
  /** Run the validator now and publish the result — used on submit. */
  validate: () => boolean
  reset: () => void
  inputProps: {
    value: string
    onChange: (event: ChangeEvent<HTMLInputElement>) => void
    onBlur: (event: FocusEvent<HTMLInputElement>) => void
  }
}

export function useValidatedField(validator: Validator = () => null, initial = ''): ValidatedField {
  const [value, setValue] = useState(initial)
  const [error, setError] = useState<string | null>(null)

  const onChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const next = event.target.value
      setValue(next)
      // Only after the first error: re-validating from the first keystroke would flash
      // "required" at someone who is still typing.
      setError((current) => (current === null ? null : validator(next)))
    },
    [validator],
  )

  const onBlur = useCallback(() => setError(validator(value)), [validator, value])

  const validate = useCallback(() => {
    const result = validator(value)
    setError(result)
    return result === null
  }, [validator, value])

  const reset = useCallback(() => {
    setValue(initial)
    setError(null)
  }, [initial])

  return {
    value,
    error,
    setValue,
    setError,
    validate,
    reset,
    inputProps: { value, onChange, onBlur },
  }
}
