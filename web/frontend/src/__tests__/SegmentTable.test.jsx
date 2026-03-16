import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import SegmentTable from '../components/SegmentTable'

const SEGS = [{ segment: 'enterprise', current_count: 130, current_value: 25.0, delta_pp: -4.5, contribution_pct: 85 }]
const SMALL = [{ segment: 'tiny', current_count: 15, current_value: 30.0, delta_pp: -2.0, contribution_pct: 5 }]

describe('SegmentTable', () => {
  it('renders segment names', () => {
    render(<SegmentTable title="T" metricLabel="CQ" segments={SEGS} insightText="" />)
    expect(screen.getByText('enterprise')).toBeInTheDocument()
  })
  it('shows insufficient data for n<30', () => {
    render(<SegmentTable title="T" metricLabel="CQ" segments={SMALL} insightText="" />)
    expect(screen.getByText('insufficient data')).toBeInTheDocument()
  })
  it('shows mix-shift annotation at >=30%', () => {
    render(<SegmentTable title="T" metricLabel="CQ" segments={SEGS} insightText="" mixShift={{ detected: true, mix_shift_contribution_pct: 35 }} />)
    expect(screen.getByText(/35% of this movement/)).toBeInTheDocument()
  })
})
