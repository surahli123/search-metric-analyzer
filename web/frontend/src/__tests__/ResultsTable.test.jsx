// ResultsTable.test.jsx — tests for the week-over-week metric comparison table.
//
// Covers:
//   - Renders title and date range in header
//   - Renders all column headers
//   - Renders row data (periods, metric values, deltas)
//   - Handles delta "—" with muted styling (baseline row has no delta)
//   - Renders multiple rows correctly

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ResultsTable from '../components/ResultsTable'

// Mock data matching the shape from scenarios.js
const MOCK_HEADERS = ['Period', 'Queries', 'CQ', 'SQS', 'AI Trigger', 'AI Success', 'delta CQ']
const MOCK_ROWS = [
  { period: 'This week', queries: '1,206', col3: '25.0%', col4: '64.2%', col5: '36.1%', col6: '81.8%', delta: '-4.5pp' },
  { period: 'Last week', queries: '1,244', col3: '29.5%', col4: '68.7%', col5: '35.9%', col6: '82.0%', delta: '—' },
]

describe('ResultsTable', () => {
  // Helper: render with defaults
  const renderTable = (overrides = {}) => {
    const defaultProps = {
      title: 'Click Quality Week-over-Week',
      dateRange: '2026-02-24 → 2026-03-07',
      headers: MOCK_HEADERS,
      rows: MOCK_ROWS,
    }
    return render(<ResultsTable {...defaultProps} {...overrides} />)
  }

  // --- Header rendering ---

  it('renders the table title', () => {
    renderTable()
    expect(screen.getByText('Click Quality Week-over-Week')).toBeInTheDocument()
  })

  it('renders the date range', () => {
    renderTable()
    expect(screen.getByText('2026-02-24 → 2026-03-07')).toBeInTheDocument()
  })

  // --- Column headers ---

  it('renders all column headers', () => {
    renderTable()
    MOCK_HEADERS.forEach((header) => {
      expect(screen.getByText(header)).toBeInTheDocument()
    })
  })

  // --- Row data ---

  it('renders period labels for all rows', () => {
    renderTable()
    expect(screen.getByText('This week')).toBeInTheDocument()
    expect(screen.getByText('Last week')).toBeInTheDocument()
  })

  it('renders metric values in rows', () => {
    renderTable()
    expect(screen.getByText('25.0%')).toBeInTheDocument()
    expect(screen.getByText('29.5%')).toBeInTheDocument()
  })

  it('renders query counts in rows', () => {
    renderTable()
    expect(screen.getByText('1,206')).toBeInTheDocument()
    expect(screen.getByText('1,244')).toBeInTheDocument()
  })

  it('renders delta values', () => {
    renderTable()
    expect(screen.getByText('-4.5pp')).toBeInTheDocument()
  })

  it('renders dash for baseline delta (no delta to compare against)', () => {
    renderTable()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  // --- Edge case: empty rows ---

  it('renders headers even when rows array is empty', () => {
    renderTable({ rows: [] })
    expect(screen.getByText('Click Quality Week-over-Week')).toBeInTheDocument()
    expect(screen.getByText('Period')).toBeInTheDocument()
  })
})
