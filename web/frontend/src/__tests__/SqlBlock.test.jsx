// SqlBlock.test.jsx — tests for the SQL query display component.
//
// Covers:
//   - Renders within a CollapsibleSection (collapsed by default)
//   - Shows query descriptions and performance metadata after expanding
//   - Renders SQL code in <pre> blocks
//   - Shows count badge matching number of queries
//   - Handles single and multiple queries

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import SqlBlock from '../components/SqlBlock'

const MOCK_QUERIES = [
  {
    description: 'Data quality gate',
    sql: 'SELECT COUNT(*) FROM search_metrics',
    duration_s: 3.2,
    rows: 7,
  },
  {
    description: 'Week-over-week comparison',
    sql: 'SELECT tenant_tier, AVG(cq) FROM metrics GROUP BY 1',
    duration_s: 5.8,
    rows: 6,
  },
]

describe('SqlBlock', () => {
  // --- Default collapsed state ---

  it('shows "SQL Queries" header when collapsed', () => {
    render(<SqlBlock queries={MOCK_QUERIES} />)
    expect(screen.getByText('SQL Queries')).toBeInTheDocument()
  })

  it('is collapsed by default (SQL content not visible)', () => {
    render(<SqlBlock queries={MOCK_QUERIES} />)
    // SQL text should NOT be visible when collapsed
    expect(screen.queryByText('SELECT COUNT(*) FROM search_metrics')).not.toBeInTheDocument()
  })

  it('shows query count badge', () => {
    render(<SqlBlock queries={MOCK_QUERIES} />)
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  // --- Expanded state ---

  it('shows query descriptions after expanding', () => {
    render(<SqlBlock queries={MOCK_QUERIES} />)
    // Expand the CollapsibleSection
    fireEvent.click(screen.getByRole('button'))

    expect(screen.getByText('Data quality gate')).toBeInTheDocument()
    expect(screen.getByText('Week-over-week comparison')).toBeInTheDocument()
  })

  it('shows SQL code after expanding', () => {
    render(<SqlBlock queries={MOCK_QUERIES} />)
    fireEvent.click(screen.getByRole('button'))

    expect(screen.getByText('SELECT COUNT(*) FROM search_metrics')).toBeInTheDocument()
    expect(screen.getByText(/SELECT tenant_tier/)).toBeInTheDocument()
  })

  it('shows duration and row count metadata after expanding', () => {
    render(<SqlBlock queries={MOCK_QUERIES} />)
    fireEvent.click(screen.getByRole('button'))

    expect(screen.getByText(/3\.2s/)).toBeInTheDocument()
    expect(screen.getByText(/7 rows/)).toBeInTheDocument()
    expect(screen.getByText(/5\.8s/)).toBeInTheDocument()
    expect(screen.getByText(/6 rows/)).toBeInTheDocument()
  })

  // --- Edge case: single query ---

  it('works with a single query', () => {
    render(<SqlBlock queries={[MOCK_QUERIES[0]]} />)
    // Count badge should show 1
    expect(screen.getByText('1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Data quality gate')).toBeInTheDocument()
  })
})
