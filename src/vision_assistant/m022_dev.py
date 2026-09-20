"""M022 development scan set: five long-page tasks with exact oracles.

Frozen contract (docs/M022_EVIDENCE_LEDGER_PLAN.md, development smoke):

- Each task is a static, deterministic "long list" page (~36-45 rows,
  several viewports tall) with three kinds of stories: ``primary`` (main
  subject AI/ML), ``decoy`` (tempting tokens — Standard ML, model railways,
  transformers as electrical gear — but the main subject is clearly not
  AI/ML), and ``plain`` filler.
- The expected selection is derived by trusted code: the three lowest-ranked
  ``primary`` stories. Decoys are ranked above the third primary so a
  misclassification would change the selection. The expected primaries span
  at least two viewports (cross-viewport evidence is required to succeed).
- ``run_checks`` proves determinism (byte-identical builds), oracle teeth
  (mutations rejected), and the viewport-span/decoy design invariants —
  all without a model, browser, or network.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import m022_scan as scan

DEV_VERSION = "m022-dev-v1"

HEADER_H = 90
ROW_H = 64
FOOTER_H = 40
WIDTH = 1280
VIEWPORT_HEIGHT = 720

_FILLER = (
    "Postgres full-text search, five years on",
    "The quiet art of log rotation",
    "A tour of B-tree variants",
    "Why clocks drift",
    "Hand-drawn maps of the London Underground",
    "The economics of bike lanes",
    "Porting a shell to a new CPU",
    "Notes on sourdough hydration",
    "The many lives of the Vim config",
    "Cheap telescopes for city skies",
    "A history of the pencil sharpener",
    "Garden irrigation with drip lines",
    "The case for monorepos",
    "Old keyboards never die",
    "sRGB vs Display P3",
    "Fixing a squeaky door hinge",
    "The lost art of the index card",
    "Lighthouses of the outer banks",
    "A gentle intro to raytracing",
    "Coffee grinders: a field test",
    "The semicolon wars",
    "Mail servers of 1996",
    "Sandboxing with seccomp",
    "The weird world of carriage returns",
    "Ferry timetables as art",
    "A weekend with a ham radio",
    "The physics of skipping stones",
    "Typography for timetables",
    "Baking bread at altitude",
    "The geometry of picture frames",
    "Knots for climbers: a field guide",
    "The forgotten history of the stub nib",
    "A weekend repairing a clock radio",
    "Safer crossings at busy streets",
    "The quiet rise of standing desks",
    "Counting birds from a kitchen window",
    "The world of custom keyboard layouts",
    "Espresso machines for small kitchens",
    "Bicycle touring on gravel roads",
    "The semantics of CSS specificity",
    "Labelling jars without smudging",
    "A gentle introduction to SQLite",
    "The last video rental store",
    "Cold-water swimming clubs",
    "Pruning apple trees in February",
    "The arithmetic of fair tips",
    "Origami cranes at scale",
    "Backyard beekeeping in year one",
    "Tuning a ukulele by ear",
    "The grammar of train announcements",
    "Houseplants that survive office light",
)


def _row(rank: int, title: str, points: int, domain: str, kind: str) -> dict:
    return {"rank": rank, "title": title, "points": points, "domain": domain,
            "kind": kind}


def _titles(rows) -> tuple:
    return tuple(row["title"] for row in rows)


def _assemble(size: int, featured: dict, filler_offset: int) -> tuple:
    """Merge ranked ``featured`` rows with deterministic filler rows."""

    filler_index = filler_offset
    rows = []
    for rank in range(1, size + 1):
        if rank in featured:
            rows.append(featured[rank])
        else:
            rows.append(_row(rank, _FILLER[filler_index % len(_FILLER)],
                             20 + (rank * 7) % 180, "filler.example", "plain"))
            filler_index += 1
    return tuple(rows)


_TASK_1 = _assemble(36, {
    3: _row(3, "AgentBench: evaluating tool-using assistants", 214,
            "agentbench.example", "primary"),
    7: _row(7, "Standard ML turns forty", 154, "pl-history.example", "decoy"),
    12: _row(12, "Model railways of the Swiss Alps", 61,
             "alpsrail.example", "decoy"),
    18: _row(18, "A field guide to on-device speech models", 192,
             "speechguide.example", "primary"),
    27: _row(27, "Open weights and the economics of fine-tuning", 88,
             "tuning.example", "primary"),
}, 0)

_TASK_2 = _assemble(42, {
    2: _row(2, "Vision transformers for tiny devices", 301,
            "tinyvision.example", "primary"),
    5: _row(5, "The AIM alliance and the PowerPC gamble", 198,
            "aimhistory.example", "decoy"),
    9: _row(9, "Neural crest cells and the vertebrate head", 109,
            "crestcells.example", "decoy"),
    16: _row(16, "Transformer oil testing at scale", 77,
             "gridoil.example", "decoy"),
    22: _row(22, "RLHF without the human: a cautionary tale", 145,
             "rlhf.example", "primary"),
    34: _row(34, "AI policy: the licensing debate", 72,
             "policywatch.example", "primary"),
}, 3)

_TASK_3 = _assemble(39, {
    4: _row(4, "Training a chess engine with self-play", 240,
            "selfplay.example", "primary"),
    8: _row(8, "The ML family of languages, revisited", 95,
            "mlfamily.example", "decoy"),
    13: _row(13, "Modeling tides with 19th-century mathematics", 63,
             "tides.example", "decoy"),
    15: _row(15, "Why your phone's dictation still mishears you", 131,
             "dictation.example", "primary"),
    31: _row(31, "Machine learning for materials discovery", 54,
             "materials.example", "primary"),
}, 6)

_TASK_4 = _assemble(45, {
    1: _row(1, "Sparse attention, cheap inference", 412,
            "sparseattn.example", "primary"),
    6: _row(6, "The Antikythera mechanism: a bronze model of the heavens",
            188, "antikythera.example", "decoy"),
    11: _row(11, "Standard ML in production compilers", 121,
             "mlprod.example", "decoy"),
    21: _row(21, "AI safety evaluations: what they miss", 166,
             "evals.example", "primary"),
    29: _row(29, "Robotics foundation models in the warehouse", 98,
             "warehouse.example", "primary"),
    41: _row(41, "A survey of retrieval-augmented pipelines", 37,
             "retrieval.example", "primary"),
}, 9)

_TASK_5 = _assemble(38, {
    3: _row(3, "The Model T and the assembly line", 230,
            "motoring.example", "decoy"),
    6: _row(6, "Evaluating LLM summarizers on legal text", 177,
            "legalsum.example", "primary"),
    10: _row(10, "Neural tube development, revisited", 102,
             "neuraltube.example", "decoy"),
    19: _row(19, "LLVM: a retrospective", 88, "llvm.example", "decoy"),
    24: _row(24, "The AI weather model that beat the forecasters", 119,
             "weather.example", "primary"),
    33: _row(33, "Speech synthesis for endangered languages", 49,
             "speechsos.example", "primary"),
}, 12)


@dataclass(frozen=True)
class DevScanTask:
    id: str
    path: str
    title: str
    rows: tuple = field(default_factory=tuple)

    @property
    def size(self) -> int:
        return len(self.rows)

    @property
    def expected(self) -> tuple:
        """(rank, title) of the three lowest-ranked primary stories."""

        primaries = sorted(
            (row for row in self.rows if row["kind"] == "primary"),
            key=lambda row: row["rank"])
        return tuple((row["rank"], row["title"]) for row in primaries[:3])

    @property
    def decoys(self) -> tuple:
        return tuple(row for row in self.rows if row["kind"] == "decoy")

    @property
    def document_height(self) -> int:
        return HEADER_H + self.size * ROW_H + FOOTER_H

    @property
    def min_observations(self) -> int:
        """Viewport bands the expected primaries must span (>= 2)."""

        return 2

    def row_top(self, rank: int) -> int:
        return HEADER_H + (rank - 1) * ROW_H


DEV_TASKS = (
    DevScanTask("d22-01", "/d22-01/", "The Long List — d22-01", _TASK_1),
    DevScanTask("d22-02", "/d22-02/", "The Long List — d22-02", _TASK_2),
    DevScanTask("d22-03", "/d22-03/", "The Long List — d22-03", _TASK_3),
    DevScanTask("d22-04", "/d22-04/", "The Long List — d22-04", _TASK_4),
    DevScanTask("d22-05", "/d22-05/", "The Long List — d22-05", _TASK_5),
)

DEV_TASKS_BY_ID = {task.id: task for task in DEV_TASKS}


def viewport_bands(document_height: int, viewport_height: int = VIEWPORT_HEIGHT):
    """The traversal's viewport tops for a document (trusted arithmetic)."""

    traversal = scan.ViewportTraversal()
    traversal.begin(scroll_y=0, viewport_height=viewport_height,
                    document_height=document_height, observation_id="obs-1")
    bands = [0]
    index = 2
    while not traversal.complete:
        step = traversal.next_step_px()
        if step is None:
            break
        traversal.advance(scroll_y=traversal.current.scroll_y + step,
                          viewport_height=viewport_height,
                          document_height=document_height,
                          observation_id="obs-{}".format(index))
        bands.append(traversal.current.scroll_y)
        index += 1
    return tuple(bands)


