import { useGetSignal } from "@workspace/api-client-react";
import { Link, useRoute } from "wouter";
import Masthead from "@/components/Masthead";
import { formatPath, toSignalView } from "@/api/viewModels";
import { useBrand } from "@/context/BrandContext";

const SERIF = "'Cormorant Garamond', serif";
const MONO = "'JetBrains Mono', monospace";

export default function SignalDetailPage() {
  const [, params] = useRoute("/signals/:signalId");
  const signalId = Number(params?.signalId);
  const { activeBrand } = useBrand();
  const query = useGetSignal(signalId, {
    query: { enabled: Number.isInteger(signalId), queryKey: ["signal", signalId] },
  });
  const detail = query.data;
  const signal = detail ? toSignalView(detail) : null;

  return (
    <div className="min-h-screen bg-[#f4f1ec] text-[#1a1815]">
      <div className="resound-page-shell max-w-[1320px] mx-auto px-14">
        <Masthead />
        <section className="border-t border-[#1a1815] pt-8 pb-7 flex justify-between items-end">
          <div><h1 style={{ font: `300 56px/.9 ${SERIF}` }}>Signal feed<em className="text-[#4a4640]">.</em></h1>
            <div className="mt-4 uppercase text-[10px] tracking-[.06em] text-[#8b857a]" style={{ fontFamily: MONO }}>{activeBrand.name} · focused detail</div>
          </div>
          <Link href="/signals" className="uppercase text-[10px] tracking-[.08em] text-[#8b857a]" style={{ fontFamily: MONO }}>Back to feed</Link>
        </section>
        {!signal || !detail ? <div className="py-24 text-center italic text-[22px] text-[#8b857a]" style={{ fontFamily: SERIF }}>{query.isError ? "Signal not found in this organization." : "Loading signal record..."}</div> : (
          <article className="resound-detail-grid border-t border-[#d9d3c7] pt-8 grid grid-cols-[145px_minmax(0,1fr)_240px] gap-10">
            <aside className="resound-detail-meta">
              {[['Source', signal.source], ['Published', signal.postedAt], ['Access', 'Public']].map(([label, value]) => <div key={label} className="mb-5"><div className="uppercase text-[9px] tracking-[.09em] text-[#8b857a]" style={{ fontFamily: MONO }}>{label}</div><div className="mt-1 text-[11px]" style={{ fontFamily: MONO }}>{value}</div></div>)}
              {signal.canonicalUrl && <a href={signal.canonicalUrl} target="_blank" rel="noreferrer" className="text-[10px] text-[#8b857a]" style={{ fontFamily: MONO }}>View source ↗</a>}
            </aside>
            <div>
              <div className="uppercase text-[11px] tracking-[.06em] mb-3" style={{ fontFamily: MONO }}>{signal.source}</div>
              <div className="uppercase text-[10px] tracking-[.05em] text-[#8b857a] mb-4" style={{ fontFamily: MONO }}>{signal.authorHandle} · {signal.authorMeta}</div>
              <p className="text-[27px] leading-[1.38] mb-7" style={{ fontFamily: SERIF }}>{signal.content}</p>
              {signal.parentContext && <section className="py-5 border-y border-[#e3ddd1]"><div className="uppercase text-[9px] tracking-[.1em] text-[#8b857a] mb-3" style={{ fontFamily: MONO }}>Parent content</div><p className="text-[21px] leading-tight" style={{ fontFamily: SERIF }}>“{signal.parentContext.excerpt}”</p></section>}
              <section className="py-5 border-b border-[#e3ddd1]"><div className="uppercase text-[9px] tracking-[.1em] text-[#8b857a] mb-3" style={{ fontFamily: MONO }}>Observed public engagement</div><div className="text-[12px] uppercase tracking-[.04em] text-[#4a4640]" style={{ fontFamily: MONO }}>{signal.metrics}</div></section>
              <div className="flex gap-4 py-5 uppercase text-[10px] tracking-[.06em]" style={{ fontFamily: MONO }}><b>{signal.area}</b><span>{signal.severity}</span><span>{signal.sentiment}</span><span>{signal.actionClass}</span></div>
            </div>
            <aside>
              <div className="border-t border-[#1a1815] pt-4"><div className="uppercase text-[9px] tracking-[.09em] text-[#8b857a]" style={{ fontFamily: MONO }}>Routed to</div><strong className="block my-1 text-[14px]" style={{ fontFamily: MONO }}>{signal.owner}</strong><div className="uppercase text-[10px] text-[#8b857a]" style={{ fontFamily: MONO }}>Conf {signal.confidence.toFixed(2)}</div></div>
              <div className="mt-8 p-4 bg-[#ebe7df] text-[9px] leading-7 text-[#8b857a]" style={{ fontFamily: MONO }}><div className="uppercase tracking-[.1em] mb-1">Source record</div><div>Platform · {signal.platform}</div><div>Content kind · {signal.contentKind}</div><div>Path · {formatPath(signal.provenancePath)}</div><div>Metric type · Observed public</div></div>
            </aside>
          </article>
        )}
        <footer className="mt-12 py-6 border-t border-[#1a1815] uppercase text-[10px] tracking-[.08em] text-[#8b857a] flex justify-between" style={{ fontFamily: MONO }}><span>Signal record · append-only</span><span>Resound v1.0</span></footer>
      </div>
    </div>
  );
}
