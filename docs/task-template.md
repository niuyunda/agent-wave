---
# Required for agvv: machine-friendly id [A-Za-z0-9._-]
name: example-task

# Optional YAML (any extra keys are kept by agvv)
# title: "…"
# links:
#   issue: "…"
---

## Acceptance criteria

- [ ] Each item is **checkable** (a test, a command, or an observable behavior— not vague “works better”).
- [ ] **Out of scope** is implied by what you omit; only list what must be true to call the task done.

## Testing / verification

- **Commands** the implementer should run (or the exact manual steps if there is no test runner).
- **Pass bar**: e.g. “exit 0”, “no new failures in suite X”, “manual checklist A–C”.
- If the repo has a standard test command (unittest, pytest, etc.), name it—don’t assume the agent will guess.

## Definition of done

- [ ] Acceptance criteria satisfied without scope creep.
- [ ] Tests or agreed verification completed; failures explained or fixed.
- [ ] No drive-by refactors unrelated to the task (unless this task is explicitly a refactor).

---

## Optional context

Use only if it helps; **do not** treat the following as a rigid template. One short paragraph or bullets is enough.

- What problem or change (bug, feature, constraint).
- Pointers: paths, modules, prior art—**only** if you already know them; leave room for the agent to explore otherwise.