def band_for_row(document_height: int, row_top: int) -> int:
    bands = viewport_bands(document_height)
    for index, start in enumerate(bands):
        if start <= row_top < start + VIEWPORT_HEIGHT:
            return index
    return len(bands) - 1


def _page_html(task: DevScanTask) -> str:
    rows = []
    for row in task.rows:
        rows.append(
            '<div class="row"><span class="rank">{}. </span>'
            "<b>{}</b> <span class=\"dom\">({})</span> "
            '<span class="pts">\u00b7 {} points</span></div>'.format(
                row["rank"], row["title"], row["domain"], row["points"]))
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        "<title>{}</title><style>"
        "body{{margin:0;padding:0;background:#ffffff;color:#111111;"
        "font:20px -apple-system,Helvetica,sans-serif}}"
        "header{{height:{}px;box-sizing:border-box;padding:28px 24px;"
        "background:#f6f6ef;font-size:26px}}"
        ".row{{height:{}px;box-sizing:border-box;padding:16px 24px;"
        "border-bottom:1px solid #eeeeee;overflow:hidden;white-space:nowrap}}"
        ".rank{{display:inline-block;min-width:48px;color:#888888}}"
        ".dom{{color:#2a7f62}}.pts{{color:#666666}}"
        "footer{{height:{}px;box-sizing:border-box;padding:12px 24px;"
        "background:#f6f6ef;color:#666666}}"
        "</style></head><body><header>{}</header>\n{}\n"
        "<footer>\u2014 end of list \u2014</footer></body></html>\n").format(
            task.title, HEADER_H, ROW_H, FOOTER_H, task.title,
            "\n".join(rows))


