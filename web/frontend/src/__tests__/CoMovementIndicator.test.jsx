// CoMovementIndicator.test.jsx — tests for the metric movement pattern component.
//
// Covers:
//   - Renders "Metric Movement Pattern" section header
//   - Expected badge for positive patterns, hidden for negative
//   - Neutral (blue) colors for positive, red/green for negative
//   - Conclusion-first rendering: explanation sentence BEFORE metric chips
//   - Positive: green checkmark + "All metrics moving as expected" text
//   - Negative: amber warning + "Unusual metric pattern detected" text
//   - Renders all 4 metric labels with arrows and delta values
//   - Pattern description text rendered

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import CoMovementIndicator from '../components/CoMovementIndicator'

const POSITIVE = {
  pattern_matched: 'ai_adoption',
  is_positive: true,
  metric_directions: {
    click_quality: { direction: 'down', delta_pct: -1.1 },
    search_quality_success: { direction: 'up', delta_pct: 0.4 },
    ai_trigger: { direction: 'up', delta_pct: 6.7 },
    ai_success: { direction: 'up', delta_pct: 1.5 },
  },
  pattern_description: 'AI adoption',
}

const NEGATIVE = {
  pattern_matched: 'ranking_regression',
  is_positive: false,
  metric_directions: {
    click_quality: { direction: 'down', delta_pct: -15.2 },
    search_quality_success: { direction: 'down', delta_pct: -4.5 },
    ai_trigger: { direction: 'stable', delta_pct: 0.3 },
    ai_success: { direction: 'stable', delta_pct: -0.1 },
  },
  pattern_description: 'Ranking regression',
}

describe('CoMovementIndicator', () => {
  // --- Existing tests ---

  it('shows Expected badge when positive', () => {
    render(<CoMovementIndicator coMovement={POSITIVE} />)
    expect(screen.getByText('Expected')).toBeInTheDocument()
  })
  it('hides Expected badge when negative', () => {
    render(<CoMovementIndicator coMovement={NEGATIVE} />)
    expect(screen.queryByText('Expected')).not.toBeInTheDocument()
  })
  it('uses neutral colors when positive', () => {
    const { container } = render(<CoMovementIndicator coMovement={POSITIVE} />)
    expect(container.innerHTML).not.toContain('var(--red)')
  })

  // --- Section header ---

  it('renders "Metric Movement Pattern" section header', () => {
    render(<CoMovementIndicator coMovement={POSITIVE} />)
    expect(screen.getByText('Metric Movement Pattern')).toBeInTheDocument()
  })

  // --- Conclusion-first rendering ---

  it('shows green checkmark and "expected" explanation for positive patterns', () => {
    render(<CoMovementIndicator coMovement={POSITIVE} />)
    // The conclusion sentence should appear BEFORE the metric chips
    expect(screen.getByText(/All metrics moving as expected/)).toBeInTheDocument()
    // Green checkmark icon
    expect(screen.getByText('✓')).toBeInTheDocument()
  })

  it('shows amber warning and "unusual" explanation for negative patterns', () => {
    render(<CoMovementIndicator coMovement={NEGATIVE} />)
    expect(screen.getByText(/Unusual metric pattern detected/)).toBeInTheDocument()
    // Amber warning icon
    expect(screen.getByText('⚠')).toBeInTheDocument()
  })

  it('does NOT show checkmark for negative patterns', () => {
    render(<CoMovementIndicator coMovement={NEGATIVE} />)
    expect(screen.queryByText('✓')).not.toBeInTheDocument()
  })

  it('does NOT show warning icon for positive patterns', () => {
    render(<CoMovementIndicator coMovement={POSITIVE} />)
    expect(screen.queryByText('⚠')).not.toBeInTheDocument()
  })

  // --- Metric labels and values ---

  it('renders all 4 metric labels', () => {
    render(<CoMovementIndicator coMovement={POSITIVE} />)
    expect(screen.getByText('Click Quality')).toBeInTheDocument()
    expect(screen.getByText('SQS')).toBeInTheDocument()
    expect(screen.getByText('AI Trigger')).toBeInTheDocument()
    expect(screen.getByText('AI Success')).toBeInTheDocument()
  })

  it('renders delta percentages with correct signs', () => {
    render(<CoMovementIndicator coMovement={POSITIVE} />)
    // Down arrows: negative deltas don't get + prefix
    expect(screen.getByText(/↓ -1.1%/)).toBeInTheDocument()
    // Up arrows: positive deltas get + prefix
    expect(screen.getByText(/↑ \+0.4%/)).toBeInTheDocument()
    expect(screen.getByText(/↑ \+6.7%/)).toBeInTheDocument()
    expect(screen.getByText(/↑ \+1.5%/)).toBeInTheDocument()
  })

  it('renders stable arrows for stable metrics', () => {
    render(<CoMovementIndicator coMovement={NEGATIVE} />)
    // AI Trigger is stable with +0.3%
    expect(screen.getByText(/→ \+0.3%/)).toBeInTheDocument()
    // AI Success is stable with -0.1%
    expect(screen.getByText(/→ -0.1%/)).toBeInTheDocument()
  })

  // --- Pattern description ---

  it('renders the pattern description', () => {
    render(<CoMovementIndicator coMovement={POSITIVE} />)
    expect(screen.getByText('AI adoption')).toBeInTheDocument()
  })

  it('renders negative pattern description', () => {
    render(<CoMovementIndicator coMovement={NEGATIVE} />)
    expect(screen.getByText('Ranking regression')).toBeInTheDocument()
  })

  // --- Color behavior for negative patterns ---

  it('uses red for down direction in negative patterns', () => {
    const { container } = render(<CoMovementIndicator coMovement={NEGATIVE} />)
    expect(container.innerHTML).toContain('var(--red)')
  })
})
