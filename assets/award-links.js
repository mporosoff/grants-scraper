(() => {
  "use strict";

  const reviewedMappings = Object.freeze({
    "362061": Object.freeze({
      source: "NSF",
      label: "Chemical Process Systems (CPS), including reviewed predecessor programs",
      criteria: Object.freeze({
        program_codes: Object.freeze(["367Y00", "140100", "764400", "141700", "140300"]),
      }),
      mapping_basis: "reviewed_parent_program",
      mapping_source_url: "https://www.nsf.gov/funding/opportunities/chemical-process-systems",
    }),
    "362062": Object.freeze({
      source: "NSF",
      label: "Engineering Biological and Biomedical Systems (EBBS), including reviewed predecessor programs",
      criteria: Object.freeze({
        program_codes: Object.freeze(["369Y00", "723600", "149100", "534200", "534500"]),
      }),
      mapping_basis: "reviewed_parent_program",
      mapping_source_url: "https://www.nsf.gov/funding/opportunities/engineering-biological-biomedical-systems",
    }),
    "nsf-cbet:PD-26-370Y": Object.freeze({
      source: "NSF",
      label: "Energy, Water, and Resource Engineering (EWRE), including reviewed predecessor programs",
      criteria: Object.freeze({
        program_codes: Object.freeze(["370Y00", "764300", "117900"]),
      }),
      mapping_basis: "reviewed_parent_program",
      mapping_source_url: "https://www.nsf.gov/funding/opportunities/energy-water-resource-engineering",
    }),
    "362063": Object.freeze({
      source: "NSF",
      label: "Transport Phenomena (TP), including reviewed predecessor programs",
      criteria: Object.freeze({
        program_codes: Object.freeze(["366Y00", "140700", "144300", "141500", "140600"]),
      }),
      mapping_basis: "reviewed_parent_program",
      mapping_source_url: "https://www.nsf.gov/funding/opportunities/transport-phenomena",
    }),
    "363616": Object.freeze({
      source: "NSF",
      label: "Chemical, Bioengineering, Energy, and Transport Systems (CBET), including reviewed predecessor programs",
      criteria: Object.freeze({
        program_codes: Object.freeze([
          "366Y00", "367Y00", "369Y00", "370Y00",
          "140100", "764400", "141700", "140300",
          "723600", "149100", "534200", "534500",
          "764300", "117900", "140700", "144300", "141500", "140600",
        ]),
      }),
      mapping_basis: "reviewed_parent_program",
      mapping_source_url: "https://www.nsf.gov/funding/opportunities/engineering-eng-chemical-bioengineering-energy-transport",
    }),
  });

  function clean(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function opportunityId(record) {
    return clean(record?.opportunity_id || record?.opportunity_number);
  }

  function isNsf(record) {
    return clean(record?.agency_code).toUpperCase() === "NSF"
      || /National Science Foundation/i.test(clean(record?.agency));
  }

  function isNih(record) {
    return /^HHS-NIH/i.test(clean(record?.agency_code))
      || /National Institutes of Health/i.test(clean(record?.agency));
  }

  function nsfProgramElementCode(opportunityNumber) {
    const match = /^PD-\d{2}-([A-Z0-9]{4})$/i.exec(clean(opportunityNumber));
    return match ? `${match[1].toUpperCase()}00` : "";
  }

  function lookupForOpportunity(record) {
    const id = opportunityId(record);
    const reviewed = reviewedMappings[id];
    if (reviewed && isNsf(record)) return reviewed;

    if (isNih(record)) {
      const number = clean(record?.opportunity_number).toUpperCase();
      if (!number || !/^[A-Z0-9-]+$/.test(number)) return null;
      return Object.freeze({
        source: "NIH",
        label: number,
        criteria: Object.freeze({ opportunity_number: number }),
        mapping_basis: "exact_nih_opportunity_number",
        mapping_source_url: clean(record?.detail_page || record?.funding_opportunity_url),
      });
    }

    if (isNsf(record)) {
      const code = nsfProgramElementCode(record?.opportunity_number);
      if (!code) return null;
      return Object.freeze({
        source: "NSF",
        label: `NSF program ${code}`,
        criteria: Object.freeze({ program_codes: Object.freeze([code]) }),
        mapping_basis: "exact_nsf_program_element",
        mapping_source_url: clean(record?.agency_status_source_url || record?.funding_opportunity_url),
      });
    }

    return null;
  }

  function fundedAwardsHref(record) {
    const id = opportunityId(record);
    return id && lookupForOpportunity(record)
      ? `./funded_awards.html?opportunity=${encodeURIComponent(id)}`
      : "";
  }

  globalThis.FUNDING_AWARD_LINKS = Object.freeze({
    fundedAwardsHref,
    lookupForOpportunity,
    nsfProgramElementCode,
    reviewedMappings,
  });
})();
