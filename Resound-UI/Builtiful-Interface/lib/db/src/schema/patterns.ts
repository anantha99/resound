import { pgTable, serial, text, integer, real, timestamp } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";

export const patternsTable = pgTable("patterns", {
  id: serial("id").primaryKey(),
  brandId: text("brand_id").notNull(),
  name: text("name").notNull(),
  area: text("area").notNull(),
  blurb: text("blurb").notNull().default(""),
  signalCount: integer("signal_count").notNull().default(0),
  weeklyVelocity: integer("weekly_velocity").notNull().default(0),
  velocityMultiple: real("velocity_multiple").notNull().default(1),
  startedAt: timestamp("started_at").notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const patternSignalsTable = pgTable("pattern_signals", {
  id: serial("id").primaryKey(),
  patternId: integer("pattern_id").notNull().references(() => patternsTable.id),
  signalId: integer("signal_id").notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertPatternSchema = createInsertSchema(patternsTable).omit({ id: true, createdAt: true });
export type InsertPattern = z.infer<typeof insertPatternSchema>;
export type Pattern = typeof patternsTable.$inferSelect;
