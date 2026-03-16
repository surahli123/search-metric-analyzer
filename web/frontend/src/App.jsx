// App.jsx — root assembly that wires all 14 components together.
//
// ARCHITECTURE: This is the single stateful component in the app. All child
// components are purely presentational — they receive data as props and render it.
// State lives here because scenario switching needs to update the entire page.
//
// Think of this like a data pipeline: SCENARIOS is the source, scenarioKey is the
// filter, and the destructured fields are the transformed outputs passed downstream
// to each visualization component.
//
// SCENARIO SWITCHING: When the user clicks a pill in QuestionInput, onScenarioChange
// updates scenarioKey, which re-reads from SCENARIOS and re-renders everything.
// This is React's "lift state up" pattern — state owned by the nearest common ancestor.

import { useState } from 'react'
import { SCENARIOS, DEFAULT_SCENARIO } from './data/scenarios'

// Layer 1: App chrome
import Header from './components/Header'

// Layer 2: Answer layer (verdict + quality signals)
import VerdictStrip from './components/VerdictStrip'
import DataQualityChecks from './components/DataQualityChecks'
import CoMovementIndicator from './components/CoMovementIndicator'
import NarrativeBlock from './components/NarrativeBlock'

// Layer 3: Evidence layer (hypotheses + data visualizations)
import HypothesisChecklist from './components/HypothesisChecklist'
import ResultsTable from './components/ResultsTable'
import DivergingBarChart from './components/DivergingBarChart'
import TrendChart from './components/TrendChart'
import SegmentTable from './components/SegmentTable'

// Layer 4: Detail layer (methodology, SQL, footer, scenario switcher)
import MethodologyBlock from './components/MethodologyBlock'
import SqlBlock from './components/SqlBlock'
import Footer from './components/Footer'
import QuestionInput from './components/QuestionInput'

function App() {
  // scenarioKey drives which scenario is displayed — starts with the default
  const [scenarioKey, setScenarioKey] = useState(DEFAULT_SCENARIO)

  // Destructure the active scenario's top-level sections for cleaner prop passing
  const scenario = SCENARIOS[scenarioKey]
  const { diagnosis, narrative, data_context, sql_queries, display } = scenario

  return (
    // Outer wrapper: full-height flex column so footer sticks to bottom
    <div className="min-h-screen flex flex-col" style={{ background: 'var(--bg-page)' }}>

      {/* Sticky header — always visible at top */}
      <Header />

      {/* Main content area — centered, max 960px wide */}
      <main className="flex-1 mx-auto w-full" style={{ maxWidth: 960 }}>

        {/* Question header: the investigation question + freshness metadata */}
        <div className="px-6 pt-6 pb-2">
          <div
            className="text-base font-medium mb-1"
            style={{ color: 'var(--text-primary)', fontFamily: "'Fira Sans', sans-serif" }}
          >
            {display.question}
          </div>
          <div
            className="flex items-center gap-3 text-xs"
            style={{ color: 'var(--text-muted)', fontFamily: "'Fira Code', monospace" }}
          >
            {/* Strip time from ISO timestamp — show date only */}
            <span>Data through {data_context.data_freshness?.raw_data?.split('T')[0]}</span>
            <span>·</span>
            {/* Freshness status gets semantic color: green=fresh, amber=stale, red=delayed */}
            <span
              style={{
                color:
                  data_context.data_freshness?.status === 'fresh'
                    ? 'var(--green)'
                    : data_context.data_freshness?.status === 'stale'
                    ? 'var(--amber)'
                    : 'var(--red)',
              }}
            >
              {data_context.data_freshness?.status}
            </span>
            <span>·</span>
            <span>{data_context.queries_analyzed} queries analyzed</span>
          </div>
        </div>

        {/* Component stack — each section is a distinct card with gap-4 spacing */}
        <div className="px-6 pb-6 flex flex-col gap-4">

          {/* ANSWER LAYER */}

          {/* VerdictStrip: the top-line verdict with severity and delta */}
          <VerdictStrip
            verdict={diagnosis.verdict_label}
            detail={` — ${diagnosis.aggregate.metric.replace(/_/g, ' ')} ${
              diagnosis.aggregate.delta_pct > 0 ? '+' : ''
            }${diagnosis.aggregate.delta_pct}% week-over-week${
              diagnosis.aggregate.severity ? ` (${diagnosis.aggregate.severity})` : ''
            }`}
            n={`n = ${data_context.queries_analyzed} queries`}
            isPositive={diagnosis.is_positive}
            severity={diagnosis.aggregate.severity}
          />

          {/* DataQualityChecks: PASS/WARN badges for logging, sampling, decomposition */}
          <DataQualityChecks checks={diagnosis.validation_checks} />

          {/* CoMovementIndicator: 4-metric direction table + pattern match badge */}
          <CoMovementIndicator coMovement={diagnosis.co_movement} />

          {/* NarrativeBlock: the plain-English explanation paragraph */}
          <NarrativeBlock text={narrative.text} />

          {/* EVIDENCE LAYER */}

          {/* HypothesisChecklist: ordered list of hypotheses with matched/not_evaluated status */}
          <HypothesisChecklist hypotheses={diagnosis.hypotheses_evaluated} />

          {/* ResultsTable: week-over-week metric comparison table */}
          <ResultsTable
            title={display.results_title}
            dateRange={display.results_date_range}
            headers={display.results_headers}
            rows={display.results_rows}
          />

          {/* DivergingBarChart: horizontal bar chart showing metric contribution to movement */}
          <DivergingBarChart
            bars={display.chart_bars}
            insightHtml={display.chart_insight_html}
            isPositive={diagnosis.is_positive}
          />

          {/* TrendChart: Recharts line chart for week-over-week trend */}
          <TrendChart
            title={display.trend_data.title}
            current={display.trend_data.current}
            previous={display.trend_data.previous}
            legendCurrent={display.trend_data.legend_current}
            legendPrevious={display.trend_data.legend_previous}
          />

          {/* SegmentTable: per-tenant-tier breakdown with mix-shift annotation */}
          <SegmentTable
            title={display.segment_title}
            metricLabel={display.segment_metric_label}
            segments={diagnosis.dimensional_breakdown.segments}
            insightText={display.segment_insight}
            mixShift={diagnosis.mix_shift}
          />

          {/* DETAIL LAYER */}

          {/* MethodologyBlock: collapsible — data source, formula, filters, freshness */}
          <MethodologyBlock dataContext={data_context} />

          {/* SqlBlock: dark code blocks showing the exact queries that ran */}
          <SqlBlock queries={sql_queries} />
        </div>
      </main>

      {/* Footer: persistent verdict echo + query count + date range */}
      <Footer
        verdict={diagnosis.verdict_label}
        summary={display.footer.summary}
        totalQueries={display.footer.total_queries}
        dateRange={display.footer.date_range}
        isPositive={diagnosis.is_positive}
        severity={diagnosis.aggregate.severity}
      />

      {/* QuestionInput: scenario switcher pills + disabled input bar */}
      <QuestionInput
        placeholder="Ask about another metric movement..."
        activeScenario={scenarioKey}
        onScenarioChange={setScenarioKey}
      />
    </div>
  )
}

export default App
