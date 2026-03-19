// Header.test.jsx — tests for the 3-tab navigation header.
//
// Covers:
//   - Renders product name and tagline
//   - Renders all 3 tab buttons (Investigate, Trace, Knowledge Base)
//   - Active tab gets accent styling (accent-light bg + accent color)
//   - Inactive tabs get muted color styling
//   - Clicking a tab calls onTabChange with the correct tab key
//   - No BETA badge rendered
//   - No disabled Dashboard button rendered

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import Header from '../components/Header'

describe('Header', () => {
  // Helper: render Header with default props
  const renderHeader = (props = {}) => {
    const defaultProps = {
      activeTab: 'investigate',
      onTabChange: vi.fn(),
    }
    return render(<Header {...defaultProps} {...props} />)
  }

  it('renders product name', () => {
    renderHeader()
    expect(screen.getByText('Search Metric Analyzer')).toBeInTheDocument()
  })

  it('renders tagline below product name', () => {
    renderHeader()
    expect(
      screen.getByText('AI-powered root cause analysis for search metric movements')
    ).toBeInTheDocument()
  })

  it('renders all 3 tab buttons', () => {
    renderHeader()
    expect(screen.getByText('Investigate')).toBeInTheDocument()
    expect(screen.getByText('Trace')).toBeInTheDocument()
    expect(screen.getByText('Knowledge Base')).toBeInTheDocument()
  })

  it('does NOT render BETA badge', () => {
    renderHeader()
    expect(screen.queryByText('BETA')).not.toBeInTheDocument()
  })

  it('does NOT render Dashboard button', () => {
    renderHeader()
    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument()
  })

  it('does NOT render Agent button', () => {
    renderHeader()
    expect(screen.queryByText('Agent')).not.toBeInTheDocument()
  })

  it('applies active styling to the active tab', () => {
    renderHeader({ activeTab: 'investigate' })
    const investigateBtn = screen.getByText('Investigate')
    // Active tab should have accent-light background and accent color
    expect(investigateBtn.style.background).toContain('accent-light')
    expect(investigateBtn.style.color).toContain('accent')
  })

  it('applies muted styling to inactive tabs', () => {
    renderHeader({ activeTab: 'investigate' })
    const traceBtn = screen.getByText('Trace')
    // Inactive tab should have muted color and no accent background
    expect(traceBtn.style.color).toContain('text-muted')
  })

  it('calls onTabChange with "investigate" when Investigate is clicked', () => {
    const onTabChange = vi.fn()
    renderHeader({ activeTab: 'trace', onTabChange })
    fireEvent.click(screen.getByText('Investigate'))
    expect(onTabChange).toHaveBeenCalledWith('investigate')
  })

  it('calls onTabChange with "trace" when Trace is clicked', () => {
    const onTabChange = vi.fn()
    renderHeader({ activeTab: 'investigate', onTabChange })
    fireEvent.click(screen.getByText('Trace'))
    expect(onTabChange).toHaveBeenCalledWith('trace')
  })

  it('calls onTabChange with "knowledge" when Knowledge Base is clicked', () => {
    const onTabChange = vi.fn()
    renderHeader({ activeTab: 'investigate', onTabChange })
    fireEvent.click(screen.getByText('Knowledge Base'))
    expect(onTabChange).toHaveBeenCalledWith('knowledge')
  })

  it('highlights the correct tab when activeTab changes', () => {
    // Render with trace as active
    renderHeader({ activeTab: 'trace' })
    const traceBtn = screen.getByText('Trace')
    const investigateBtn = screen.getByText('Investigate')
    // Trace should be active-styled
    expect(traceBtn.style.background).toContain('accent-light')
    // Investigate should be inactive-styled
    expect(investigateBtn.style.color).toContain('text-muted')
  })
})
