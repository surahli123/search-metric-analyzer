import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import VerdictStrip from '../components/VerdictStrip'

describe('VerdictStrip', () => {
  it('renders verdict text and detail', () => {
    render(<VerdictStrip verdict="Within Variance" detail=" — SQS +0.3pp" n="n = 348" isPositive={false} severity="P2" />)
    expect(screen.getByText('Within Variance')).toBeInTheDocument()
  })
  it('uses green background for P2', () => {
    const { container } = render(<VerdictStrip verdict="Test" detail="" n="n=1" isPositive={false} severity="P2" />)
    expect(container.firstChild.style.background).toContain('green-bg')
  })
  it('uses red background for P1', () => {
    const { container } = render(<VerdictStrip verdict="Test" detail="" n="n=1" isPositive={false} severity="P1" />)
    expect(container.firstChild.style.background).toContain('red-bg')
  })
  it('uses blue background when isPositive', () => {
    const { container } = render(<VerdictStrip verdict="Test" detail="" n="n=1" isPositive={true} severity="P2" />)
    expect(container.firstChild.style.background).toContain('accent-light')
  })
})
