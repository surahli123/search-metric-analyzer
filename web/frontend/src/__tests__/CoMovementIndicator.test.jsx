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
})
