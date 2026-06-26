#!/usr/bin/env python3
"""Bundle the modular prototype (styles.css + data.js + app.js) into a single
self-contained index.html so it renders in any context (http, file://, webview)
with zero external subresource requests. Re-run after editing the source files."""
from pathlib import Path

here = Path(__file__).parent
css = (here / "styles.css").read_text()
data_js = (here / "data.js").read_text()
app_js = (here / "app.js").read_text()

BODY = """  <!-- Prototype chrome: screen switcher (not part of the product UI) -->
  <div class="proto-bar">
    <span class="proto-brand">AlphaLabs Prototype</span>
    <div class="proto-tabs">
      <button data-goto="brief" class="proto-tab active">A &middot; Brief</button>
      <button data-goto="detail" class="proto-tab">B &middot; Detail</button>
      <button data-goto="queue" class="proto-tab">C &middot; Approval</button>
      <button data-goto="explain" class="proto-tab">D &middot; Explain</button>
    </div>
    <span class="proto-note">Mock data &middot; no APIs</span>
  </div>

  <div class="stage">
    <div class="device">
      <div class="device-notch"></div>
      <div id="app" class="screen-host"></div>
    </div>
  </div>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1" />
  <meta name="theme-color" content="#090b10" />
  <title>AlphaLabs &mdash; PM Approval Prototype</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />
  <style>
{css}
  </style>
</head>
<body>
{BODY}

  <script>
{data_js}
{app_js}
  </script>
</body>
</html>
"""

out = here / "index.html"
out.write_text(html)
print(f"Wrote {out} ({len(html):,} bytes, self-contained)")
