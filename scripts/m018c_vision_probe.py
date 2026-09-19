"""Scratch diagnostic: does the model actually see the loop's screenshot?

One model call, no task budget consumed. Prints the scaled image dimensions,
the first part of the served prompt, and the model's description of the page.
"""

import json
import tempfile
import time
from pathlib import Path

from vision_assistant import browser_fixtures as fixtures
from vision_assistant.browser_agent import build_loop_prompt
from vision_assistant.browser_session import BrowserSession, compile_helper
from vision_assistant.fixture_server import FixtureServer
from vision_assistant.pixels import fit_for_model
from vision_assistant.runtime_llamaserver import LlamaServerAdapter

REPO = Path(__file__).resolve().parents[1]
PIN = REPO / "models" / "qwen3.5-4b"

tmp = Path(tempfile.mkdtemp(prefix="m018c-probe-"))
site = tmp / "site"
fixtures.build_site("dev", site)
server = FixtureServer("dev", site)
port = server.start()

session = BrowserSession(port=port, helper_bin=compile_helper(),
                         snapshot_dir=tmp / "shots")
session.launch()
url = session.navigate("/search/")
time.sleep(0.8)
shot = session.snapshot()
full = Path(shot.path).read_bytes()
scaled = fit_for_model(full)
probe_shot = tmp / "scaled.png"
probe_shot.write_bytes(scaled)
print("full :", len(full), "bytes,", shot.width, "x", shot.height,
      "scale", shot.scale)
import struct
w = int.from_bytes(scaled[16:20], "big")
h = int.from_bytes(scaled[20:24], "big")
print("model:", len(scaled), "bytes,", w, "x", h)
print("kept:", probe_shot)

pin = json.loads((PIN / "pin.json").read_text())
model = next(f for f in pin["files"] if f["role"] == "model")
mmproj = next(f for f in pin["files"] if f["role"] == "mmproj")
adapter = LlamaServerAdapter(PIN / model["name"], PIN / mmproj["name"],
                             ctx_size=4096, jinja=True,
                             chat_template_kwargs={"enable_thinking": False},
                             log_path=tmp / "server.log")
adapter.start()
try:
    question = ('You are looking at one screenshot of a web page. '
                'Describe briefly: what page is it, and where is the search '
                'input box? Reply as JSON {"page": "...", "input": "..."}.')
    answer, timings = adapter.predict_image(
        scaled, question,
        json_schema={"type": "object",
                     "properties": {"page": {"type": "string"},
                                    "input": {"type": "string"}},
                     "required": ["page", "input"]})
    text = " ".join((*answer.visible, *answer.inferred, *answer.unknown))
    print("first_ms:", timings.get("first_token_ms"), "complete_ms:",
          timings.get("complete_ms"))
    print("model says:", text[:600])
finally:
    adapter.stop()
    session.stop()
    server.stop()
print("done")
