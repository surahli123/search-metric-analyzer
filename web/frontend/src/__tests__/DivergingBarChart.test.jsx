import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import DivergingBarChart from '../components/DivergingBarChart'

const RED_BARS = [
  { label: 'CQ', value: '-4.5', width_pct: 90, direction: 'left', color: 'red', opacity: 1, bold: true },
  { label: 'AI', value: '+0.2', width_pct: 4, direction: 'right', color: 'muted', opacity: 0.4, bold: false },
]

describe('DivergingBarChart', () => {
  it('renders bar labels', () => {
    render(<DivergingBarChart bars={RED_BARS} insightHtml="" isPositive={false} />)
    expect(screen.getByText('CQ')).toBeInTheDocument()
  })
  it('when isPositive, overrides to accent', () => {
    const { container } = render(<DivergingBarChart bars={RED_BARS} insightHtml="" isPositive={true} />)
    expect(container.innerHTML).not.toContain('var(--red)')
  })
  it('when not isPositive, uses fixture colors', () => {
    const { container } = render(<DivergingBarChart bars={RED_BARS} insightHtml="" isPositive={false} />)
    expect(container.innerHTML).toContain('var(--red)')
  })
})
