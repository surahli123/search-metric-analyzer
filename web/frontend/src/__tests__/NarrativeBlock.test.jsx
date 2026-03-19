// NarrativeBlock.test.jsx — tests for the narrative summary component.
//
// Covers:
//   - Renders "Summary" section header
//   - Renders HTML content from the text prop
//   - Renders plain text when no HTML tags are present
//   - Handles empty string gracefully

import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import NarrativeBlock from '../components/NarrativeBlock'

describe('NarrativeBlock', () => {
  it('renders the "Summary" section header', () => {
    render(<NarrativeBlock text="Some text" />)
    expect(screen.getByText('Summary')).toBeInTheDocument()
  })

  it('renders plain text content', () => {
    render(<NarrativeBlock text="Click Quality dropped 3.2pp week-over-week." />)
    expect(screen.getByText('Click Quality dropped 3.2pp week-over-week.')).toBeInTheDocument()
  })

  it('renders HTML content from the text prop', () => {
    const html = '<strong>Click Quality</strong> dropped <strong>3.2pp</strong>'
    const { container } = render(<NarrativeBlock text={html} />)
    // The <strong> tags should render as actual bold elements
    const strongElements = container.querySelectorAll('strong')
    expect(strongElements.length).toBe(2)
    expect(strongElements[0].textContent).toBe('Click Quality')
    expect(strongElements[1].textContent).toBe('3.2pp')
  })

  it('handles empty text gracefully', () => {
    const { container } = render(<NarrativeBlock text="" />)
    // Should still render the section header without crashing
    expect(screen.getByText('Summary')).toBeInTheDocument()
    // The content div should be empty but present
    expect(container.querySelector('.text-sm')).toBeInTheDocument()
  })
})
