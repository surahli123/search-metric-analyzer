import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import MethodologyBlock from '../components/MethodologyBlock'

const CTX = {
  data_source: 'search_query_relevance_metrics_enriched',
  queries_analyzed: 348,
  metric_formula: 'max(click_component, ai_trigger * ai_success)',
  filters_applied: ["searchExperience = 'fullPageSearch'"],
  data_freshness: { status: 'fresh', status_note: 'fresh (<6h)' },
}

describe('MethodologyBlock', () => {
  it('is collapsed by default', () => {
    render(<MethodologyBlock dataContext={CTX} />)
    expect(screen.queryByText(/search_query_relevance/)).not.toBeInTheDocument()
  })
  it('expands on click', () => {
    render(<MethodologyBlock dataContext={CTX} />)
    fireEvent.click(screen.getByText('Methodology'))
    expect(screen.getByText(/search_query_relevance/)).toBeInTheDocument()
  })
})
