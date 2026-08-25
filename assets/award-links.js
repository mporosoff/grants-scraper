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
      program_identity: Object.freeze({ id: "nsf:cbet:cps", label: "Chemical Process Systems (CPS)" }),
    }),
    "362062": Object.freeze({
      source: "NSF",
      label: "Engineering Biological and Biomedical Systems (EBBS), including reviewed predecessor programs",
      criteria: Object.freeze({
        program_codes: Object.freeze(["369Y00", "723600", "149100", "534200", "534500"]),
      }),
      mapping_basis: "reviewed_parent_program",
      mapping_source_url: "https://www.nsf.gov/funding/opportunities/engineering-biological-biomedical-systems",
      program_identity: Object.freeze({ id: "nsf:cbet:ebbs", label: "Engineering Biological and Biomedical Systems (EBBS)" }),
    }),
    "nsf-cbet:PD-26-370Y": Object.freeze({
      source: "NSF",
      label: "Energy, Water, and Resource Engineering (EWRE), including reviewed predecessor programs",
      criteria: Object.freeze({
        program_codes: Object.freeze(["370Y00", "764300", "117900"]),
      }),
      mapping_basis: "reviewed_parent_program",
      mapping_source_url: "https://www.nsf.gov/funding/opportunities/energy-water-resource-engineering",
      program_identity: Object.freeze({ id: "nsf:cbet:ewre", label: "Energy, Water, and Resource Engineering (EWRE)" }),
    }),
    "362063": Object.freeze({
      source: "NSF",
      label: "Transport Phenomena (TP), including reviewed predecessor programs",
      criteria: Object.freeze({
        program_codes: Object.freeze(["366Y00", "140700", "144300", "141500", "140600"]),
      }),
      mapping_basis: "reviewed_parent_program",
      mapping_source_url: "https://www.nsf.gov/funding/opportunities/transport-phenomena",
      program_identity: Object.freeze({ id: "nsf:cbet:tp", label: "Transport Phenomena (TP)" }),
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
      program_identity: Object.freeze({ id: "nsf:cbet", label: "Chemical, Bioengineering, Energy, and Transport Systems (CBET)" }),
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

  function isDoeOfficeScience(record) {
    const code = clean(record?.agency_code).toUpperCase();
    const agency = clean(record?.agency);
    return code === "PAMS-SC"
      || /^Office of Science$/i.test(agency)
      || /^(?:U\.S\. )?Department of Energy(?: \(DOE\))? (?:-|–) Office of Science$/i.test(agency);
  }

  function nsfProgramElementCode(opportunityNumber) {
    const match = /^PD-\d{2}-([A-Z0-9]{4})$/i.exec(clean(opportunityNumber));
    return match ? `${match[1].toUpperCase()}00` : "";
  }

  function exactProgramIdentity(record) {
    if (!isNsf(record)) return null;
    const id = opportunityId(record);
    const reviewed = reviewedMappings[id];
    if (reviewed?.program_identity) return reviewed.program_identity;
    const code = nsfProgramElementCode(record?.opportunity_number);
    if (!code) return null;
    const specific = Object.values(reviewedMappings).find(mapping => (
      mapping.program_identity?.id !== "nsf:cbet"
      && mapping.criteria.program_codes.includes(code)
    ));
    return specific?.program_identity || Object.freeze({
      id: `nsf:program-element:${code}`,
      label: `NSF program ${code}`,
    });
  }

  function programIdentityForOpportunity(record) {
    // NIH opportunity numbers identify an exact FOA, not a stable program
    // family across cycles. Until a controlled cross-cycle NIH registry exists,
    // do not offer a misleading NIH program watch.
    return exactProgramIdentity(record);
  }

  function matchesProgramIdentity(programId, record) {
    const watched = clean(programId).toLowerCase();
    if (!watched || !isNsf(record)) return false;
    const direct = exactProgramIdentity(record);
    if (clean(direct?.id).toLowerCase() === watched) return true;
    const code = nsfProgramElementCode(record?.opportunity_number);
    if (!code) return false;
    if (watched === "nsf:cbet") {
      return reviewedMappings["363616"].criteria.program_codes.includes(code);
    }
    const reviewed = Object.values(reviewedMappings).find(
      mapping => mapping.program_identity?.id === watched,
    );
    if (reviewed) return reviewed.criteria.program_codes.includes(code);
    return watched === `nsf:program-element:${code}`.toLowerCase();
  }

  function programIdentityById(programId) {
    const watched = clean(programId).toLowerCase();
    const reviewed = Object.values(reviewedMappings).find(
      mapping => mapping.program_identity?.id === watched,
    );
    if (reviewed) return reviewed.program_identity;
    const match = /^nsf:program-element:([a-z0-9]{6})$/i.exec(watched);
    return match ? Object.freeze({
      id: `nsf:program-element:${match[1].toUpperCase()}`,
      label: `NSF program ${match[1].toUpperCase()}`,
    }) : null;
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

    if (isDoeOfficeScience(record)) {
      const number = clean(record?.opportunity_number).toUpperCase();
      if (!/^DE-FOA-\d+$/.test(number)) return null;
      return Object.freeze({
        source: "DOE",
        label: number,
        criteria: Object.freeze({ opportunity_number: number }),
        mapping_basis: "exact_doe_foa_number",
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
    isDoeOfficeScience,
    lookupForOpportunity,
    matchesProgramIdentity,
    nsfProgramElementCode,
    programIdentityById,
    programIdentityForOpportunity,
    reviewedMappings,
  });
})();
