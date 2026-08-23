#!/usr/bin/env node

throw new Error(
  "Iteration-3 Phase-4C holdout is sealed and has never been executed. "
  + "This development runner intentionally cannot load or score it. "
  + "A separately authorized Phase-4C session must replace this lock with a single-use runner.",
);
