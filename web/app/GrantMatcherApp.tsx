"use client";

import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";

type View = "profile" | "feed" | "matches";
type Notice = { tone: "success" | "error" | "info"; text: string } | null;

type Profile = {
  id?: string;
  name: string;
  academicTitle: string;
  careerStage: string;
  yearsSinceDoctorate: number | "";
  synopsis: string;
  topics: string;
  methods: string;
  applicationAreas: string;
  futureDirections: string;
  excludeTopics: string;
  groupWebsite: string;
  updatedAt?: string;
};

type Opportunity = {
  id: string;
  opportunityNumber: string;
  title: string;
  agency: string;
  status: string;
  description: string;
  closeDate: string;
  awardCeiling: string;
  limitedSubmission: boolean;
  costShareRequired: boolean;
  hasPreliminaryStage: boolean;
  detailPage: string;
  nofoPdfUrl: string;
  importedAt: string;
};

type Match = {
  opportunity: Opportunity;
  verdict: "strong" | "plausible" | "poor" | "ineligible";
  score: number;
  rationale: string;
  eligibility: string;
  overlap: string[];
  feedback: string;
};

const EMPTY_PROFILE: Profile = {
  name: "",
  academicTitle: "",
  careerStage: "unknown",
  yearsSinceDoctorate: "",
  synopsis: "",
  topics: "",
  methods: "",
  applicationAreas: "",
  futureDirections: "",
  excludeTopics: "",
  groupWebsite: "",
};

const DEFAULT_SEARCH_TOPICS =
  "catalysis, carbon capture, separations, chemical engineering";

async function readJson<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & { error?: string };
  if (!response.ok) {
    throw new Error(payload.error || "The request could not be completed.");
  }
  return payload;
}

function formatDate(value: string) {
  if (!value) return "No deadline listed";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }).format(date);
}

function formatMoney(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return value || "Not listed";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
    notation: numeric >= 1_000_000 ? "compact" : "standard",
  }).format(numeric);
}

function csvCell(value: unknown) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

