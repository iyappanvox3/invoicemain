"""
update-bg.py
============
Run this script whenever you change bg.png.
It embeds bg.png as a base64 data URL into invoice.html so that
"Save as PDF" works directly from file:// (double-clicking the file).

Usage:
    python update-bg.py
"""

import base64
import re
import sys
import os

BG_FILE = "bg.png"
HTML_FILE = "invoice.html"
PATTERN = r"(var INVOICE_BG_DATA\s*=\s*')[^']*(';\s*)"

# ── 1. Read bg.png ──────────────────────────────────────────────────────────
if not os.path.exists(BG_FILE):
    print(f"ERROR: {BG_FILE} not found in the same directory as this script.")
    sys.exit(1)

with open(BG_FILE, "rb") as f:
    b64 = base64.b64encode(f.read()).decode("utf-8")

data_url = f"data:image/png;base64,{b64}"

# ── 2. Read invoice.html ─────────────────────────────────────────────────────
if not os.path.exists(HTML_FILE):
    print(f"ERROR: {HTML_FILE} not found in the same directory as this script.")
    sys.exit(1)

with open(HTML_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# ── 3. Inject base64 into the INVOICE_BG_DATA variable ───────────────────────
new_content, n = re.subn(PATTERN, lambda m: m.group(1) + data_url + m.group(2), content)

if n == 0:
    print("ERROR: Could not find 'var INVOICE_BG_DATA' in invoice.html.")
    print("       Make sure the variable exists in the <script> block.")
    sys.exit(1)

# ── 4. Write back ─────────────────────────────────────────────────────────────
with open(HTML_FILE, "w", encoding="utf-8") as f:
    f.write(new_content)

size_kb = len(b64) * 3 / 4 / 1024
print(f"SUCCESS: bg.png embedded into invoice.html ({size_kb:.1f} KB of image data).")
print(
    f"         Reload invoice.html in your browser — Save as PDF will now work directly."
)
