/**
 * DivergingBarChart — CSS-positioned horizontal bars with center zero axis.
 * NOT Recharts. When isPositive, all bars are neutral blue.
 *
 * Bar widths are half-relative: width_pct=100 fills the entire half.
 * Text renders OUTSIDE the bar when the bar is too narrow to contain it.
 */
const COLOR_MAP = { accent: 'var(--accent)', red: 'var(--red)', green: 'var(--green)', muted: 'var(--text-muted)' }

// Bars narrower than this threshold render their value text outside
const MIN_WIDTH_FOR_INSIDE_TEXT = 12

export default function DivergingBarChart({ bars, insightHtml, isPositive }) {
  return (
    <div>
      {/* Section header — sits ABOVE the card per design convention */}
      <div
        className="text-xs font-semibold uppercase tracking-wider mb-2"
        style={{ color: 'var(--text-muted)', fontFamily: "'Fira Sans', sans-serif" }}
      >
        Metric Contribution to Movement
      </div>

      <div className="rounded-lg border overflow-hidden" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>
        <div className="p-4">
          {bars.map((bar, i) => {
            const barColor = isPositive ? 'var(--accent)' : (COLOR_MAP[bar.color] || bar.color)
            const isLast = i === bars.length - 1
            const labelWeight = bar.bold ? { fontWeight: 600, color: 'var(--text-primary)' } : { color: 'var(--text-secondary)' }
            // Whether the bar is wide enough to fit text inside
            const textInside = bar.width_pct >= MIN_WIDTH_FOR_INSIDE_TEXT
            const halfWidth = bar.width_pct / 2

            return (
              <div key={bar.label} className="flex items-center gap-3" style={{ marginBottom: isLast ? 0 : 16 }}>
                {/* Label column */}
                <div className="text-right text-xs" style={{ width: 110, flexShrink: 0, fontFamily: "'Fira Sans', sans-serif", ...labelWeight }}>{bar.label}</div>

                {/* Bar area */}
                <div className="flex-1 relative overflow-hidden" style={{ height: 28 }}>
                  {/* Center zero axis */}
                  <div className="absolute top-0 bottom-0" style={{ left: '50%', width: 1, background: 'var(--border)' }} />

                  {bar.direction === 'dot' ? (
                    /* Zero value — dot on center line */
                    <>
                      <div className="absolute rounded-full" style={{ left: 'calc(50% - 4px)', top: 10, width: 8, height: 8, background: 'var(--text-muted)', opacity: 0.5 }} />
                      <span className="absolute text-xs" style={{ left: 'calc(50% + 12px)', top: 6, fontFamily: "'Fira Code', monospace", color: 'var(--text-muted)' }}>{bar.value}</span>
                    </>
                  ) : bar.direction === 'right' ? (
                    /* Positive bar — extends right from center */
                    <>
                      <div className="absolute" style={{ left: '50%', top: 4, height: 20, width: `${halfWidth}%`, background: barColor, opacity: bar.opacity, borderRadius: '0 4px 4px 0' }} />
                      <span className="absolute text-xs font-semibold" style={{
                        top: 6,
                        left: textInside ? undefined : `calc(50% + ${halfWidth}% + 6px)`,
                        right: textInside ? `calc(50% - ${halfWidth}% + 8px)` : undefined,
                        color: textInside ? 'white' : 'var(--text-secondary)',
                        fontFamily: "'Fira Code', monospace",
                        whiteSpace: 'nowrap',
                      }}>{bar.value}</span>
                    </>
                  ) : (
                    /* Negative bar — extends left from center */
                    <>
                      <div className="absolute" style={{ right: '50%', top: 4, height: 20, width: `${halfWidth}%`, background: barColor, opacity: bar.opacity, borderRadius: '4px 0 0 4px' }} />
                      <span className="absolute text-xs font-semibold" style={{
                        top: 6,
                        right: textInside ? undefined : `calc(50% + ${halfWidth}% + 6px)`,
                        left: textInside ? `calc(50% - ${halfWidth}% + 8px)` : undefined,
                        color: textInside ? 'white' : 'var(--text-secondary)',
                        fontFamily: "'Fira Code', monospace",
                        whiteSpace: 'nowrap',
                      }}>{bar.value}</span>
                    </>
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
    </div>
  )
}
