// CollapsibleSection.test.jsx — tests for the reusable expand/collapse wrapper.
//
// Covers:
//   - Renders title text
//   - Renders optional count badge when provided
//   - Hides count badge when not provided
//   - Shows children when defaultOpen=true (default behavior)
//   - Hides children when defaultOpen=false
//   - Clicking header toggles visibility of children
//   - Double-click restores original state
//   - aria-expanded reflects open/closed state

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import CollapsibleSection from '../components/CollapsibleSection'

describe('CollapsibleSection', () => {
  // --- Rendering ---

  it('renders the title text', () => {
    render(
      <CollapsibleSection title="Supporting Evidence">
        <p>Content here</p>
      </CollapsibleSection>
    )
    expect(screen.getByText('Supporting Evidence')).toBeInTheDocument()
  })

  it('renders the count badge when count is provided', () => {
    render(
      <CollapsibleSection title="Evidence" count={5}>
        <p>Content</p>
      </CollapsibleSection>
    )
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('does NOT render a count badge when count is omitted', () => {
    const { container } = render(
      <CollapsibleSection title="Evidence">
        <p>Content</p>
      </CollapsibleSection>
    )
    // The count badge uses a specific className pattern — if no count,
    // the only text nodes should be the title and the chevron
    const badges = container.querySelectorAll('.px-1\\.5')
    expect(badges).toHaveLength(0)
  })

  it('renders count badge when count is 0 (zero is a valid count)', () => {
    render(
      <CollapsibleSection title="Empty" count={0}>
        <p>Content</p>
      </CollapsibleSection>
    )
    expect(screen.getByText('0')).toBeInTheDocument()
  })

  // --- Default open/closed state ---

  it('shows children by default (defaultOpen=true is the default)', () => {
    render(
      <CollapsibleSection title="Test">
        <p>Visible content</p>
      </CollapsibleSection>
    )
    expect(screen.getByText('Visible content')).toBeInTheDocument()
  })

  it('hides children when defaultOpen=false', () => {
    render(
      <CollapsibleSection title="Test" defaultOpen={false}>
        <p>Hidden content</p>
      </CollapsibleSection>
    )
    expect(screen.queryByText('Hidden content')).not.toBeInTheDocument()
  })

  // --- Toggle behavior ---

  it('hides children after clicking the header (collapse)', () => {
    render(
      <CollapsibleSection title="Collapsible">
        <p>Toggle me</p>
      </CollapsibleSection>
    )
    // Content visible initially
    expect(screen.getByText('Toggle me')).toBeInTheDocument()

    // Click the header button to collapse
    fireEvent.click(screen.getByRole('button'))

    // Content should now be hidden
    expect(screen.queryByText('Toggle me')).not.toBeInTheDocument()
  })

  it('shows children after clicking a collapsed section (expand)', () => {
    render(
      <CollapsibleSection title="Collapsed" defaultOpen={false}>
        <p>Reveal me</p>
      </CollapsibleSection>
    )
    // Content hidden initially
    expect(screen.queryByText('Reveal me')).not.toBeInTheDocument()

    // Click to expand
    fireEvent.click(screen.getByRole('button'))

    // Content should now be visible
    expect(screen.getByText('Reveal me')).toBeInTheDocument()
  })

  it('double-click restores original state', () => {
    render(
      <CollapsibleSection title="DoubleClick">
        <p>Still here</p>
      </CollapsibleSection>
    )
    const button = screen.getByRole('button')

    // Collapse
    fireEvent.click(button)
    expect(screen.queryByText('Still here')).not.toBeInTheDocument()

    // Re-expand
    fireEvent.click(button)
    expect(screen.getByText('Still here')).toBeInTheDocument()
  })

  // --- Accessibility ---

  it('sets aria-expanded=true when open', () => {
    render(
      <CollapsibleSection title="Open">
        <p>Content</p>
      </CollapsibleSection>
    )
    expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'true')
  })

  it('sets aria-expanded=false when closed', () => {
    render(
      <CollapsibleSection title="Closed" defaultOpen={false}>
        <p>Content</p>
      </CollapsibleSection>
    )
    expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'false')
  })

  it('toggles aria-expanded when clicked', () => {
    render(
      <CollapsibleSection title="Toggle">
        <p>Content</p>
      </CollapsibleSection>
    )
    const button = screen.getByRole('button')

    expect(button).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })
})
