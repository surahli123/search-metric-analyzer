// QuestionInput.test.jsx — tests for the scenario switcher and disabled input bar.
//
// Covers:
//   - Renders all scenario pills (Within Variance, Ranking Regression)
//   - Active pill gets accent styling, inactive gets muted styling
//   - Clicking a pill calls onScenarioChange with the correct key
//   - Input bar is read-only (disabled in mock mode)
//   - Investigate button is disabled
//   - Placeholder text is rendered

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import QuestionInput from '../components/QuestionInput'

describe('QuestionInput', () => {
  // Helper: render with default props
  const renderInput = (overrides = {}) => {
    const defaultProps = {
      placeholder: 'Ask about another metric movement...',
      activeScenario: 'ranking_regression',
      onScenarioChange: vi.fn(),
    }
    return { ...render(<QuestionInput {...defaultProps} {...overrides} />), props: { ...defaultProps, ...overrides } }
  }

  // --- Scenario pills ---

  it('renders Within Variance pill', () => {
    renderInput()
    expect(screen.getByText('Within Variance')).toBeInTheDocument()
  })

  it('renders Ranking Regression pill', () => {
    renderInput()
    expect(screen.getByText('Ranking Regression')).toBeInTheDocument()
  })

  it('calls onScenarioChange with "within_variance" when that pill is clicked', () => {
    const onScenarioChange = vi.fn()
    renderInput({ onScenarioChange })
    fireEvent.click(screen.getByText('Within Variance'))
    expect(onScenarioChange).toHaveBeenCalledWith('within_variance')
  })

  it('calls onScenarioChange with "ranking_regression" when that pill is clicked', () => {
    const onScenarioChange = vi.fn()
    renderInput({ onScenarioChange })
    fireEvent.click(screen.getByText('Ranking Regression'))
    expect(onScenarioChange).toHaveBeenCalledWith('ranking_regression')
  })

  it('highlights the active pill with accent background', () => {
    const { container } = renderInput({ activeScenario: 'within_variance' })
    const withinPill = screen.getByText('Within Variance')
    // Active pill should have accent background
    expect(withinPill.style.background).toContain('var(--accent)')
    expect(withinPill.style.color).toBe('white')
  })

  it('shows inactive pill with muted styling', () => {
    renderInput({ activeScenario: 'ranking_regression' })
    const withinPill = screen.getByText('Within Variance')
    // Inactive pill should NOT have accent background
    expect(withinPill.style.background).toContain('var(--bg-input)')
  })

  // --- Input bar ---

  it('renders the placeholder text', () => {
    renderInput()
    expect(screen.getByPlaceholderText('Ask about another metric movement...')).toBeInTheDocument()
  })

  it('input is read-only in mock mode', () => {
    renderInput()
    const input = screen.getByPlaceholderText('Ask about another metric movement...')
    expect(input).toHaveAttribute('readOnly')
  })

  // --- Investigate button ---

  it('renders the Investigate button', () => {
    renderInput()
    // QuestionInput always has exactly one "Investigate" button
    expect(screen.getByText('Investigate')).toBeInTheDocument()
  })

  it('Investigate button is disabled in mock mode', () => {
    renderInput()
    const button = screen.getByText('Investigate')
    expect(button).toBeDisabled()
  })
})
