import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useGetPattern, useListPatterns } from "@workspace/api-client-react";
import Masthead from "@/components/Masthead";
import SignalRow from "@/components/SignalRow";
import { useBrand } from "@/context/BrandContext";
import { toPatternView, toSignalView, type OwnerOption, type PatternView } from "@/api/viewModels";

const CG = "'Cormorant Garamond', serif";

export default function PatternsPage() {
  const { activeBrand } = useBrand();
  const patternsQuery = useListPatterns({ brandId: activeBrand.id }, {
    query: { enabled: activeBrand.id !== "loading", queryKey: ["patterns", activeBrand.id] },
  });
  const brandPatterns = (patternsQuery.data ?? []).map(toPatternView);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    setExpanded((current) => (
      brandPatterns.some((pattern) => pattern.id === current) ? current : brandPatterns[0]?.id ?? null
    ));
  }, [patternsQuery.data, activeBrand.id]);

  const velocityColor = (m: number) => m >= 2.5 ? "#b8431f" : m >= 1.5 ? "#c97a30" : "#8b857a";

  return (
    <div className="min-h-screen" style={{ backgroundColor: "#f4f1ec", color: "#1a1815" }}>
      <div className="max-w-[1320px] mx-auto px-14">
        <Masthead />
        <div className="border-t mt-1 pt-8 pb-8" style={{ borderColor: "#1a1815" }}>
          <h1 style={{ fontFamily: CG, fontSize: 56, fontWeight: 300, letterSpacing: "-0.025em", lineHeight: 0.9 }}>
            Emerging patterns<em style={{ fontStyle: "italic", color: "#4a4640" }}>.</em>
          </h1>
          <div className="mt-4" style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.06em", color: "#8b857a", textTransform: "uppercase" }}>
            {activeBrand.name} · derived from memory · {brandPatterns.length} active pattern{brandPatterns.length !== 1 ? "s" : ""}
          </div>
        </div>
        <div className="pb-16">
          {brandPatterns.length === 0 ? (
            <div className="py-24 text-center" style={{ fontFamily: CG, fontStyle: "italic", fontSize: 20, color: "#8b857a" }}>
              {patternsQuery.isError
                ? "Unable to load patterns from the backend."
                : patternsQuery.isLoading
                  ? "Loading patterns from memory..."
                  : `No patterns detected for ${activeBrand.name} yet.`}
            </div>
          ) : brandPatterns.map((pattern) => {
            const isExpanded = expanded === pattern.id;
            return (
              <PatternBlock
                key={pattern.id}
                pattern={pattern}
                isExpanded={isExpanded}
                ownerOptions={activeBrand.ownerOptions}
                onToggle={() => setExpanded(isExpanded ? null : pattern.id)}
                velocityColor={velocityColor}
              />
            );
          })}
        </div>
        <footer className="py-6 pb-12 flex justify-between items-baseline" style={{ borderTop: "1px solid #1a1815", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "#8b857a" }}>
          <span>Patterns derived from memory · updated with API reads</span>
          <span>Resound v1.0 · {activeBrand.id}</span>
        </footer>
      </div>
    </div>
  );
}

function PatternBlock({ pattern, isExpanded, ownerOptions, onToggle, velocityColor }: {
  pattern: PatternView;
  isExpanded: boolean;
  ownerOptions: OwnerOption[];
  onToggle: () => void;
  velocityColor: (m: number) => string;
}) {
  const detailQuery = useGetPattern(pattern.id, {
    query: { enabled: isExpanded, queryKey: ["pattern", pattern.id] },
  });
  const patternSignals = (detailQuery.data?.signals ?? []).map(toSignalView);

  return (
    <div className="border-t" style={{ borderColor: "#d9d3c7" }}>
      <motion.div onClick={onToggle}
        className="grid py-8 cursor-pointer" style={{ gridTemplateColumns: "1fr 180px 80px", gap: 32, alignItems: "center" }}
        whileHover={{ backgroundColor: "#ebe7df" }} transition={{ duration: 0.15 }} data-testid={`pattern-header-${pattern.id}`}>
        <div>
          <div style={{ fontFamily: CG, fontSize: 30, fontWeight: 300, lineHeight: 1.1, letterSpacing: "-0.015em", marginBottom: 10 }}>{pattern.name}</div>
          <div style={{ fontFamily: CG, fontStyle: "italic", color: "#4a4640", fontSize: 16, lineHeight: 1.5, marginBottom: 12, maxWidth: 640 }}>{pattern.blurb}</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8b857a" }}>
            {pattern.area.toUpperCase()} · {pattern.signalCount} signals · started {pattern.startedAt.toUpperCase()}
          </div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontFamily: CG, fontSize: 52, fontWeight: 300, color: velocityColor(pattern.velocityMultiple), lineHeight: 1, letterSpacing: "-0.025em", marginBottom: 6 }}>
            {pattern.velocityMultiple}×
          </div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8b857a", lineHeight: 1.5 }}>
            weekly vol<br />vs 4-wk avg
          </div>
        </div>
        <div style={{ textAlign: "right", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.06em", textTransform: "uppercase", color: "#8b857a" }}>
          {isExpanded ? "Collapse ↑" : `${pattern.signalCount} signals ↓`}
        </div>
      </motion.div>
      <AnimatePresence>
        {isExpanded && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25 }} style={{ overflow: "hidden" }}>
            <div style={{ paddingBottom: 32 }}>
              {detailQuery.isLoading && (
                <div className="py-8 text-center" style={{ fontFamily: CG, fontStyle: "italic", fontSize: 18, color: "#8b857a" }}>
                  Loading pattern signals...
                </div>
              )}
              {!detailQuery.isLoading && patternSignals.length === 0 && (
                <div className="py-8 text-center" style={{ fontFamily: CG, fontStyle: "italic", fontSize: 18, color: "#8b857a" }}>
                  No constituent signals available for this pattern yet.
                </div>
              )}
              {patternSignals.map((signal, i) => (
                <SignalRow
                  key={signal.id}
                  signal={signal}
                  ownerOptions={ownerOptions}
                  index={i}
                  showPattern
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
