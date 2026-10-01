"""Generate pixel-perfect Web Operations Console screenshot using local HTML rendering and Edge headless."""

import subprocess
from pathlib import Path

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE_DIR = Path(r"C:\Users\alexander\.gemini\antigravity-ide\scratch\canarymesh")
STATIC_HTML = BASE_DIR / "src" / "canarymesh" / "api" / "static" / "index.html"
OUT_FILE = BASE_DIR / "docs" / "images" / "web_console.png"
TEMP_HTML = BASE_DIR / "docs" / "images" / "temp_console.html"

raw_html = STATIC_HTML.read_text(encoding="utf-8")

chart_points_js = """
    for (let i = 0; i < 24; i++) {
      historyPoints.push({
        stableP99: 16.0 + Math.sin(i * 0.5) * 4.0,
        canaryP99: 34.0 + Math.cos(i * 0.4) * 8.0 + (i > 18 ? 12.0 : 0.0),
        errRate: i > 18 ? 2.1 : 0.4
      });
    }

    applyTelemetryData({
      canary_weight: 25.0,
      telemetry: {
        stable: { rps: 84.5, p99_ms: 18.2, status_2xx: 1420, status_5xx: 0, p50_ms: 12.4, p90_ms: 15.8 },
        canary: { rps: 28.1, p99_ms: 42.6, status_2xx: 468, status_5xx: 8, error_rate_percent: 1.68, p50_ms: 22.1, p90_ms: 36.4 }
      },
      guard: {
        state: 'HEALTHY',
        comparative: {
          summary: 'Canary metrics are healthy relative to Stable baseline',
          latency_ratio: 2.34,
          error_diff_percent: 1.68
        },
        recent_trips: [
          {
            timestamp: "2026-09-10T14:22:18.000Z",
            reason: "Canary p99 latency (384.2ms) exceeded SLA limit (350.0ms)",
            previous_weight: 35.0,
            total_requests: 84,
            p99_ms: 384.2
          }
        ]
      },
      rollout: {
        state: 'IN_PROGRESS',
        scenario_name: 'progressive-rollout.yaml',
        total_steps: 5,
        current_step: { step_number: 2, weight: 25.0, remaining_seconds: 42 }
      },
      shadow: {
        enabled: true,
        shadow_percentage: 100,
        total_shadowed_requests: 1240,
        total_shadow_errors: 12,
        parity_rate_percent: 99.0
      }
    });

    drawChart();
"""

modified_html = raw_html.replace("init();", chart_points_js)

styled_page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>CanaryMesh — Control Plane Operations Console</title>
  <style>
    body {{
      background: #030712;
      margin: 0;
      padding: 24px;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}
    .browser-frame {{
      background: #090d16;
      border-radius: 12px;
      box-shadow: 0 25px 60px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.1);
      overflow: hidden;
      width: 1360px;
    }}
    .browser-toolbar {{
      background: #111827;
      padding: 10px 18px;
      display: flex;
      align-items: center;
      gap: 14px;
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }}
    .window-dots {{
      display: flex;
      gap: 8px;
    }}
    .dot {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }}
    .dot-red {{ background: #ef4444; }}
    .dot-yellow {{ background: #f59e0b; }}
    .dot-green {{ background: #10b981; }}
    .address-bar {{
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 6px;
      color: #9ca3af;
      font-size: 13px;
      padding: 5px 14px;
      flex: 1;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .address-bar span.secure {{
      color: #10b981;
      font-weight: bold;
    }}
    .browser-content {{
      padding: 4px;
    }}
  </style>
</head>
<body>
  <div class="browser-frame">
    <div class="browser-toolbar">
      <div class="window-dots">
        <div class="dot dot-red"></div>
        <div class="dot dot-yellow"></div>
        <div class="dot dot-green"></div>
      </div>
      <div class="address-bar">
        <span class="secure">🔒</span>
        <span style="color: #e5e7eb;">http://localhost:8090/ui</span>
      </div>
      <div style="font-size: 12px; color: #6b7280; font-weight: 500;">CanaryMesh v0.1.0</div>
    </div>
    <div class="browser-content">
      {modified_html}
    </div>
  </div>
</body>
</html>"""

TEMP_HTML.write_text(styled_page, encoding="utf-8")

cmd = [
    EDGE_PATH,
    "--headless=new",
    "--window-size=1420,1380",
    "--default-background-color=030712",
    f"--screenshot={OUT_FILE.resolve()}",
    TEMP_HTML.resolve().as_uri(),
]

subprocess.run(cmd, check=True)
TEMP_HTML.unlink(missing_ok=True)
print(f"Captured Web Operations Console screenshot: {OUT_FILE.exists()} ({OUT_FILE.stat().st_size} bytes)")
