"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const layers = {
  pixels: {
    overlay: "VISIBLE · password field has a red border\nVISIBLE · “Password is required” appears below it",
    caption: "Pixels show the dialog, fields, warning colour, and labels. They do not prove why the database rejected a connection.",
    className: "",
  },
  metadata: {
    overlay: "TRUSTED · PNG · 480 × 300\nTRUSTED · private mode 0600\nTRUSTED · deleted after release",
    caption: "Trusted code owns dimensions, format, digest, timing, and lifecycle. Paths and raw pixels stay out of the trace.",
    className: "metadata-view",
  },
  reasoning: {
    overlay: "INFERRED · a password may be needed before connection\nRULE · label this as inference, not visible fact",
    caption: "A model can suggest a cause, but the answer policy must separate that suggestion from facts directly visible in the screen.",
    className: "reasoning-view",
  },
  unknown: {
    overlay: "UNKNOWN · whether PostgreSQL is running\nUNKNOWN · whether credentials are correct\nNEXT · ask for terminal/service evidence",
    caption: "A useful assistant knows what the screenshot cannot establish and asks for the next bounded piece of evidence.",
    className: "unknown-view",
  },
};

function showLayer(name) {
  const layer = layers[name];
  const specimen = $("#screenSpecimen");
  specimen.className = `screen-specimen ${layer.className}`.trim();
  $("#evidenceOverlay").textContent = layer.overlay;
  $("#layerCaption").textContent = layer.caption;
  $$("[data-layer]").forEach((button) => button.classList.toggle("active", button.dataset.layer === name));
}
$$('[data-layer]').forEach((button) => button.addEventListener("click", () => showLayer(button.dataset.layer)));
showLayer("pixels");

const stages = {
  select: ["The user chooses the boundary", "A region or window is safer than a whole display. No background window or hidden app should enter the turn by accident.", "User gesture", "Not captured", "Scope must be explicit"],
  validate: ["Trusted code proves the container", "Milestone 003 checks PNG structure, CRCs, dimensions, decompressed size, filters, and limits before another decoder touches it.", "PNG normalizer", "Bounded bytes", "Reject malformed or oversized input"],
  store: ["The screenshot enters a private room", "A 0700 directory holds one 0600 normalized artifact. Symlink escapes are rejected. Retention is opt-in.", "Artifact store", "Ephemeral local file", "No path or pixels in trace"],
  model: ["A local model will observe—not control", "The VisionModelPort will receive the internal artifact reference. No real VLM is acquired until the frozen M004 corpus exists.", "VisionModelPort", "Image + bounded question", "Model remains untrusted"],
  policy: ["The answer is split by evidence strength", "Visible facts, inference, and unknowns are different output sections. A plausible diagnosis unsupported by the screen is still a failure.", "AnswerPolicy", "Labelled statements", "Unsupported claims must fall"],
  release: ["Custody ends explicitly", "The capture CLI deletes its artifact even if writing the summary fails, unless retention was deliberately requested. Tests prove cleanup on output failure and explicit retention.", "Artifact store", "Deleted by default", "No silent screenshot history"],
};

$$('[data-stage]').forEach((button) => button.addEventListener("click", () => {
  const [title, body, owner, data, gate] = stages[button.dataset.stage];
  $$("[data-stage]").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
  $("#stageTitle").textContent = title;
  $("#stageBody").textContent = body;
  $("#stageOwner").textContent = owner;
  $("#stageData").textContent = data;
  $("#stageGate").textContent = gate;
}));

const scenarios = {
  success: {
    file: "m002-success.jsonl", terminal: "turn.completed", lesson: "Eleven ordered events end in one final completed state.",
    events: ["turn.started", "capture.requested", "capture.frame_ready", "model.started", "model.first_token", "model.token ×4", "answer.ready", "turn.completed"],
  },
  failure: {
    file: "m002-failure.jsonl", terminal: "turn.failed", lesson: "Capture failure terminates after three events. No model or answer event follows.",
    events: ["turn.started", "capture.requested", "turn.failed"],
  },
  cancel: {
    file: "m002-cancel.jsonl", terminal: "turn.cancelled", lesson: "Cancellation is final. Every later model and UI-success event is suppressed.",
    events: ["turn.started", "capture.requested", "turn.cancelled"],
  },
  timeout: {
    file: "m002-timeout.jsonl", terminal: "turn.timed_out", lesson: "The absolute budget ends the turn deterministically; timeout is not called cancellation.",
    events: ["turn.started", "capture.requested", "capture.frame_ready", "model.started", "turn.timed_out"],
  },
};
let traceTimer = null;

