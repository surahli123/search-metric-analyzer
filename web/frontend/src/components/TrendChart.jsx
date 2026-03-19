/**
 * TrendChart — Recharts line chart comparing this week vs last week.
 * Solid blue = current, dashed gray = previous.
 *
 * The title prop is rendered in a header bar above the chart.
 * The y-axis includes a label showing the metric name for context.
 */
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Label } from 'recharts'

export default function TrendChart({ title, current, previous, legendCurrent, legendPrevious }) {
  const data = current.map((point, i) => ({ day: point.day, current: point.value, previous: previous[i]?.value ?? null }))
  return (
    <div className="rounded-lg border overflow-hidden" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>
      {/* Title bar — always visible so readers know what metric this chart shows */}
      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)', fontFamily: "'Fira Sans', sans-serif" }}>{title}</span>
      </div>
      <div className="px-4 py-3">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="day" tick={{ fontSize: 11, fill: 'var(--text-muted)', fontFamily: "'Fira Code', monospace" }} axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
            <YAxis domain={['dataMin - 2', 'dataMax + 2']} tick={{ fontSize: 11, fill: 'var(--text-muted)', fontFamily: "'Fira Code', monospace" }} axisLine={false} tickLine={false} width={50}>
              {/* Y-axis label — rotated vertically, shows the metric name */}
              <Label
                value={title}
                angle={-90}
                position="insideLeft"
                offset={-5}
                style={{ fontSize: 10, fill: 'var(--text-muted)', fontFamily: "'Fira Sans', sans-serif", textAnchor: 'middle' }}
              />
            </YAxis>
            <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontFamily: "'Fira Code', monospace", fontSize: 12 }} />
            <Line type="monotone" dataKey="previous" stroke="var(--text-muted)" strokeDasharray="5 5" strokeWidth={2} strokeOpacity={0.4} dot={{ r: 3, fill: 'var(--text-muted)', strokeWidth: 0, opacity: 0.4 }} name="Last week" />
            <Line type="monotone" dataKey="current" stroke="var(--accent)" strokeWidth={2} dot={{ r: 3, fill: 'var(--accent)', strokeWidth: 0 }} name="This week" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex gap-6 px-4 py-2 border-t text-xs" style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 h-0.5" style={{ background: 'var(--accent)' }} />{legendCurrent}</span>
        <span className="flex items-center gap-1.5"><span className="inline-block w-4 h-0.5" style={{ background: 'var(--text-muted)', opacity: 0.4 }} />{legendPrevious}</span>
      </div>
    </div>
  )
}
