"""Shared helpers: open PDFs, render crops, read words from the text layer or OCR."""
import os
import re
import sys
import warnings

if sys.version_info < (3, 9):
    sys.exit("These scripts need Python 3.9 or newer (tested on 3.11); this is %d.%d. "
             "Try 'python3' instead of 'python'." % sys.version_info[:2])
warnings.filterwarnings("ignore", category=FutureWarning, module="pymupdf")
try:
    import pymupdf
except ImportError:
    sys.exit("PyMuPDF is not installed. Run: pip install -r requirements.txt (from the skill folder)")

MAX_RENDER_PIXELS = 60_000_000  # ~ an A4 page at 900 dpi; larger renders exhaust memory

NUM_RE = re.compile(r"^[\(\[]?[+\-−–]?(\d+(\.\d*)?|\.\d+)([eE][+\-−]?\d+)?[\)\]]?[%,;]?$")


def parse_number(s):
    """Number from a printed label; None if the label is not a plain number.
    Unicode minus and en dash count as minus. Thousands commas are NOT accepted here
    (a comma may be a decimal comma); tables handle them explicitly."""
    t = s.strip().replace("−", "-").replace("–", "-")
    if not NUM_RE.match(t):
        return None
    t = t.strip("()[]%,;")
    try:
        return float(t)
    except ValueError:
        return None


def open_pdf(path):
    if not os.path.isfile(path):
        sys.exit("PDF not found: %s" % path)
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # pymupdf raises its own types for damaged/encrypted files
        sys.exit("cannot open %s as a PDF (%s)" % (path, e))
    if doc.needs_pass:
        sys.exit("%s is password-protected; ask for an unlocked copy" % path)
    return doc


def image_cover(page, clip=None):
    """Fraction of the clip (default: page) covered by embedded images."""
    area = clip or page.rect
    tot = 0.0
    for im in page.get_images(full=True):
        for r in page.get_image_rects(im[0]):
            tot += (r & area).width * (r & area).height if r.intersects(area) else 0.0
    return min(tot / max(area.width * area.height, 1), 1.0)


def rect_from_arg(page, crop):
    """crop: None (whole page), 'x0,y0,x1,y1' in PDF points, or fractions of the page if all <= 1."""
    r = page.rect
    if not crop:
        return pymupdf.Rect(r)
    vals = [float(v) for v in str(crop).split(",")]
    if len(vals) != 4:
        raise ValueError("crop must be x0,y0,x1,y1")
    if all(0 <= v <= 1 for v in vals):
        vals = [vals[0] * r.width, vals[1] * r.height, vals[2] * r.width, vals[3] * r.height]
    rect = pymupdf.Rect(*vals) & r
    if rect.is_empty or rect.width < 5 or rect.height < 5:
        raise ValueError("crop %s is empty or outside the page" % crop)
    return rect


def render(page, clip, dpi=300):
    """Render clip to an RGB numpy array. Returns (array, zoom) with zoom = pixels per point."""
    import numpy as np
    zoom = dpi / 72.0
    if clip.width * clip.height * zoom * zoom > MAX_RENDER_PIXELS:
        zoom = (MAX_RENDER_PIXELS / (clip.width * clip.height)) ** 0.5
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False, colorspace=pymupdf.csRGB)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].copy()
    return arr, zoom


SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺",
                            "0123456789-+")


def text_words(page, clip=None):
    """Text-layer words as dicts {text, x0, y0, x1, y1, conf} in page points.

    Built from characters, not from get_text('words'): a word that changes font size is
    split, so a raised small exponent is seen as its own token. '10' followed by a raised
    exponent '2' becomes '1e2' (otherwise the label 10^2 reads as the number 102, silently).
    """
    toks = []
    raw = page.get_text("rawdict", clip=clip)
    for b in raw.get("blocks", []):
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                cur = None
                for ch in sp.get("chars", []):
                    c = ch["c"]
                    x0, y0, x1, y1 = ch["bbox"]
                    if c.isspace():
                        cur = None
                        continue
                    if cur is None:
                        cur = {"text": "", "x0": x0, "y0": y0, "x1": x1, "y1": y1, "size": sp["size"],
                               "conf": 1.0, "src": "text"}
                        toks.append(cur)
                    cur["text"] += c
                    cur["x1"] = max(cur["x1"], x1)
                    cur["y0"] = min(cur["y0"], y0)
                    cur["y1"] = max(cur["y1"], y1)
    out = []
    for t in toks:
        prev = out[-1] if out else None
        if (prev and t["size"] < 0.85 * prev["size"] and abs(t["x0"] - prev["x1"]) < 0.5 * prev["size"]
                and (t["y0"] + t["y1"]) / 2 < (prev["y0"] + prev["y1"]) / 2
                and re.fullmatch(r"[+\-−]?\d+", t["text"].translate(SUPERSCRIPT))):
            m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*[×x⋅·])?10", prev["text"])
            if m:
                exp = t["text"].translate(SUPERSCRIPT).replace("−", "-")
                prev["text"] = (m.group(1) or "1") + "e" + exp
                prev["x1"] = t["x1"]
                prev["y0"] = min(prev["y0"], t["y0"])
                continue
            prev["text"] += "^" + t["text"]   # unknown raised token: keep, but it will not parse as a number
            prev["x1"] = t["x1"]
            continue
        out.append(t)
    for t in out:
        u = t["text"].translate(SUPERSCRIPT)
        m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*[×x⋅·])?10([+\-−]?\d+)", u)
        if m and t["text"] != u:   # unicode superscript form, e.g. 10⁻²
            t["text"] = (m.group(1) or "1") + "e" + m.group(2).replace("−", "-")
    return out


_OCR = None


def ocr_words(page, clip, dpi=300):
    """OCR words via RapidOCR (local, no network) mapped back to page points."""
    global _OCR
    if _OCR is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as e:
            raise RuntimeError("OCR needs rapidocr-onnxruntime (pip install -r requirements.txt)") from e
        _OCR = RapidOCR()
    img, zoom = render(page, clip, dpi)
    res, _ = _OCR(img)
    out = []
    for box, text, conf in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        for part in _split_box(text, min(xs), max(xs)):
            t, a, b = part
            out.append({"text": t, "x0": clip.x0 + a / zoom, "x1": clip.x0 + b / zoom,
                        "y0": clip.y0 + min(ys) / zoom, "y1": clip.y0 + max(ys) / zoom,
                        "conf": float(conf), "src": "ocr"})
    return out


def _split_box(text, x0, x1):
    """OCR often returns one box for several space-separated cells; split it and give each
    token an x-range proportional to its character position (good enough to bin columns)."""
    toks = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    if len(toks) <= 1:
        return [(text.strip(), x0, x1)] if text.strip() else []
    n = max(len(text), 1)
    w = (x1 - x0) / n
    return [(t, x0 + s * w, x0 + e * w) for t, s, e in toks]


def digits_in_text_layer(page):
    return sum(ch.isdigit() for ch in page.get_text("text"))
