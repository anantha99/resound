import { useState } from "react";
import { motion } from "framer-motion";
import { useListSignals } from "@workspace/api-client-react";
import { useLocation } from "wouter";
import Masthead from "@/components/Masthead";
import SignalRow from "@/components/SignalRow";
import { useBrand } from "@/context/BrandContext";
import { toSignalView, type Area, type Severity, type Sentiment } from "@/api/viewModels";

type SourceFilter = "All" | "Reddit" | "Instagram" | "TikTok" | "X" | "YouTube";
type AreaFilter = "All" | Area;
type SeverityFilter = "All" | Severity;
type SentimentFilter = "All" | Sentiment;

const CG = "'Cormorant Garamond', serif";

const FilterBtn = ({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) => (
  <button onClick={onClick}
    style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", padding: "5px 10px", border: "1px solid", borderColor: active ? "#1a1815" : "#d9d3c7", background: active ? "#1a1815" : "transparent", color: active ? "#f4f1ec" : "#8b857a", cursor: "pointer", transition: "all 0.15s" }}>
    {label}
  </button>
);

export default function SignalsPage() {
  const { activeBrand } = useBrand();
  const [, setLocation] = useLocation();
  const [source, setSource] = useState<SourceFilter>("All");
  const [area, setArea] = useState<AreaFilter>("All");
  const [severity, setSeverity] = useState<SeverityFilter>("All");
  const [sentiment, setSentiment] = useState<SentimentFilter>("All");

  const query = useListSignals({
    brandId: activeBrand.id,
    source: source === "All" ? undefined : source.toLowerCase(),
    area: area === "All" ? undefined : area,
    severity: severity === "All" ? undefined : severity,
    sentiment: sentiment === "All" ? undefined : sentiment,
    period: "qtd",
    limit: 100,
  }, {
    query: { enabled: activeBrand.id !== "loading", queryKey: ["signals", activeBrand.id, source, area, severity, sentiment] },
  });
  const filtered = (query.data?.signals ?? []).map(toSignalView);
  const total = query.data?.total ?? filtered.length;

  return (
    <div className="min-h-screen" style={{ backgroundColor: "#f4f1ec", color: "#1a1815" }}>
      <div className="resound-page-shell max-w-[1320px] mx-auto px-14">
        <Masthead />
        <div className="border-t mt-1 pt-8 pb-8" style={{ borderColor: "#1a1815" }}>
          <div className="flex items-end justify-between mb-8">
            <div>
              <h1 style={{ fontFamily: CG, fontSize: 56, fontWeight: 300, letterSpacing: "-0.025em", lineHeight: 0.9 }}>
                Signal feed<em style={{ fontStyle: "italic", color: "#4a4640" }}>.</em>
              </h1>
              <div className="mt-4" style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.06em", color: "#8b857a", textTransform: "uppercase" }}>
                {activeBrand.name} · {filtered.length} of {total} signals
              </div>
            </div>
          </div>
          <div className="flex gap-6 flex-wrap">
            <div className="flex gap-0.5 flex-wrap">{(["All","Reddit","Instagram","TikTok","X","YouTube"] as SourceFilter[]).map(s => <FilterBtn key={s} label={s} active={source === s} onClick={() => setSource(s)} />)}</div>
            <div className="flex gap-0.5 flex-wrap">{(["All","product","ops","billing","cs","marketing","engineering"] as AreaFilter[]).map(a => <FilterBtn key={a} label={a} active={area === a} onClick={() => setArea(a)} />)}</div>
            <div className="flex gap-0.5">{(["All","critical","high","medium","low"] as SeverityFilter[]).map(s => <FilterBtn key={s} label={s} active={severity === s} onClick={() => setSeverity(s)} />)}</div>
            <div className="flex gap-0.5">{(["All","negative","positive","neutral","mixed"] as SentimentFilter[]).map(s => <FilterBtn key={s} label={s} active={sentiment === s} onClick={() => setSentiment(s)} />)}</div>
          </div>
        </div>
        <div className="pb-16">
          {filtered.length === 0 ? (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="py-24 text-center"
              style={{ fontFamily: CG, fontStyle: "italic", fontSize: 22, color: "#8b857a" }}>
              {query.isError
                ? "Unable to load signals from the backend."
                : query.isLoading
                  ? "Loading signals from memory..."
                  : `No signals match the current filters for ${activeBrand.name}.`}
            </motion.div>
          ) : (
            filtered.map((signal, i) => (
              <SignalRow
                key={signal.id}
                signal={signal}
                ownerOptions={activeBrand.ownerOptions}
                index={i}
                onOpen={(id) => setLocation(`/signals/${id}`)}
              />
            ))
          )}
        </div>
        <footer className="py-6 pb-12 flex justify-between items-baseline" style={{ borderTop: "1px solid #1a1815", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "#8b857a" }}>
          <span>{activeBrand.name} · signal feed</span>
          <span>Resound v1.0</span>
        </footer>
      </div>
    </div>
  );
}
