// Footer.test.jsx — tests for the persistent footer verdict strip.
//
// Covers:
//   - Renders verdict text, summary, metadata
//   - Blue background for isPositive=true (AI adoption signal)
//   - Red background for P0/P1 severity (regression)
//   - Green background for P2 severity (within variance)
//   - Renders query count and date range

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Footer from '../components/Footer'

describe('Footer', () => {
  // Helper: render Footer with default props
  const renderFooter = (overrides = {}) => {
    const defaultProps = {
      verdict: 'Within Variance',
      summary: 'SQS trending positive',
      totalQueries: '695 total',
      dateRange: '2026-02-03 → 2026-02-24',
      isPositive: false,
      severity: 'P2',
    }
    return render(<Footer {...defaultProps} {...overrides} />)
  }

  // --- Content rendering ---

  it('renders the verdict text', () => {
    renderFooter()
    expect(screen.getByText('Within Variance')).toBeInTheDocument()
  })

  it('renders the summary text', () => {
    renderFooter()
    expect(screen.getByText('SQS trending positive')).toBeInTheDocument()
  })

  it('renders the total queries count', () => {
    renderFooter()
    expect(screen.getByText('695 total')).toBeInTheDocument()
  })

  it('renders the date range', () => {
    renderFooter()
    expect(screen.getByText('2026-02-03 → 2026-02-24')).toBeInTheDocument()
  })

  // --- Color logic (3 severity states, same as VerdictStrip) ---

  it('uses blue (accent) badge when isPositive=true', () => {
    const { container } = renderFooter({ isPositive: true })
    // The verdict badge span should use accent-light background
    expect(container.innerHTML).toContain('var(--accent-light)')
    expect(container.innerHTML).toContain('var(--accent)')
  })

  it('uses red badge for P1 severity', () => {
    const { container } = renderFooter({ severity: 'P1', isPositive: false })
    expect(container.innerHTML).toContain('var(--red-bg)')
    expect(container.innerHTML).toContain('var(--red)')
  })

  it('uses red badge for P0 severity', () => {
    const { container } = renderFooter({ severity: 'P0', isPositive: false })
    expect(container.innerHTML).toContain('var(--red-bg)')
    expect(container.innerHTML).toContain('var(--red)')
  })

  it('uses green badge for P2 severity', () => {
    const { container } = renderFooter({ severity: 'P2', isPositive: false })
    expect(container.innerHTML).toContain('var(--green-bg)')
    expect(container.innerHTML).toContain('var(--green)')
  })

  it('isPositive takes priority over severity (blue overrides red)', () => {
    // Even with P1 severity, isPositive=true means the movement is expected
    const { container } = renderFooter({ severity: 'P1', isPositive: true })
    expect(container.innerHTML).toContain('var(--accent-light)')
    expect(container.innerHTML).not.toContain('var(--red-bg)')
  })
})
