/**
 * ResultsTable — week-over-week metric comparison table.
 * Raw values only — no CIs, no significance badges.
 */
export default function ResultsTable({ title, dateRange, headers, rows }) {
  return (
    <div className="rounded-lg border overflow-hidden" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>
      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)', fontFamily: "'Fira Sans', sans-serif" }}>{title}</span>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{dateRange}</span>
      </div>
      <table className="w-full text-sm" style={{ fontFamily: "'Fira Code', monospace" }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {headers.map((h) => (<th key={h} className="px-4 py-2 text-left text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>{h}</th>))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t" style={{ borderColor: 'var(--border)' }}>
              <td className="px-4 py-2 font-medium" style={{ fontFamily: "'Fira Sans', sans-serif", color: 'var(--text-primary)' }}>{row.period}</td>
              <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{row.queries}</td>
              <td className="px-4 py-2 font-semibold" style={{ color: 'var(--text-primary)' }}>{row.col3}</td>
              <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{row.col4}</td>
              <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{row.col5}</td>
              <td className="px-4 py-2" style={{ color: 'var(--text-secondary)' }}>{row.col6}</td>
              <td className="px-4 py-2 font-semibold" style={{ color: row.delta === '—' ? 'var(--text-muted)' : 'var(--text-primary)' }}>{row.delta}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
