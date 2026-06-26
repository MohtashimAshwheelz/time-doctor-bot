import json, base64, gzip, re, os

with open(r"D:\Projects\Automation\Bots\Time Doctor Bot\Time Doctor Bot.html", encoding="utf-8") as f:
    html = f.read()

m = re.search(r'<script type="__bundler/manifest">(.*?)</script>', html, re.DOTALL)
manifest = json.loads(m.group(1).strip())

out_dir = r"D:\Projects\Automation\Bots\Time Doctor Bot\design_extracted"
os.makedirs(out_dir, exist_ok=True)

for uuid, entry in manifest.items():
    data = base64.b64decode(entry["data"])
    if entry.get("compressed"):
        try:
            data = gzip.decompress(data)
        except Exception as e:
            print(f"Decompress fail {uuid}: {e}")
    mime = entry.get("mime", "")
    if "javascript" in mime:
        ext = "js"
    elif "css" in mime:
        ext = "css"
    elif "woff2" in mime:
        ext = "woff2"
    else:
        ext = "bin"
    fname = os.path.join(out_dir, uuid + "." + ext)
    with open(fname, "wb") as f:
        f.write(data)
    if "javascript" in mime:
        print(f"JS  {uuid}.js  {len(data)} bytes")

print("Done.")
