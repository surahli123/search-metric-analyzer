/**
 * SegmentTable — per-tenant-tier decomposition table with contribution bars.
 * n < 30 → muted + "insufficient data" label, no contribution bar.
 * mix_shift_contribution_pct >= 30 → amber annotation.
 */
export default function SegmentTable({ title, metricLabel, segments, insightText, mixShift }) {
  return (
    <div className="rounded-lg border overflow-hidden" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>
      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)', fontFamily: "'Fira Sans', sans-serif" }}>{title}</span>
      </div>
      <table className="w-full text-sm" style={{ fontFamily: "'Fira Code', monospace" }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            <th className="px-4 py-2 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Segment</th>
            <th className="px-4 py-2 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Queries</th>
            <th className="px-4 py-2 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>{metricLabel}</th>
            <th className="px-4 py-2 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Δ {metricLabel}</th>
            <th className="px-4 py-2 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>Share of Movement</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((seg) => {
            const insufficientData = seg.current_count < 30
            return (
              <tr key={seg.segment} className="border-t" style={{ borderColor: 'var(--border)' }}>
                <td className="px-4 py-2 font-medium capitalize" style={{ fontFamily: "'Fira Sans', sans-serif", color: insufficientData ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                  {seg.segment}
                  {insufficientData && <span className="ml-2 text-xs" style={{ color: 'var(--amber)' }}>insufficient data</span>}
                </td>
                <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{seg.current_count}</td>
                <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{seg.current_value}%</td>
                <td className="px-4 py-2" style={{ fontWeight: Math.abs(seg.delta_pp) > 1 ? 600 : 400, color: insufficientData ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                  {seg.delta_pp > 0 ? '+' : ''}{seg.delta_pp}pp
                </td>
                <td className="px-4 py-2">
                  {!insufficientData && (
                    <div className="flex items-center gap-1.5">
                      <div className="rounded-full overflow-hidden" style={{ width: 60, height: 6, background: 'var(--bg-input)' }}>
                        <div className="h-full rounded-full" style={{ width: `${Math.min(seg.contribution_pct, 100)}%`, background: 'var(--accent)', opacity: seg.contribution_pct > 50 ? 1 : seg.contribution_pct > 20 ? 0.5 : 0.3 }} />
                      </div>
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{seg.contribution_pct}%</span>
                    </div>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="px-4 py-3 text-xs border-t" style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', fontFamily: "'Fira Sans', sans-serif" }}>
        {/* dangerouslySetInnerHTML is intentional — insightText comes from fixture data
            (controlled static JSON), not user input. Phase 2: add sanitization. */}
        <div dangerouslySetInnerHTML={{ __html: insightText }} />
        {mixShift?.mix_shift_contribution_pct >= 30 && (
          <div className="mt-2 px-2 py-1 rounded text-xs" style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}>
            {mixShift.mix_shift_contribution_pct}% of this movement is traffic composition change (mix-shift).
          </div>
        )}
      </div>
    </div>
  )
}
