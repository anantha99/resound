import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useQueryClient } from "@tanstack/react-query";
import { useListRoutes, useSubmitFeedback } from "@workspace/api-client-react";
import Masthead from "@/components/Masthead";
import { useBrand } from "@/context/BrandContext";
import { routeAuditToSignalView } from "@/api/viewModels";

const CG = "'Cormorant Garamond', serif";

const feedbackColor = (val?: boolean) => val === true ? "#4a6b3f" : val === false ? "#b8431f" : "#8b857a";
const feedbackLabel = (val?: boolean) => val === true ? "Correct" : val === false ? "Wrong" : "Pending";

const severityColor: Record<string, string> = { critical: "#b8431f", high: "#c97a30", medium: "#4a4640", low: "#8b857a" };

export default function MemoryPage() {
  const { activeBrand } = useBrand();
  const queryClient = useQueryClient();
  const routesQuery = useListRoutes({ brandId: activeBrand.id, period: "qtd", limit: 100 }, {
    query: { enabled: activeBrand.id !== "loading", queryKey: ["routes", activeBrand.id] },
  });
  const brandSignals = (routesQuery.data ?? []).map((route) => routeAuditToSignalView(route, activeBrand.id));
  const [feedbacks, setFeedbacks] = useState<Record<number, boolean | undefined>>(
    {}
  );
  const feedback = useSubmitFeedback({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries(),
    },
  });

  useEffect(() => {
    setFeedbacks(Object.fromEntries(brandSignals.map(s => [s.routeId, s.feedbackCorrect])));
  }, [routesQuery.data, activeBrand.id]);

  const mark = (routeId: number, correct: boolean) => {
    setFeedbacks(prev => ({ ...prev, [routeId]: correct }));
    feedback.mutate({ routeId, data: { correct } });
  };

  const total = brandSignals.length;
  const correct = brandSignals.filter(s => feedbacks[s.routeId] === true).length;
  const wrong = brandSignals.filter(s => feedbacks[s.routeId] === false).length;
  const pending = total - correct - wrong;
  const accuracy = correct + wrong > 0 ? Math.round((correct / (correct + wrong)) * 100) : null;

  return (
    <div className="min-h-screen" style={{ backgroundColor: "#f4f1ec", color: "#1a1815" }}>
      <div className="max-w-[1320px] mx-auto px-14">
        <Masthead />
        <div className="border-t mt-1 pt-8" style={{ borderColor: "#1a1815" }}>
          <h1 style={{ fontFamily: CG, fontSize: 56, fontWeight: 300, letterSpacing: "-0.025em", lineHeight: 0.9 }}>
            Memory<em style={{ fontStyle: "italic", color: "#4a4640" }}>.</em>
          </h1>
          <div className="mt-4 mb-8" style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.06em", color: "#8b857a", textTransform: "uppercase" }}>
            {activeBrand.name} · routing audit log · append-only · {total} events
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 1, background: "#d9d3c7", marginBottom: 36 }}>
            {[
              { label: "Routing accuracy", value: accuracy !== null ? `${accuracy}%` : "—", sub: `${correct + wrong} judged` },
              { label: "Correct routes", value: correct, sub: `${total > 0 ? Math.round(correct / total * 100) : 0}% of total` },
              { label: "Awaiting feedback", value: pending, sub: `${total > 0 ? Math.round(pending / total * 100) : 0}% unreviewed` },
            ].map(stat => (
              <div key={stat.label} style={{ background: "#f4f1ec", padding: "20px 24px" }}>
                <div style={{ fontFamily: CG, fontSize: 40, fontWeight: 300, lineHeight: 1, letterSpacing: "-0.02em", marginBottom: 6 }}>{stat.value}</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "#8b857a" }}>{stat.label}</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#8b857a", marginTop: 3 }}>{stat.sub}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="pb-16">
          <div className="grid py-3 border-b" style={{ gridTemplateColumns: "80px 1fr 140px 100px 80px 100px", borderColor: "#1a1815", fontFamily: "'JetBrains Mono', monospace", fontSize: 9, letterSpacing: "0.1em", textTransform: "uppercase", color: "#8b857a" }}>
            <span>Source</span><span>Summary</span><span>Routed to</span><span>Conf</span><span>Area</span><span>Feedback</span>
          </div>
          {brandSignals.length === 0 ? (
            <div className="py-24 text-center" style={{ fontFamily: CG, fontStyle: "italic", fontSize: 20, color: "#8b857a" }}>
              {routesQuery.isError
                ? "Unable to load route audit from the backend."
                : routesQuery.isLoading
                  ? "Loading route audit from memory..."
                  : `No routing events for ${activeBrand.name} yet.`}
            </div>
          ) : brandSignals.map((signal, i) => (
            <motion.div key={signal.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, delay: i * 0.03 }}
              className="grid py-4 border-b items-start" style={{ gridTemplateColumns: "80px 1fr 140px 100px 80px 100px", borderColor: "#e3ddd1" }}>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, textTransform: "uppercase", color: "#1a1815", fontWeight: 500 }}>{signal.source}</div>
              <div>
                <div style={{ fontFamily: CG, fontSize: 15, lineHeight: 1.4, color: "#1a1815", marginBottom: 4 }}>{signal.summary}</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#8b857a", textTransform: "uppercase", letterSpacing: "0.06em" }}>{signal.postedAt} · {signal.authorHandle}</div>
              </div>
              <div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#1a1815", fontWeight: 500 }}>{signal.owner}</div>
                {signal.ruleMatched && <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "#8b857a", marginTop: 2 }}>rule: {signal.ruleMatched}</div>}
              </div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: signal.confidence < 0.7 ? "#b8431f" : "#8b857a" }}>
                {signal.confidence.toFixed(2)}{signal.confidence < 0.7 ? " · low" : ""}
              </div>
              <div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, textTransform: "uppercase", color: "#1a1815" }}>{signal.area}</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: severityColor[signal.severity], marginTop: 2 }}>{signal.severity}</div>
              </div>
              <div className="flex flex-col gap-1">
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: feedbackColor(feedbacks[signal.id]), letterSpacing: "0.04em" }}>
                  {feedbackLabel(feedbacks[signal.routeId])}
                </div>
                {feedbacks[signal.routeId] === undefined && (
                  <div className="flex gap-1 mt-1">
                    <button onClick={() => mark(signal.routeId, true)} style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, padding: "3px 6px", border: "1px solid #4a6b3f", color: "#4a6b3f", background: "transparent", cursor: "pointer" }}>✓</button>
                    <button onClick={() => mark(signal.routeId, false)} style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, padding: "3px 6px", border: "1px solid #b8431f", color: "#b8431f", background: "transparent", cursor: "pointer" }}>✗</button>
                  </div>
                )}
              </div>
            </motion.div>
          ))}
        </div>
        <footer className="py-6 pb-12 flex justify-between items-baseline" style={{ borderTop: "1px solid #1a1815", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "#8b857a" }}>
          <span>Schema append-only · no deletes · no updates</span>
          <span>Resound Memory v1.0</span>
        </footer>
      </div>
    </div>
  );
}
