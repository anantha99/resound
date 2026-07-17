import { useState } from "react";
import { motion } from "framer-motion";
import { useGetBrandStats, useListPatterns, useListSignals } from "@workspace/api-client-react";
import type { PatternSummary } from "@workspace/api-client-react";
import Masthead from "@/components/Masthead";
import SignalRow from "@/components/SignalRow";
import { useBrand } from "@/context/BrandContext";
import {
  apiPeriod,
  barChart,
  deltaDisplay,
  sparklinePath,
  toPatternView,
  toSignalView,
  type DeltaTone,
  type SignalView,
} from "@/api/viewModels";

type Period = "24h" | "7d" | "30d" | "QTD";
type ActivePane = "sentiment" | "critical" | "emerging" | "volume";

const PERIODS: Period[] = ["24h", "7d", "30d", "QTD"];
const CG = "'Cormorant Garamond', serif";
const MONO = "'JetBrains Mono', monospace";

function kpiColors(active: boolean) {
  return {
    bg: active ? "#1a1815" : "#f4f1ec",
    hoverBg: active ? "#1a1815" : "#ebe7df",
    label: active ? "#ebe7df" : "#8b857a",
    number: active ? "#f4f1ec" : "#1a1815",
    sub: active ? "#ebe7df" : "#8b857a",
    spark: active ? "#f4f1ec" : "#1a1815",
  };
}

/** Resolve a delta/velocity tone to a token, honouring the active (dark) card. */
function toneColor(tone: DeltaTone, active: boolean): string {
  if (tone === "neutral") return active ? "#ebe7df" : "#8b857a";
  if (tone === "positive") return active ? "#8fae82" : "#4a6b3f";
  return active ? "#f4a890" : "#b8431f";
}

/** Honest velocity copy keyed on the comparable-window velocity state. */
function velocityLabel(issue: PatternSummary, period: Period): { text: string; tone: DeltaTone } {
  switch (issue.velocityState) {
    case "accelerating":
      return { text: `${issue.velocityMultiple}× · accelerating`, tone: "negative" };
    case "cooling":
      return { text: `${issue.velocityMultiple}× · cooling`, tone: "positive" };
    case "steady":
      return { text: `${issue.velocityMultiple}× · steady`, tone: "neutral" };
    case "no_baseline":
    default:
      return { text: `${issue.signalCount} signals · ${period} activity`, tone: "neutral" };
  }
}

