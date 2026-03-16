// SqlBlock.jsx — dark code blocks showing the SQL queries that produced the analysis.
//
// WHY show SQL: transparency about exactly what data was queried builds trust.
// Engineers reviewing a P1 incident can verify the query logic without guessing.
// The duration_s and rows metadata help them assess whether this was an expensive
// query or whether row counts look reasonable.
//
// WHY dark background (--code-bg): SQL is code, not prose. Dark backgrounds are
// the industry convention for code display and signal "this is technical output."

export default function SqlBlock({ queries }) {
  return (
    <div className="flex flex-col gap-3">
      {queries.map((q, i) => (
        <div
          key={i}
          className="rounded-lg overflow-hidden"
          style={{ border: '1px solid var(--border)' }}
        >
          {/* Query header row — description on left, performance stats on right */}
          <div
            className="flex items-center justify-between px-4 py-2 text-xs"
            style={{
              background: 'var(--bg-elevated)',
              color: 'var(--text-secondary)',
              fontFamily: "'Fira Sans', sans-serif",
            }}
          >
            <span className="font-medium">{q.description}</span>
            {/* Monospace for the numbers so they align cleanly */}
            <span
              style={{
                color: 'var(--text-muted)',
                fontFamily: "'Fira Code', monospace",
              }}
            >
              {q.duration_s}s · {q.rows} rows
            </span>
          </div>

          {/* SQL code block — <pre> preserves whitespace/indentation in the SQL string */}
          <pre
            className="px-4 py-3 text-xs overflow-x-auto"
            style={{
              background: 'var(--code-bg)',
              color: 'var(--code-text)',
              fontFamily: "'Fira Code', monospace",
              lineHeight: 1.6,
              margin: 0,
            }}
          >
            {q.sql}
          </pre>
        </div>
      ))}
    </div>
  )
}
