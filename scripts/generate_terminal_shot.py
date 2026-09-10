"""Generate terminal dashboard screenshot using Rich HTML export and Edge headless."""

import io
import subprocess
from pathlib import Path

from rich.console import Console

from canarymesh.config import CanaryMeshConfig, UpstreamConfig
from canarymesh.controller.rollback_guard import RollbackGuard
from canarymesh.controller.rollout_engine import RolloutEngine
from canarymesh.proxy.router import TrafficRouter
from canarymesh.proxy.stats import TelemetryManager
from canarymesh.tui.widgets import build_dashboard_layout

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUT_FILE = Path(r"C:\Users\alexander\.gemini\antigravity-ide\scratch\canarymesh\docs\images\terminal_dashboard.png")

# Setup simulated state
cfg = CanaryMeshConfig(
    stable=UpstreamConfig(name="stable", url="http://127.0.0.1:8081"),
    canary=UpstreamConfig(name="canary", url="http://127.0.0.1:8082"),
    initial_canary_weight=20.0,
)
router = TrafficRouter(cfg)
telemetry = TelemetryManager(window_size_seconds=60)
guard = RollbackGuard(router=router, telemetry=telemetry, sla=cfg.sla)
rollout = RolloutEngine(router=router, guard=guard)

# Feed some realistic telemetry
for _ in range(85):
    telemetry.record("stable", 200, 18.5)
for _ in range(3):
    telemetry.record("stable", 404, 12.1)

for _ in range(22):
    telemetry.record("canary", 200, 32.4)
telemetry.record("canary", 500, 95.0)

# Build layout and export HTML
output_buffer = io.StringIO()
console = Console(record=True, file=output_buffer, width=130, height=38, force_terminal=True)
layout = build_dashboard_layout(
    {"proxy_port": 8080, "control_port": 8090, "stable": cfg.stable.model_dump(), "canary": cfg.canary.model_dump()},
    router,
    telemetry,
    guard,
    rollout,
)
console.print(layout)
html_body = console.export_html(inline_styles=True)

# Wrap in a terminal window frame
html_wrapped = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      background: #0d1117;
      margin: 0;
      padding: 24px;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      font-family: 'Consolas', 'Courier New', monospace;
    }}
    .terminal-window {{
      background: #161b22;
      border-radius: 12px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.1);
      overflow: hidden;
      width: 1100px;
    }}
    .terminal-header {{
      background: #21262d;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      gap: 8px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .btn {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
      display: inline-block;
    }}
    .btn-red {{ background: #ff5f56; }}
    .btn-yellow {{ background: #ffbd2e; }}
    .btn-green {{ background: #27c93f; }}
    .terminal-title {{
      color: #8b949e;
      font-size: 13px;
      margin-left: 8px;
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    }}
    .terminal-body {{
      padding: 16px 20px;
      overflow: hidden;
    }}
    pre {{
      margin: 0 !important;
      line-height: 1.25 !important;
      font-size: 13px !important;
    }}
  </style>
</head>
<body>
  <div class="terminal-window">
    <div class="terminal-header">
      <span class="btn btn-red"></span>
      <span class="btn btn-yellow"></span>
      <span class="btn btn-green"></span>
      <span class="terminal-title">canarymesh — split-screen live dashboard</span>
    </div>
    <div class="terminal-body">
      {html_body}
    </div>
  </div>
</body>
</html>"""

temp_html = Path(r"C:\Users\alexander\.gemini\antigravity-ide\scratch\canarymesh\docs\images\temp_term.html")
temp_html.write_text(html_wrapped, encoding="utf-8")

cmd = [
    EDGE_PATH,
    "--headless=new",
    "--window-size=1200,900",
    "--default-background-color=0d1117",
    f"--screenshot={OUT_FILE.resolve()}",
    temp_html.resolve().as_uri(),
]
subprocess.run(cmd, check=True)
temp_html.unlink(missing_ok=True)
print(f"Generated terminal dashboard: {OUT_FILE.exists()} ({OUT_FILE.stat().st_size} bytes)")