export function GrantMatcherApp() {
  const [view, setView] = useState<View>("profile");
  const [profile, setProfile] = useState<Profile>(EMPTY_PROFILE);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [filter, setFilter] = useState("all");
  const [searchTopics, setSearchTopics] = useState(DEFAULT_SEARCH_TOPICS);
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const [profileResponse, opportunityResponse] = await Promise.all([
          fetch("/api/profile", { cache: "no-store" }),
          fetch("/api/opportunities", { cache: "no-store" }),
        ]);
        const profilePayload = await readJson<{ profile: Profile | null }>(
          profileResponse,
        );
        const opportunityPayload = await readJson<{
          opportunities: Opportunity[];
        }>(opportunityResponse);
        if (profilePayload.profile) setProfile(profilePayload.profile);
        setOpportunities(opportunityPayload.opportunities);
      } catch (error) {
        setNotice({
          tone: "error",
          text:
            error instanceof Error
              ? error.message
              : "The workspace could not be loaded.",
        });
      } finally {
        setLoaded(true);
      }
    }
    void load();
  }, []);

  const profileReady = Boolean(profile.id);
  const visibleMatches = useMemo(
    () =>
      matches.filter((match) =>
        filter === "all" ? true : match.verdict === filter,
      ),
    [filter, matches],
  );
  const strongCount = matches.filter(
    (match) => match.verdict === "strong",
  ).length;

  function updateProfile(
    event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) {
    const { name, value } = event.target;
    setProfile((current) => ({
      ...current,
      [name]: name === "yearsSinceDoctorate" && value ? Number(value) : value,
    }));
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    setBusy("profile");
    setNotice(null);
    try {
      const response = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(profile),
      });
      const payload = await readJson<{ profile: Profile }>(response);
      setProfile(payload.profile);
      setNotice({
        tone: "success",
        text: "Research profile saved. It is now the basis for every match.",
      });
      setView(opportunities.length ? "matches" : "feed");
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof Error ? error.message : "Profile save failed.",
      });
    } finally {
      setBusy("");
    }
  }

  async function reloadOpportunities() {
    const response = await fetch("/api/opportunities", { cache: "no-store" });
    const payload = await readJson<{ opportunities: Opportunity[] }>(response);
    setOpportunities(payload.opportunities);
  }

  async function refreshLiveOpportunities() {
    const keywords = searchTopics
      .split(/[\n,;]+/)
      .map((value) => value.trim())
      .filter(Boolean)
      .slice(0, 5);
    setBusy("refresh");
    setNotice({
      tone: "info",
      text: "Checking Grants.gov and normalizing the newest matching records…",
    });
    try {
      const response = await fetch("/api/opportunities/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keywords, limit: 18 }),
      });
      const payload = await readJson<{ fetched: number; saved: number }>(
        response,
      );
      await reloadOpportunities();
      setNotice({
        tone: "success",
        text: `${payload.saved} live opportunities are ready to screen.`,
      });
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof Error
            ? error.message
            : "The live refresh failed.",
      });
    } finally {
      setBusy("");
    }
  }

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy("import");
    setNotice(null);
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      const response = await fetch("/api/opportunities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed),
      });
      const payload = await readJson<{ saved: number }>(response);
      await reloadOpportunities();
      setNotice({
        tone: "success",
        text: `${payload.saved} opportunities imported from ${file.name}.`,
      });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof Error ? error.message : "Import failed.",
      });
    } finally {
      event.target.value = "";
      setBusy("");
    }
  }

  async function runMatches() {
    setBusy("matches");
    setNotice(null);
    try {
      const response = await fetch("/api/matches", { cache: "no-store" });
      const payload = await readJson<{ matches: Match[] }>(response);
      setMatches(payload.matches);
      setNotice({
        tone: "success",
        text: `${payload.matches.length} opportunities screened against your profile.`,
      });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof Error ? error.message : "Matching failed.",
      });
    } finally {
      setBusy("");
    }
  }

  async function sendFeedback(opportunityId: string, decision: string) {
    const current = matches.find(
      (match) => match.opportunity.id === opportunityId,
    )?.feedback;
    const nextDecision = current === decision ? "clear" : decision;
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ opportunityId, decision: nextDecision }),
      });
      const payload = await readJson<{ decision: string }>(response);
      setMatches((rows) =>
        rows.map((match) =>
          match.opportunity.id === opportunityId
            ? { ...match, feedback: payload.decision }
            : match,
        ),
      );
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof Error ? error.message : "Feedback was not saved.",
      });
    }
  }

  function exportVisibleMatches() {
    const header = [
      "verdict",
      "score",
      "title",
      "agency",
      "opportunity_number",
      "deadline",
      "award_ceiling",
      "rationale",
      "eligibility",
      "feedback",
      "opportunity_url",
      "nofo_url",
    ];
    const rows = visibleMatches.map((match) => [
      match.verdict,
      match.score,
      match.opportunity.title,
      match.opportunity.agency,
      match.opportunity.opportunityNumber,
      match.opportunity.closeDate,
      match.opportunity.awardCeiling,
      match.rationale,
      match.eligibility,
      match.feedback,
      match.opportunity.detailPage,
      match.opportunity.nofoPdfUrl,
    ]);
    const csv = [header, ...rows]
      .map((row) => row.map(csvCell).join(","))
      .join("\r\n");
    const blob = new Blob([`\uFEFF${csv}`], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `grant-matches-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => setView("profile")}>
          <span className="brand-mark">GM</span>
          <span>
            <strong>UR Grant Matcher</strong>
            <small>Chemical &amp; Sustainability Engineering</small>
          </span>
        </button>
        <nav aria-label="Primary">
          {(["profile", "feed", "matches"] as View[]).map((item, index) => (
            <button
              key={item}
              className={view === item ? "nav-item active" : "nav-item"}
              onClick={() => setView(item)}
            >
              <span>{index + 1}</span>
              {item === "feed" ? "Opportunity feed" : item}
            </button>
          ))}
        </nav>
        <span className="pilot-chip">Private pilot</span>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">Personal funding intelligence</p>
          <h1>Funding worth your attention.</h1>
          <p>
            Describe the work you want to do. The matcher screens live
            opportunities, explains the overlap, and learns which recommendations
            are useful.
          </p>
        </div>
        <div className="hero-status">
          <button onClick={() => setView("profile")}>
            <strong>{profileReady ? "Ready" : "Needed"}</strong>
            <span>Research profile</span>
          </button>
          <button onClick={() => setView("feed")}>
            <strong>{opportunities.length}</strong>
            <span>Opportunities</span>
          </button>
          <button onClick={() => setView("matches")}>
            <strong>{strongCount}</strong>
            <span>Strong matches</span>
          </button>
        </div>
      </section>

      {notice && (
        <div className={`notice ${notice.tone}`} role="status">
          {notice.text}
          <button aria-label="Dismiss message" onClick={() => setNotice(null)}>
            ×
          </button>
        </div>
      )}

      {!loaded ? (
        <section className="loading-panel">Opening your grant workspace…</section>
      ) : view === "profile" ? (
        <section className="workspace">
          <div className="section-heading">
            <div>
              <p className="step-label">Step 1 · Research profile</p>
              <h2>Tell the matcher what matters.</h2>
              <p>
                Use your own language. This profile is editable and replaces
                department-page scraping.
              </p>
            </div>
            <span className={profileReady ? "state ready" : "state"}>
              {profileReady ? "Saved" : "Not saved"}
            </span>
          </div>

          <form className="profile-form" onSubmit={saveProfile}>
            <div className="form-grid two">
              <label>
                Name
                <input
                  name="name"
                  value={profile.name}
                  onChange={updateProfile}
                  placeholder="Marc D. Porosoff"
                  required
                />
              </label>
              <label>
                Academic title
                <input
                  name="academicTitle"
                  value={profile.academicTitle}
                  onChange={updateProfile}
                  placeholder="Associate Professor"
                />
              </label>
              <label>
                Career stage
                <select
                  name="careerStage"
                  value={profile.careerStage}
                  onChange={updateProfile}
                >
                  <option value="unknown">Choose a stage</option>
                  <option value="assistant">Assistant professor</option>
                  <option value="associate">Associate professor</option>
                  <option value="full">Full professor</option>
                  <option value="research">Research faculty</option>
                </select>
              </label>
              <label>
                Years since doctorate
                <input
                  type="number"
                  min="0"
                  max="80"
                  name="yearsSinceDoctorate"
                  value={profile.yearsSinceDoctorate}
                  onChange={updateProfile}
                  placeholder="Optional"
                />
              </label>
            </div>

            <label className="wide-field">
              Research synopsis
              <textarea
                name="synopsis"
                value={profile.synopsis}
                onChange={updateProfile}
                rows={6}
                placeholder="Describe the problems your group works on, why they matter, and the scientific approaches you use."
                required
              />
              <small>
                Aim for 150–300 words. Concrete nouns and future-facing ideas
                produce better recommendations.
              </small>
            </label>

            <div className="form-grid two">
              <label>
                Research topics
                <textarea
                  name="topics"
                  value={profile.topics}
                  onChange={updateProfile}
                  rows={4}
                  placeholder="CO₂ conversion, heterogeneous catalysis, reactive separations"
                />
              </label>
              <label>
                Methods and capabilities
                <textarea
                  name="methods"
                  value={profile.methods}
                  onChange={updateProfile}
                  rows={4}
                  placeholder="Operando spectroscopy, reactor design, machine learning"
                />
              </label>
              <label>
                Application areas
                <textarea
                  name="applicationAreas"
                  value={profile.applicationAreas}
                  onChange={updateProfile}
                  rows={4}
                  placeholder="Decarbonization, sustainable fuels, circular chemicals"
                />
              </label>
              <label>
                Future directions
                <textarea
                  name="futureDirections"
                  value={profile.futureDirections}
                  onChange={updateProfile}
                  rows={4}
                  placeholder="New directions you would pursue if the right call appeared"
                />
              </label>
              <label>
                Topics not to send
                <textarea
                  name="excludeTopics"
                  value={profile.excludeTopics}
                  onChange={updateProfile}
                  rows={3}
                  placeholder="Clinical trials, undergraduate curriculum development"
                />
              </label>
              <label>
                Group website
                <input
                  name="groupWebsite"
                  value={profile.groupWebsite}
                  onChange={updateProfile}
                  placeholder="https://..."
                />
              </label>
            </div>

            <div className="form-actions">
              <button className="primary-button" disabled={busy === "profile"}>
                {busy === "profile" ? "Saving…" : "Save research profile"}
              </button>
              <span>
                Your profile stays in the application database, not in GitHub.
              </span>
            </div>
          </form>
        </section>
      ) : view === "feed" ? (
        <section className="workspace">
          <div className="section-heading">
            <div>
              <p className="step-label">Step 2 · Opportunity feed</p>
              <h2>Bring in opportunities once.</h2>
              <p>
                Refresh directly from Grants.gov or import normalized JSON from
                the existing Python pipeline.
              </p>
            </div>
            <span className={opportunities.length ? "state ready" : "state"}>
              {opportunities.length} available
            </span>
          </div>

          <div className="feed-controls">
            <div>
              <label htmlFor="search-topics">Grants.gov search topics</label>
              <textarea
                id="search-topics"
                rows={3}
                value={searchTopics}
                onChange={(event) => setSearchTopics(event.target.value)}
              />
              <small>Up to five comma-separated topics · 18 results per refresh</small>
            </div>
            <div className="feed-actions">
              <button
                className="primary-button"
                onClick={refreshLiveOpportunities}
                disabled={busy === "refresh"}
              >
                {busy === "refresh" ? "Refreshing…" : "Refresh live opportunities"}
              </button>
              <label className="file-button">
                {busy === "import" ? "Importing…" : "Import grants.json"}
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={importFile}
                  disabled={Boolean(busy)}
                />
              </label>
            </div>
          </div>

          {opportunities.length ? (
            <div className="opportunity-list">
              <div className="list-header">
                <span>Recently imported</span>
                <button onClick={() => setView("matches")}>Screen these →</button>
              </div>
              {opportunities.slice(0, 12).map((opportunity) => (
                <article key={opportunity.id} className="opportunity-row">
                  <div>
                    <p>{opportunity.title}</p>
                    <span>
                      {opportunity.agency || "Agency not listed"} ·{" "}
                      {opportunity.opportunityNumber || opportunity.id}
                    </span>
                  </div>
                  <div className="row-meta">
                    <span>{formatDate(opportunity.closeDate)}</span>
                    <strong>{formatMoney(opportunity.awardCeiling)}</strong>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state">
              <strong>No opportunities yet.</strong>
              <p>Refresh Grants.gov to create the first shared opportunity feed.</p>
            </div>
          )}
        </section>
      ) : (
        <section className="workspace">
          <div className="section-heading matches-heading">
            <div>
              <p className="step-label">Step 3 · Match explorer</p>
              <h2>{profileReady ? `Matches for ${profile.name}` : "Your matches"}</h2>
              <p>
                Every recommendation shows the concrete overlap and any hard
                eligibility concern.
              </p>
            </div>
            <button
              className="primary-button"
              onClick={runMatches}
              disabled={!profileReady || !opportunities.length || busy === "matches"}
            >
              {busy === "matches" ? "Screening…" : "Run matching"}
            </button>
          </div>

          {!profileReady || !opportunities.length ? (
            <div className="empty-state action-state">
              <strong>
                {!profileReady
                  ? "Save your research profile first."
                  : "Add opportunities before matching."}
              </strong>
              <button onClick={() => setView(!profileReady ? "profile" : "feed")}>
                Go to {!profileReady ? "profile" : "opportunity feed"} →
              </button>
            </div>
          ) : matches.length ? (
            <>
              <div className="match-toolbar">
                <div>
                  {["all", "strong", "plausible", "poor", "ineligible"].map(
                    (value) => (
                      <button
                        key={value}
                        className={filter === value ? "filter active" : "filter"}
                        onClick={() => setFilter(value)}
                      >
                        {value}
                      </button>
                    ),
                  )}
                </div>
                <div className="toolbar-actions">
                  <span>
                    Transparent baseline · semantic reranking is the next upgrade
                  </span>
                  <button
                    className="export-button"
                    onClick={exportVisibleMatches}
                  >
                    Export visible CSV
                  </button>
                </div>
              </div>
              <div className="matches-list">
                {visibleMatches.map((match) => (
                  <article
                    key={match.opportunity.id}
                    className={`match-card verdict-${match.verdict}`}
                  >
                    <div className="match-score">
                      <strong>{match.score}</strong>
                      <span>fit score</span>
                    </div>
                    <div className="match-body">
                      <div className="match-topline">
                        <span className={`verdict ${match.verdict}`}>
                          {match.verdict}
                        </span>
                        <span>
                          {match.opportunity.agency || "Agency not listed"}
                        </span>
                      </div>
                      <h3>{match.opportunity.title}</h3>
                      <p className="rationale">{match.rationale}</p>
                      {match.eligibility && (
                        <p className="eligibility-note">{match.eligibility}</p>
                      )}
                      <div className="grant-facts">
                        <span>
                          Deadline <strong>{formatDate(match.opportunity.closeDate)}</strong>
                        </span>
                        <span>
                          Ceiling <strong>{formatMoney(match.opportunity.awardCeiling)}</strong>
                        </span>
                        {match.opportunity.hasPreliminaryStage && (
                          <span className="warning-chip">Preliminary stage</span>
                        )}
                        {match.opportunity.limitedSubmission && (
                          <span className="warning-chip">Limited submission</span>
                        )}
                        {match.opportunity.costShareRequired && (
                          <span className="warning-chip">Cost share</span>
                        )}
                      </div>
                      <div className="card-actions">
                        {match.opportunity.detailPage && (
                          <a
                            href={match.opportunity.detailPage}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Opportunity page ↗
                          </a>
                        )}
                        {match.opportunity.nofoPdfUrl && (
                          <a
                            href={match.opportunity.nofoPdfUrl}
                            target="_blank"
                            rel="noreferrer"
                          >
                            NOFO ↗
                          </a>
                        )}
                        <div className="feedback-buttons">
                          <button
                            className={
                              match.feedback === "relevant" ? "selected" : ""
                            }
                            onClick={() =>
                              sendFeedback(match.opportunity.id, "relevant")
                            }
                          >
                            Useful
                          </button>
                          <button
                            className={
                              match.feedback === "not_relevant" ? "selected" : ""
                            }
                            onClick={() =>
                              sendFeedback(match.opportunity.id, "not_relevant")
                            }
                          >
                            Not relevant
                          </button>
                        </div>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state action-state">
              <strong>Ready to screen {opportunities.length} opportunities.</strong>
              <p>Run matching to create a ranked, explained triage list.</p>
            </div>
          )}
        </section>
      )}

      <footer>
        <span>UR Grant Matcher · private pilot</span>
        <span>Faculty-controlled profiles · live federal data · visible rationale</span>
      </footer>
    </main>
  );
}
