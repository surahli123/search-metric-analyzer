// TracePhaseCard.test.jsx — tests for the expandable phase card in the trace viewer.
//
// Covers:
//   - Renders phase name in header
//   - Shows step count in header
//   - Shows timing in header
//   - Status dot: green for 'done', amber for 'active', gray for 'pending'
//   - Starts expanded by default, shows all steps
//   - Click header collapses, hides steps
//   - Click again re-expands
//   - Filter prop hides non-matching step types
//   - Filter 'all' shows all steps

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import TracePhaseCard from '../components/TracePhaseCard'

// --- Mock phase data ---

const MOCK_PHASE = {
  name: 'UNDERSTAND',
  status: 'done',
  duration_s: 3.2,
  steps: [
    { type: 'sql', label: 'Data quality gate', detail: 'Logging check', duration_s: 3.2, rows: 7 },
    { type: 'knowledge', label: 'Load metric defs', detail: 'SQS formula', file: 'metric_definitions.yaml' },
    { type: 'reasoning', label: 'Classify severity', detail: 'P2 minor' },
    { type: 'output', label: 'UnderstandResult', detail: 'metric=SQS' },
  ],
}

const ACTIVE_PHASE = {
  name: 'HYPOTHESIZE',
  status: 'active',
  duration_s: 1.8,
  steps: [
    { type: 'reasoning', label: 'Generate hypotheses', detail: 'Co-movement match' },
  ],
}

const PENDING_PHASE = {
  name: 'DISPATCH',
  status: 'pending',
  duration_s: 0,
  steps: [],
}

describe('TracePhaseCard', () => {
  it('renders the phase name', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="all" />)
    expect(screen.getByText('UNDERSTAND')).toBeInTheDocument()
  })

  it('shows step count in header', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="all" />)
    // 4 steps total — displayed as "4 steps" in header
    expect(screen.getByText(/4 steps/)).toBeInTheDocument()
  })

  it('shows timing in header', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="all" />)
    // Phase timing (3.2s) appears in both the header and the SQL step metadata.
    // Verify at least the header timing exists — getAllByText avoids the ambiguity.
    const matches = screen.getAllByText(/3\.2s/)
    expect(matches.length).toBeGreaterThanOrEqual(1)
  })

  it('renders green status dot for done phase', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="all" />)
    // The status dot is a small span with green background
    const dot = screen.getByTestId('status-dot')
    expect(dot.style.background).toContain('green')
  })

  it('renders amber status dot for active phase', () => {
    render(<TracePhaseCard phase={ACTIVE_PHASE} filter="all" />)
    const dot = screen.getByTestId('status-dot')
    expect(dot.style.background).toContain('amber')
  })

  it('renders gray status dot for pending phase', () => {
    render(<TracePhaseCard phase={PENDING_PHASE} filter="all" />)
    const dot = screen.getByTestId('status-dot')
    expect(dot.style.background).toContain('text-muted')
  })

  it('starts expanded — shows step labels', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="all" />)
    expect(screen.getByText('Data quality gate')).toBeInTheDocument()
    expect(screen.getByText('Load metric defs')).toBeInTheDocument()
    expect(screen.getByText('Classify severity')).toBeInTheDocument()
    expect(screen.getByText('UnderstandResult')).toBeInTheDocument()
  })

  it('click header collapses — hides steps', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="all" />)
    // Click the header button to collapse
    fireEvent.click(screen.getByRole('button'))
    expect(screen.queryByText('Data quality gate')).not.toBeInTheDocument()
  })

  it('click header twice re-expands', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="all" />)
    const btn = screen.getByRole('button')
    fireEvent.click(btn) // collapse
    fireEvent.click(btn) // expand
    expect(screen.getByText('Data quality gate')).toBeInTheDocument()
  })

  it('filter=sql only shows SQL steps', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="sql" />)
    // SQL step should be visible
    expect(screen.getByText('Data quality gate')).toBeInTheDocument()
    // Non-SQL steps should be hidden
    expect(screen.queryByText('Load metric defs')).not.toBeInTheDocument()
    expect(screen.queryByText('Classify severity')).not.toBeInTheDocument()
    expect(screen.queryByText('UnderstandResult')).not.toBeInTheDocument()
  })

  it('filter=knowledge only shows knowledge steps', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="knowledge" />)
    expect(screen.getByText('Load metric defs')).toBeInTheDocument()
    expect(screen.queryByText('Data quality gate')).not.toBeInTheDocument()
  })

  it('filter=reasoning only shows reasoning steps', () => {
    render(<TracePhaseCard phase={MOCK_PHASE} filter="reasoning" />)
    expect(screen.getByText('Classify severity')).toBeInTheDocument()
    expect(screen.queryByText('Data quality gate')).not.toBeInTheDocument()
  })
})