def build_site(dest) -> dict:
    """Write the five static pages; deterministic and byte-identical."""

    dest = Path(dest)
    files = {}
    for task in DEV_TASKS:
        page = dest / task.id / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        text = _page_html(task)
        page.write_text(text, encoding="utf-8")
        files[str(page.relative_to(dest))] = hashlib.sha256(
            text.encode("utf-8")).hexdigest()
    index = dest / "index.html"
    links = "\n".join('<li><a href="{}/">{}</a></li>'.format(task.id, task.id)
                      for task in DEV_TASKS)
    index.write_text("<!doctype html>\n<html><body><ul>{}</ul></body></html>\n"
                     .format(links), encoding="utf-8")
    files["index.html"] = hashlib.sha256(
        index.read_bytes()).hexdigest()
    tree = hashlib.sha256(
        "\n".join("{} {}".format(name, files[name])
                  for name in sorted(files)).encode("utf-8")).hexdigest()
    return {"files": len(files), "tree_sha256": tree}


def manifest_sha256() -> str:
    payload = [{"id": task.id, "path": task.path, "rows": list(task.rows),
                "expected": list(task.expected)} for task in DEV_TASKS]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_dev_task(task: DevScanTask, report: dict) -> dict:
    """The dev oracle: outcome, exact selection, cross-viewport evidence."""

    failures = []
    if report.get("outcome") != "finished":
        failures.append("outcome: expected 'finished', got {!r}".format(
            report.get("outcome")))
    selection = report.get("selection") or []
    expected = task.expected
    actual_pairs = [(entry.get("rank"), entry.get("title"))
                    for entry in selection]
    expected_norm = [(rank, scan.normalize_title(title))
                     for rank, title in expected]
    actual_norm = [(rank, scan.normalize_title(title or ""))
                   for rank, title in actual_pairs]
    if actual_norm != expected_norm:
        failures.append("selection: expected {}, got {}".format(
            expected_norm, actual_norm))
    observations = {entry.get("observation_id") for entry in selection}
    if len(observations) < task.min_observations:
        failures.append("evidence: selection spans {} observation(s); at "
                        "least {} required".format(len(observations),
                                                   task.min_observations))
    if len(report.get("ledger") or []) < len(expected):
        failures.append("ledger: fewer entries than the expected selection")
    return {"ok": not failures, "task": task.id, "failures": failures}


