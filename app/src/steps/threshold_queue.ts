// Threshold updates while a carving run is under way (UX 5.5, 6.4). The engine checks for cancel only between stages, so
// cancelling a one-stage carving run saves nothing: the run in progress is left to end, values that arrive meanwhile replace
// each other, and exactly one more run follows with the last of them.

export interface ThresholdUpdateQueue {
  /** Applies *value* and runs the carving now, or after the run in progress when there is one. */
  submit: (value: number) => void;
  /** A run is in progress or a value waits for one. */
  busy: () => boolean;
}

interface Submission {
  value: number;
  serial: number;     // counts the values submitted
}

/**
 * At most one *applyAndRun* at a time. *applyAndRun* saves the value, starts the carving run and resolves at the run's last
 * event; it reports its own failures, and a rejection only ends that call, so a value waiting behind it still runs.
 * *isSuperseded* tells, at any time, whether a value has been submitted since this one: the user has left this value, so the
 * results of its run are not the ones to show.
 */
export function createThresholdUpdateQueue(applyAndRun: (value: number, isSuperseded: () => boolean) => Promise<void>): ThresholdUpdateQueue {
  let running = false;
  let waiting: Submission | null = null;
  let submissionCount = 0;

  const run = async ({ value, serial }: Submission): Promise<void> => {
    running = true;
    try {
      await applyAndRun(value, () => submissionCount > serial);
    } catch {
      // applyAndRun has shown what went wrong; the next value still gets its run
    } finally {
      running = false;
    }
    if (waiting !== null) {
      const next = waiting;
      waiting = null;
      void run(next);
    }
  };

  return {
    submit: (value) => {
      const submission = { value, serial: ++submissionCount };
      if (running) waiting = submission;
      else void run(submission);
    },
    busy: () => running || waiting !== null,
  };
}
