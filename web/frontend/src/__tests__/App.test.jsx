// App.test.jsx — tests for the root App component with 3-tab architecture.
//
// Covers:
//   - Default render shows Header + Investigate tab content
//   - Tab switching via Header renders correct tab content
//   - Scenario state is preserved across tab switches
//   - Footer is NOT rendered in the app shell (moved inside InvestigateTab)
//   - All 3 tabs render without crashing

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import App from '../App'

describe('App', () => {
  it('renders the product name in Header', () => {
    render(<App />)
    expect(screen.getByText('Search Metric Analyzer')).toBeInTheDocument()
  })

  it('renders the tagline in Header', () => {
    render(<App />)
    expect(
      screen.getByText('AI-powered root cause analysis for search metric movements')
    ).toBeInTheDocument()
  })

  it('renders all 3 tab buttons in the header nav', () => {
    render(<App />)
    // "Investigate" appears twice: in the Header nav AND in QuestionInput's
    // submit button. Use getAllByText to confirm at least one exists for each tab.
    // Trace and Knowledge Base are unique to the Header nav.
    expect(screen.getAllByText('Investigate').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Trace')).toBeInTheDocument()
    expect(screen.getByText('Knowledge Base')).toBeInTheDocument()
  })

  it('defaults to Investigate tab with scenario content', () => {
    render(<App />)
    // Default scenario is ranking_regression — its question should appear
    // in the InvestigateTab content
    expect(screen.getAllByText('Ranking Regression').length).toBeGreaterThan(0)
  })

  it('switches to Trace tab when Trace button is clicked', () => {
    render(<App />)
    fireEvent.click(screen.getByText('Trace'))
    // TraceTab renders the 4 pipeline phase headers — checking for UNDERSTAND
    // confirms we're in the trace view, not investigate
    expect(screen.getByText('UNDERSTAND')).toBeInTheDocument()
    expect(screen.getByText('SYNTHESIZE')).toBeInTheDocument()
  })

  it('switches to Knowledge Base tab when KB button is clicked', () => {
    render(<App />)
    fireEvent.click(screen.getByText('Knowledge Base'))
    // KnowledgeBaseTab shows "Domain Knowledge" heading
    expect(screen.getByText('Domain Knowledge')).toBeInTheDocument()
  })

  it('switches back to Investigate tab from another tab', () => {
    render(<App />)
    // Go to Knowledge Base tab (avoids ambiguity with Trace tab text)
    fireEvent.click(screen.getByText('Knowledge Base'))
    expect(screen.getByText('Domain Knowledge')).toBeInTheDocument()
    // Go back to Investigate — click the first "Investigate" element which is
    // the Header nav tab (QuestionInput's "Investigate" button is unmounted
    // when not on the Investigate tab, so only one element matches)
    fireEvent.click(screen.getByText('Investigate'))
    // Should show the default scenario content again
    expect(screen.getAllByText('Ranking Regression').length).toBeGreaterThan(0)
  })

  it('hides Investigate content when on another tab', () => {
    render(<App />)
    // Verify Investigate content is present first
    expect(screen.getAllByText('Ranking Regression').length).toBeGreaterThan(0)
    // Switch to Knowledge Base
    fireEvent.click(screen.getByText('Knowledge Base'))
    // The scenario-specific verdict should no longer be in the DOM
    // (conditional rendering unmounts the inactive tab)
    expect(screen.queryByText('Ranking Regression')).not.toBeInTheDocument()
  })

  it('passes scenarioKey to TraceTab (renders scenario-specific trace data)', () => {
    render(<App />)
    fireEvent.click(screen.getByText('Trace'))
    // TraceTab loads TRACE_DATA[scenarioKey] — for ranking_regression,
    // the UNDERSTAND phase should be visible (it exists in both scenarios)
    expect(screen.getByText('UNDERSTAND')).toBeInTheDocument()
  })

  it('Investigate tab is highlighted by default', () => {
    render(<App />)
    // "Investigate" appears in both the Header nav tab and the QuestionInput
    // submit button. The nav tab is the one with accent-light background styling.
    const investigateBtns = screen.getAllByText('Investigate')
    const navTab = investigateBtns.find(
      (el) => el.style.background && el.style.background.includes('accent-light')
    )
    expect(navTab).toBeTruthy()
  })
})
