import { pgTable, serial, integer, text, real, timestamp } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";
import { signalsTable } from "./signals";
import { classificationsTable } from "./classifications";

export const routesTable = pgTable("routes", {
  id: serial("id").primaryKey(),
  signalId: integer("signal_id").notNull().references(() => signalsTable.id),
  classificationId: integer("classification_id").notNull().references(() => classificationsTable.id),
  owner: text("owner").notNull(),
  ruleMatched: text("rule_matched"),
  confidence: real("confidence").notNull().default(0.8),
  reroutedFrom: text("rerouted_from"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertRouteSchema = createInsertSchema(routesTable).omit({ id: true, createdAt: true });
export type InsertRoute = z.infer<typeof insertRouteSchema>;
export type Route = typeof routesTable.$inferSelect;
