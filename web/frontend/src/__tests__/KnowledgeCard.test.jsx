// KnowledgeCard.test.jsx — tests for the expandable knowledge file card.
//
// Covers:
//   - Renders file name and description when collapsed
//   - Shows section count badge
//   - Does NOT show sections when collapsed (default state)
//   - Expands on click to show sections
//   - Each section renders label and summary
//   - Shows file path in expanded view
//   - Collapses on second click
//   - Has correct aria-expanded attribute

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import KnowledgeCard from '../components/KnowledgeCard'

// Minimal fixture matching the shape from knowledge_index.js
const MOCK_FILE = {
  id: 'metric_definitions',
  name: 'Metric Definitions',
  file: 'data/knowledge/metric_definitions.yaml',
  description: 'Core metric formulas, baselines by segment, alert thresholds.',
  sections: [
    {
      key: 'metrics',
      label: 'Metric Formulas',
      summary: 'Click Quality, SQS, AI Trigger formulas',
    },
    {
      key: 'baseline_by_segment',
      label: 'Baselines by Segment',
      summary: 'Expected metric values for each tier',
    },
  ],
}

// Single-section fixture for testing singular "section" label
const SINGLE_SECTION_FILE = {
  id: 'corrections',
  name: 'Corrections Log',
  file: 'data/knowledge/corrections.yaml',
  description: 'Past diagnostic mistakes and corrections.',
  sections: [
    {
      key: 'corrections',
      label: 'Corrections',
      summary: 'Historical corrections with 90-day expiry',
    },
  ],
}

describe('KnowledgeCard', () => {
  it('renders file name and description', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    expect(screen.getByText('Metric Definitions')).toBeInTheDocument()
    expect(screen.getByText('Core metric formulas, baselines by segment, alert thresholds.')).toBeInTheDocument()
  })

  it('shows section count badge with plural label', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    expect(screen.getByText('2 sections')).toBeInTheDocument()
  })

  it('shows singular "section" for single-section files', () => {
    render(<KnowledgeCard file={SINGLE_SECTION_FILE} />)
    expect(screen.getByText('1 section')).toBeInTheDocument()
  })

  it('is collapsed by default — sections not visible', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    // Section labels should NOT be in the document when collapsed
    expect(screen.queryByText('Metric Formulas')).not.toBeInTheDocument()
    expect(screen.queryByText('Baselines by Segment')).not.toBeInTheDocument()
    // File path should NOT be visible when collapsed
    expect(screen.queryByText('data/knowledge/metric_definitions.yaml')).not.toBeInTheDocument()
  })

  it('has aria-expanded=false when collapsed', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    const button = screen.getByRole('button')
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })

  it('expands on click to show sections', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    fireEvent.click(screen.getByRole('button'))
    // Both sections should now be visible
    expect(screen.getByText('Metric Formulas')).toBeInTheDocument()
    expect(screen.getByText('Baselines by Segment')).toBeInTheDocument()
  })

  it('shows section summaries when expanded', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Click Quality, SQS, AI Trigger formulas')).toBeInTheDocument()
    expect(screen.getByText('Expected metric values for each tier')).toBeInTheDocument()
  })

  it('shows file path when expanded', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('data/knowledge/metric_definitions.yaml')).toBeInTheDocument()
  })

  it('has aria-expanded=true when expanded', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    const button = screen.getByRole('button')
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
  })

  it('collapses on second click — sections disappear', () => {
    render(<KnowledgeCard file={MOCK_FILE} />)
    const button = screen.getByRole('button')
    // Expand
    fireEvent.click(button)
    expect(screen.getByText('Metric Formulas')).toBeInTheDocument()
    // Collapse
    fireEvent.click(button)
    expect(screen.queryByText('Metric Formulas')).not.toBeInTheDocument()
  })
})
