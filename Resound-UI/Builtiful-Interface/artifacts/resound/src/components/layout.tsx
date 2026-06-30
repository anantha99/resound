export function AppHeader() {
  return (
    <header className="flex items-baseline justify-between py-9">
      <div className="font-serif text-[32px] tracking-[-0.02em] leading-none text-foreground flex items-baseline">
        Resound<span className="inline-block w-1.5 h-1.5 bg-[#b8431f] rounded-full ml-[3px] transform -translate-y-px"></span>
      </div>
      <div className="flex gap-7 items-baseline font-mono text-[10px] tracking-[0.08em] uppercase text-[#8b857a]">
        <span className="flex items-center">
          <span className="inline-block w-[5px] h-[5px] bg-[#4a6b3f] rounded-full mr-1.5 animate-pulse"></span>
          LIVE
        </span>
        <span>BRAND <strong className="text-foreground font-medium">liquiddeath</strong></span>
        <span>OPERATOR <strong className="text-foreground font-medium">ak@</strong></span>
      </div>
    </header>
  );
}

export function SystemStatusFooter() {
  return (
    <footer className="mt-16 py-6 pb-12 border-t border-foreground flex justify-between items-baseline font-mono text-[10px] tracking-[0.08em] uppercase text-[#8b857a]">
      <div className="flex items-center gap-6">
        <span><span className="inline-block w-[5px] h-[5px] rounded-full bg-[#4a6b3f] mr-1.5 align-middle"></span>SYSTEM <strong>ONLINE</strong></span>
        <span>CLASSIFIER <strong>v2.4.1</strong></span>
        <span>LATENCY <strong>42ms</strong></span>
      </div>
      <div>Resound Intelligence — Internal</div>
    </footer>
  );
}