def run_checks() -> dict:
    """Deterministic freeze checks: builds, design invariants, teeth."""

    problems = []
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        first = build_site(Path(tmp) / "a")
        second = build_site(Path(tmp) / "b")
        if first != second:
            problems.append("fixture build is not byte-identical")
    per_task = {}
    for task in DEV_TASKS:
        bands = viewport_bands(task.document_height)
        expected_rows = [row for row in task.rows
                         if (row["rank"], row["title"]) in task.expected]
        spans = {band_for_row(task.document_height, task.row_top(row["rank"]))
                 for row in expected_rows}
        decoy_min = min((row["rank"] for row in task.decoys), default=None)
        third_primary = task.expected[-1][0]
        task_problems = []
        if len(task.expected) != 3:
            task_problems.append("expected selection is not three primaries")
        if len(spans) < task.min_observations:
            task_problems.append("expected primaries do not span viewports")
        if decoy_min is None or decoy_min >= third_primary:
            task_problems.append("decoys are not ranked above the third primary")
        if task.document_height < 2 * VIEWPORT_HEIGHT:
            task_problems.append("page is not multi-viewport")
        if len(bands) > scan.MAX_VIEWPORTS:
            task_problems.append("page needs more than {} viewports".format(
                scan.MAX_VIEWPORTS))
        if 2 * len(bands) + 1 > scan.MAX_CALLS:
            task_problems.append("expected calls exceed the call budget")
        per_task[task.id] = {"bands": len(bands), "span": len(spans),
                             "document_height": task.document_height,
                             "expected": [rank for rank, _ in task.expected],
                             "problems": task_problems}
        problems.extend("{}: {}".format(task.id, item)
                        for item in task_problems)
    good = {
        "outcome": "finished",
        "selection": [{"rank": rank, "title": title,
                       "observation_id": "obs-{}".format(1 if rank < 20 else 2)}
                      for rank, title in DEV_TASKS[0].expected],
        "ledger": [1] * len(DEV_TASKS[0].expected),
    }
    if not verify_dev_task(DEV_TASKS[0], good)["ok"]:
        problems.append("oracle rejects the correct selection")
    mutations = [
        ({**good, "selection": good["selection"][:2]}, "missing story"),
        ({**good, "selection": [dict(good["selection"][0], rank=2)]
          + good["selection"][1:]}, "wrong rank"),
        ({**good, "selection": [dict(good["selection"][0], title="Other")]
          + good["selection"][1:]}, "wrong title"),
        ({**good, "selection": good["selection"]
          + [dict(good["selection"][0], rank=99)]}, "extra story"),
        ({**good, "selection": [dict(entry, observation_id="obs-1")
                                for entry in good["selection"]]},
         "evidence collapsed to one observation"),
        ({**good, "selection": [dict(entry, observation_id=None)
                                for entry in good["selection"]]},
         "missing evidence ids"),
        ({**good, "outcome": "stopped"}, "wrong outcome"),
    ]
    for payload, label in mutations:
        if verify_dev_task(DEV_TASKS[0], payload)["ok"]:
            problems.append("oracle accepts mutation: {}".format(label))
    return {
        "ok": not problems,
        "version": DEV_VERSION,
        "tasks": len(DEV_TASKS),
        "manifest_sha256": manifest_sha256(),
        "per_task": per_task,
        "problems": problems,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "m022dev"

    def do_GET(self):  # noqa: N802 - stdlib handler API
        site = self.server.site_dir
        rel = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        candidate = (site / rel).resolve()
        try:
            candidate.relative_to(site.resolve())
        except ValueError:
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silence request logging
        return


class DevSiteServer:
    """Loopback-only static server for the generated dev pages."""

    def __init__(self, site_dir) -> None:
        self.site_dir = Path(site_dir).resolve()
        self._httpd = None
        self._thread = None

    def start(self, port: int = 0) -> int:
        handler = _Handler
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self._httpd.site_dir = self.site_dir
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self._httpd.server_address[1]

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
