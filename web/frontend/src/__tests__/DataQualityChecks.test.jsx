import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import DataQualityChecks from '../components/DataQualityChecks'

describe('DataQualityChecks', () => {
  it('renders PASS badges with human-readable labels', () => {
    render(<DataQualityChecks checks={[{ label: 'Logging artifact', status: 'pass' }]} />)
    // PASS badges show human-readable label ("Data integrity" instead of "Logging artifact")
    expect(screen.getByText(/PASS Data integrity/)).toBeInTheDocument()
  })
  it('renders WARN badges with technical label in parentheses', () => {
    render(<DataQualityChecks checks={[{ label: 'Trust gate', status: 'warn' }]} />)
    // WARN badges show human label + technical label: "Data quality (Trust gate)"
    expect(screen.getByText(/WARN Data quality \(Trust gate\)/)).toBeInTheDocument()
  })
  it('renders WARN badges for unknown labels as-is', () => {
    render(<DataQualityChecks checks={[{ label: 'Decomposition', status: 'warn' }]} />)
    // Unknown labels pass through without mapping
    expect(screen.getByText(/WARN Decomposition/)).toBeInTheDocument()
  })
})
