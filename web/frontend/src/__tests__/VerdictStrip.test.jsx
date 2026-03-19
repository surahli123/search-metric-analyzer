// VerdictStrip.test.jsx — tests for the verdict banner component.
//
// Covers:
//   - Renders verdict text and detail
//   - 3-state color logic: blue (positive), red (P0/P1), green (P2)
//   - verdictHuman prop: shows human verdict prominently, technical verdict as subtitle
//   - severityHuman prop: shows combined "Human (Technical)" badge
//   - Fallback behavior when human labels are not provided
//   - n badge always rendered

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import VerdictStrip from '../components/VerdictStrip'

describe('VerdictStrip', () => {
  // --- Existing tests (color logic) ---

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

  // --- New: verdictHuman prop ---

  it('shows verdictHuman as the primary text when provided', () => {
    render(
      <VerdictStrip
        verdict="Ranking Regression"
        verdictHuman="Ranking quality dropped — needs investigation"
        detail=" — CQ -15.2%"
        n="n=2,450"
        isPositive={false}
        severity="P1"
      />
    )
    // Human verdict is the prominent text
    expect(screen.getByText('Ranking quality dropped — needs investigation')).toBeInTheDocument()
  })

  it('shows technical verdict as subtitle when verdictHuman is provided', () => {
    render(
      <VerdictStrip
        verdict="Ranking Regression"
        verdictHuman="Ranking quality dropped — needs investigation"
        detail=" — CQ -15.2%"
        n="n=2,450"
        isPositive={false}
        severity="P1"
      />
    )
    // Technical verdict + detail shown in smaller text
    expect(screen.getByText(/Ranking Regression — CQ -15.2%/)).toBeInTheDocument()
  })

  it('falls back to technical verdict when verdictHuman is not provided', () => {
    render(
      <VerdictStrip
        verdict="Within Variance"
        detail=" — SQS +0.3pp"
        n="n=348"
        isPositive={false}
        severity="P2"
      />
    )
    // Without verdictHuman, the technical verdict is the primary text
    expect(screen.getByText('Within Variance')).toBeInTheDocument()
  })

  // --- New: severityHuman prop ---

  it('shows combined severity badge "Human (Technical)" when severityHuman is provided', () => {
    render(
      <VerdictStrip
        verdict="Test"
        verdictHuman="Test Human"
        detail=""
        n="n=1"
        isPositive={false}
        severity="P1"
        severityHuman="Urgent"
      />
    )
    expect(screen.getByText('Urgent (P1)')).toBeInTheDocument()
  })

  it('shows just technical severity when severityHuman is not provided', () => {
    render(
      <VerdictStrip
        verdict="Test"
        detail=""
        n="n=1"
        isPositive={false}
        severity="P2"
      />
    )
    expect(screen.getByText('P2')).toBeInTheDocument()
  })

  it('shows "Minor (P2)" badge for within-variance scenario', () => {
    render(
      <VerdictStrip
        verdict="Within Variance"
        verdictHuman="Normal fluctuation — no action needed"
        detail=""
        n="n=348"
        isPositive={false}
        severity="P2"
        severityHuman="Minor"
      />
    )
    expect(screen.getByText('Minor (P2)')).toBeInTheDocument()
  })

  // --- n badge ---

  it('always renders the n badge', () => {
    render(<VerdictStrip verdict="Test" detail="" n="n = 14,200 queries" isPositive={false} severity="P2" />)
    expect(screen.getByText('n = 14,200 queries')).toBeInTheDocument()
  })

  // --- P0 severity ---

  it('uses red background for P0 (critical)', () => {
    const { container } = render(<VerdictStrip verdict="Test" detail="" n="n=1" isPositive={false} severity="P0" />)
    expect(container.firstChild.style.background).toContain('red-bg')
  })
})
