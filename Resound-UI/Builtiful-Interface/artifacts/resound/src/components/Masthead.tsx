import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Nav from "@/components/Nav";
import { useBrand } from "@/context/BrandContext";

function ResoundMark() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, userSelect: "none" }}>
      {/* Signal-wave SVG mark */}
      <svg
        width="22"
        height="22"
        viewBox="0 0 22 22"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{ flexShrink: 0, marginBottom: 1 }}
      >
        {/* Outer arc */}
        <path
          d="M3.5 18.5 C3.5 18.5 1 14.5 1 11 C1 7.5 3.5 3.5 3.5 3.5"
          stroke="#b8431f"
          strokeWidth="1.25"
          strokeLinecap="round"
          fill="none"
          opacity="0.45"
        />
        {/* Middle arc */}
        <path
          d="M6.5 16 C6.5 16 4.5 13.5 4.5 11 C4.5 8.5 6.5 6 6.5 6"
          stroke="#b8431f"
          strokeWidth="1.35"
          strokeLinecap="round"
          fill="none"
          opacity="0.7"
        />
        {/* Inner arc */}
        <path
          d="M9.5 13.8 C9.5 13.8 8 12.2 8 11 C8 9.8 9.5 8.2 9.5 8.2"
          stroke="#b8431f"
          strokeWidth="1.5"
          strokeLinecap="round"
          fill="none"
        />
        {/* Center dot */}
        <circle cx="13.5" cy="11" r="1.6" fill="#1a1815" />
        {/* Right arcs — mirrored, lighter */}
        <path
          d="M15.5 13.8 C15.5 13.8 17 12.2 17 11 C17 9.8 15.5 8.2 15.5 8.2"
          stroke="#1a1815"
          strokeWidth="1.2"
          strokeLinecap="round"
          fill="none"
          opacity="0.25"
        />
        <path
          d="M18 15.5 C18 15.5 20 13 20 11 C20 9 18 6.5 18 6.5"
          stroke="#1a1815"
          strokeWidth="1"
          strokeLinecap="round"
          fill="none"
          opacity="0.12"
        />
      </svg>

      {/* Wordmark */}
      <div style={{ display: "flex", flexDirection: "column", lineHeight: 1, gap: 1 }}>
        <span style={{
          fontFamily: "'Cormorant SC', serif",
          fontWeight: 300,
          fontSize: 22,
          letterSpacing: "0.18em",
          color: "#1a1815",
          lineHeight: 1,
          textTransform: "uppercase",
        }}>
          Resound
        </span>
        <span style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 7.5,
          letterSpacing: "0.22em",
          color: "#8b857a",
          textTransform: "uppercase",
          lineHeight: 1,
          paddingLeft: 1,
        }}>
          Signal Intelligence
        </span>
      </div>
    </div>
  );
}

export default function Masthead() {
  const { activeBrand, brands, isLoading, isError, setActiveBrand } = useBrand();
  const [open, setOpen] = useState(false);

  return (
    <header className="flex items-center justify-between pt-8 pb-6">
      <ResoundMark />

      <div className="flex gap-7 items-center" style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "#8b857a" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            display: "inline-block", width: 5, height: 5,
            background: "#4a6b3f", borderRadius: "50%",
            animation: "pulse 2s ease-in-out infinite",
          }} />
          {isError ? "Offline" : isLoading ? "Syncing" : "Live"}
        </span>

        {/* Brand switcher */}
        <div className="relative">
          <button
            onClick={() => setOpen(!open)}
            data-testid="brand-switcher"
            style={{
              background: "transparent", border: "none", cursor: "pointer",
              fontFamily: "'JetBrains Mono', monospace", fontSize: 10,
              letterSpacing: "0.08em", textTransform: "uppercase",
              color: "#8b857a", padding: 0, display: "flex", alignItems: "center", gap: 5,
            }}
          >
            Brand{" "}<strong style={{ color: "#1a1815", fontWeight: 500 }}>{activeBrand.id}</strong>
            <svg width="8" height="8" viewBox="0 0 8 8" fill="none" style={{ opacity: 0.5 }}>
              <path d="M1 3L4 1L7 3M1 5L4 7L7 5" stroke="#1a1815" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          <AnimatePresence>
            {open && (
              <>
                {/* Backdrop */}
                <div
                  style={{ position: "fixed", inset: 0, zIndex: 40 }}
                  onClick={() => setOpen(false)}
                />
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 6 }}
                  transition={{ duration: 0.15, ease: "easeOut" }}
                  style={{
                    position: "absolute", top: "calc(100% + 12px)", right: 0,
                    background: "#1a1815", color: "#f4f1ec", minWidth: 280, zIndex: 50,
                    boxShadow: "0 12px 40px rgba(26,24,21,0.25), 0 2px 8px rgba(26,24,21,0.15)",
                    border: "1px solid #2a2825",
                  }}
                >
                  {/* Header */}
                  <div style={{
                    padding: "10px 14px 8px",
                    borderBottom: "1px solid #2a2825",
                    fontFamily: "'JetBrains Mono', monospace", fontSize: 9,
                    letterSpacing: "0.12em", textTransform: "uppercase", color: "#4a4640",
                  }}>
                    Switch workspace
                  </div>

                  {brands.length === 0 && (
                    <div style={{ padding: "14px", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: "#8b857a" }}>
                      No backend brands available.
                    </div>
                  )}
                  {brands.map((brand) => {
                    const isActive = activeBrand.id === brand.id;
                    return (
                      <button
                        key={brand.id}
                        data-testid={`brand-option-${brand.id}`}
                        onClick={() => { setActiveBrand(brand); setOpen(false); }}
                        style={{
                          display: "flex", flexDirection: "column", width: "100%",
                          padding: "11px 14px",
                          background: isActive ? "#2a2825" : "transparent",
                          border: "none", cursor: "pointer", textAlign: "left",
                          transition: "background 0.1s",
                          borderBottom: "1px solid #222",
                        }}
                        onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "#242220"; }}
                        onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                      >
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <span style={{
                            fontFamily: "'Cormorant Garamond', serif",
                            fontWeight: 400, fontSize: 17,
                            color: "#f4f1ec", lineHeight: 1.15,
                          }}>
                            {brand.name}
                          </span>
                          {isActive && (
                            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                              <circle cx="5" cy="5" r="2" fill="#4a6b3f" />
                            </svg>
                          )}
                        </div>
                        <span style={{
                          fontFamily: "'JetBrains Mono', monospace", fontSize: 9,
                          color: "#4a4640", letterSpacing: "0.04em", marginTop: 4,
                        }}>
                          {brand.tagline}
                        </span>
                      </button>
                    );
                  })}
                </motion.div>
              </>
            )}
          </AnimatePresence>
        </div>

        <span>Op <strong style={{ color: "#1a1815", fontWeight: 500 }}>{activeBrand.primaryContact}</strong></span>
        <Nav />
      </div>

      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }`}</style>
    </header>
  );
}
