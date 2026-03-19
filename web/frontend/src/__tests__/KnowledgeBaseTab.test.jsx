// KnowledgeBaseTab.test.jsx — tests for the knowledge base tab page.
//
// Covers:
//   - Renders page title "Domain Knowledge"
//   - Renders subtitle describing the tab's purpose
//   - Renders all 6 knowledge file cards
//   - Shows file count footer
//   - Each card is independently expandable

import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import KnowledgeBaseTab from '../components/KnowledgeBaseTab'
import { KNOWLEDGE_FILES } from '../data/knowledge_index'

describe('KnowledgeBaseTab', () => {
  it('renders page title', () => {
    render(<KnowledgeBaseTab />)
    expect(screen.getByText('Domain Knowledge')).toBeInTheDocument()
  })

  it('renders subtitle', () => {
    render(<KnowledgeBaseTab />)
    expect(
      screen.getByText('The diagnostic system draws on these knowledge files to analyze metric movements.')
    ).toBeInTheDocument()
  })

  it('renders all 6 knowledge file cards by name', () => {
    render(<KnowledgeBaseTab />)
    expect(screen.getByText('Metric Definitions')).toBeInTheDocument()
    expect(screen.getByText('Historical Patterns')).toBeInTheDocument()
    expect(screen.getByText('Search Pipeline')).toBeInTheDocument()
    expect(screen.getByText('Architecture Tradeoffs')).toBeInTheDocument()
    expect(screen.getByText('Evaluation Methods')).toBeInTheDocument()
    expect(screen.getByText('Corrections Log')).toBeInTheDocument()
  })

  it('renders file count footer', () => {
    render(<KnowledgeBaseTab />)
    expect(screen.getByText(`${KNOWLEDGE_FILES.length} knowledge files`)).toBeInTheDocument()
  })

  it('all cards start collapsed — no section labels visible', () => {
    render(<KnowledgeBaseTab />)
    // "Metric Formulas" is a section label inside the first card — should be hidden
    expect(screen.queryByText('Metric Formulas')).not.toBeInTheDocument()
    // "Seasonal Patterns" is a section label inside the second card — should be hidden
    expect(screen.queryByText('Seasonal Patterns')).not.toBeInTheDocument()
  })

  it('expanding one card does not expand others', () => {
    render(<KnowledgeBaseTab />)
    // Click the first card (Metric Definitions)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[0])
    // First card's sections should be visible
    expect(screen.getByText('Metric Formulas')).toBeInTheDocument()
    // Second card's sections should still be hidden
    expect(screen.queryByText('Seasonal Patterns')).not.toBeInTheDocument()
  })

  it('knowledge_index data integrity — all files have at least 1 section', () => {
    // This is a data integrity check, not a UI test — ensures the index
    // doesn't have any files with empty sections arrays
    KNOWLEDGE_FILES.forEach((file) => {
      expect(file.sections.length).toBeGreaterThan(0)
    })
  })

  it('knowledge_index data integrity — all files have required fields', () => {
    KNOWLEDGE_FILES.forEach((file) => {
      expect(file.id).toBeTruthy()
      expect(file.name).toBeTruthy()
      expect(file.file).toBeTruthy()
      expect(file.description).toBeTruthy()
      expect(Array.isArray(file.sections)).toBe(true)
    })
  })

  it('knowledge_index data integrity — all sections have required fields', () => {
    KNOWLEDGE_FILES.forEach((file) => {
      file.sections.forEach((section) => {
        expect(section.key).toBeTruthy()
        expect(section.label).toBeTruthy()
        expect(section.summary).toBeTruthy()
      })
    })
  })
})
