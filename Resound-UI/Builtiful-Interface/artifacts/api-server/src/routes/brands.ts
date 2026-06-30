import { Router } from "express";
import { db } from "@workspace/db";
import { brandsTable, signalsTable, classificationsTable, routesTable, patternsTable, feedbackEventsTable } from "@workspace/db";
import { eq, desc, gte, count, avg, and, or, sql } from "drizzle-orm";

const router = Router();

router.get("/brands", async (req, res) => {
  const brands = await db.select().from(brandsTable).orderBy(brandsTable.name);
  res.json(brands.map(b => ({
    id: b.id,
    name: b.name,
    slug: b.slug,
    description: b.description,
    primaryContact: b.primaryContact,
    sourcesActive: b.sourcesActive,
    lastIngested: b.lastIngested?.toISOString() ?? null,
  })));
});

router.get("/brands/:brandId/stats/:period", async (req, res) => {
  const { brandId, period } = req.params;
  const brand = await db.select().from(brandsTable).where(eq(brandsTable.slug, brandId)).limit(1);
  if (!brand.length) {
    res.status(404).json({ error: "Brand not found" });
    return;
  }

  const periodDays: Record<string, number> = { "24h": 1, "7d": 7, "30d": 30, "qtd": 90 };
  const days = periodDays[period] ?? 7;
  const since = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  const prevSince = new Date(Date.now() - 2 * days * 24 * 60 * 60 * 1000);

  // Current period signals
  const currentSignals = await db
    .select({ signalId: signalsTable.id })
    .from(signalsTable)
    .where(and(eq(signalsTable.brandId, brandId), gte(signalsTable.postedAt, since)));

  const currentIds = currentSignals.map(s => s.signalId);

  // Previous period signals
  const prevSignals = await db
    .select({ signalId: signalsTable.id })
    .from(signalsTable)
    .where(and(eq(signalsTable.brandId, brandId), gte(signalsTable.postedAt, prevSince)));
  const prevIds = prevSignals.map(s => s.signalId).filter(id => !currentIds.includes(id));

  const getClassifications = async (ids: number[]) => {
    if (!ids.length) return [];
    return db.select().from(classificationsTable)
      .where(sql`${classificationsTable.signalId} = ANY(${ids})`);
  };

  const currClass = await getClassifications(currentIds);
  const prevClass = await getClassifications(prevIds);

  const calcSentiment = (classes: typeof currClass) => {
    const pos = classes.filter(c => c.sentiment === "positive").length;
    const neg = classes.filter(c => c.sentiment === "negative").length;
    const total = classes.length || 1;
    return { score: Math.round(((pos - neg) / total) * 100), pos: Math.round(pos / total * 100), neg: Math.round(neg / total * 100), neu: Math.round((total - pos - neg) / total * 100) };
  };

  const currSent = calcSentiment(currClass);
  const prevSent = calcSentiment(prevClass);

  const criticalCurr = currClass.filter(c => c.severity === "critical" || c.severity === "high").length;
  const criticalPrev = prevClass.filter(c => c.severity === "critical" || c.severity === "high").length;

  // Source mix
  const sourceCounts: Record<string, number> = {};
  for (const id of currentIds) {
    const sig = await db.select({ source: signalsTable.source }).from(signalsTable).where(eq(signalsTable.id, id)).limit(1);
    if (sig[0]) sourceCounts[sig[0].source] = (sourceCounts[sig[0].source] || 0) + 1;
  }
  const total = currentIds.length || 1;
  const sourceMix = Object.entries(sourceCounts).map(([source, cnt]) => ({
    source, count: cnt, pct: Math.round(cnt / total * 100)
  }));

  // Top emerging pattern
  const topPattern = await db.select().from(patternsTable)
    .where(eq(patternsTable.brandId, brandId))
    .orderBy(desc(patternsTable.velocityMultiple))
    .limit(1);

  const tp = topPattern[0];

  res.json({
    brandId,
    period,
    netSentiment: currSent.score,
    netSentimentDelta: currSent.score - prevSent.score,
    criticalCount: criticalCurr,
    criticalDelta: criticalCurr - criticalPrev,
    totalVolume: currentIds.length,
    volumeDelta: prevIds.length ? (currentIds.length - prevIds.length) / prevIds.length : 0,
    sourceMix,
    sentimentBreakdown: { positive: currSent.pos, neutral: currSent.neu, negative: currSent.neg },
    topEmergingIssue: tp ? {
      id: tp.id,
      name: tp.name,
      area: tp.area,
      signalCount: tp.signalCount,
      weeklyVelocity: tp.weeklyVelocity,
      velocityMultiple: tp.velocityMultiple,
    } : {
      id: 0, name: "No emerging issues", area: "ops", signalCount: 0, weeklyVelocity: 0, velocityMultiple: 1
    },
  });
});

export default router;
