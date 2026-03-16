/**
 * DivergingBarChart — CSS-positioned horizontal bars with center zero axis.
 * NOT Recharts. When isPositive, all bars are neutral blue.
 */
const COLOR_MAP = { accent: 'var(--accent)', red: 'var(--red)', green: 'var(--green)', muted: 'var(--text-muted)' }

export default function DivergingBarChart({ bars, insightHtml, isPositive }) {
  return (
    <div className="rounded-lg border overflow-hidden" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>
      <div className="p-4">
        {bars.map((bar, i) => {
          const barColor = isPositive ? 'var(--accent)' : (COLOR_MAP[bar.color] || bar.color)
          const isLast = i === bars.length - 1
          const labelWeight = bar.bold ? { fontWeight: 600, color: 'var(--text-primary)' } : { color: 'var(--text-secondary)' }
          return (
            <div key={bar.label} className="flex items-center gap-3" style={{ marginBottom: isLast ? 0 : 16 }}>
              <div className="text-right text-xs" style={{ width: 110, fontFamily: "'Fira Sans', sans-serif", ...labelWeight }}>{bar.label}</div>
              <div className="flex-1 relative" style={{ height: 28 }}>
                <div className="absolute top-0 bottom-0" style={{ left: '50%', width: 1, background: 'var(--border)' }} />
                {bar.direction === 'dot' ? (
                  <>
                    <div className="absolute rounded-full" style={{ left: 'calc(50% - 4px)', top: 10, width: 8, height: 8, background: 'var(--text-muted)', opacity: 0.5 }} />
                    <span className="absolute text-xs" style={{ left: 'calc(50% + 12px)', top: 6, fontFamily: "'Fira Code', monospace", color: 'var(--text-muted)' }}>{bar.value}</span>
                  </>
                ) : bar.direction === 'right' ? (
                  <div className="absolute flex items-center justify-end px-2" style={{ left: '50%', top: 4, height: 20, width: `${bar.width_pct}%`, background: barColor, opacity: bar.opacity, borderRadius: '0 4px 4px 0' }}>
                    <span className="text-xs font-semibold text-white" style={{ fontFamily: "'Fira Code', monospace" }}>{bar.value}</span>
                  </div>
                ) : (
                  <div className="absolute flex items-center px-2" style={{ right: '50%', top: 4, height: 20, width: `${bar.width_pct}%`, background: barColor, opacity: bar.opacity, borderRadius: '4px 0 0 4px' }}>
                    <span className="text-xs font-semibold text-white" style={{ fontFamily: "'Fira Code', monospace" }}>{bar.value}</span>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
      {insightHtml && (
        <div className="px-4 py-3 text-xs border-t" style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', fontFamily: "'Fira Sans', sans-serif" }} dangerouslySetInnerHTML={{ __html: insightHtml }} />
      )}
    </div>
  )
}
