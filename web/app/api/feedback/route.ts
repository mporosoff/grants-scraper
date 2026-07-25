import { and, eq } from "drizzle-orm";
import { ensureSchema, getDb } from "@/db";
import { facultyProfiles, matchFeedback } from "@/db/schema";
import { getRequestUserEmail } from "@/lib/request-user";

const DECISIONS = new Set(["relevant", "not_relevant", "pursue", "clear"]);

export async function POST(request: Request) {
  await ensureSchema();
  const ownerEmail = getRequestUserEmail(request);
  const payload = (await request.json()) as {
    opportunityId?: unknown;
    decision?: unknown;
  };
  const opportunityId = String(payload.opportunityId ?? "").trim();
  const decision = String(payload.decision ?? "").trim();

  if (!opportunityId || !DECISIONS.has(decision)) {
    return Response.json({ error: "Invalid feedback." }, { status: 400 });
  }

  const db = getDb();
  const [profile] = await db
    .select()
    .from(facultyProfiles)
    .where(eq(facultyProfiles.ownerEmail, ownerEmail))
    .limit(1);
  if (!profile) {
    return Response.json({ error: "Profile not found." }, { status: 409 });
  }

  const whereOwnerOpportunity = and(
    eq(matchFeedback.ownerEmail, ownerEmail),
    eq(matchFeedback.opportunityId, opportunityId),
  );
  const [existing] = await db
    .select()
    .from(matchFeedback)
    .where(whereOwnerOpportunity)
    .limit(1);

  if (decision === "clear") {
    if (existing) {
      await db.delete(matchFeedback).where(whereOwnerOpportunity);
    }
    return Response.json({ decision: "" });
  }

  const now = new Date().toISOString();
  if (existing) {
    await db
      .update(matchFeedback)
      .set({ decision, updatedAt: now })
      .where(eq(matchFeedback.id, existing.id));
  } else {
    await db.insert(matchFeedback).values({
      id: crypto.randomUUID(),
      ownerEmail,
      profileId: profile.id,
      opportunityId,
      decision,
      createdAt: now,
      updatedAt: now,
    });
  }

  return Response.json({ decision });
}
