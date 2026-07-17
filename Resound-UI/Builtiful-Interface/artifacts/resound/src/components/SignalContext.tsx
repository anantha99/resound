import type { SignalView } from "@/api/viewModels";

const SERIF = "'Cormorant Garamond', serif";
const MONO = "'JetBrains Mono', monospace";

export function CompactSignalMetrics({ metrics }: { metrics: SignalView["metrics"] }) {
  return <>{metrics.compact}</>;
}

export function SignalMetricGrid({ metrics }: { metrics: SignalView["metrics"] }) {
  return (
    <div className="resound-metric-grid grid grid-cols-4 gap-px bg-[#d9d3c7] mt-1">
      {metrics.items.map((metric) => (
        <div key={metric.label} className="bg-[#f4f1ec] px-4 py-4">
          <b className="block text-[25px] leading-none font-light mb-1.5" style={{ fontFamily: SERIF }}>
            {metric.value == null ? "—" : compactNumber(metric.value)}
          </b>
          <span className="uppercase text-[9px] tracking-[.08em] text-[#8b857a]" style={{ fontFamily: MONO }}>
            {metric.label}
          </span>
        </div>
      ))}
    </div>
  );
}

export function SignalParentContext({
  parent,
  compact = false,
}: {
  parent: NonNullable<SignalView["parentContext"]>;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <div className="resound-parent-context flex gap-2.5 items-baseline py-2.5 mb-3 border-y border-[#e3ddd1] text-[#4a4640]">
        <span className="shrink-0 font-mono text-[9px] tracking-[0.08em] uppercase text-[#8b857a]">
          On {parent.sourceLabel}
        </span>
        <span className="font-serif italic text-[14px] leading-[1.35]">{parent.excerpt}</span>
      </div>
    );
  }

  return (
    <section className="py-5 border-y border-[#e3ddd1]">
      <div className="uppercase text-[9px] tracking-[.1em] text-[#8b857a] mb-3" style={{ fontFamily: MONO }}>
        {parent.label}
      </div>
      <p className="text-[21px] leading-tight mb-2" style={{ fontFamily: SERIF }}>“{parent.excerpt}”</p>
      <div className="uppercase text-[10px] leading-relaxed tracking-[.04em] text-[#8b857a]" style={{ fontFamily: MONO }}>
        {parent.sourceLabel}
        {parent.authorHandle ? ` · ${parent.authorHandle}` : ""}
        {parent.publishedAt ? ` · published ${parent.publishedAt}` : " · published —"}
        {parent.url ? <>{" · "}<a href={parent.url} target="_blank" rel="noreferrer">View source ↗</a></> : null}
      </div>
    </section>
  );
}

function compactNumber(value: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: value >= 1000 ? 1 : 0,
  }).format(value);
}
