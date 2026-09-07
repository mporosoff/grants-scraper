import {readFileSync} from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../../assets/submission-schedule.js", import.meta.url), "utf8");

// Focused browser contracts extract actual application functions. Include the
// new shared dependency rather than stubbing selection or changing assertions.
export function installSubmissionSchedule(context, app, asOf = "2026-09-07") {
  if (!vm.isContext(context)) vm.createContext(context);
  context.runtimeDateIso ||= () => asOf;
  vm.runInContext(source, context);
  for (const name of ["nextSubmission", "nextSubmissionDate"]) {
    const start = app.indexOf(`  function ${name}(`);
    if (start >= 0) vm.runInContext(app.slice(start, app.indexOf("\n  }", start) + 4), context);
  }
}
