#!/usr/bin/env node
// Deliberate pre-Phase-4B lock. This module must not import the search harness,
// read the sealed query frame, or produce candidate output before a separately
// authorized Phase 4B replaces this lock with a one-time executor.

throw new Error(
  "Iteration-2 holdout is sealed and has never been executed. Phase 4B is not authorized in this session.",
);
