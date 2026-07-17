import { useState } from "react";
import { motion } from "framer-motion";
import { useGetBrandStats, useListPatterns, useListSignals, useListSourceHealth } from "@workspace/api-client-react";
import Masthead from "@/components/Masthead";
import SignalRow from "@/components/SignalRow";
import { useBrand } from "@/context/BrandContext";
import { apiPeriod, formatPath, formatSource, toPatternView, toSignalView, type SignalView } from "@/api/viewModels";

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
  const healthQuery = useListSourceHealth({ brandId: activeBrand.id }, {
    query: { enabled: apiReady, queryKey: ["source-health", activeBrand.id] },
  });

  const brandSignals = (signalsQuery.data?.signals ?? []).map(toSignalView);
  const brandPatterns = (patternsQuery.data ?? []).map(toPatternView);
  const stats = statsQuery.data;

  const criticalSignals = brandSignals.filter(s => s.severity === "critical" || s.severity === "high");
  const negativeSignals = brandSignals.filter(s => s.sentiment === "negative");
  const topPattern = brandPatterns[0];
  const emergingSignals = topPattern ? brandSignals.filter(s => s.patternId === topPattern.id) : [];

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
      blurb: `${(stats?.criticalDelta ?? 0) > 0 ? (stats?.criticalDelta ?? 0) + " more" : Math.abs(stats?.criticalDelta ?? 0) + " fewer"} than last period. Each signal is already routed; verify or reroute below.`,
    },
    sentiment: {
      title: "Dragging sentiment down",
      sub: "Negative-sentiment signals · sorted by reach",
      blurb: `Net sentiment ${(stats?.netSentimentDelta ?? 0) < 0 ? "fell" : "rose"} ${Math.abs(stats?.netSentimentDelta ?? 0)} points this period. These are the loudest voices behind the shift.`,
    },
    emerging: {
      title: topPattern ? topPattern.name : "No emerging patterns",
      sub: topPattern ? `Auto-clustered · ${topPattern.signalCount} signals · started ${topPattern.startedAt}` : "",
      blurb: "",
    },
    volume: {
      title: "Conversation volume · " + period,
      sub: `${brandSignals.length} signals · sorted by reach`,
      blurb: `Volume ${(stats?.volumeDelta ?? 0) >= 0 ? "up" : "down"} ${Math.abs(stats?.volumeDelta ?? 0)}% vs previous period.`,
    },
  };

  const netSentiment = stats?.netSentiment ?? 0;
  const netSentimentDelta = stats?.netSentimentDelta ?? 0;
  const criticalCount = stats?.criticalCount ?? criticalSignals.length;
  const criticalDelta = stats?.criticalDelta ?? 0;
  const totalVolume = stats?.totalVolume ?? brandSignals.length;
  const volumeDelta = stats?.volumeDelta ?? 0;
  const sentimentBreakdown = stats?.sentimentBreakdown ?? { positive: 0, neutral: 0, negative: 0 };
  const sourceMix = stats?.sourceMix ?? [];
  const isLoading = statsQuery.isLoading || signalsQuery.isLoading || patternsQuery.isLoading;
  const isError = statsQuery.isError || signalsQuery.isError || patternsQuery.isError;

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
              <div style={{ fontFamily: MONO, fontSize: 11, color: netSentimentDelta < 0 ? (activePane === "sentiment" ? "#f4a890" : "#b8431f") : "#4a6b3f", letterSpacing: "0.02em" }}>
                {netSentimentDelta < 0 ? "↓" : "↑"} {Math.abs(netSentimentDelta)}pt
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
                <path stroke={s.spark} fill="none" strokeWidth="1.2" d={netSentimentDelta < 0 ? "M0,4 L8,5 L16,3 L24,6 L32,8 L40,10 L48,12 L56,11 L64,13 L70,14" : "M0,14 L8,12 L16,13 L24,10 L32,8 L40,7 L48,5 L56,4 L64,3 L70,2"} />
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
              <div style={{ fontFamily: MONO, fontSize: 11, color: criticalDelta > 0 ? (activePane === "critical" ? "#f4a890" : "#b8431f") : "#4a6b3f", letterSpacing: "0.02em" }}>
                {criticalDelta > 0 ? `↑ +${criticalDelta}` : `↓ ${criticalDelta}`} vs prev
              </div>
            </div>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.04em", textTransform: "uppercase", color: c.label, marginTop: "auto", paddingTop: 16 }}>
              {[...new Set(criticalSignals.map(s => s.area.toUpperCase()))].slice(0, 3).join(" · ") || "No critical signals"}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12, fontFamily: MONO, fontSize: 10, letterSpacing: "0.05em", textTransform: "uppercase", color: c.label }}>
              <span>weekly</span>
              <svg width="70" height="18" viewBox="0 0 70 18">
                <path fill={c.spark} opacity="0.4" d="M2,14 h6 v4 h-6z M14,12 h6 v6 h-6z M26,13 h6 v5 h-6z M38,11 h6 v7 h-6z M50,10 h6 v8 h-6z M62,4 h6 v14 h-6z" />
              </svg>
            </div>
          </motion.div>

          {/* Emerging */}
          <motion.div whileHover={{ backgroundColor: e.hoverBg }} onClick={() => setActivePane("emerging")} data-testid="kpi-emerging"
            style={{ background: e.bg, padding: "28px 24px 24px", cursor: "pointer", minHeight: 200, display: "flex", flexDirection: "column", transition: "background 0.2s" }}>
            <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", textTransform: "uppercase", color: e.label, marginBottom: 20 }}>Top emerging issue</div>
            {topPattern ? (
              <>
                <div style={{ fontFamily: CG, fontStyle: "italic", fontWeight: 300, fontSize: 26, lineHeight: 1.15, letterSpacing: "-0.01em", marginBottom: 8, color: e.number }}>
                  "{topPattern.name}"
                </div>
                <div style={{ fontFamily: MONO, fontSize: 11, color: activePane === "emerging" ? "#f4a890" : "#b8431f", letterSpacing: "0.02em" }}>
                  {topPattern.velocityMultiple}× WoW · accelerating
                </div>
                <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.04em", textTransform: "uppercase", color: e.label, marginTop: "auto", paddingTop: 16 }}>
                  {topPattern.area.toUpperCase()} · {topPattern.signalCount} signals
                </div>
              </>
            ) : (
              <div style={{ fontFamily: CG, fontStyle: "italic", fontSize: 18, color: e.label, marginTop: 8 }}>No patterns detected yet.</div>
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
              <div style={{ fontFamily: MONO, fontSize: 11, color: volumeDelta >= 0 ? "#4a6b3f" : "#b8431f", letterSpacing: "0.02em" }}>
                {volumeDelta >= 0 ? "↑" : "↓"} {volumeDelta >= 0 ? "+" : ""}{volumeDelta}%
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
              <span>vs prev {period}</span>
              <svg width="70" height="18" viewBox="0 0 70 18">
                <path stroke={v.spark} fill="none" strokeWidth="1.2" d="M0,12 L8,10 L16,11 L24,9 L32,7 L40,8 L48,6 L56,5 L64,4 L70,3" />
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

          {activePane === "emerging" && topPattern && (
            <motion.div className="resound-pattern-summary" key={topPattern.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              style={{ padding: 32, background: "#ebe7df", marginBottom: 32, gap: 32, alignItems: "center" }}>
              <div>
                <div style={{ fontFamily: CG, fontSize: 34, fontWeight: 300, lineHeight: 1.1, letterSpacing: "-0.015em", marginBottom: 12, color: "#1a1815" }}>{topPattern.name}</div>
                <div style={{ fontFamily: CG, fontStyle: "italic", color: "#4a4640", fontSize: 17, lineHeight: 1.5, marginBottom: 16 }}>{topPattern.blurb}</div>
                <div style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8b857a" }}>
                  {topPattern.area.toUpperCase()} · started {topPattern.startedAt.toUpperCase()} · {topPattern.signalCount} signals · {topPattern.weeklyVelocity} this week
                </div>
              </div>
              <div style={{ textAlign: "center", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8b857a" }}>
                <span style={{ fontFamily: CG, fontSize: 64, fontWeight: 300, color: "#b8431f", display: "block", lineHeight: 1, marginBottom: 8, letterSpacing: "-0.025em" }}>
                  {topPattern.velocityMultiple}×
                </span>
                weekly volume<br />vs prev 4-week avg
              </div>
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

        <section className="resound-health-footer mt-6 pt-5 pb-2 border-t border-[#1a1815]">
          <div className="flex justify-between items-baseline mb-4 uppercase" style={{ fontFamily: MONO }}><strong className="text-[10px] tracking-[.09em]">Public source health</strong><span className="text-[9px] tracking-[.06em] text-[#8b857a]">Latest bounded sync</span></div>
          <div className="resound-health-table border-t border-[#d9d3c7]">
            <div className="resound-health-row grid grid-cols-[150px_minmax(0,1fr)_120px_160px] gap-4 px-3 py-2 border-b border-[#1a1815] uppercase text-[9px] tracking-[.1em] text-[#8b857a]" style={{ fontFamily: MONO }}><span>Platform</span><span>Path</span><span>Status</span><span className="text-right">Last success</span></div>
            {(healthQuery.data ?? []).map(row => <div key={`${row.canonicalSource}-${row.path}`} className="resound-health-row grid grid-cols-[150px_minmax(0,1fr)_120px_160px] gap-4 items-center min-h-9 px-3 py-2 border-b border-[#e3ddd1] text-[10px]" style={{ fontFamily: MONO }}>
              <b className="uppercase font-medium">{formatSource(row.canonicalSource)}</b><span className="text-[#4a4640]">{formatPath(row.path)}</span><span className={`uppercase ${row.status === "ok" ? "text-[#4a6b3f]" : row.status === "partial" ? "text-[#c97a30]" : "text-[#b8431f]"}`}>● {row.status}</span><span className="text-right uppercase text-[9px] text-[#8b857a]">{row.lastSuccessAt ? new Date(row.lastSuccessAt).toLocaleString() : "—"}</span>
            </div>)}
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
