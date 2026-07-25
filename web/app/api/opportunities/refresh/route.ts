import { fetchLiveOpportunities } from "@/lib/grants-gov";
import { saveOpportunities } from "@/lib/opportunities";

export async function POST(request: Request) {
  const payload = (await request.json().catch(() => ({}))) as {
    keywords?: unknown;
    limit?: unknown;
  };
  const keywords = Array.isArray(payload.keywords)
    ? payload.keywords
        .map((value) => String(value).trim())
        .filter(Boolean)
        .slice(0, 5)
    : [];
  const limit = Math.max(1, Math.min(30, Number(payload.limit) || 12));

  if (!keywords.length) {
    return Response.json(
      { error: "Enter at least one Grants.gov search topic." },
      { status: 400 },
    );
  }

  try {
    const records = await fetchLiveOpportunities(keywords, limit);
    const saved = await saveOpportunities(records);
    return Response.json({ fetched: records.length, saved });
  } catch (error) {
    return Response.json(
      {
        error:
          error instanceof Error
            ? error.message
            : "Could not refresh Grants.gov.",
      },
      { status: 502 },
    );
  }
}
