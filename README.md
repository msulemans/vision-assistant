# Local Vision Assistant Lab

Build a private assistant that can look at a selected screenshot, accept a
question, and explain what is visible:

```text
selected screen/window -> privacy boundary -> normalized image
                       -> local vision model + question -> grounded answer
```

Later, after the observation path is measured and trustworthy, extend it into
a supervised computer-use loop:

```text
observe -> propose typed action -> policy + user approval -> execute -> observe
```

This is both a product project and a learning lab. Every capability must have a
lesson, deterministic evidence, a labelled real-device measurement, and an
honest failure record.

## Direct answer

The correct first product is **screenshot question answering**, not an
autonomous mouse agent. We will first prove that capture is explicit, private,
fast, and accurate on frozen UI/error screenshots. Action support comes later
through typed, policy-checked operations with visible approval and an emergency
stop.

The reference machine is an Apple M2 Max MacBook Pro with 32 GB unified memory.
The initial model hypothesis is a quantized 4B-class multimodal model. A 9B
candidate is a quality control only if the smaller option misses the frozen
accuracy gate. No model is promoted from parameter count or public benchmarks.

## Product promise

The first useful capstone should answer questions such as:

- "Why is this application failing?" from a terminal or error dialog.
- "What should I click next?" from a settings or setup screen.
- "Which field is invalid?" from a form with visible validation feedback.
- "What changed between these two screens?" from before/after captures.
- "Summarize the important status on this dashboard."

An answer must distinguish visible evidence from inference. If the screenshot
does not contain enough evidence, the assistant should say so and ask for a
more useful capture instead of inventing a cause.

## Project rules

- Local inference is the product path. Hosted inference may be a labelled
  comparison only.
- Capture is user-initiated and visibly scoped to a chosen window, region, or
  display.
- Screenshots are ephemeral by default and never committed.
- Do not capture hidden windows, background apps, or a full display when a
  smaller selection is sufficient.
- Logs store metrics and redacted metadata, not raw pixels or sensitive text by
  default.
- The model may describe or propose an action; trusted code owns validation,
  policy, confirmation, execution, budgets, and stop reasons.
- No raw shell tool and no unrestricted mouse/keyboard interface is exposed to
  a model.
- Prefer Accessibility element identities to pixel coordinates. Coordinate
  actions are a later, riskier fallback.
- Preserve failed runs and negative model comparisons.
- Implement and verify exactly one milestone at a time.
- Do not download a model or install a dependency until the bake-off is frozen.

## Where to start

1. Read [VISION_STATE.md](VISION_STATE.md), the canonical project record.
2. Read [docs/MILESTONES.md](docs/MILESTONES.md); only the current milestone may
   be implemented.
3. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
   [docs/METRICS.md](docs/METRICS.md).
4. Use [learning/CURRICULUM.md](learning/CURRICULUM.md) to learn the system in
   the same order it is built.
5. Run the read-only inventory:

   ```bash
   ./scripts/check_environment.sh
   ```

## Current status

Milestone 001 is complete: the learning contract,
architecture boundary, metrics, research baseline, host inventory, privacy
rules, and end-to-end roadmap are recorded. No model, dependency, screenshot,
or permission was acquired. The repository is initialized on `main`.

Milestone 002 is next: a deterministic event spine, fake capture/model ports,
and a small browser UI using synthetic fixtures only.
