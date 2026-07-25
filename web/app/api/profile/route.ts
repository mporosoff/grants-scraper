import { eq } from "drizzle-orm";
import { ensureSchema, getDb } from "@/db";
import { facultyProfiles } from "@/db/schema";
import { getRequestUserEmail } from "@/lib/request-user";

export const dynamic = "force-dynamic";

function text(value: unknown, maxLength = 5000) {
  return String(value ?? "").trim().slice(0, maxLength);
}

export async function GET(request: Request) {
  await ensureSchema();
  const ownerEmail = getRequestUserEmail(request);
  const db = getDb();
  const [profile] = await db
    .select()
    .from(facultyProfiles)
    .where(eq(facultyProfiles.ownerEmail, ownerEmail))
    .limit(1);

  return Response.json({ profile: profile ?? null });
}

export async function PUT(request: Request) {
  await ensureSchema();
  const ownerEmail = getRequestUserEmail(request);
  const payload = (await request.json()) as Record<string, unknown>;
  const name = text(payload.name, 160);
  const synopsis = text(payload.synopsis, 6000);

  if (!name || synopsis.length < 40) {
    return Response.json(
      {
        error:
          "Enter your name and a research synopsis of at least 40 characters.",
      },
      { status: 400 },
    );
  }

  const db = getDb();
  const [existing] = await db
    .select()
    .from(facultyProfiles)
    .where(eq(facultyProfiles.ownerEmail, ownerEmail))
    .limit(1);
  const yearsValue =
    payload.yearsSinceDoctorate === "" ||
    payload.yearsSinceDoctorate === null ||
    payload.yearsSinceDoctorate === undefined
      ? null
      : Number(payload.yearsSinceDoctorate);
  const now = new Date().toISOString();
  const record = {
    ownerEmail,
    name,
    academicTitle: text(payload.academicTitle, 240),
    careerStage: text(payload.careerStage, 80) || "unknown",
    yearsSinceDoctorate:
      yearsValue !== null && Number.isFinite(yearsValue)
        ? Math.max(0, Math.min(80, Math.round(yearsValue)))
        : null,
    synopsis,
    topics: text(payload.topics, 2000),
    methods: text(payload.methods, 2000),
    applicationAreas: text(payload.applicationAreas, 2000),
    futureDirections: text(payload.futureDirections, 3000),
    excludeTopics: text(payload.excludeTopics, 2000),
    groupWebsite: text(payload.groupWebsite, 500),
    updatedAt: now,
  };

  if (existing) {
    await db
      .update(facultyProfiles)
      .set(record)
      .where(eq(facultyProfiles.id, existing.id));
  } else {
    await db.insert(facultyProfiles).values({
      id: crypto.randomUUID(),
      ...record,
      createdAt: now,
    });
  }

  const [profile] = await db
    .select()
    .from(facultyProfiles)
    .where(eq(facultyProfiles.ownerEmail, ownerEmail))
    .limit(1);

  return Response.json({ profile });
}
