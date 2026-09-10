"""Render modern SVG logo and PNG asset for CanaryMesh."""

import subprocess
from pathlib import Path

BASE_DIR = Path(r"C:\Users\alexander\.gemini\antigravity-ide\scratch\canarymesh")
SVG_FILE = BASE_DIR / "docs" / "images" / "logo.svg"
PNG_FILE = BASE_DIR / "docs" / "images" / "logo.png"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="canaryGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#fbbf24" />
      <stop offset="50%" stop-color="#f59e0b" />
      <stop offset="100%" stop-color="#d97706" />
    </linearGradient>
    <linearGradient id="meshGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8" />
      <stop offset="50%" stop-color="#3b82f6" />
      <stop offset="100%" stop-color="#1d4ed8" />
    </linearGradient>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#020617" />
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="12" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <!-- Background rounded card -->
  <rect width="512" height="512" rx="108" fill="url(#bgGrad)" stroke="#1e293b" stroke-width="4" />
  
  <!-- Subtle background grid lines -->
  <g stroke="#334155" stroke-width="1.5" stroke-dasharray="6,6" opacity="0.3">
    <line x1="96" y1="180" x2="416" y2="180" />
    <line x1="96" y1="256" x2="416" y2="256" />
    <line x1="96" y1="332" x2="416" y2="332" />
    <line x1="180" y1="96" x2="180" y2="416" />
    <line x1="256" y1="96" x2="256" y2="416" />
    <line x1="332" y1="96" x2="332" y2="416" />
  </g>

  <!-- Split traffic arrows / Mesh nodes -->
  <!-- Central input node -->
  <circle cx="130" cy="256" r="18" fill="url(#meshGrad)" filter="url(#glow)" />
  <circle cx="130" cy="256" r="8" fill="#ffffff" />

  <!-- Split paths -->
  <!-- Top path to Canary (Amber/Gold) -->
  <path d="M 130 256 C 220 256, 250 160, 360 160" fill="none" stroke="url(#canaryGrad)" stroke-width="12" stroke-linecap="round" />
  <circle cx="360" cy="160" r="22" fill="url(#canaryGrad)" filter="url(#glow)" />
  <circle cx="360" cy="160" r="10" fill="#ffffff" />

  <!-- Bottom path to Stable (Cyan/Blue) -->
  <path d="M 130 256 C 220 256, 250 352, 360 352" fill="none" stroke="url(#meshGrad)" stroke-width="12" stroke-linecap="round" />
  <circle cx="360" cy="352" r="22" fill="url(#meshGrad)" filter="url(#glow)" />
  <circle cx="360" cy="352" r="10" fill="#ffffff" />

  <!-- Mesh cross connection (Supervisor/Guard monitor loop) -->
  <path d="M 360 160 L 360 352" fill="none" stroke="#64748b" stroke-width="4" stroke-dasharray="8,8" />
  <circle cx="360" cy="256" r="14" fill="#10b981" filter="url(#glow)" />
  <path d="M 354 256 L 358 260 L 366 252" fill="none" stroke="#ffffff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />

  <!-- Geometric Canary wing silhouette on top node -->
  <path d="M 360 120 Q 420 125, 430 160 Q 390 175, 360 160 Z" fill="url(#canaryGrad)" opacity="0.9" />
</svg>
"""

SVG_FILE.write_text(svg_content, encoding="utf-8")

# Render to PNG using Edge headless
html_temp = BASE_DIR / "docs" / "images" / "temp_logo.html"
html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: transparent; display: flex; justify-content: center; align-items: center; width: 512px; height: 512px; overflow: hidden; }}
    svg {{ width: 512px; height: 512px; }}
  </style>
</head>
<body>
  {svg_content}
</body>
</html>"""

html_temp.write_text(html_content, encoding="utf-8")

cmd = [
    EDGE_PATH,
    "--headless=new",
    "--window-size=512,512",
    "--default-background-color=00000000",
    f"--screenshot={PNG_FILE.resolve()}",
    html_temp.resolve().as_uri(),
]
subprocess.run(cmd, check=True)
html_temp.unlink(missing_ok=True)
print(f"Rendered logo: SVG and PNG ({PNG_FILE.stat().st_size} bytes)")
