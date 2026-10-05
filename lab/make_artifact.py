"""Write lab/dist/wheel-lab.html for publishing: index.html without the
document wrapper (doctype, html/head/body, charset/viewport), which the
artifact host adds itself. Publish it with data.js and engine.js alongside."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
s = open(os.path.join(HERE, "index.html")).read()
for pat in (r"<!doctype html>\s*", r"</?html[^>]*>\s*", r"</?head>\s*", r"<meta charset[^>]*>\s*",
            r'<meta name="viewport"[^>]*>\s*', r"</?body>\s*"):
    s = re.sub(pat, "", s, flags=re.I)
os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
out = os.path.join(HERE, "dist", "wheel-lab.html")
open(out, "w").write(s)
print("wrote", out, len(s), "chars; <title> at", s.find("<title>"))
