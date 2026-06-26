"""
Extract the design template HTML and component script from the bundle.
Writes: design_extracted/template.html, design_extracted/component.js
"""
import json, base64, gzip, re, os

with open(r"D:\Projects\Automation\Bots\Time Doctor Bot\Time Doctor Bot.html", encoding="utf-8") as f:
    html = f.read()

# ── Extract template ─────────────────────────────────────────────────────────
m = re.search(r'<script type="__bundler/template">(.*?)</script>', html, re.DOTALL)
obj = json.loads(m.group(1).strip())
page_html = list(obj["pages"].values())[0]

# ── Extract manifest (for dc-runtime JS) ─────────────────────────────────────
m2 = re.search(r'<script type="__bundler/manifest">(.*?)</script>', html, re.DOTALL)
manifest = json.loads(m2.group(1).strip())

out = r"D:\Projects\Automation\Bots\Time Doctor Bot\design_extracted"
os.makedirs(out, exist_ok=True)

# Decode all JS assets
js_assets = {}
for uuid, entry in manifest.items():
    if "javascript" not in entry.get("mime", ""):
        continue
    data = base64.b64decode(entry["data"])
    if entry.get("compressed"):
        data = gzip.decompress(data)
    js_assets[uuid] = data.decode("utf-8", errors="replace")
    print(f"JS: {uuid}  {len(data)} bytes")

# Write assets
for uuid, code in js_assets.items():
    with open(os.path.join(out, uuid + ".js"), "w", encoding="utf-8") as f:
        f.write(code)

# Write full template HTML
with open(os.path.join(out, "template.html"), "w", encoding="utf-8") as f:
    f.write(page_html)

# Extract just the dc-script content
script_match = re.search(r'<script[^>]*data-dc-script[^>]*>(.*?)</script>', page_html, re.DOTALL)
if script_match:
    component_js = script_match.group(1)
    with open(os.path.join(out, "component.js"), "w", encoding="utf-8") as f:
        f.write(component_js)
    print(f"Component script: {len(component_js)} chars")

# Extract x-dc template
xdc_match = re.search(r'<x-dc>(.*?)</x-dc>', page_html, re.DOTALL)
if xdc_match:
    xdc_html = xdc_match.group(1)
    with open(os.path.join(out, "xdc_template.html"), "w", encoding="utf-8") as f:
        f.write(xdc_html)
    print(f"x-dc template: {len(xdc_html)} chars")

print("Done.")
