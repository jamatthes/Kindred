import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { TimeField } from './TimeField'
import type { IsoTime } from './calendar'

function Harness({ initial = '', step }: { initial?: IsoTime | ''; step?: number }) {
  const [value, setValue] = useState<IsoTime | ''>(initial)
  return <TimeField label="Time" value={value} onChange={setValue} step={step} />
}

const field = () => screen.getByLabelText('Time', { selector: 'input' })

function type(text: string) {
  fireEvent.change(field(), { target: { value: text } })
  fireEvent.blur(field())
}

describe('TimeField — typing is the base', () => {
  it('accepts the ways people write a time and normalises to 24 hours', () => {
    render(<Harness />)
    type('2.30pm')
    expect(field()).toHaveValue('14:30')
  })

  it('snaps to the itinerary’s 15-minute grid', () => {
    render(<Harness />)
    type('14:38')
    expect(field()).toHaveValue('14:45')
  })

  it('honours a caller-supplied step', () => {
    render(<Harness step={30} />)
    type('10:20')
    expect(field()).toHaveValue('10:30')
  })

  it('rejects nonsense with an inline explanation and keeps what was typed', () => {
    render(<Harness />)
    type('lunchtime')
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a time like 14:30 or 2.30pm.')
    expect(field()).toHaveValue('lunchtime')
    expect(field()).toHaveAttribute('aria-invalid', 'true')
  })

  it('clears cleanly on an empty field', () => {
    render(<Harness initial="09:00" />)
    type('')
    expect(field()).toHaveValue('')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('commits on Enter without waiting for a blur', () => {
    render(<Harness />)
    fireEvent.change(field(), { target: { value: '0930' } })
    fireEvent.keyDown(field(), { key: 'Enter' })
    expect(field()).toHaveValue('09:30')
  })

  it('nudges by one grid step with ↑ and ↓', () => {
    render(<Harness initial="09:00" />)
    fireEvent.keyDown(field(), { key: 'ArrowUp' })
    expect(field()).toHaveValue('09:15')
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    fireEvent.keyDown(field(), { key: 'ArrowDown' })
    expect(field()).toHaveValue('08:45')
  })
})

describe('TimeField — the list', () => {
  it('offers every slot on the grid as a listbox', () => {
    render(<Harness initial="09:00" />)
    fireEvent.click(screen.getByRole('button', { name: /choose from the list/ }))
    const list = screen.getByRole('listbox', { name: 'Time' })
    expect(screen.getAllByRole('option')).toHaveLength(96)
    expect(list).toBeInTheDocument()
  })

  it('marks the current value as the selected option', () => {
    render(<Harness initial="09:00" />)
    fireEvent.click(screen.getByRole('button', { name: /choose from the list/ }))
    const selected = screen.getAllByRole('option').filter((o) => o.getAttribute('aria-selected') === 'true')
    expect(selected).toHaveLength(1)
  })

  it('is reachable by keyboard even before a value exists', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: /choose from the list/ }))
    const focusable = screen.getAllByRole('option').filter((o) => o.getAttribute('tabindex') === '0')
    expect(focusable).toHaveLength(1)
  })

  it('picks from the list and closes', () => {
    render(<Harness initial="09:00" />)
    fireEvent.click(screen.getByRole('button', { name: /choose from the list/ }))
    fireEvent.click(screen.getAllByRole('option')[40]) // 10:00
    expect(field()).toHaveValue('10:00')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on Escape', () => {
    render(<Harness initial="09:00" />)
    fireEvent.click(screen.getByRole('button', { name: /choose from the list/ }))
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'Escape' })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('rolls focus down the column with the arrow keys', () => {
    render(<Harness initial="09:00" />)
    fireEvent.click(screen.getByRole('button', { name: /choose from the list/ }))
    const options = screen.getAllByRole('option')
    options[36].focus()
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'ArrowDown' })
    expect(document.activeElement).toBe(options[37])
    fireEvent.keyDown(screen.getByRole('listbox'), { key: 'ArrowUp' })
    expect(document.activeElement).toBe(options[36])
  })
})