function renderScenario(name, play = false) {
  if (traceTimer) window.clearInterval(traceTimer);
  const scenario = scenarios[name];
  $("#traceName").textContent = scenario.file;
  $("#traceTerminal").textContent = scenario.terminal;
  $("#traceLesson").textContent = scenario.lesson;
  $$("[data-scenario]").forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.scenario === name)));
  const list = $("#traceEvents");
  list.replaceChildren(...scenario.events.map((event, index) => {
    const item = document.createElement("li");
    item.innerHTML = `<span>${String(index + 1).padStart(2, "0")}</span><b>${event.split(".")[0]}</b><span>${event}</span>`;
    return item;
  }));
  const items = $$("li", list);
  if (!play) { items.forEach((item) => item.classList.add("visible")); return; }
  let index = 0;
  traceTimer = window.setInterval(() => {
    items[index]?.classList.add("visible");
    index += 1;
    if (index >= items.length) window.clearInterval(traceTimer);
  }, 240);
}
$$('[data-scenario]').forEach((tab) => tab.addEventListener("click", () => renderScenario(tab.dataset.scenario)));
$("#playTrace").addEventListener("click", () => renderScenario($("[data-scenario][aria-selected='true']").dataset.scenario, true));
renderScenario("success");

const milestones = [
  { id: 1, phase: 1, status: "done", title: "Project contract, research, and environment", build: "Freeze the privacy boundary, host evidence, metrics, architecture, curriculum, and roadmap.", gate: "No model, package, capture, or permission acquired." },
  { id: 2, phase: 1, status: "done", title: "Deterministic event spine and browser shell", build: "Build fake capture/model ports, exact event states, traces, cancellation, timeout, and a synthetic UI.", gate: "Success, failure, cancel, and timeout are byte-identical and round-trip." },
  { id: 3, phase: 1, status: "done", title: "Explicit screenshot ingest and capture", build: "Build file ingest, user-triggered selection, bounded PNG normalization, and an ephemeral artifact lifecycle.", gate: "Generated fixture, selected file, and two user-selected regions pass and are deleted by default." },
  { id: 4, phase: 1, status: "done", title: "Frozen screen-understanding corpus", build: "Create 48 cases: 24 development and 24 held-out, covering eight categories; verify the scorer with hand-authored answers.", gate: "Manifest, splits, prompt, numerical quality/resource targets, and scoring are frozen before model output or downloads." },
  { id: 5, phase: 1, status: "done", title: "Local VLM and runtime bake-off", build: "Prove one 4B/runtime baseline, then compare sequentially: at most three configurations plus one justified ≤9B control.", gate: "Real timing, private traces, cancellation, and cleanup precede inference; promote only after frozen held-out and resource gates pass." },
  { id: 6, phase: 1, status: "done", title: "One-shot local Vision Assistant", build: "Deliver preview/retake, explicit submit, local answer, stop, retry, and reset with real timing and honest evidence labels.", gate: "Usable local demo: capstone smoke tests plus frozen quality/latency gates, offline operation, and no persistent private content." },
  { id: 7, phase: 2, status: "done", title: "Evidence augmentation and focused re-observation", build: "Measure OCR, Accessibility facts, crop, zoom, and a bounded second look.", gate: "Augmentation improves the difficult subset without widening privacy or hallucination." },
  { id: 8, phase: 2, status: "done", title: "Multi-turn visual conversation", build: "Add bounded follow-ups, current-capture identity, reset, and stale-image warnings.", gate: "Reference and correction tasks pass without cross-session screenshots." },
  { id: 9, phase: 2, status: "current", title: "Usable capture and answer UI", build: "Add picker, preview, redact, retake, status, copy, and a failure explorer.", gate: "A new user completes five read-only capstones without terminal help; choose optional actions or proceed to read-only packaging." },
  { id: 10, phase: 3, status: "future", title: "Typed action intents and policy—no execution", build: "Define observe, click, type, key, scroll, cancel, finish, target preview, and consequence policy.", gate: "Adversarial proposals cannot bypass schema, scope, approval, or budget." },
  { id: 11, phase: 3, status: "future", title: "Disposable simulated action loop", build: "Run observe, propose, approve, fake execute, verify, retry, and stop in a practice app.", gate: "Tasks finish within budgets with zero host input events." },
  { id: 12, phase: 3, status: "future", title: "Read-only macOS UI grounding", build: "Align screenshot regions with Accessibility element roles, names, states, and identities.", gate: "Target identity passes across scaling and layout variants with no posted input." },
  { id: 13, phase: 3, status: "future", title: "Supervised mouse and keyboard execution", build: "Add opt-in Accessibility execution, visible target overlay, confirmation, stop, and observation.", gate: "Zero wrong-target, secret-field, approval-bypass, or stale-frame actions." },
  { id: 14, phase: 3, status: "future", title: "Recovery and bounded task agent", build: "Add step/time budgets, takeover, focus-change detection, recovery, blocked, and finished states.", gate: "Unexpected dialogs and prompt injection cause a safe stop or recovery." },
  { id: 15, phase: 4, status: "future", title: "Profiles, packaging, and offline verification", build: "Package only measured passing profiles after M009; M014 is required only for action-enabled packaging.", gate: "A clean Mac reproduces read-only operation fully offline." },
  { id: 16, phase: 4, status: "future", title: "Evaluation and reciprocal learning field manual", build: "Consolidate the failure explorer, comparisons, quizzes, and reproduction material maintained at every milestone.", gate: "A new learner can explain, measure, modify, and safely reproduce the system." },
  { id: 17, phase: 4, status: "future", title: "Public beta hardening", build: "Audit privacy, redaction, malicious screen text, supply chain, recovery, accessibility, and signing.", gate: "Zero critical safety failures and verified rollback/removal." },
];

