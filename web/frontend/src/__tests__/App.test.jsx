import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from '../App'

describe('App', () => {
  it('renders without crashing', () => {
    render(<App />)
    expect(screen.getByText('Search Metric Analyzer')).toBeInTheDocument()
  })
  it('renders default scenario (ranking_regression)', () => {
    render(<App />)
    expect(screen.getByText('Ranking Regression')).toBeInTheDocument()
  })
})
