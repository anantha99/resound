import { pgTable, serial, integer, text, boolean, real, timestamp } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";
import { signalsTable } from "./signals";

export const classificationsTable = pgTable("classifications", {
  id: serial("id").primaryKey(),
  signalId: integer("signal_id").notNull().references(() => signalsTable.id),
  isAboutBrand: boolean("is_about_brand").notNull().default(true),
  area: text("area").notNull(),
  subarea: text("subarea"),
  sentiment: text("sentiment").notNull(),
  severity: text("severity").notNull(),
  actionClass: text("action_class").notNull(),
  rootCauseHypothesis: text("root_cause_hypothesis").notNull().default(""),
  summary: text("summary").notNull().default(""),
  confidence: real("confidence").notNull().default(0.8),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertClassificationSchema = createInsertSchema(classificationsTable).omit({ id: true, createdAt: true });
export type InsertClassification = z.infer<typeof insertClassificationSchema>;
export type Classification = typeof classificationsTable.$inferSelect;
