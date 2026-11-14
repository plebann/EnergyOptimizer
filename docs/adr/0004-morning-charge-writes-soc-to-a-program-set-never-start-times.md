# Morning Charge writes SOC to a Morning Charge Program Set and never moves a program start time

Morning Charge used to move Program 2's start time to the Night Buy Window start and write its temporary SOC to Program 2 only. With the Night Buy Window now allowed anywhere in 22:00-06:00, the window can begin while Program 6 or Program 1 is active, so a Program 2 target alone does not hold for the whole window, and moving a start time changes the user's own program layout and was never undone at completion. We decided that Morning Charge reads the program start times, selects the Morning Charge Program Set (every program whose active interval overlaps the Night Buy Window from the later of the decision time and the window start), writes the same target SOC to each, and never writes a start time. Morning Charge Completion returns each program to its Normal SOC Target, the value it held before Morning Charge changed it, recorded per program in the persisted completion plan; the first record for a window is kept when Morning Charge runs again in that window.

## Considered Options

- Keep moving Program 2's start time to the window start: rejected — it cannot cover a window that begins in an earlier program, and it silently rewrites the user's program times.
- Restore every program to `min_soc` at completion: rejected — Evening Behavior legitimately leaves different values per program (for example `min_soc - 4` on Program 2), and a fixed value would overwrite them.

## Consequences

- Program 2 after completion returns to what Evening Behavior left, not always to `min_soc`; the CONTEXT.md term "Program 2 Normal SOC Target" became "Normal SOC Target".
- The write is transactional across the set (a failed write rolls back the programs already written); completion is not — each program is restored independently and only failed ones are retried after five minutes.
- The persisted completion plan carries an entity-to-Normal-SOC-Target list. A plan in the old format, without that list, is completed the old way: Program 2 to `min_soc`.
- Start times of Programs 6, 1 and 2 must all be readable, or the run fails with `charge_failed` and writes nothing.
- A program that already holds the target when Morning Charge runs, with no record for the window, has no earlier value to return to, so completion returns it to `min_soc` as before; nothing is scheduled when that equals the target.
