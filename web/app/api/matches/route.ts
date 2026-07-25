import { desc, eq } from "drizzle-orm";
import { ensureSchema, getDb } from "@/db";
import {
  facultyProfiles,
  matchFeedback,
  opportunities,
} from "@/db/schema";
import { rankOpportunities } from "@/lib/matching";
import { getRequestUserEmail } from "@/lib/request-user";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  await ensureSchema();
  const ownerEmail = getRequestUserEmail(request);
  const db = getDb();
  const [profile] = await db
    .select()
    .from(facultyProfiles)
    .where(eq(facultyProfiles.ownerEmail, ownerEmail))
    .limit(1);

  if (!profile) {
    return Response.json(
      { error: "Create and save a research profile first." },
      { status: 409 },
    );
  }

  const [grantRows, feedbackRows] = await Promise.all([
    db
      .select()
      .from(opportunities)
      .orderBy(desc(opportunities.importedAt))
      .limit(500),
    db
      .select()
      .from(matchFeedback)
      .where(eq(matchFeedback.ownerEmail, ownerEmail)),
  ]);
  const feedback = new Map(
    feedbackRows.map((row) => [row.opportunityId, row.decision]),
  );
  const matches = rankOpportunities(profile, grantRows).map((match) => ({
    ...match,
    feedback: feedback.get(match.opportunity.id) ?? "",
  }));

  return Response.json({
    profile: { id: profile.id, name: profile.name },
    considered: grantRows.length,
    strategy: "transparent lexical baseline",
    matches,
  });
}
