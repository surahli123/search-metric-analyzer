import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import HypothesisChecklist from '../components/HypothesisChecklist'

const MOCK = [
  { category: 'instrumentation', status: 'not_evaluated' },
  { category: 'algorithm_model', status: 'matched', reason: 'Pattern matched' },
  { category: 'seasonal', status: 'not_evaluated' },
]

describe('HypothesisChecklist', () => {
  it('renders all categories', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    expect(screen.getByText(/Instrumentation/)).toBeInTheDocument()
    expect(screen.getByText(/Algorithm/)).toBeInTheDocument()
  })
  it('shows matched badge', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    expect(screen.getByText('matched')).toBeInTheDocument()
  })
  it('shows not evaluated badges', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    expect(screen.getAllByText('not evaluated')).toHaveLength(2)
  })
  it('does NOT show ruled_out', () => {
    render(<HypothesisChecklist hypotheses={MOCK} />)
    expect(screen.queryByText('ruled out')).not.toBeInTheDocument()
  })
})
