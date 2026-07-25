import { desc } from "drizzle-orm";
import { ensureSchema, getDb } from "@/db";
import { opportunities } from "@/db/schema";
import { saveOpportunities } from "@/lib/opportunities";

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

export async function POST(request: Request) {
  const payload = (await request.json()) as unknown;
  const records = Array.isArray(payload)
    ? payload
    : payload &&
        typeof payload === "object" &&
        Array.isArray((payload as { grants?: unknown[] }).grants)
      ? (payload as { grants: unknown[] }).grants
      : [];

  if (!records.length) {
    return Response.json(
      { error: "Upload a JSON array of grant opportunities." },
      { status: 400 },
    );
  }

  try {
    const saved = await saveOpportunities(
      records.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      ),
    );
    return Response.json({ saved }, { status: 201 });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "Import failed." },
      { status: 400 },
    );
  }
}
