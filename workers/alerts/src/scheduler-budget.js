export const DEFAULT_SCHEDULER_TIMEOUT_MS = 10 * 60_000;
export const MAX_SCHEDULER_TIMEOUT_MS = 12 * 60_000;
export const FINALIZATION_RESERVE_MS = 15_000;

export class SchedulerTimeoutError extends Error {
  constructor(stage) {
    super(`Alert scheduler stage timed out: ${stage}`);
    this.name = "SchedulerTimeoutError";
    this.code = "scheduler_deadline_exceeded";
    this.stage = stage;
  }
}

export class SchedulerBudget {
  constructor({ timeoutMs, clock = () => Date.now(), setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
    this.clock = clock;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.startedAt = clock();
    this.timeoutMs = Math.max(1, Math.min(
      MAX_SCHEDULER_TIMEOUT_MS,
      Number(timeoutMs) || DEFAULT_SCHEDULER_TIMEOUT_MS,
    ));
    this.deadlineAt = this.startedAt + this.timeoutMs;
  }

  remainingMs({ reserveFinalization = true } = {}) {
    const reserve = reserveFinalization
      ? Math.min(FINALIZATION_RESERVE_MS, Math.floor(this.timeoutMs / 4))
      : 0;
    return Math.max(0, this.deadlineAt - this.clock() - reserve);
  }

  async run(stage, operation, maximumMs = null, options = {}) {
    const remaining = this.remainingMs(options);
    const timeoutMs = Math.max(0, Math.min(
      remaining,
      Number(maximumMs) > 0 ? Number(maximumMs) : remaining,
    ));
    if (!timeoutMs) throw new SchedulerTimeoutError(stage);
    let timer;
    try {
      return await Promise.race([
        Promise.resolve().then(operation),
        new Promise((_, reject) => {
          timer = this.setTimer(() => reject(new SchedulerTimeoutError(stage)), timeoutMs);
        }),
      ]);
    } finally {
      if (timer !== undefined) this.clearTimer(timer);
    }
  }
}

export async function boundedFinalization(operation, timeoutMs = FINALIZATION_RESERVE_MS) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(operation),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new SchedulerTimeoutError("finalization")), timeoutMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
