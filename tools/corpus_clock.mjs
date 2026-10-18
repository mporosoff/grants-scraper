// Historical recovery evaluates archived runtime bytes at their authenticated
// vector generation instant. It must never fall back to the verifier's clock.
export function corpusDateClass(stamp) {
  const instant = Date.parse(String(stamp || ""));
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(String(stamp || ""))
    || !Number.isFinite(instant)) {
    throw new Error("A valid authenticated corpus timestamp is required.");
  }
  return class CorpusDate extends Date {
    constructor(...args) { super(...(args.length ? args : [instant])); }
    static now() { return instant; }
  };
}
