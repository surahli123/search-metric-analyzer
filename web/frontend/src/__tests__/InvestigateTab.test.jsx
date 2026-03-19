// InvestigateTab.test.jsx — tests for the main investigation layout.
//
// InvestigateTab is the orchestrator component that assembles all sub-components
// into a ChatGPT-style layout with progressive disclosure (3 tiers).
//
// Covers:
//   - Renders investigation question text
//   - Renders data freshness metadata
//   - Renders the 3-tier progressive disclosure structure
//   - Supporting Evidence section is expanded by default
//   - Technical Details section is collapsed by default
//   - Expanding Technical Details reveals SQL, methodology, data quality
//   - Renders VerdictStrip with correct scenario data
//   - Renders QuestionInput at the bottom
//   - No "Customer Cohort FPS" text anywhere (regression guard)

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import InvestigateTab from '../components/InvestigateTab'
import { SCENARIOS } from '../data/scenarios'

describe('InvestigateTab', () => {
  // Use the ranking_regression scenario as default test fixture
  const SCENARIO = SCENARIOS.ranking_regression

  // Helper: render with default props
  const renderTab = (overrides = {}) => {
    const defaultProps = {
      scenario: SCENARIO,
      scenarioKey: 'ranking_regression',
      onScenarioChange: vi.fn(),
    }
    return render(<InvestigateTab {...defaultProps} {...overrides} />)
  }

  // --- Question & metadata ---

  it('renders the investigation question', () => {
    renderTab()
    expect(
      screen.getByText('Why did Click Quality drop for enterprise-tier tenants last week?')
    ).toBeInTheDocument()
  })

  it('renders the data freshness date', () => {
    renderTab()
    // data_freshness.raw_data is "2026-03-07T18:00:00Z" → displays "2026-03-07"
    // Multiple elements match (metadata row + results table date range), so use getAllByText
    expect(screen.getAllByText(/2026-03-07/).length).toBeGreaterThanOrEqual(1)
  })

  it('renders the freshness status', () => {
    renderTab()
    expect(screen.getByText('fresh')).toBeInTheDocument()
  })

  it('renders the query count', () => {
    renderTab()
    expect(screen.getByText(/2450 queries analyzed/)).toBeInTheDocument()
  })

  // --- Answer layer (always visible) ---

  it('renders the verdict strip with human-readable verdict', () => {
    renderTab()
    // VerdictStrip should show the human verdict
    expect(screen.getByText('Ranking quality dropped — needs investigation')).toBeInTheDocument()
  })

  it('renders the severity badge', () => {
    renderTab()
    // VerdictStrip shows "Urgent (P1)" when severityHuman is provided
    expect(screen.getByText(/Urgent/)).toBeInTheDocument()
  })

  it('renders the co-movement pattern description', () => {
    renderTab()
    // "ranking regression" appears in multiple places (verdict, co-movement, pattern description)
    // so use getAllByText to confirm at least one match
    expect(screen.getAllByText(/ranking regression/i).length).toBeGreaterThanOrEqual(1)
  })

  it('renders the narrative summary', () => {
    renderTab()
    // Narrative contains "Click Quality for Enterprise tenants"
    expect(screen.getByText(/Click Quality for Enterprise tenants/)).toBeInTheDocument()
  })

  // --- Supporting Evidence tier (default open) ---

  it('renders Supporting Evidence section header', () => {
    renderTab()
    expect(screen.getByText('Supporting Evidence')).toBeInTheDocument()
  })

  it('shows hypothesis checklist in Evidence tier (expanded by default)', () => {
    renderTab()
    // HypothesisChecklist renders "Root Cause Analysis" header
    expect(screen.getByText('Root Cause Analysis')).toBeInTheDocument()
  })

  it('shows the results table in Evidence tier', () => {
    renderTab()
    expect(screen.getByText('Click Quality Week-over-Week — Enterprise Tenants')).toBeInTheDocument()
  })

  it('shows the segment table in Evidence tier', () => {
    renderTab()
    expect(screen.getByText('Click Quality by Tenant Tier — Decomposition')).toBeInTheDocument()
  })

  // --- Technical Details tier (default collapsed) ---

  it('renders Technical Details section header', () => {
    renderTab()
    expect(screen.getByText('Technical Details')).toBeInTheDocument()
  })

  it('hides SQL queries by default (Technical Details is collapsed)', () => {
    renderTab()
    // SQL Queries header is inside the collapsed Technical Details section,
    // so it should NOT be visible
    expect(screen.queryByText('SQL Queries')).not.toBeInTheDocument()
  })

  it('reveals SQL queries after expanding Technical Details', () => {
    renderTab()
    // Find and click the Technical Details toggle button
    // It's the second CollapsibleSection button (first is Supporting Evidence)
    const buttons = screen.getAllByRole('button', { expanded: false })
    // The Technical Details button has aria-expanded=false
    const techButton = buttons.find((btn) => btn.textContent.includes('Technical Details'))
    if (techButton) fireEvent.click(techButton)

    // SQL Queries header should now be visible (inside CollapsibleSection within Technical Details)
    expect(screen.getByText('SQL Queries')).toBeInTheDocument()
  })

  // --- QuestionInput at bottom ---

  it('renders the scenario pills at the bottom', () => {
    renderTab()
    expect(screen.getByText('Within Variance')).toBeInTheDocument()
    // "Ranking Regression" also appears in the verdict, so check for the pill specifically
    expect(screen.getAllByText('Ranking Regression').length).toBeGreaterThanOrEqual(1)
  })

  it('renders the input placeholder', () => {
    renderTab()
    expect(
      screen.getByPlaceholderText('Ask about another metric movement...')
    ).toBeInTheDocument()
  })

  // --- Within Variance scenario ---

  it('renders correctly with the within_variance scenario', () => {
    renderTab({ scenario: SCENARIOS.within_variance, scenarioKey: 'within_variance' })
    expect(
      screen.getByText('How is Search Quality Success (SQS) performing this week vs. last?')
    ).toBeInTheDocument()
    expect(screen.getByText('Normal fluctuation — no action needed')).toBeInTheDocument()
  })

  // --- Regression guard ---

  it('does NOT contain "Customer Cohort FPS" anywhere (naming cleanup regression guard)', () => {
    const { container } = renderTab()
    expect(container.textContent).not.toContain('Customer Cohort FPS')
    expect(container.textContent).not.toContain('customer_cohort_fps')
  })

  it('does NOT contain "Customer Cohort FPS" in within_variance scenario either', () => {
    const { container } = renderTab({
      scenario: SCENARIOS.within_variance,
      scenarioKey: 'within_variance',
    })
    expect(container.textContent).not.toContain('Customer Cohort FPS')
  })
})
