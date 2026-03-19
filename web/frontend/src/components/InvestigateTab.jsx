// InvestigateTab.jsx — search-style investigate layout.
//
// LAYOUT: Query box at top, results below. This follows the search engine pattern
// (Google, Databricks): user types a question, hits Go, results appear below.
// Unlike ChatGPT (input at bottom for multi-turn chat), this tool handles
// single-query diagnostics — the query IS the starting point, not a continuation.
//
// PROGRESSIVE DISCLOSURE: Results are grouped into 3 tiers:
//   1. Answer Layer (always visible): VerdictStrip + CoMovement + Narrative
//   2. Evidence (collapsible, default open): Hypothesis + Tables + Charts
//   3. Technical Details (collapsible, default collapsed): Quality + Methodology + SQL
//
// Props:
//   scenario    {object} — The active scenario data from scenarios.js
//   scenarioKey {string} — Active scenario key for pill highlighting
//   onScenarioChange {function} — Callback when user switches scenario

import VerdictStrip from './VerdictStrip'
import DataQualityChecks from './DataQualityChecks'
import CoMovementIndicator from './CoMovementIndicator'
import NarrativeBlock from './NarrativeBlock'
import HypothesisChecklist from './HypothesisChecklist'
import ResultsTable from './ResultsTable'
import DivergingBarChart from './DivergingBarChart'
import TrendChart from './TrendChart'
import SegmentTable from './SegmentTable'
import MethodologyBlock from './MethodologyBlock'
import SqlBlock from './SqlBlock'
import CollapsibleSection from './CollapsibleSection'
import QuestionInput from './QuestionInput'

export default function InvestigateTab({ scenario, scenarioKey, onScenarioChange }) {
  const { diagnosis, narrative, data_context, sql_queries, display } = scenario

  return (
    // Full-height flex column: query at top, scrollable results below.
    <div className="flex-1 flex flex-col overflow-hidden">

      {/* Query input at top — the entry point for every investigation */}
      <QuestionInput
        placeholder="Ask about a metric movement..."
        activeScenario={scenarioKey}
        onScenarioChange={onScenarioChange}
      />

      {/* Scrollable results area */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full" style={{ maxWidth: 960 }}>

          {/* Investigation question + freshness metadata */}
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
              <span>Data through {data_context.data_freshness?.raw_data?.split('T')[0]}</span>
              <span>·</span>
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

          <div className="px-6 pb-6 flex flex-col gap-4">

            {/* ═══ ANSWER LAYER — always visible, above the fold ═══ */}

            <VerdictStrip
              verdict={diagnosis.verdict_label}
              verdictHuman={display.verdict_human}
              detail={` — ${diagnosis.aggregate.metric.replace(/_/g, ' ')} ${
                diagnosis.aggregate.delta_pct > 0 ? '+' : ''
              }${diagnosis.aggregate.delta_pct}% week-over-week`}
              n={`n = ${data_context.queries_analyzed} queries`}
              isPositive={diagnosis.is_positive}
              severity={diagnosis.aggregate.severity}
              severityHuman={display.severity_human}
            />

            <CoMovementIndicator coMovement={diagnosis.co_movement} />

            <NarrativeBlock text={narrative.text} />

            {/* ═══ EVIDENCE LAYER — collapsible, default open ═══ */}

            {/* count={5} must match child components below: Hypothesis, Results, DivergingBar, Trend, Segment */}
            <CollapsibleSection title="Supporting Evidence" count={5} defaultOpen={true}>
              <HypothesisChecklist hypotheses={diagnosis.hypotheses_evaluated} />

              <ResultsTable
                title={display.results_title}
                dateRange={display.results_date_range}
                headers={display.results_headers}
                rows={display.results_rows}
              />

              <DivergingBarChart
                bars={display.chart_bars}
                insightHtml={display.chart_insight_html}
                isPositive={diagnosis.is_positive}
              />

              <TrendChart
                title={display.trend_data.title}
                yAxisLabel={display.trend_data.y_axis_label}
                current={display.trend_data.current}
                previous={display.trend_data.previous}
                legendCurrent={display.trend_data.legend_current}
                legendPrevious={display.trend_data.legend_previous}
              />

              <SegmentTable
                title={display.segment_title}
                metricLabel={display.segment_metric_label}
                segments={diagnosis.dimensional_breakdown.segments}
                insightText={display.segment_insight}
                mixShift={diagnosis.mix_shift}
              />
            </CollapsibleSection>

            {/* ═══ TECHNICAL LAYER — collapsible, default collapsed ═══ */}

            {/* count={3} must match child components below: DataQuality, Methodology, SQL */}
            <CollapsibleSection title="Technical Details" count={3} defaultOpen={false}>
              <DataQualityChecks checks={diagnosis.validation_checks} />
              <MethodologyBlock dataContext={data_context} />
              <SqlBlock queries={sql_queries} />
            </CollapsibleSection>

          </div>
        </div>
      </div>
    </div>
  )
}
