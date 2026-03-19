// TrendChart.test.jsx — tests for the Recharts line chart component.
//
// Note: Recharts renders as SVG inside a ResponsiveContainer. The actual chart
// internals (lines, axes, gridlines) are hard to test meaningfully with RTL.
// We focus on what's testable and valuable:
//   - Title bar renders the chart title
//   - Legend labels render correctly
//   - Component doesn't crash with valid data

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import TrendChart from '../components/TrendChart'

// Mock data matching the shape from scenarios.js
const MOCK_CURRENT = [
  { day: 'Mon', value: 27.0 },
  { day: 'Tue', value: 26.2 },
  { day: 'Wed', value: 25.5 },
]

const MOCK_PREVIOUS = [
  { day: 'Mon', value: 29.8 },
  { day: 'Tue', value: 30.0 },
  { day: 'Wed', value: 29.2 },
]

describe('TrendChart', () => {
  // Helper
  const renderChart = (overrides = {}) => {
    const defaultProps = {
      title: 'Click Quality Daily Trend',
      current: MOCK_CURRENT,
      previous: MOCK_PREVIOUS,
      legendCurrent: 'This week (25.0% avg, n=1,206)',
      legendPrevious: 'Last week (29.5% avg, n=1,244)',
    }
    return render(<TrendChart {...defaultProps} {...overrides} />)
  }

  it('renders the chart title in the header bar', () => {
    renderChart()
    expect(screen.getByText('Click Quality Daily Trend')).toBeInTheDocument()
  })

  it('renders the current-week legend label', () => {
    renderChart()
    expect(screen.getByText('This week (25.0% avg, n=1,206)')).toBeInTheDocument()
  })

  it('renders the previous-week legend label', () => {
    renderChart()
    expect(screen.getByText('Last week (29.5% avg, n=1,244)')).toBeInTheDocument()
  })

  it('does not crash with minimal data (1 data point)', () => {
    renderChart({
      current: [{ day: 'Mon', value: 25.0 }],
      previous: [{ day: 'Mon', value: 29.8 }],
    })
    expect(screen.getByText('Click Quality Daily Trend')).toBeInTheDocument()
  })

  it('renders without crashing when previous data has fewer points', () => {
    // Edge case: previous week might have fewer data points if a day is missing
    renderChart({
      current: MOCK_CURRENT,
      previous: [{ day: 'Mon', value: 29.8 }],
    })
    expect(screen.getByText('Click Quality Daily Trend')).toBeInTheDocument()
  })
})
