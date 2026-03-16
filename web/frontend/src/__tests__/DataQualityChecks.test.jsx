import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import DataQualityChecks from '../components/DataQualityChecks'

describe('DataQualityChecks', () => {
  it('renders PASS badges', () => {
    render(<DataQualityChecks checks={[{ label: 'Logging artifact', status: 'pass' }]} />)
    expect(screen.getByText(/PASS Logging artifact/)).toBeInTheDocument()
  })
  it('renders WARN badges', () => {
    render(<DataQualityChecks checks={[{ label: 'Decomposition', status: 'warn' }]} />)
    expect(screen.getByText(/WARN Decomposition/)).toBeInTheDocument()
  })
})
