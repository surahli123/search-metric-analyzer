// TraceStep.test.jsx — tests for the individual step row in the trace viewer.
//
// Covers:
//   - Renders type badge with correct text for each step type
//   - Renders label and detail text
//   - SQL steps show duration and row count metadata
//   - Knowledge steps show file reference
//   - Reasoning/output steps do NOT show SQL-specific metadata
//   - Type badge uses correct color variables per type

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import TraceStep from '../components/TraceStep'

// --- Mock steps for each type ---

const SQL_STEP = {
  type: 'sql',
  label: 'Data quality gate',
  detail: 'Logging completeness check',
  duration_s: 3.2,
  rows: 7,
}

const KNOWLEDGE_STEP = {
  type: 'knowledge',
  label: 'Load metric definitions',
  detail: 'metric_definitions.yaml → SQS formula',
  file: 'metric_definitions.yaml',
}

const REASONING_STEP = {
  type: 'reasoning',
  label: 'Classify severity',
  detail: '+0.3pp → P2 (Minor), within normal fluctuation',
}

const OUTPUT_STEP = {
  type: 'output',
  label: 'UnderstandResult',
  detail: 'metric=SQS, severity=P2, co_movement=ai_adoption',
}

describe('TraceStep', () => {
  it('renders the type badge text', () => {
    render(<TraceStep step={SQL_STEP} />)
    expect(screen.getByText('sql')).toBeInTheDocument()
  })

  it('renders the label', () => {
    render(<TraceStep step={SQL_STEP} />)
    expect(screen.getByText('Data quality gate')).toBeInTheDocument()
  })

  it('renders the detail text', () => {
    render(<TraceStep step={SQL_STEP} />)
    expect(screen.getByText('Logging completeness check')).toBeInTheDocument()
  })

  it('shows duration and row count for SQL steps', () => {
    render(<TraceStep step={SQL_STEP} />)
    // Metadata line includes both duration and row count
    expect(screen.getByText(/3\.2s/)).toBeInTheDocument()
    expect(screen.getByText(/7 rows/)).toBeInTheDocument()
  })

  it('shows file reference for knowledge steps', () => {
    render(<TraceStep step={KNOWLEDGE_STEP} />)
    // The file name appears in both detail and metadata — check that at least
    // the metadata line exists by looking for all matches (detail + metadata).
    const matches = screen.getAllByText(/metric_definitions\.yaml/)
    expect(matches.length).toBeGreaterThanOrEqual(2)
  })

  it('renders knowledge type badge', () => {
    render(<TraceStep step={KNOWLEDGE_STEP} />)
    expect(screen.getByText('knowledge')).toBeInTheDocument()
  })

  it('renders reasoning type badge', () => {
    render(<TraceStep step={REASONING_STEP} />)
    expect(screen.getByText('reasoning')).toBeInTheDocument()
  })

  it('renders output type badge', () => {
    render(<TraceStep step={OUTPUT_STEP} />)
    expect(screen.getByText('output')).toBeInTheDocument()
  })

  it('does NOT show duration metadata for reasoning steps', () => {
    render(<TraceStep step={REASONING_STEP} />)
    // Reasoning steps have no duration_s or rows
    expect(screen.queryByText(/rows/)).not.toBeInTheDocument()
  })

  it('applies correct color variable to SQL badge', () => {
    render(<TraceStep step={SQL_STEP} />)
    const badge = screen.getByText('sql')
    expect(badge.style.background).toContain('purple-bg')
    expect(badge.style.color).toContain('purple')
  })

  it('applies correct color variable to knowledge badge', () => {
    render(<TraceStep step={KNOWLEDGE_STEP} />)
    const badge = screen.getByText('knowledge')
    expect(badge.style.background).toContain('teal-bg')
    expect(badge.style.color).toContain('teal')
  })

  it('applies correct color variable to reasoning badge', () => {
    render(<TraceStep step={REASONING_STEP} />)
    const badge = screen.getByText('reasoning')
    expect(badge.style.background).toContain('coral-bg')
    expect(badge.style.color).toContain('coral')
  })

  it('applies correct color variable to output badge', () => {
    render(<TraceStep step={OUTPUT_STEP} />)
    const badge = screen.getByText('output')
    expect(badge.style.background).toContain('green-bg')
    expect(badge.style.color).toContain('green')
  })
})
