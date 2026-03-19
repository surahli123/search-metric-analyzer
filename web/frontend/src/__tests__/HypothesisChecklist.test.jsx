import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import HypothesisChecklist from '../components/HypothesisChecklist'

const MOCK = [
  { category: 'instrumentation', status: 'not_evaluated' },
  { category: 'algorithm_model', status: 'matched', reason: 'Pattern matched' },
  { category: 'seasonal', status: 'not_evaluated' },
]

describe('HypothesisChecklist', () => {
  it('renders matched category prominently', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    // Matched hypothesis is always visible without expanding
    expect(screen.getByText(/Algorithm/)).toBeInTheDocument()
  })
  it('shows non-matched categories after expanding', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    // Non-matched hypotheses are hidden behind expand toggle
    expect(screen.queryByText(/Instrumentation/)).not.toBeInTheDocument()
    // Click the expand toggle
    fireEvent.click(screen.getByText(/other hypothesis/))
    // Now non-matched categories should be visible
    expect(screen.getByText(/Instrumentation/)).toBeInTheDocument()
  })
  it('shows matched badge', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    expect(screen.getByText('matched')).toBeInTheDocument()
  })
  it('shows "not indicated" badges after expanding', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    // Expand the remaining hypotheses
    fireEvent.click(screen.getByText(/other hypothesis/))
    expect(screen.getAllByText('not indicated')).toHaveLength(2)
  })
  it('shows section header as Root Cause Analysis', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    expect(screen.getByText('Root Cause Analysis')).toBeInTheDocument()
  })
  it('does NOT show ruled_out', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    expect(screen.queryByText('ruled out')).not.toBeInTheDocument()
  })
})
