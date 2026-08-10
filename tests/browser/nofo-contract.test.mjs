import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);

async function loadNofoApi(profile = {}) {
  const source = await readFile(new URL("assets/nofo.js", root), "utf8");
  const context = { FUNDING_PROFILE: profile };
  context.globalThis = context;
  vm.runInNewContext(source, context, { filename: "nofo.js" });
  return context.FUNDING_NOFO;
}

test("matches an uploaded notice to an exact catalog opportunity number", async () => {
  const api = await loadNofoApi();
  const records = [
    {
      opportunity_number: "26-MMR-NOFO-002",
      title: "Advanced Manufacturing Demonstrations",
      status: "posted",
    },
    {
      opportunity_number: "NSF-26-501",
      title: "Sustainable Systems",
      status: "forecasted",
    },
  ];

  const match = api.matchCatalog(
    "Funding Opportunity Announcement 26-MMR-NOFO-002. Applications are due soon.",
    "notice.pdf",
    records,
  );

  assert.equal(match.record, records[0]);
  assert.equal(match.confidence, "exact");
  assert.match(match.reason, /26-MMR-NOFO-002/);
});

test("falls back to a distinctive title match when no opportunity number is found", async () => {
  const api = await loadNofoApi();
  const records = [
    {
      opportunity_number: "TEST-1",
      title: "Rural Community Health Workforce Innovation Initiative",
      agency: "Health Resources Administration",
      status: "posted",
    },
    {
      opportunity_number: "TEST-2",
      title: "Quantum Materials Research Centers",
      agency: "National Science Foundation",
      status: "posted",
    },
  ];

  const match = api.matchCatalog(
    "The Rural Community Health Workforce Innovation Initiative will support local training partnerships.",
    "funding-notice.pdf",
    records,
  );

  assert.equal(match.record, records[0]);
  assert.match(match.confidence, /title/);
});

test("extracts page-marked PDF text locally and rejects non-PDF files", async () => {
  const api = await loadNofoApi();
  const pdf = { name: "DE-FOA-123.pdf", type: "application/pdf", size: 2048 };
  const extracted = await api.extract(pdf, {
    extractPdfText: async () => ({
      pages: [
        "Funding Opportunity DE-FOA-123 supports catalytic research with detailed application requirements.",
        "Eligibility includes institutions of higher education. Applications are due September 30, 2026.",
        "Review criteria include technical merit, impact, and team qualifications for the proposed work.",
      ],
      pageCount: 3,
      truncated: false,
    }),
  });

  assert.match(extracted.text, /\[Page 1\]/);
  assert.match(extracted.text, /\[Page 3\]/);
  assert.equal(extracted.pageCount, 3);
  assert.equal(extracted.truncated, false);

  await assert.rejects(
    api.extract({ name: "notice.docx", type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", size: 10 }),
    /Only PDF notices/,
  );
});

test("rejects an incorrect catalog connection without discarding the uploaded notice", async () => {
  const api = await loadNofoApi();
  const notice = {
    fileName: "uploaded-nofo.pdf",
    text: "Locally extracted notice text",
    matchedId: "25-533",
    matchConfidence: "title",
    rejectedIds: ["OLD-1"],
  };

  const reconciled = api.rejectCatalogMatch(notice);

  assert.equal(reconciled.matchedId, "");
  assert.equal(reconciled.matchConfidence, "rejected");
  assert.match(reconciled.matchReason, /marked as unrelated/);
  assert.deepEqual([...reconciled.rejectedIds], ["OLD-1", "25-533"]);
  assert.equal(reconciled.text, notice.text);
  assert.equal(notice.matchedId, "25-533", "the helper must not mutate caller state");
});
