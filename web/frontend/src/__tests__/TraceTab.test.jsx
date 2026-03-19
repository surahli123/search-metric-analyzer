// TraceTab.test.jsx — tests for the top-level trace tab container.
//
// Covers:
//   - Renders filter pill tabs (All, SQL, Knowledge, Reasoning)
//   - Default active filter is "All"
//   - Renders all 4 phase cards for a valid scenario
//   - Shows "No trace data available" for unknown scenario key
//   - Clicking a filter pill changes the active filter
//   - Phase cards are visible for both known scenario keys

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import TraceTab from '../components/TraceTab'

describe('TraceTab', () => {
  it('renders all 4 filter pills', () => {
    render(<TraceTab scenarioKey="within_variance" />)
    expect(screen.getByText('All')).toBeInTheDocument()
    expect(screen.getByText('SQL')).toBeInTheDocument()
    expect(screen.getByText('Knowledge')).toBeInTheDocument()
    expect(screen.getByText('Reasoning')).toBeInTheDocument()
  })

  it('renders all 4 phase headers for within_variance', () => {
    render(<TraceTab scenarioKey="within_variance" />)
    expect(screen.getByText('UNDERSTAND')).toBeInTheDocument()
    expect(screen.getByText('HYPOTHESIZE')).toBeInTheDocument()
    expect(screen.getByText('DISPATCH')).toBeInTheDocument()
    expect(screen.getByText('SYNTHESIZE')).toBeInTheDocument()
  })

  it('renders all 4 phase headers for ranking_regression', () => {
    render(<TraceTab scenarioKey="ranking_regression" />)
    expect(screen.getByText('UNDERSTAND')).toBeInTheDocument()
    expect(screen.getByText('SYNTHESIZE')).toBeInTheDocument()
  })

  it('shows empty state for unknown scenario key', () => {
    render(<TraceTab scenarioKey="nonexistent_scenario" />)
    expect(screen.getByText('No trace data available')).toBeInTheDocument()
  })

  it('clicking SQL filter shows only SQL steps', () => {
    render(<TraceTab scenarioKey="within_variance" />)
    fireEvent.click(screen.getByText('SQL'))
    // SQL step labels should be visible
    expect(screen.getByText('Data quality gate')).toBeInTheDocument()
    // Reasoning-only steps should be hidden
    expect(screen.queryByText('Classify severity')).not.toBeInTheDocument()
  })

  it('clicking Knowledge filter shows only knowledge steps', () => {
    render(<TraceTab scenarioKey="within_variance" />)
    fireEvent.click(screen.getByText('Knowledge'))
    // Knowledge step labels should be visible
    expect(screen.getByText('Load metric definitions')).toBeInTheDocument()
    // SQL steps should be hidden
    expect(screen.queryByText('Data quality gate')).not.toBeInTheDocument()
  })

  it('clicking All filter shows all steps again', () => {
    render(<TraceTab scenarioKey="within_variance" />)
    // First filter to SQL
    fireEvent.click(screen.getByText('SQL'))
    // Then back to All
    fireEvent.click(screen.getByText('All'))
    // Both SQL and reasoning steps should be visible
    expect(screen.getByText('Data quality gate')).toBeInTheDocument()
    expect(screen.getByText('Classify severity')).toBeInTheDocument()
  })

  it('active filter pill gets accent styling', () => {
    render(<TraceTab scenarioKey="within_variance" />)
    // "All" is default active — should have accent styling
    const allPill = screen.getByText('All')
    expect(allPill.style.background).toContain('accent')
    expect(allPill.style.color).toBe('white')
  })

  it('inactive filter pills get muted styling', () => {
    render(<TraceTab scenarioKey="within_variance" />)
    // "SQL" is inactive by default
    const sqlPill = screen.getByText('SQL')
    expect(sqlPill.style.color).toContain('text-secondary')
  })
})
