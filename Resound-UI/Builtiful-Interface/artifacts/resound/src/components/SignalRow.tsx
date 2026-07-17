import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useQueryClient } from "@tanstack/react-query";
import { useRerouteSignal } from "@workspace/api-client-react";
import { type OwnerOption, type SignalView } from "@/api/viewModels";
import { CompactSignalMetrics, SignalParentContext } from "@/components/SignalContext";

interface SignalRowProps {
  signal: SignalView;
  ownerOptions?: OwnerOption[];
  onReroute?: (routeId: number, newOwner: string) => void;
  showPattern?: boolean;
  index?: number;
  onOpen?: (signalId: number) => void;
}

const severityClass: Record<string, string> = {
  critical: "text-[#b8431f] font-medium",
  high: "text-[#c97a30] font-medium",
  medium: "text-[#4a4640]",
  low: "text-[#8b857a]",
};

const sentimentClass: Record<string, string> = {
  negative: "text-[#b8431f]",
  positive: "text-[#4a6b3f]",
  neutral: "text-[#8b857a]",
  mixed: "text-[#c97a30]",
};

export default function SignalRow({ signal, ownerOptions = [], onReroute, showPattern, index = 0, onOpen }: SignalRowProps) {
  const [rerouteOpen, setRerouteOpen] = useState(false);
  const [currentOwner, setCurrentOwner] = useState(signal.owner);
  const [confidence, setConfidence] = useState(signal.confidence);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const reroute = useRerouteSignal({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries();
      },
      onError: (err) => {
        setCurrentOwner(signal.owner);
        setConfidence(signal.confidence);
        setError(err instanceof Error ? err.message : "Reroute failed");
      },
    },
  });

  useEffect(() => {
    setCurrentOwner(signal.owner);
    setConfidence(signal.confidence);
  }, [signal.owner, signal.confidence]);

  const opts = ownerOptions.filter((opt) => opt.owner !== currentOwner);

  const handleReroute = (newOwner: string) => {
    setError(null);
    setCurrentOwner(newOwner);
    setConfidence(0.99);
    setRerouteOpen(false);
    onReroute?.(signal.routeId, newOwner);
    reroute.mutate({ routeId: signal.routeId, data: { owner: newOwner } });
  };

  const isLowConfidence = confidence < 0.7;

  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05 }}
      className="resound-signal-row grid gap-8 py-6 border-t border-[#e3ddd1] items-start"
      onClick={() => onOpen?.(signal.id)}
      style={{ cursor: onOpen ? "pointer" : undefined }}
      data-testid={`signal-row-${signal.id}`}
    >
      {/* Meta */}
      <div className="font-mono text-[10px] text-[#8b857a] uppercase tracking-[0.05em] leading-[1.7]">
        <span className="block text-[#1a1815] font-medium">{signal.source}</span>
        <span className="block mt-0.5">{signal.postedAt}</span>
        <span className="block mt-1.5 normal-case">
          {signal.metrics.compact ? <CompactSignalMetrics metrics={signal.metrics} /> : signal.reach}
        </span>
      </div>

      {/* Body */}
      <div className="resound-signal-body min-w-0">
        <div className="resound-signal-author font-mono text-[10px] text-[#8b857a] mb-2 uppercase tracking-[0.04em]">
          {signal.authorHandle} · {signal.authorMeta}
        </div>
        <blockquote
          className="font-serif text-[18px] leading-[1.45] text-[#1a1815] tracking-[-0.005em] mb-3.5"
          style={{ fontFamily: "'Instrument Serif', serif" }}
        >
          {signal.content}
        </blockquote>
        {signal.parentContext && <SignalParentContext parent={signal.parentContext} compact />}
        <div className="resound-signal-tags flex gap-3.5 items-center font-mono text-[10px] uppercase tracking-[0.06em] text-[#8b857a]">
          <span className="text-[#1a1815] font-medium">{signal.area.toUpperCase()}</span>
          <span className={severityClass[signal.severity]}>{signal.severity.toUpperCase()}</span>
          <span className={sentimentClass[signal.sentiment]}>{signal.sentiment.toUpperCase()}</span>
          <span>{signal.actionClass.toUpperCase()}</span>
          {showPattern && signal.patternName && (
            <span className="text-[#c97a30]">CLUSTER</span>
          )}
        </div>
      </div>

      {/* Routing */}
      <div className="resound-signal-routing text-right font-mono text-[11px] text-[#8b857a] leading-[1.6] relative">
        <div className="text-[10px] uppercase tracking-[0.08em] text-[#8b857a] mb-1">Routed to</div>
        <div className="text-[#1a1815] font-medium text-[13px] tracking-normal">{currentOwner}</div>
        <div className={`text-[10px] tracking-[0.04em] mt-1 ${isLowConfidence ? "text-[#b8431f]" : "text-[#8b857a]"}`}>
          CONF {confidence.toFixed(2)}{isLowConfidence ? " · LOW" : ""}
        </div>
        <div className="relative">
          <button
            data-testid={`reroute-btn-${signal.id}`}
            onClick={(event) => { event.stopPropagation(); setRerouteOpen(!rerouteOpen); }}
            disabled={reroute.isPending || opts.length === 0}
            className="mt-3 bg-transparent border border-[#d9d3c7] text-[#4a4640] font-sans text-[11px] px-3 py-1.5 cursor-pointer transition-all duration-150 hover:border-[#1a1815] hover:text-[#1a1815]"
          >
            {reroute.isPending ? "Moving..." : "Reroute →"}
          </button>

          <AnimatePresence>
            {rerouteOpen && (
              <motion.div
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 4 }}
                transition={{ duration: 0.12 }}
                className="absolute top-full right-0 mt-1.5 bg-[#1a1815] text-[#f4f1ec] min-w-[220px] z-20 shadow-[0_8px_24px_rgba(26,24,21,0.18)]"
                data-testid={`reroute-popover-${signal.id}`}
              >
                <div className="font-mono text-[9px] uppercase tracking-[0.1em] text-[#8b857a] px-2.5 py-1.5 pt-2">
                  Send instead to
                </div>
                {opts.length === 0 && (
                  <div className="px-2.5 py-2 font-mono text-[11px] text-[#8b857a] text-left">
                    No configured handoff targets.
                  </div>
                )}
                {opts.map((opt) => (
                  <button
                    key={opt.owner}
                    onClick={(event) => { event.stopPropagation(); handleReroute(opt.owner); }}
                    className="flex justify-between items-center w-full px-2.5 py-1.75 font-mono text-[12px] text-[#f4f1ec] cursor-pointer transition-colors duration-[0.12s] hover:bg-[#4a4640] text-left"
                    data-testid={`reroute-option-${opt.owner.replace(/[^a-z0-9]/gi, "-")}`}
                  >
                    <span>{opt.owner}</span>
                    <span className="font-mono text-[9px] text-[#8b857a] uppercase tracking-[0.04em]">{opt.hint}</span>
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        {signal.reroutedFrom && (
          <div className="text-[9px] text-[#8b857a] mt-2 tracking-[0.04em]">
            moved from {signal.reroutedFrom}
          </div>
        )}
        {error && (
          <div className="text-[9px] text-[#b8431f] mt-2 tracking-[0.04em]">
            {error}
          </div>
        )}
      </div>
    </motion.article>
  );
}
