import type { facultyProfiles, opportunities } from "@/db/schema";

type Profile = typeof facultyProfiles.$inferSelect;
type Opportunity = typeof opportunities.$inferSelect;

export type MatchVerdict = "strong" | "plausible" | "poor" | "ineligible";

export type GrantMatch = {
  opportunity: Opportunity;
  verdict: MatchVerdict;
  score: number;
  rationale: string;
  eligibility: string;
  overlap: string[];
};

const STOP_WORDS = new Set(
  [
    "about", "above", "after", "again", "against", "also", "among", "another",
    "and", "any", "application", "applications", "are", "award", "awards",
    "based", "basic", "because", "been", "before", "being", "between", "both",
    "but", "can", "could",
    "department", "development", "faculty", "federal", "for", "funding", "grant",
    "grants", "group", "has", "have", "including", "into", "institution",
    "institutions", "investigator", "investigators", "its", "may", "more",
    "most", "must", "not", "opportunity", "our", "over", "program", "project",
    "proposal", "proposals", "research", "science", "support", "supports",
    "than", "that", "the", "their", "them", "these", "they", "this", "those",
    "through", "under", "university", "use", "used", "using", "was", "were",
    "which", "will", "with", "within", "would",
  ],
);

function tokenize(value: string) {
  return value
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 2 && !STOP_WORDS.has(token));
}

function phrases(value: string) {
  return value
    .split(/[\n,;]+/)
    .map((part) => part.trim().toLowerCase())
    .filter((part) => part.length > 2);
}

function deadlineHasPassed(value: string) {
  if (!value) return false;
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return false;
  return parsed < Date.now() - 24 * 60 * 60 * 1000;
}

function eligibilityBlock(profile: Profile, opportunity: Opportunity) {
  if (deadlineHasPassed(opportunity.closeDate)) {
    return "The listed deadline has passed.";
  }

  const title = opportunity.title.toLowerCase();
  const structuredSignal = opportunity.careerStageSignal.toLowerCase();
  const eligibility = opportunity.eligibilityText.toLowerCase();
  const earlyCareerTitle =
    /early[\s-]?career|faculty career|doctoral new investigator|young investigator/.test(
      title,
    );
  const structuredRestriction =
    /untenured|assistant professor|within\s+\w+\s+years/.test(
      structuredSignal,
    );
  const eligibilityRestriction =
    /(?:only|eligible|restricted|required)[^.\n]{0,100}(?:early[\s-]?career|untenured|assistant professor|within\s+\w+\s+years)/.test(
      eligibility,
    );
  const earlyCareerOnly =
    earlyCareerTitle || structuredRestriction || eligibilityRestriction;
  const earlyCareerProfile = ["assistant", "assistant_research"].includes(
    profile.careerStage,
  );
  if (earlyCareerOnly && !earlyCareerProfile) {
    return "The opportunity appears restricted to early-career or untenured investigators.";
  }

  return "";
}

export function rankOpportunities(
  profile: Profile,
  allOpportunities: Opportunity[],
): GrantMatch[] {
  const profileText = [
    profile.synopsis,
    profile.topics,
    profile.methods,
    profile.applicationAreas,
    profile.futureDirections,
  ].join(" ");
  const profileTokens = new Set(tokenize(profileText));
  const topicTokens = new Set(tokenize(profile.topics));
  const topicPhrases = phrases(profile.topics);
  const exclusions = phrases(profile.excludeTopics);

  return allOpportunities
    .map((opportunity): GrantMatch => {
      const grantText = [
        opportunity.title,
        opportunity.agency,
        opportunity.description,
        opportunity.eligibilityText,
      ].join(" ");
      const lowerGrant = grantText.toLowerCase();
      const titleTokens = new Set(tokenize(opportunity.title));
      const grantTokens = new Set(tokenize(grantText));
      const overlap = [...profileTokens]
        .filter((token) => grantTokens.has(token))
        .sort((left, right) => {
          const leftTitle = titleTokens.has(left) ? 1 : 0;
          const rightTitle = titleTokens.has(right) ? 1 : 0;
          return rightTitle - leftTitle || left.localeCompare(right);
        })
        .slice(0, 6);
      const phraseMatches = topicPhrases.filter((topic) =>
        lowerGrant.includes(topic),
      );
      const excluded = exclusions.find((topic) => lowerGrant.includes(topic));
      const hardBlock = eligibilityBlock(profile, opportunity);

      if (hardBlock) {
        return {
          opportunity,
          verdict: "ineligible",
          score: 0,
          rationale: hardBlock,
          eligibility: hardBlock,
          overlap,
        };
      }

      const titleOverlap = overlap.filter((token) => titleTokens.has(token)).length;
      const topicOverlap = overlap.filter((token) => topicTokens.has(token)).length;
      let score =
        8 +
        overlap.length * 6 +
        titleOverlap * 8 +
        topicOverlap * 10 +
        phraseMatches.length * 18;
      score = Math.min(96, Math.round(score));

      let verdict: MatchVerdict =
        score >= 58 ? "strong" : score >= 22 ? "plausible" : "poor";
      let eligibility = "";

      if (excluded) {
        score = Math.min(score, 24);
        verdict = "poor";
        eligibility = `Profile excludes “${excluded}.”`;
      }

      const concreteOverlap = [
        ...phraseMatches.slice(0, 2),
        ...overlap.filter((term) => !phraseMatches.join(" ").includes(term)),
      ].slice(0, 3);
      const rationale = excluded
        ? `The topic overlaps with an area this profile explicitly excludes: ${excluded}.`
        : concreteOverlap.length
          ? `The clearest overlap is ${concreteOverlap.join(", ")}.`
          : "The current profile and opportunity share little specific technical language.";

      return {
        opportunity,
        verdict,
        score,
        rationale,
        eligibility,
        overlap,
      };
    })
    .sort((left, right) => {
      const rank: Record<MatchVerdict, number> = {
        strong: 0,
        plausible: 1,
        poor: 2,
        ineligible: 3,
      };
      return rank[left.verdict] - rank[right.verdict] || right.score - left.score;
    });
}
