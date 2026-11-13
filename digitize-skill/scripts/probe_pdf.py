"""Look at every page of a PDF and say how its tables and plots can be read.

Usage: python probe_pdf.py PAPER.pdf [--json probe.json]

For each page: digits in the text layer, vector drawing count, embedded images, and the
figure/table captions found. Route per page:
  text      - numbers are in the text layer: read tables directly, plots from vectors
  vector    - plot curves are drawn as vector paths: exact coordinates are available
  scan      - page is an image: OCR for tables, pixel tracing for plots
  scan+ocr  - page is an image that carries a hidden OCR text layer (made by the scanner).
              Treat it as a scan: that hidden text is often wrong. The extractors OCR it afresh.
Page numbers are 1-based (the first page is page 1), as all the scripts use them.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_util import digits_in_text_layer, image_cover, open_pdf  # noqa: E402

CAP_RE = re.compile(r"^\s*(fig(?:ure)?\.?|table)\s*([A-Z]?\d+[a-z]?)", re.I | re.M)


def probe(path):
    doc = open_pdf(path)
    pages = []
    for i, page in enumerate(doc):
        txt = page.get_text("text")
        digits = digits_in_text_layer(page)
        try:
            drawings = page.get_drawings()
        except Exception as e:  # malformed content streams happen in old PDFs; report, don't hide
            drawings = []
            print("page %d: could not read vector drawings (%s)" % (i + 1, e), file=sys.stderr)
        colored = sum(1 for d in drawings if _is_colored(d.get("color")) or _is_colored(d.get("fill")))
        images = page.get_images(full=True)
        cover = image_cover(page)  # the same rule extract_tables uses to decide on OCR
        caps = sorted({(m.group(1).lower().startswith("t") and "Table " or "Figure ") + m.group(2)
                       for m in CAP_RE.finditer(txt)})
        if cover >= 0.8:
            route = "scan+ocr" if digits >= 20 else "scan"
        elif len(drawings) > 50 or colored > 0:
            route = "vector"
        else:
            route = "text" if digits >= 20 else "scan"
        notes = []
        if page.rotation:
            notes.append("page rotated %d deg (crop fractions follow the page as displayed)" % page.rotation)
        if route.startswith("scan") and not caps:
            notes.append("scanned page with no caption read: look at it (figure/table without OCR text?)")
        pages.append({"page": i + 1, "text_chars": len(txt.strip()), "text_digits": digits,
                      "vector_paths": len(drawings), "colored_paths": colored,
                      "images": len(images), "image_cover": round(cover, 2),
                      "captions": caps, "route": route, "notes": notes})
    # caption numbering holes, per kind and per letter prefix ("A" for appendix: A1, A2, ...)
    seq = {}
    for p in pages:
        for c in p["captions"]:
            kind, num = c.split(" ", 1)
            m = re.match(r"([A-Z]?)(\d+)", num)
            if m:
                seq.setdefault("%s %s" % (kind, m.group(1)), set()).add(int(m.group(2)))
    holes = {k.strip(): sorted(set(range(1, max(v) + 1)) - v) for k, v in seq.items() if v}
    return {"file": os.path.basename(path), "pages": pages, "caption_numbers_missing": holes}


def _is_colored(c):
    if not c:
        return False
    r, g, b = c[:3]
    return max(r, g, b) - min(r, g, b) > 0.15


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    res = probe(a.pdf)
    print("%-5s %-8s %7s %7s %7s %6s  %s" % ("page", "route", "digits", "paths", "colored", "imgcov", "captions"))
    for p in res["pages"]:
        print("%-5d %-8s %7d %7d %7d %6.2f  %s" % (p["page"], p["route"], p["text_digits"], p["vector_paths"],
                                                   p["colored_paths"], p["image_cover"], ", ".join(p["captions"])))
        for n in p["notes"]:
            print("      note: " + n)
    for k, v in res["caption_numbers_missing"].items():
        if v:
            pre = k.split(" ", 1)[1] if " " in k else ""
            print("WARNING: %s numbers never seen as a caption: %s (check those pages by eye)"
                  % (k.split(" ")[0], ", ".join(pre + str(n) for n in v)))
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
