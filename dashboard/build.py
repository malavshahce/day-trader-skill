#!/usr/bin/env python3
"""Inline lib.js into src/index.src.html -> index.html (the file that gets published)."""
import pathlib
d = pathlib.Path(__file__).parent
lib = (d / "lib.js").read_text()
assert "</script" not in lib.lower()
src = (d / "src" / "index.src.html").read_text()
assert "/*__LIB__*/" in src
(d / "index.html").write_text(src.replace("/*__LIB__*/", lib))
print("built index.html", (d / "index.html").stat().st_size, "bytes")
