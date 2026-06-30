import type {
  Brand,
  Pattern,
  RouteAudit,
  SignalDetail,
} from "@workspace/api-client-react";

export type Severity = "low" | "medium" | "high" | "critical";
export type Sentiment = "positive" | "negative" | "neutral" | "mixed";
export type ActionClass = "immediate" | "sprint" | "roadmap" | "fyi" | "ignore";
export type Area = "product" | "engineering" | "billing" | "cs" | "marketing" | "ops" | "other";

export interface OwnerOption {
  owner: string;
  label: string;
  hint: string;
}

export interface BrandView {
  id: string;
  numericId: number;
  name: string;
  tagline: string;
  primaryContact: string;
  sourcesActive: string[];
  lastIngested: string | null;
  ownerOptions: OwnerOption[];
}

export interface SignalView {
  id: number;
  routeId: number;
  brandId: string;
  source: string;
  authorHandle: string;
  authorMeta: string;
  reach: string;
  content: string;
  postedAt: string;
  area: Area;
  severity: Severity;
  sentiment: Sentiment;
  actionClass: ActionClass;
  summary: string;
  confidence: number;
  owner: string;
  ruleMatched: string;
  reroutedFrom?: string;
  patternId?: number | null;
  patternName?: string | null;
  feedbackCorrect?: boolean;
}

export interface PatternView {
  id: number;
  brandId: string;
  name: string;
  area: Area;
  blurb: string;
  signalCount: number;
  weeklyVelocity: number;
  velocityMultiple: number;
  startedAt: string;
}

type BrandWithExtras = Brand & {
  tagline?: string;
  ownerOptions?: OwnerOption[];
};

export function toBrandView(brand: BrandWithExtras): BrandView {
  return {
    id: brand.slug,
    numericId: brand.id,
    name: brand.name,
    tagline: brand.tagline || brand.description,
    primaryContact: compactContact(brand.primaryContact),
    sourcesActive: brand.sourcesActive.map(formatSource),
    lastIngested: brand.lastIngested,
    ownerOptions: brand.ownerOptions ?? [],
  };
}

export function toSignalView(detail: SignalDetail): SignalView {
  return {
    id: detail.signal.id,
    routeId: detail.route.id,
    brandId: detail.signal.brandId,
    source: formatSource(detail.signal.source),
    authorHandle: detail.signal.authorHandle || "unknown",
    authorMeta: detail.signal.authorMeta || "source metadata unavailable",
    reach: formatReach(detail.signal.source, detail.signal.reach),
    content: detail.signal.content,
    postedAt: relativeTime(detail.signal.postedAt),
    area: normalizeArea(detail.classification.area),
    severity: detail.classification.severity as Severity,
    sentiment: detail.classification.sentiment as Sentiment,
    actionClass: detail.classification.actionClass as ActionClass,
    summary: detail.classification.summary,
    confidence: detail.route.confidence ?? detail.classification.confidence,
    owner: detail.route.owner,
    ruleMatched: detail.route.ruleMatched || "default",
    reroutedFrom: detail.route.reroutedFrom ?? undefined,
    patternId: detail.patternId,
    patternName: detail.patternName,
  };
}

export function routeAuditToSignalView(route: RouteAudit, brandId: string): SignalView {
  return {
    id: route.signalId,
    routeId: route.id,
    brandId,
    source: formatSource(route.source),
    authorHandle: "memory",
    authorMeta: "routing audit",
    reach: "recorded",
    content: route.content,
    postedAt: relativeTime(route.createdAt),
    area: normalizeArea(route.area),
    severity: route.severity as Severity,
    sentiment: route.sentiment as Sentiment,
    actionClass: "fyi",
    summary: route.summary,
    confidence: route.confidence,
    owner: route.owner,
    ruleMatched: route.ruleMatched || "default",
    reroutedFrom: route.reroutedFrom ?? undefined,
    feedbackCorrect: route.feedbackCorrect ?? undefined,
  };
}

export function toPatternView(pattern: Pattern): PatternView {
  return {
    id: pattern.id,
    brandId: pattern.brandId,
    name: pattern.name,
    area: normalizeArea(pattern.area),
    blurb: pattern.blurb,
    signalCount: pattern.signalCount,
    weeklyVelocity: pattern.weeklyVelocity,
    velocityMultiple: pattern.velocityMultiple,
    startedAt: pattern.startedAt,
  };
}

export function apiPeriod(period: "24h" | "7d" | "30d" | "QTD"): "24h" | "7d" | "30d" | "qtd" {
  return period === "QTD" ? "qtd" : period;
}

export function formatSource(source: string): string {
  const normalized = source.toLowerCase();
  if (normalized === "g2") return "G2";
  if (normalized === "twitter") return "Twitter";
  if (normalized === "reddit") return "Reddit";
  return source.charAt(0).toUpperCase() + source.slice(1);
}

function formatReach(source: string, reach?: number | null): string {
  if (reach == null) return "reach unknown";
  const normalized = source.toLowerCase();
  if (normalized === "reddit") return `${reach.toLocaleString()} upvotes`;
  if (normalized === "twitter") return `~${reach.toLocaleString()} engagements`;
  if (normalized === "g2") return `${Math.round(reach / 20)} stars`;
  return reach.toLocaleString();
}

function compactContact(value: string): string {
  if (!value) return "operator";
  if (value.includes("@")) return value.split("@")[0] + "@";
  return value;
}

function normalizeArea(area: string): Area {
  const allowed: Area[] = ["product", "engineering", "billing", "cs", "marketing", "ops", "other"];
  return allowed.includes(area as Area) ? (area as Area) : "other";
}

function relativeTime(value: string): string {
  const date = new Date(value);
  const diffMs = Date.now() - date.getTime();
  if (Number.isNaN(diffMs)) return value;
  const minutes = Math.max(0, Math.round(diffMs / 60000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