export default function Dashboard() {
  const { activeBrand } = useBrand();
  const [period, setPeriod] = useState<Period>("QTD");
  const [activePane, setActivePane] = useState<ActivePane>("critical");
  const apiReady = activeBrand.id !== "loading";

  const statsQuery = useGetBrandStats(activeBrand.id, apiPeriod(period), {
    query: { enabled: apiReady, queryKey: ["brand-stats", activeBrand.id, period] },
  });
  const signalsQuery = useListSignals({ brandId: activeBrand.id, period: apiPeriod(period), limit: 100 }, {
    query: { enabled: apiReady, queryKey: ["dashboard-signals", activeBrand.id, period] },
  });
  const patternsQuery = useListPatterns({ brandId: activeBrand.id }, {
    query: { enabled: apiReady, queryKey: ["dashboard-patterns", activeBrand.id] },
  });

  const brandSignals = (signalsQuery.data?.signals ?? []).map(toSignalView);
  const brandPatterns = (patternsQuery.data ?? []).map(toPatternView);
  const stats = statsQuery.data;

  // Period-scoped emerging issue is the source of truth (from brand_stats).
  // id === 0 is the empty sentinel from _empty_pattern_summary().
  const emergingIssue = stats?.topEmergingIssue;
  const hasEmerging = !!emergingIssue && emergingIssue.id !== 0;
  // Look up extra all-history display fields (blurb, startedAt) by matching id;
  // these must NOT override the period-scoped title/count/velocity/area.
  const emergingExtras = hasEmerging
    ? brandPatterns.find(p => p.id === emergingIssue!.id)
    : undefined;

  const criticalSignals = brandSignals.filter(s => s.severity === "critical" || s.severity === "high");
  const negativeSignals = brandSignals.filter(s => s.sentiment === "negative");
  const emergingSignals = hasEmerging ? brandSignals.filter(s => s.patternId === emergingIssue!.id) : [];

  const netSentiment = stats?.netSentiment ?? 0;
  const netSentimentDelta = stats?.netSentimentDelta ?? 0;
  const criticalCount = stats?.criticalCount ?? criticalSignals.length;
  const criticalDelta = stats?.criticalDelta ?? 0;
  const totalVolume = stats?.totalVolume ?? brandSignals.length;
  const volumeDelta = stats?.volumeDelta ?? 0;
  const sentimentBreakdown = stats?.sentimentBreakdown ?? { positive: 0, neutral: 0, negative: 0 };
  const sourceMix = stats?.sourceMix ?? [];
  const trend = stats?.trend ?? [];
  const isLoading = statsQuery.isLoading || signalsQuery.isLoading || patternsQuery.isLoading;
  const isError = statsQuery.isError || signalsQuery.isError || patternsQuery.isError;

  // Shared zero-delta-aware delta displays.
  const netDelta = deltaDisplay(netSentimentDelta, { unit: "pt", upIsGood: true, flatText: "0pt · flat" });
  const critDelta = deltaDisplay(criticalDelta, { signed: true, suffix: " vs prev", upIsGood: false, flatText: "no change" });
  const volDelta = deltaDisplay(volumeDelta, { unit: "%", signed: true, upIsGood: true, flatText: "0% · flat" });

  const paneSignals: Record<ActivePane, SignalView[]> = {
    critical: criticalSignals,
    sentiment: negativeSignals,
    emerging: emergingSignals,
    volume: brandSignals.slice(0, 6),
  };

  const paneTitles: Record<ActivePane, { title: string; sub: string; blurb: string }> = {
    critical: {
      title: "Critical & high · need attention now",
      sub: `${criticalSignals.length} signals · ${period} · sorted by recency`,
      blurb:
        criticalDelta === 0
          ? "Unchanged vs last period. Each signal is already routed; verify or reroute below."
          : `${criticalDelta > 0 ? `${criticalDelta} more` : `${Math.abs(criticalDelta)} fewer`} than last period. Each signal is already routed; verify or reroute below.`,
    },
    sentiment: {
      title: "Dragging sentiment down",
      sub: "Negative-sentiment signals · sorted by reach",
      blurb:
        netSentimentDelta === 0
          ? "Net sentiment was unchanged this period. These are the loudest voices in the conversation."
          : `Net sentiment ${netSentimentDelta < 0 ? "fell" : "rose"} ${Math.abs(netSentimentDelta)} points this period. These are the loudest voices behind the shift.`,
    },
    emerging: {
      title: hasEmerging ? emergingIssue!.name : "No emerging patterns",
      sub: hasEmerging ? `Auto-clustered · ${emergingIssue!.signalCount} signals${emergingExtras ? ` · started ${emergingExtras.startedAt}` : ""}` : "",
      blurb: "",
    },
    volume: {
      title: "Conversation volume · " + period,
      sub: `Top ${brandSignals.length} of ${totalVolume.toLocaleString()} · sorted by reach`,
      blurb:
        volumeDelta === 0
          ? "Volume was unchanged vs the previous period."
          : `Volume ${volumeDelta > 0 ? "up" : "down"} ${Math.abs(volumeDelta)}% vs previous period.`,
    },
  };

  const s = kpiColors(activePane === "sentiment");
  const c = kpiColors(activePane === "critical");
  const e = kpiColors(activePane === "emerging");
  const v = kpiColors(activePane === "volume");

  return (
    <div className="min-h-screen" style={{ backgroundColor: "#f4f1ec", color: "#1a1815" }}>
      <div className="resound-dashboard-shell max-w-[1320px] mx-auto px-14">
        <Masthead />

        {/* Brand bar */}
        <section className="resound-brand-bar flex items-end justify-between pb-10 border-t mt-1 pt-6" style={{ borderColor: "#1a1815" }}>
          <div className="min-w-0">
            <h1 className="resound-brand-title" style={{ fontFamily: CG, fontSize: 64, fontWeight: 300, letterSpacing: "-0.025em", lineHeight: 0.9, color: "#1a1815" }}>
              {activeBrand.name}<em style={{ fontStyle: "italic", color: "#4a4640" }}>.</em>
            </h1>
            <div className="mt-4" style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", color: "#8b857a", textTransform: "uppercase" }}>
              Brand health · {period.toLowerCase()} window
            </div>
          </div>
          <div className="resound-period-controls flex">
            {PERIODS.map((p, i) => (
              <button key={p} data-testid={`period-${p}`} onClick={() => setPeriod(p)}
                style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", padding: "6px 12px", cursor: "pointer", border: "1px solid", borderRight: i < PERIODS.length - 1 ? "none" : "1px solid", borderColor: period === p ? "#1a1815" : "#d9d3c7", background: period === p ? "#1a1815" : "transparent", color: period === p ? "#f4f1ec" : "#8b857a", transition: "all 0.15s" }}>
                {p}
              </button>
            ))}
          </div>
        </section>

        {/* KPI Cards */}
        <div className="resound-kpi-grid" style={{ background: "#d9d3c7" }}>

          {/* Net Sentiment */}
          <motion.div whileHover={{ backgroundColor: s.hoverBg }} onClick={() => setActivePane("sentiment")} data-testid="kpi-sentiment"
            style={{ background: s.bg, padding: "28px 24px 24px", cursor: "pointer", minHeight: 200, display: "flex", flexDirection: "column", transition: "background 0.2s" }}>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: s.label, marginBottom: 20 }}>Net sentiment</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16 }}>
              <div style={{ fontFamily: CG, fontSize: 56, fontWeight: 300, letterSpacing: "-0.03em", lineHeight: 1, color: s.number }}>
                {netSentiment > 0 ? "+" : ""}{netSentiment}
              </div>
              <div style={{ fontFamily: MONO, fontSize: 11, color: toneColor(netDelta.tone, activePane === "sentiment"), letterSpacing: "0.02em" }}>
                {netDelta.arrow} {netDelta.text}
              </div>
            </div>
            <div style={{ display: "flex", width: "100%", height: 4, margin: "0 0 6px", overflow: "hidden" }}>
              <div style={{ width: `${sentimentBreakdown.positive}%`, background: "#4a6b3f" }} />
              <div style={{ width: `${sentimentBreakdown.neutral}%`, background: activePane === "sentiment" ? "#4a4640" : "#d9d3c7" }} />
              <div style={{ width: `${sentimentBreakdown.negative}%`, background: "#b8431f" }} />
            </div>
            <div style={{ fontFamily: MONO, fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase", color: s.label, display: "flex", gap: 12, marginTop: 4 }}>
              <span>{sentimentBreakdown.positive}% pos</span><span>{sentimentBreakdown.neutral}% neu</span><span>{sentimentBreakdown.negative}% neg</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "auto", paddingTop: 16, fontFamily: MONO, fontSize: 10, letterSpacing: "0.05em", textTransform: "uppercase", color: s.label }}>
              <span>{period} trend</span>
              <svg width="70" height="18" viewBox="0 0 70 18">
                <path stroke={s.spark} fill="none" strokeWidth="1.2" strokeLinejoin="round" d={sparklinePath(trend.map(p => p.netSentiment), 70, 18)} />
              </svg>
            </div>
          </motion.div>

          {/* Critical */}
          <motion.div whileHover={{ backgroundColor: c.hoverBg }} onClick={() => setActivePane("critical")} data-testid="kpi-critical"
            style={{ background: c.bg, padding: "28px 24px 24px", cursor: "pointer", minHeight: 200, display: "flex", flexDirection: "column", transition: "background 0.2s" }}>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: c.label, marginBottom: 20 }}>Critical & high · {period}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16 }}>
              <div style={{ fontFamily: CG, fontSize: 56, fontWeight: 300, letterSpacing: "-0.03em", lineHeight: 1, color: c.number }}>
                {criticalCount}
              </div>
              <div style={{ fontFamily: MONO, fontSize: 11, color: toneColor(critDelta.tone, activePane === "critical"), letterSpacing: "0.02em" }}>
                {critDelta.arrow} {critDelta.text}
              </div>
            </div>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.04em", textTransform: "uppercase", color: c.label, marginTop: "auto", paddingTop: 16 }}>
              {[...new Set(criticalSignals.map(s => s.area.toUpperCase()))].slice(0, 3).join(" · ") || "No critical signals"}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, fontFamily: MONO, fontSize: 10, letterSpacing: "0.05em", textTransform: "uppercase", color: c.label }}>
              <span>{period} trend</span>
              <svg width="70" height="18" viewBox="0 0 70 18">
                {barChart(trend.map(p => p.criticalCount), 70, 18).map((bar, i) => (
                  <rect key={i} x={bar.x} y={bar.y} width={bar.width} height={bar.height} fill={c.spark} opacity={bar.opacity} />
                ))}
              </svg>
            </div>
          </motion.div>

          {/* Emerging */}
          <motion.div whileHover={{ backgroundColor: e.hoverBg }} onClick={() => setActivePane("emerging")} data-testid="kpi-emerging"
            style={{ background: e.bg, padding: "28px 24px 24px", cursor: "pointer", minHeight: 200, display: "flex", flexDirection: "column", transition: "background 0.2s" }}>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: e.label, marginBottom: 20 }}>Top emerging issue</div>
            {!hasEmerging ? (
              <div style={{ fontFamily: CG, fontStyle: "italic", fontSize: 18, color: e.label, marginTop: 8 }}>No patterns detected yet.</div>
            ) : (
              <>
                <div style={{ fontFamily: CG, fontStyle: "italic", fontWeight: 300, fontSize: 26, lineHeight: 1.15, letterSpacing: "-0.01em", marginBottom: 8, color: e.number }}>
                  "{emergingIssue!.name}"
                </div>
                <div style={{ fontFamily: MONO, fontSize: 11, color: toneColor(velocityLabel(emergingIssue!, period).tone, activePane === "emerging"), letterSpacing: "0.02em" }}>
                  {velocityLabel(emergingIssue!, period).text}
                </div>
                <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.04em", textTransform: "uppercase", color: e.label, marginTop: "auto", paddingTop: 16 }}>
                  {emergingIssue!.area.toUpperCase()} · {emergingIssue!.signalCount} signals
                </div>
              </>
            )}
          </motion.div>

          {/* Volume */}
          <motion.div whileHover={{ backgroundColor: v.hoverBg }} onClick={() => setActivePane("volume")} data-testid="kpi-volume"
            style={{ background: v.bg, padding: "28px 24px 24px", cursor: "pointer", minHeight: 200, display: "flex", flexDirection: "column", transition: "background 0.2s" }}>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: v.label, marginBottom: 20 }}>Conversation volume · {period}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16 }}>
              <div style={{ fontFamily: CG, fontSize: 56, fontWeight: 300, letterSpacing: "-0.03em", lineHeight: 1, color: v.number }}>
                {totalVolume.toLocaleString()}
              </div>
              <div style={{ fontFamily: MONO, fontSize: 11, color: toneColor(volDelta.tone, activePane === "volume"), letterSpacing: "0.02em" }}>
                {volDelta.arrow} {volDelta.text}
              </div>
            </div>
            <div style={{ display: "flex", gap: 2, height: 4, margin: "0 0 6px" }}>
              {sourceMix.map((src) => (
                <div key={src.source} style={{ width: `${src.pct}%`, height: "100%", background: activePane === "volume" ? "rgba(244,241,236,0.55)" : (src.source === "Reddit" ? "#1a1815" : src.source === "Twitter" ? "rgba(74,70,64,0.7)" : "#8b857a") }} />
              ))}
            </div>
            <div style={{ fontFamily: MONO, fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase", color: v.label, display: "flex", gap: 12, marginTop: 4, flexWrap: "wrap" }}>
              {sourceMix.map(src => <span key={src.source}>{src.pct}% {src.source.toUpperCase()}</span>)}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "auto", paddingTop: 16, fontFamily: MONO, fontSize: 10, textTransform: "uppercase", color: v.label }}>
              <span>{period} trend</span>
              <svg width="70" height="18" viewBox="0 0 70 18">
                <path stroke={v.spark} fill="none" strokeWidth="1.2" strokeLinejoin="round" d={sparklinePath(trend.map(p => p.volume), 70, 18)} />
              </svg>
            </div>
          </motion.div>
        </div>

        {/* Signal Pane */}
        <section className="py-12 pb-6">
          <div className="resound-pane-header flex justify-between items-baseline mb-4">
            <h2 style={{ fontFamily: CG, fontSize: 30, fontWeight: 300, letterSpacing: "-0.015em", lineHeight: 1, color: "#1a1815" }}>
              {paneTitles[activePane].title}
            </h2>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "#8b857a" }}>
              {paneTitles[activePane].sub}
            </div>
          </div>

          {activePane === "emerging" && hasEmerging && (
            <motion.div className="resound-pattern-summary" key={emergingIssue!.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              style={{ padding: 32, background: "#ebe7df", marginBottom: 32, gap: 32, alignItems: "center" }}>
              <div>
                <div style={{ fontFamily: CG, fontSize: 34, fontWeight: 300, lineHeight: 1.1, letterSpacing: "-0.015em", marginBottom: 12, color: "#1a1815" }}>{emergingIssue!.name}</div>
                {emergingExtras?.blurb && (
                  <div style={{ fontFamily: CG, fontStyle: "italic", color: "#4a4640", fontSize: 17, lineHeight: 1.5, marginBottom: 16 }}>{emergingExtras.blurb}</div>
                )}
                <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8b857a" }}>
                  {emergingIssue!.area.toUpperCase()}{emergingExtras ? ` · started ${emergingExtras.startedAt.toUpperCase()}` : ""} · {emergingIssue!.signalCount} signals · {period} scope
                </div>
              </div>
              {emergingIssue!.velocityState === "no_baseline" ? (
                <div style={{ textAlign: "center", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8b857a" }}>
                  <span style={{ fontFamily: CG, fontSize: 64, fontWeight: 300, color: "#1a1815", display: "block", lineHeight: 1, marginBottom: 8, letterSpacing: "-0.025em" }}>
                    {emergingIssue!.signalCount}
                  </span>
                  signals<br />{period} activity
                </div>
              ) : (
                <div style={{ textAlign: "center", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8b857a" }}>
                  <span style={{ fontFamily: CG, fontSize: 64, fontWeight: 300, color: emergingIssue!.velocityState === "cooling" ? "#4a6b3f" : "#b8431f", display: "block", lineHeight: 1, marginBottom: 8, letterSpacing: "-0.025em" }}>
                    {emergingIssue!.velocityMultiple}×
                  </span>
                  {period} volume<br />vs prior {period} · {emergingIssue!.velocityState}
                </div>
              )}
            </motion.div>
          )}

          {paneTitles[activePane].blurb && (
            <p style={{ fontFamily: CG, fontStyle: "italic", fontSize: 18, color: "#4a4640", marginBottom: 28, maxWidth: 620, lineHeight: 1.45 }}>
              {paneTitles[activePane].blurb}
            </p>
          )}

          <div>
            {paneSignals[activePane].length === 0 ? (
              <div className="py-16 text-center" style={{ fontFamily: CG, fontStyle: "italic", fontSize: 20, color: "#8b857a" }}>
                No signals in this category for {activeBrand.name}.
              </div>
            ) : (
                paneSignals[activePane].map((signal, i) => (
                 <SignalRow
                   key={signal.id}
                   signal={signal}
                   ownerOptions={activeBrand.ownerOptions}
                   index={i}
                   showPattern={activePane === "emerging"}
                 />
               ))
            )}
          </div>
        </section>

        <footer className="resound-dashboard-footer mt-8 py-6 pb-12 flex justify-between items-baseline" style={{ borderTop: "1px solid #1a1815", fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "#8b857a" }}>
          <div className="resound-source-status flex gap-6 items-center">
            {activeBrand.sourcesActive.map(src => (
              <span key={src}>
                <span style={{ display: "inline-block", width: 5, height: 5, borderRadius: "50%", background: "#4a6b3f", marginRight: 6, verticalAlign: "middle" }} />
                <strong style={{ color: "#1a1815", fontWeight: 500 }}>{src}</strong> — {isError ? "Check API" : "Configured"}
              </span>
            ))}
          </div>
          <span>{isLoading ? "Loading memory" : `Last ingested ${activeBrand.lastIngested ? "available" : "not yet"}`} · Memory layer v1.0</span>
        </footer>
      </div>
    </div>
  );
}
