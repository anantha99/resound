import { pgTable, serial, text, integer, timestamp } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";

export const signalsTable = pgTable("signals", {
  id: serial("id").primaryKey(),
  brandId: text("brand_id").notNull(),
  source: text("source").notNull(),
  externalId: text("external_id").notNull(),
  url: text("url").notNull().default(""),
  authorHandle: text("author_handle").notNull(),
  authorMeta: text("author_meta"),
  reach: integer("reach"),
  content: text("content").notNull(),
  postedAt: timestamp("posted_at").notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertSignalSchema = createInsertSchema(signalsTable).omit({ id: true, createdAt: true });
export type InsertSignal = z.infer<typeof insertSignalSchema>;
export type Signal = typeof signalsTable.$inferSelect;
