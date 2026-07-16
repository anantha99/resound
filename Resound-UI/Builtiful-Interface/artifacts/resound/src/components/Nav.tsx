import { Link, useLocation } from "wouter";

const navItems = [
  { label: "Dashboard", href: "/" },
  { label: "Signals", href: "/signals" },
  { label: "Memory", href: "/memory" },
  { label: "Patterns", href: "/patterns" },
];

export default function Nav() {
  const [location] = useLocation();

  return (
    <nav className="resound-nav flex gap-6 items-center">
      {navItems.map((item) => {
        const active = item.href === "/" ? location === "/" : location.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`font-mono text-[10px] uppercase tracking-[0.08em] transition-colors duration-150 ${
              active ? "text-[#1a1815]" : "text-[#8b857a] hover:text-[#4a4640]"
            }`}
            data-testid={`nav-${item.label.toLowerCase()}`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
