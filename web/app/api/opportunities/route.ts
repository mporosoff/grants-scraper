import { desc } from "drizzle-orm";
import { ensureSchema, getDb } from "@/db";
import { opportunities } from "@/db/schema";

export const dynamic = "force-dynamic";

export async function GET() {
  await ensureSchema();
  const db = getDb();
  const rows = await db
    .select()
    .from(opportunities)
    .orderBy(desc(opportunities.importedAt))
    .limit(500);

  return Response.json({ opportunities: rows, count: rows.length });
}