const phaseNames = { 1: "SEE ONE IMAGE RELIABLY", 2: "UNDERSTAND A LIVE UI", 3: "PROPOSE BEFORE ACTING", 4: "FINISH THE LOCAL PRODUCT" };
const map = $("#milestoneMap");
milestones.forEach((milestone) => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `milestone-dot ${milestone.status}`;
  button.dataset.milestone = String(milestone.id);
  button.dataset.phase = String(milestone.phase);
  button.textContent = String(milestone.id).padStart(2, "0");
  button.setAttribute("aria-label", `Milestone ${milestone.id}: ${milestone.title}`);
  map.append(button);
});

function showMilestone(id) {
  const item = milestones.find((milestone) => milestone.id === Number(id));
  $("#milestoneStatus").textContent = item.status === "done" ? "COMPLETE" : item.status === "current" ? "IN PROGRESS" : "PLANNED";
  $("#milestoneStatus").style.background = item.status === "done" ? "var(--green)" : item.status === "current" ? "var(--blue)" : "var(--muted)";
  $("#milestonePhase").textContent = `PHASE ${item.phase} · ${phaseNames[item.phase]}`;
  $("#milestoneTitle").textContent = `${String(item.id).padStart(3, "0")} · ${item.title}`;
  $("#milestoneBuild").textContent = item.build;
  $("#milestoneGate").textContent = item.gate;
}
map.addEventListener("click", (event) => {
  const button = event.target.closest("[data-milestone]");
  if (button) showMilestone(button.dataset.milestone);
});
$$('[data-phase]').forEach((button) => button.addEventListener("click", () => {
  const phase = button.dataset.phase;
  $$(".phase-filter button").forEach((candidate) => candidate.classList.toggle("active", candidate === button));
  $$(".milestone-dot").forEach((dot) => dot.classList.toggle("hidden", phase !== "all" && dot.dataset.phase !== phase));
}));

const flashcards = [
  ["Why build a fake visual turn first?", "It isolates state, cancellation, failure, trace, and UI bugs before a real model can hide them."],
  ["What does ephemeral mean?", "The artifact exists only while needed, is private while present, and has a tested deletion path."],
  ["Visible or inferred: “the database is stopped”?", "Inferred. A connection error may suggest it, but the screenshot must show service state to make it visible evidence."],
  ["Why not download the 9B model now?", "The frozen corpus and promotion rule do not exist yet. Size is not evidence of product fit."],
  ["Who is allowed to click later?", "Trusted typed execution after policy and user approval—not the vision model itself."],
];
let flashIndex = 0;
function renderCard() {
  $("#flashFront").textContent = flashcards[flashIndex][0];
  $("#flashBack").textContent = flashcards[flashIndex][1];
  $("#cardCount").textContent = `${flashIndex + 1} / ${flashcards.length}`;
  $("#flashcard").classList.remove("flipped");
}
$("#flashcard").addEventListener("click", () => $("#flashcard").classList.toggle("flipped"));
$("#nextCard").addEventListener("click", () => { flashIndex = (flashIndex + 1) % flashcards.length; renderCard(); });
renderCard();

$("#glossarySearch").addEventListener("input", (event) => {
  const query = event.target.value.trim().toLowerCase();
  $$("#glossary > div").forEach((entry) => { entry.hidden = !entry.textContent.toLowerCase().includes(query); });
});

$("#quiz").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const answers = [data.get("q1") === "user", data.get("q2") === "no", data.get("q3") === "m013"];
  const score = answers.filter(Boolean).length;
  const output = $("#quizResult");
  output.textContent = score === 3 ? "3 / 3 — you can explain the trust boundary." : `${score} / 3 — revisit capture scope, retention, and the action roadmap.`;
  output.style.color = score === 3 ? "var(--green)" : "var(--coral)";
});

$("#copyCommand").addEventListener("click", async () => {
  const command = $("#captureCommand").textContent;
  try {
    await navigator.clipboard.writeText(command);
    $("#copyStatus").textContent = "Copied. Run it from the project root in a normal Terminal.";
  } catch (_) {
    $("#copyStatus").textContent = "Copy was unavailable. Select the command text manually.";
  }
});

const notesToggle = $("#notesToggle");
notesToggle.addEventListener("click", () => {
  const active = document.body.classList.toggle("show-notes");
  notesToggle.setAttribute("aria-pressed", String(active));
  notesToggle.textContent = active ? "Hide deeper notes" : "Deeper notes";
});

const trackedSections = $$("[data-track]");
$("#resumeButton").addEventListener("click", () => {
  const id = localStorage.getItem("visionLab.lastSection") || "anatomy";
  ($(`#${id}`) || $("#anatomy")).scrollIntoView();
});
window.addEventListener("scroll", () => {
  let current = "top";
  trackedSections.forEach((section) => { if (section.getBoundingClientRect().top <= 130) current = section.id || section.dataset.track; });
  localStorage.setItem("visionLab.lastSection", current);
}, { passive: true });
