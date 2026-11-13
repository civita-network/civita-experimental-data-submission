"""Digitize the curves of one plot on a PDF page.

Usage:
  python digitize_plot.py PAPER.pdf --page 3 --crop x0,y0,x1,y1 --out fig3.json
         [--route auto|vector|raster] [--calib calib.json] [--colors red,#1f77b4,black]
         [--include-black] [--box x0,y0,x1,y1] [--overlay fig3_check.png]
         [--preview fig3_grid.png] [--max-points 150]

Two ways to get the numbers:
  vector  The curve is drawn as vector paths in the PDF (most journal PDFs made from
          plotting software). Coordinates are exact; only the axis calibration adds error.
  raster  The plot is a picture (scans, pasted images). Pixels of each curve colour are
          traced column by column. Expect error of about one line width.

Axis calibration (value <-> position on the page):
  auto    Reads the numbers printed at the axis ticks (text layer, else OCR) and fits a
          straight line (or a log line) through them. Needs >= 3 readable ticks per axis.
  manual  --calib calib.json with {"x": [[pos, value], ...], "y": [[pos, value], ...],
          "xscale": "linear"|"log", "yscale": "linear"|"log"} where pos is in PDF points
          (x along the page, y down the page). Use --preview to get an image of the crop
          with a labelled coordinate grid, read two tick positions per axis from it.

Axes box (the plotted area): found from the axis lines. --box x0,y0,x1,y1 (PDF points)
overrides it. The result's "axis_bounds" are the data values at the box edges.

Always open the --overlay image: the digitized points are drawn back over the plot.
A curve that does not sit on the printed line is wrong, whatever the numbers say.
"""
import argparse
import json
import math
import os
import statistics
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore", category=FutureWarning)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_util import (digits_in_text_layer, image_cover, ocr_words, open_pdf, parse_number,  # noqa: E402
                      rect_from_arg, render, text_words)

NAMED = {"red": (220, 30, 30), "blue": (30, 60, 220), "green": (30, 160, 60), "black": (0, 0, 0),
         "orange": (250, 140, 20), "purple": (140, 50, 170), "magenta": (220, 30, 200), "cyan": (20, 190, 210),
         "brown": (140, 80, 30), "gray": (128, 128, 128), "grey": (128, 128, 128)}


# ---------------------------------------------------------------- calibration
def fit_axis(pairs, scale):
    """pairs [(pos, value)]; returns dict(a, b, scale, resid_pct) with value = a + b*pos (log10 for log)."""
    if len(pairs) < 2:
        raise ValueError("need at least 2 ticks per axis, got %d" % len(pairs))
    pos = np.array([p for p, _ in pairs], float)
    val = np.array([v for _, v in pairs], float)
    if scale == "log":
        if np.any(val <= 0):
            raise ValueError("log axis with a tick value <= 0")
        val = np.log10(val)
    if np.ptp(pos) < 1e-6:
        raise ValueError("all ticks at the same position")
    b, a = np.polyfit(pos, val, 1)
    resid = val - (a + b * pos)
    span = np.ptp(val) or 1.0
    return {"a": float(a), "b": float(b), "scale": scale, "ticks": [[float(p), float(v)] for p, v in pairs],
            "resid_pct": float(100 * np.max(np.abs(resid)) / span) if len(pairs) > 2 else None}


def apply_axis(ax, pos):
    v = ax["a"] + ax["b"] * np.asarray(pos, float)
    return 10 ** v if ax["scale"] == "log" else v


def invert_axis(ax, val):
    v = np.log10(np.asarray(val, float)) if ax["scale"] == "log" else np.asarray(val, float)
    return (v - ax["a"]) / ax["b"]


def best_fit(pairs):
    cands = [fit_axis(pairs, "linear")]
    if all(v > 0 for _, v in pairs) and len(pairs) >= 3:
        cands.append(fit_axis(pairs, "log"))
    return min(cands, key=lambda c: c["resid_pct"] if c["resid_pct"] is not None else 0)


def find_axes_box(page, clip):
    """Longest dark horizontal/vertical vector lines in the clip: bottom = x axis, left = y axis."""
    hs, vs = [], []
    for d in page.get_drawings():
        col = d.get("color")
        if col is None or not _achromatic(col) or not _touches(clip, d["rect"]):
            continue
        for it in d["items"]:
            segs = []
            if it[0] == "l":
                segs = [(it[1], it[2])]
            elif it[0] == "re":
                r = it[1]
                segs = [((r.x0, r.y1), (r.x1, r.y1)), ((r.x0, r.y0), (r.x0, r.y1)),
                        ((r.x0, r.y0), (r.x1, r.y0)), ((r.x1, r.y0), (r.x1, r.y1))]
            for p, q in segs:
                (x0, y0), (x1, y1) = (p[0], p[1]), (q[0], q[1])
                if abs(y0 - y1) < 0.5 and abs(x1 - x0) > 0.4 * clip.width:
                    hs.append((y0, min(x0, x1), max(x0, x1)))
                if abs(x0 - x1) < 0.5 and abs(y1 - y0) > 0.4 * clip.height:
                    vs.append((x0, min(y0, y1), max(y0, y1)))
    if not hs or not vs:
        return None
    xa = max(hs, key=lambda h: h[0])
    ya = min(vs, key=lambda v: v[0])
    return {"x_axis_y": xa[0], "y_axis_x": ya[0], "x_extent": (xa[1], xa[2]), "y_extent": (ya[1], ya[2]),
            "top": min(v[1] for v in vs), "right": max(h[2] for h in hs)}


def _longest_runs(mask):
    """Per row of a boolean array: (length, start) of the longest run of True."""
    out = []
    for row in mask:
        idx = np.flatnonzero(row)
        if idx.size == 0:
            out.append((0, 0))
            continue
        cuts = np.flatnonzero(np.diff(idx) > 2) + 1
        best = max(np.split(idx, cuts), key=len)
        out.append((int(best[-1] - best[0] + 1), int(best[0])))
    return out


def otsu(gray):
    """Otsu threshold of a uint8-valued array: the grey level that best splits ink from paper."""
    hist = np.bincount(np.clip(gray, 0, 255).astype(np.uint8).ravel(), minlength=256).astype(float)
    p = hist / max(hist.sum(), 1)
    om = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    sb = (mu[-1] * om - mu) ** 2 / np.maximum(om * (1 - om), 1e-12)
    return int(np.argmax(sb))


def dark_mask(img):
    """Ink pixels: darker than an adaptive (Otsu) threshold, capped so pale paper noise and
    light-grey fills stay out. Scanned black ink is often grey (70-115), not black."""
    g = img.max(axis=2)
    return g <= min(otsu(g), 170)


def _band_fraction(mask, band):
    """Per row: share of columns that have a set pixel within +-band rows. A slightly skewed
    scanned line spreads over several rows; the band gathers it back into one profile."""
    cs = np.vstack([np.zeros((1, mask.shape[1]), int), np.cumsum(mask, axis=0)])
    n = mask.shape[0]
    lo = np.clip(np.arange(n) - band, 0, n)
    hi = np.clip(np.arange(n) + band + 1, 0, n)
    return ((cs[hi] - cs[lo]) > 0).mean(axis=1)


def _line_groups(frac, thresh):
    """Runs of consecutive rows whose band fraction is >= thresh: [(first, last), ...]."""
    idx = np.flatnonzero(frac >= thresh)
    if idx.size == 0:
        return []
    return [(int(g[0]), int(g[-1])) for g in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)]


def _run_in_band(mask, a, b, gap):
    """(start, end) of the longest run of columns that have ink in rows a..b (gaps <= gap px)."""
    idx = np.flatnonzero(mask[a:b + 1].any(axis=0))
    if idx.size == 0:
        return 0, 0
    best = max(np.split(idx, np.flatnonzero(np.diff(idx) > gap) + 1), key=len)
    return int(best[0]), int(best[-1])


def raster_axes_box(img, zoom, clip):
    """Axis lines in a picture. A row (column) belongs to a long line when most of the crop
    width (height) has ink within a few pixels of it, so skewed scans still count. The x axis
    is the lowest such line, the y axis the leftmost; their ink runs give the box extent."""
    dark = dark_mask(img)
    h, w = dark.shape
    band = max(2, int(math.ceil(0.004 * max(h, w))))
    rf = _band_fraction(dark, band)
    cf = _band_fraction(dark.T, band)
    if rf.max() < 0.2 or cf.max() < 0.2:
        return None
    rows = _line_groups(rf, max(0.2, 0.6 * rf.max()))
    cols = _line_groups(cf, max(0.2, 0.6 * cf.max()))
    ra, rb = rows[-1]
    ca, cb = cols[0]
    gap = max(3, int(2 * zoom))
    x_start, x_end = _run_in_band(dark, ra, rb, gap)
    y_start, y_end = _run_in_band(dark.T, ca, cb, gap)
    yi, xi = (ra + rb) / 2, (ca + cb) / 2
    return {"x_axis_y": clip.y0 + yi / zoom, "y_axis_x": clip.x0 + xi / zoom,
            "x_extent": (clip.x0 + x_start / zoom, clip.x0 + x_end / zoom),
            "y_extent": (clip.y0 + y_start / zoom, clip.y0 + y_end / zoom),
            "top": clip.y0 + y_start / zoom, "right": clip.x0 + x_end / zoom, "band_pt": band / zoom}


def box_from_arg(s):
    """--box x0,y0,x1,y1 in PDF points: left, top, right, bottom of the plotted area."""
    v = [float(t) for t in s.split(",")]
    if len(v) != 4 or v[2] <= v[0] or v[3] <= v[1]:
        raise ValueError("--box must be x0,y0,x1,y1 in PDF points with x1 > x0 and y1 > y0")
    return {"x_axis_y": v[3], "y_axis_x": v[0], "x_extent": (v[0], v[2]), "y_extent": (v[1], v[3]),
            "top": v[1], "right": v[2], "source": "--box"}


def box_cover(box, clip):
    return ((box["right"] - box["y_axis_x"]) * (box["x_axis_y"] - box["top"])) / max(clip.width * clip.height, 1e-9)


def auto_calibration(page, clip, box, words, ticks=None):
    nums = []
    for w in words:
        v = parse_number(w["text"])
        if v is not None:
            nums.append(dict(w, v=v, xc=(w["x0"] + w["x1"]) / 2, yc=(w["y0"] + w["y1"]) / 2))
    if not nums:
        raise ValueError("no numeric tick labels found in the crop")
    h = statistics.median([w["y1"] - w["y0"] for w in nums])
    if box:
        # x labels: a row anywhere inside the box or just below it. The x axis may cross
        # y = 0 in mid-plot, so its labels are not always at the bottom.
        xcand = [w for w in nums if box["top"] + 0.5 * h < w["yc"] and w["y0"] < box["x_axis_y"] + 2.5 * h
                 and w["xc"] > box["y_axis_x"] - 0.3 * h]
        ycand = [w for w in nums if box["y_axis_x"] - 8 * h < w["x1"] < box["y_axis_x"] + 0.3 * h
                 and w["yc"] < box["x_axis_y"] + h]
    else:
        xcand = [w for w in nums if w["yc"] > clip.y0 + 0.6 * clip.height]
        ycand = [w for w in nums if w["xc"] < clip.x0 + 0.4 * clip.width]
    # equal-sized rows: the lowest wins
    xcand.sort(key=lambda w: -w["yc"])
    xrow = _largest_group(xcand, key=lambda w: w["yc"], tol=0.5 * h)
    ycol = _largest_group(ycand, key=lambda w: w["x1"], tol=1.0 * h)
    ycol = [w for w in ycol if w not in xrow]
    if len(xrow) < 3 or len(ycol) < 3:
        raise ValueError("found %d x-tick and %d y-tick labels; need 3 each (use --calib)" % (len(xrow), len(ycol)))
    # A label's centre is not exactly its tick: snap each label to the nearest tick mark.
    snapped = 0
    xpos, ypos = [w["xc"] for w in xrow], [w["yc"] for w in ycol]
    if ticks:
        xpos, n1 = _snap(xpos, ticks.get("x", []), [0.6 * (w["x1"] - w["x0"]) for w in xrow])
        ypos, n2 = _snap(ypos, ticks.get("y", []), [0.8 * (w["y1"] - w["y0"]) for w in ycol])
        snapped = n1 + n2
    cal = {"x": best_fit(list(zip(xpos, [w["v"] for w in xrow]))),
           "y": best_fit(list(zip(ypos, [w["v"] for w in ycol]))),
           "method": "auto ticks (%s), %d/%d labels snapped to tick marks" % (xrow[0]["src"], snapped, len(xrow) + len(ycol))}
    return cal


def _snap(pos, ticks, tol):
    out, n = [], 0
    for p, t in zip(pos, tol):
        near = min(ticks, key=lambda k: abs(k - p)) if ticks else None
        if near is not None and abs(near - p) <= t:
            out.append(near)
            n += 1
        else:
            out.append(p)
    return out, n


def vector_ticks(page, clip, box):
    """Short dark segments touching the axes: tick marks, in page points."""
    if not box:
        return {}
    xt, yt = [], []
    for d in page.get_drawings():
        col = d.get("color")
        if col is None or not _achromatic(col) or not _touches(clip, d["rect"]):
            continue
        for it in d["items"]:
            if it[0] != "l":
                continue
            (x0, y0), (x1, y1) = (it[1].x, it[1].y), (it[2].x, it[2].y)
            L = math.hypot(x1 - x0, y1 - y0)
            if L > 0.06 * max(clip.width, clip.height) or L < 0.5:
                continue
            if abs(x0 - x1) < 0.2 and min(abs(y0 - box["x_axis_y"]), abs(y1 - box["x_axis_y"])) < 1.0:
                xt.append(x0)
            if abs(y0 - y1) < 0.2 and min(abs(x0 - box["y_axis_x"]), abs(x1 - box["y_axis_x"])) < 1.0:
                yt.append(y0)
    return {"x": sorted(set(round(v, 3) for v in xt)), "y": sorted(set(round(v, 3) for v in yt))}


def raster_ticks(img, zoom, clip, box):
    """Tick marks in a picture: short dark stubs just inside or outside each axis line."""
    if not box:
        return {}
    dark = dark_mask(img)
    h, w = dark.shape
    yi = int(round((box["x_axis_y"] - clip.y0) * zoom))
    xi = int(round((box["y_axis_x"] - clip.x0) * zoom))
    band = max(3, int(2 * zoom))  # ~2 pt away from the axis line
    def centres(v):
        idx = np.flatnonzero(v)
        if idx.size == 0:
            return []
        return [g.mean() for g in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1) if len(g) <= 3 * zoom]
    xt, yt = [], []
    for rows in (dark[max(0, yi - 3 * band):max(0, yi - band)], dark[min(h, yi + band):min(h, yi + 3 * band)]):
        if rows.size:
            xt += centres(rows.sum(axis=0) >= 0.8 * rows.shape[0])
    for cols in (dark[:, min(w, xi + band):min(w, xi + 3 * band)], dark[:, max(0, xi - 3 * band):max(0, xi - band)]):
        if cols.size:
            yt += centres(cols.sum(axis=1) >= 0.8 * cols.shape[1])
    return {"x": [clip.x0 + v / zoom for v in xt], "y": [clip.y0 + v / zoom for v in yt]}


def _largest_group(ws, key, tol):
    best = []
    for w in ws:
        g = [u for u in ws if abs(key(u) - key(w)) <= tol]
        if len(g) > len(best):
            best = g
    # one label per position: drop duplicates of the same value
    seen, out = set(), []
    for w in sorted(best, key=lambda u: (u["xc"], u["yc"])):
        k = (round(w["xc"], 1), round(w["yc"], 1))
        if k not in seen:
            seen.add(k)
            out.append(w)
    return out


def manual_calibration(path):
    with open(path, encoding="utf-8") as f:
        c = json.load(f)
    return {"x": fit_axis([tuple(p) for p in c["x"]], c.get("xscale", "linear")),
            "y": fit_axis([tuple(p) for p in c["y"]], c.get("yscale", "linear")), "method": "manual"}


# ---------------------------------------------------------------- vector curves
def _touches(area, r):
    """PyMuPDF treats a perfectly straight line's bounding box as empty, so Rect.intersects
    is False for axis lines and ticks. Compare coordinates instead."""
    return r.x1 >= area.x0 - 0.5 and r.x0 <= area.x1 + 0.5 and r.y1 >= area.y0 - 0.5 and r.y0 <= area.y1 + 0.5


def _achromatic(c):
    r, g, b = c[:3]
    return max(r, g, b) - min(r, g, b) < 0.12


def _bezier(p0, p1, p2, p3, n=8):
    pts = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1 - t
        pts.append((mt ** 3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t ** 3 * p3[0],
                    mt ** 3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t ** 3 * p3[1]))
    return pts


def _plen(pc):
    return sum(math.hypot(pc[i][0] - pc[i - 1][0], pc[i][1] - pc[i - 1][1]) for i in range(1, len(pc)))


def _ext(pc):
    return max(max(p[0] for p in pc) - min(p[0] for p in pc), max(p[1] for p in pc) - min(p[1] for p in pc))


def _centre(pc):
    xs, ys = [p[0] for p in pc], [p[1] for p in pc]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def _near(a, b, tol):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def chain_pieces(pieces, tol=0.5):
    """Join pieces whose endpoints meet (within tol points) into one polyline. Plotting
    software (Excel especially) often draws one curve as many short separate paths."""
    cell = {}

    def k(p):
        return (int(math.floor(p[0] / tol)), int(math.floor(p[1] / tol)))

    def add(i, p):
        cell.setdefault(k(p), set()).add(i)

    for i, pc in enumerate(pieces):
        add(i, pc[0])
        add(i, pc[-1])
    used = [False] * len(pieces)

    def partner(p, me):
        cx, cy = k(p)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cell.get((cx + dx, cy + dy), ()):
                    if j == me or used[j]:
                        continue
                    pc = pieces[j]
                    for end, rev in ((pc[0], False), (pc[-1], True)):
                        if _near(p, end, tol):
                            d = math.hypot(p[0] - end[0], p[1] - end[1])
                            if best is None or d < best[0]:
                                best = (d, j, rev)
        return best

    chains = []
    for i in range(len(pieces)):
        if used[i]:
            continue
        used[i] = True
        cur = list(pieces[i])
        for forward in (True, False):
            while True:
                p = cur[-1] if forward else cur[0]
                m = partner(p, i)
                if m is None:
                    break
                _, j, at_end = m  # at_end: the match is the partner's last point
                used[j] = True
                pc = list(pieces[j])
                if forward:
                    cur += (pc[::-1] if at_end else pc)[1:]
                else:
                    cur = (pc if at_end else pc[::-1])[:-1] + cur
        chains.append(cur)
    return chains


def _squarish(w, h):
    return max(w, h) > 0.5 and min(w, h) >= 0.3 * max(w, h)


def _split_markers(raw, marker):
    """Sort raw pieces of one colour into marker centres and curve pieces.
    A piece is a marker only when it is a small closed shape (square, triangle, diamond),
    or a small straight stroke that crosses another at its middle (x, +), or one of >= 3
    equal small strokes radiating from one point (Excel's x and * markers). Short open
    pieces otherwise stay curve pieces: Excel draws one curve as many short paths."""
    markers, rest, thin = [], [], 0  # markers: (x, y, size)
    segs = []
    for pc in raw:
        if _ext(pc) >= marker:
            rest.append(pc)
            continue
        if len(pc) >= 4 and _near(pc[0], pc[-1], 0.5):
            xs, ys = [p[0] for p in pc], [p[1] for p in pc]
            if _squarish(max(xs) - min(xs), max(ys) - min(ys)):
                markers.append(_centre(pc) + (_ext(pc),))
            else:
                thin += 1
            continue
        if len(pc) == 2:
            segs.append(pc)
        else:
            rest.append(pc)
    is_mark = [False] * len(segs)
    mids = [((s[0][0] + s[1][0]) / 2, (s[0][1] + s[1][1]) / 2) for s in segs]
    lens = [_plen(s) for s in segs]
    dirs = [((s[1][0] - s[0][0]) / max(L, 1e-9), (s[1][1] - s[0][1]) / max(L, 1e-9)) for s, L in zip(segs, lens)]

    def crossing(i, j):  # not parallel: an x or + marker, not a stroke drawn twice
        return abs(dirs[i][0] * dirs[j][0] + dirs[i][1] * dirs[j][1]) < 0.9
    # crossing strokes: two equal strokes with the same midpoint
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if _near(mids[i], mids[j], 0.3) and abs(lens[i] - lens[j]) <= 0.25 * max(lens[i], lens[j]) \
                    and crossing(i, j):
                if not is_mark[i]:
                    markers.append(mids[i] + (lens[i],))
                is_mark[i] = is_mark[j] = True
    # radiating strokes: >= 3 equal strokes in different directions sharing one end point
    ends = {}
    for i, s in enumerate(segs):
        for p in (s[0], s[1]):
            ends.setdefault((round(p[0], 1), round(p[1], 1)), []).append(i)
    for p, ids in ends.items():
        ids = [i for i in ids if not is_mark[i]]
        if len(ids) < 3:
            continue
        med = statistics.median(lens[i] for i in ids)
        same = [i for i in ids if abs(lens[i] - med) <= 0.15 * med]
        ndir = len(set(round(math.degrees(math.atan2(*dirs[i][::-1]))) // 20 for i in same))
        if len(same) >= 3 and ndir >= 3:
            markers.append(p + (2 * med,))
            for i in same:
                is_mark[i] = True
    rest += [s for s, m in zip(segs, is_mark) if not m]
    return markers, rest, thin


def vector_pieces(page, clip, box, want_black):
    """Per colour: {"lines": [(length, polyline)], "markers": [(x, y)], "grid": n, "ticks": n}.
    Lines are already chained across separate paths. Gridlines, the frame and white paths
    are left out."""
    diag = math.hypot(clip.width, clip.height)
    marker = 0.02 * diag
    inner = clip
    bw, bh = clip.width, clip.height
    if box:
        import pymupdf
        inner = pymupdf.Rect(box["y_axis_x"] - 1, box["top"] - 1, box["right"] + 1, box["x_axis_y"] + 1)
        bw, bh = box["right"] - box["y_axis_x"], box["x_axis_y"] - box["top"]
    raw = {}
    for d in page.get_drawings():
        if not _touches(inner, d["rect"]):
            continue
        col = d.get("color") or d.get("fill")
        if col is None or min(col[:3]) > 0.9:  # no colour, or white/near-white background
            continue
        achro = _achromatic(col)
        if achro and not want_black:
            continue
        key = "#%02x%02x%02x" % tuple(int(round(255 * c)) for c in col[:3])
        r = d["rect"]
        g = raw.setdefault(key, {"pieces": [], "markers": [], "grid": 0, "ticks": 0})
        if max(r.width, r.height) < marker and d["items"] and (
                d.get("fill") is not None or any(it[0] in ("re", "qu") for it in d["items"])):
            if _squarish(r.width, r.height):
                g["markers"].append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, max(r.width, r.height)))
            else:
                g["ticks"] += 1  # thin filled sliver: a tick mark or a rule drawn as a filled box
            continue
        # split the path into connected pieces; a new piece starts wherever the pen jumps
        pieces, cur = [], []
        for it in d["items"]:
            if it[0] == "l":
                a, b = (it[1].x, it[1].y), (it[2].x, it[2].y)
                seg = [a, b]
                if achro and ((abs(a[1] - b[1]) < 0.5 and abs(a[0] - b[0]) > 0.5 * bw) or
                              (abs(a[0] - b[0]) < 0.5 and abs(a[1] - b[1]) > 0.5 * bh)):
                    g["grid"] += 1  # gridline, axis line or frame side
                    if cur:
                        pieces.append(cur)
                    cur = []
                    continue
            elif it[0] == "c":
                a = (it[1].x, it[1].y)
                seg = [a] + _bezier(a, (it[2].x, it[2].y), (it[3].x, it[3].y), (it[4].x, it[4].y))
            else:
                continue
            if cur and math.hypot(cur[-1][0] - seg[0][0], cur[-1][1] - seg[0][1]) < 0.01:
                cur.extend(seg[1:])
            else:
                if cur:
                    pieces.append(cur)
                cur = list(seg)
        if cur:
            pieces.append(cur)
        g["pieces"] += pieces
    groups = {}
    for key, g in raw.items():
        achro = _achromatic([int(key[i:i + 2], 16) / 255 for i in (1, 3, 5)])
        markers, rest, thin = _split_markers(g["pieces"], marker)
        markers = g["markers"] + markers
        if achro:  # other short straight axis-parallel black strokes are tick marks
            n0 = len(rest)
            rest = [pc for pc in rest if not (len(pc) == 2 and _plen(pc) < marker and (
                abs(pc[0][0] - pc[1][0]) < 0.2 or abs(pc[0][1] - pc[1][1]) < 0.2))]
            g["ticks"] += n0 - len(rest)
        chains = chain_pieces(rest)
        # unchained small open shapes repeated >= 3 times are markers too
        sig = {}
        for pc in chains:
            if _ext(pc) < marker:
                s = tuple((round(p[0] - pc[0][0], 1), round(p[1] - pc[0][1], 1)) for p in pc)
                sig.setdefault(s, []).append(pc)
        rep = set(id(pc) for v in sig.values() if len(v) >= 3 for pc in v)
        markers += [_centre(pc) + (_ext(pc),) for pc in chains if id(pc) in rep]
        lines, ticks, grid = [], g["ticks"] + thin, g["grid"]
        for pc in chains:
            if id(pc) in rep:
                continue
            L = _plen(pc)
            if achro and all(abs(a[0] - b[0]) < 0.2 or abs(a[1] - b[1]) < 0.2 for a, b in zip(pc[:-1], pc[1:])):
                if L < marker:
                    ticks += 1  # short axis-parallel black strokes: tick marks
                    continue
                if _near(pc[0], pc[-1], 0.5):
                    grid += 1  # closed axis-parallel outline: legend box or frame
                    continue
            lines.append((L, pc))
        seen, uniq = set(), []
        for m in markers:
            k = (round(m[0] / 0.3), round(m[1] / 0.3))
            if k not in seen:
                seen.add(k)
                uniq.append(m)
        groups[key] = {"lines": lines, "markers": uniq, "grid": grid, "ticks": ticks}
    return groups


def _dots(marks):
    """Split markers into (markers, dots): dots are shapes under half the size of the
    largest size that at least 3 markers reach - the dots and dashes of a dotted line
    drawn as tiny filled boxes, next to the real, larger data markers."""
    sizes = sorted((m[2] for m in marks), reverse=True)
    if len(sizes) < 3:
        return marks, []
    ref = next((s for s in sizes if sum(1 for t in sizes if t >= 0.8 * s) >= 3), sizes[-1])
    return [m for m in marks if m[2] >= 0.5 * ref], [m for m in marks if m[2] < 0.5 * ref]


def _xr(cal, xs):
    """'x a..b' for warnings, in data units when the calibration is known."""
    if not xs:
        return ""
    lo, hi = min(xs), max(xs)
    if cal:
        lo, hi = sorted(apply_axis(cal["x"], [lo, hi]))
        return "x %.4g..%.4g" % (lo, hi)
    return "page x %.1f..%.1f pt" % (lo, hi)


def vector_curves(page, clip, box, want_black, cal=None):
    out, warns = [], []
    groups = vector_pieces(page, clip, box, want_black)
    # Legend samples: a short, straight, horizontal stroke. Judged against the plot width,
    # not against the same colour's longest piece (a scatter series' only "line" may be its
    # legend sample).
    def legend_like(L, pc):
        ys = [p[1] for p in pc]
        return L < 0.12 * clip.width and max(ys) - min(ys) < 0.5
    for key, g in groups.items():
        legend = [pc for L, pc in g["lines"] if legend_like(L, pc)]
        lines = [(L, pc) for L, pc in g["lines"] if not legend_like(L, pc)]
        if legend:
            warns.append("%s: ignored %d short straight horizontal stroke(s) as legend sample(s)" % (key, len(legend)))
        if g["grid"] or g["ticks"]:
            warns.append("%s: ignored %d gridline/axis/frame segment(s) and %d tick mark(s)" % (key, g["grid"], g["ticks"]))
        # a marker sitting on a legend sample stroke is the legend's marker
        marks = [m for m in g["markers"] if not any(
            abs(m[1] - pc[0][1]) < 2 and min(pc[0][0], pc[-1][0]) - 2 <= m[0] <= max(pc[0][0], pc[-1][0]) + 2
            for pc in legend)]
        marks, dots = _dots(marks)
        if dots:
            warns.append("%s: ignored %d tiny shape(s) under half the marker size (%s) - dots/dashes of a dotted "
                         "line? not digitized" % (key, len(dots), _xr(cal, [m[0] for m in dots])))
        if lines:
            Lmax = max(L for L, _ in lines)
            keep = [pc for L, pc in lines if L >= 0.05 * Lmax]
            drop = [pc for L, pc in lines if L < 0.05 * Lmax]
            keep = [pc[::-1] if pc[0][0] > pc[-1][0] else pc for pc in keep]
            keep.sort(key=lambda pc: pc[0][0])
            out.append({"color": key, "kind": "line", "page_pieces": keep, "pieces": len(keep),
                        "dropped_short_pieces": len(drop), "markers_stripped": len(marks)})
            if drop:
                warns.append("%s: dropped %d short piece(s) under 5%% of the longest piece's length (%s) - "
                             "legend samples, ticks or curve fragments? check overlay"
                             % (key, len(drop), _xr(cal, [p[0] for pc in drop for p in pc])))
            if len(keep) > 1:
                warns.append("%s: line is %d separate pieces with gaps between them (no points bridge a gap)"
                             % (key, len(keep)))
        if len(marks) >= 3:
            pts = sorted((round(m[0], 3), round(m[1], 3)) for m in marks)
            out.append({"color": key, "kind": "scatter", "page_pieces": [pts], "pieces": 1,
                        "dropped_short_pieces": 0, "markers_stripped": 0})
            if lines:
                warns.append("%s: %d marker(s) (%s) emitted as their own scatter series next to the %s line; "
                             "check whether they are data points or only decorate the line"
                             % (key, len(marks), _xr(cal, [m[0] for m in marks]), key))
        elif marks:
            warns.append("%s: stripped %d marker(s) (%s): fewer than 3, not emitted"
                         % (key, len(marks), _xr(cal, [m[0] for m in marks])))
    return out, warns


# ---------------------------------------------------------------- raster curves
def parse_colors(spec):
    out = []
    for s in [t.strip() for t in spec.split(",") if t.strip()]:
        if s.lower() in NAMED:
            out.append((s.lower(), NAMED[s.lower()]))
        elif s.startswith("#") and len(s) == 7:
            out.append((s, tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))))
        else:
            raise ValueError("colour %r: use a name (%s) or #rrggbb" % (s, ", ".join(NAMED)))
    return out


def auto_colors(img):
    px = img.reshape(-1, 3).astype(float) / 255
    mx, mn = px.max(1), px.min(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0)
    sel = px[(sat > 0.35) & (mx > 0.25)]
    if len(sel) == 0:
        return []
    r, g, b = sel[:, 0], sel[:, 1], sel[:, 2]
    mxs = sel.max(1)
    mns = sel.min(1)
    d = np.maximum(mxs - mns, 1e-9)
    hue = np.where(mxs == r, ((g - b) / d) % 6, np.where(mxs == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    bins = (hue // 30).astype(int) % 12
    out = []
    for k in range(12):
        m = bins == k
        if m.sum() > 0.0015 * len(px):
            c = tuple(int(v) for v in np.median(sel[m], axis=0) * 255)
            out.append(("#%02x%02x%02x" % c, c))
    return out


def _remove_lines(mask, band, share=0.6):
    """Clear long straight horizontal/vertical lines (gridlines, frame) from a curve mask.
    A row band counts as a line when ink lies within +-band rows across > share of the width."""
    n = 0
    for m, whole in ((mask.T, True), (mask, False)):  # .T is a view: clearing it clears mask
        if m.shape[0] == 0 or m.shape[1] == 0:
            continue
        runmin = max(20, int(0.05 * m.shape[1]))
        for a, b in _line_groups(_band_fraction(m, band), share):
            n += 1
            if whole:  # vertical line: clear the band; the curve only loses a few columns
                m[max(0, a):b + 1, :] = False
                continue
            # horizontal line: clear only long runs along it, so a curve running close to a
            # gridline (or crossing it) keeps its pixels
            for i in range(max(0, a), b + 1):
                idx = np.flatnonzero(m[i])
                if idx.size < runmin:
                    continue
                for r in np.split(idx, np.flatnonzero(np.diff(idx) > 2) + 1):
                    if r[-1] - r[0] + 1 >= runmin:
                        m[i, r[0]:r[-1] + 1] = False
    return n


def raster_curves(img, zoom, clip, box, colors, tol=70):
    h, w = img.shape[:2]
    pad = 3 + int(math.ceil(box.get("band_pt", 0) * zoom)) if box else 0
    x0 = int(max(0, (box["y_axis_x"] - clip.x0) * zoom + pad)) if box else 0
    y1 = int(min(h, (box["x_axis_y"] - clip.y0) * zoom - pad)) if box else h
    yt = int(max(0, (box["top"] - clip.y0) * zoom + pad)) if box else 0
    xr = int(min(w, (box["right"] - clip.x0) * zoom - pad)) if box else w
    sub = img[yt:y1, x0:xr].astype(int)
    band = max(1, int(math.ceil(0.004 * max(sub.shape[:2]))))
    out, warns = [], []
    for name, rgb in colors:
        if max(rgb) - min(rgb) < 40 and max(rgb) < 160:  # black or dark grey
            mask = dark_mask(sub)
            _remove_lines(mask, band, 0.6)
            warns.append("%s curve traced from pixels: text, arrows and markers are also dark - check overlay closely" % name)
        else:
            dist = np.sqrt(((sub - np.array(rgb)) ** 2).sum(axis=2))
            mask = dist < tol
            # coloured gridlines are rare and a flat curve must survive: stricter share
            _remove_lines(mask, band, 0.8)
        pieces, pts, hist = [], [], []  # hist: (column, y) of the traced pixels
        look = max(3, int(round(2 * zoom)))  # slope over the last ~2 pt
        jump = 4 * zoom  # largest step off the predicted path, ~4 pt
        lastcol = None  # last column with any matching pixel
        for cx in range(mask.shape[1]):
            ys = np.flatnonzero(mask[:, cx])
            if ys.size == 0:
                continue
            blank = lastcol is not None and cx - lastcol > 5 * zoom  # wider than a gridline gap
            lastcol = cx
            runs = np.split(ys, np.flatnonzero(np.diff(ys) > 1) + 1)
            centres = [r.mean() for r in runs]
            if not hist:
                yc = max(runs, key=len).mean()
            else:
                # where the trace is heading: carry on straight through crossings
                pc_, py_ = hist[-1]
                old = [h for h in hist[-4 * look:] if pc_ - h[0] >= look]
                pred = py_
                if old and pc_ - old[-1][0] > 0:
                    pred = py_ + (py_ - old[-1][1]) / (pc_ - old[-1][0]) * (cx - pc_)
                yc = min(centres, key=lambda c: abs(c - pred))
                # a far jump is another curve or a stray mark: skip the column, unless the
                # trace has been lost for > 15 pt (steep part or a gap), then take the nearest
                # A column with one run next to the last traced one, reaching near the last y,
                # offers no other curve to jump to (steep stretches move fast): take it.
                alone = len(runs) == 1 and cx - pc_ <= 2 * zoom and abs(yc - py_) <= jump + len(runs[0])
                if not alone and abs(yc - pred) > jump + abs(pred - py_):
                    if cx - pc_ < 15 * zoom:
                        continue
                    pieces.append(pts)  # re-acquired somewhere else: a new piece, no bridge
                    pts = []
                elif blank:
                    pieces.append(pts)  # blank stretch: never bridge it
                    pts = []
            hist.append((cx, yc))
            pts.append((clip.x0 + (x0 + cx) / zoom, clip.y0 + (yt + yc) / zoom))
        pieces = [pc for pc in pieces + [pts] if pc]
        if sum(len(pc) for pc in pieces) >= 5:
            wmax = max(pc[-1][0] - pc[0][0] for pc in pieces)
            keep = [pc for pc in pieces if pc[-1][0] - pc[0][0] >= 0.05 * wmax]
            drop = [pc for pc in pieces if pc[-1][0] - pc[0][0] < 0.05 * wmax]
            if drop:
                warns.append("%s: dropped %d short traced fragment(s) (page x %s pt) - stray marks?"
                             % (name, len(drop), ", ".join("%.0f" % pc[0][0] for pc in drop)))
            out.append({"color": name, "kind": "line", "page_pieces": keep, "pieces": len(keep),
                        "dropped_short_pieces": len(drop), "markers_stripped": 0})
            if len(keep) > 1:
                warns.append("%s: trace lost and re-acquired %d time(s): the pieces may belong to different "
                             "curves - check overlay" % (name, len(keep) - 1))
        else:
            warns.append("%s: fewer than 5 pixels columns matched - colour not found?" % name)
    dark = [c for c in out if any(n == c["color"] and max(v) - min(v) < 40 and max(v) < 160 for n, v in colors)]
    if dark and len(out) == len(dark):
        warns.append("one black trace may merge several series (marker-only plots) or pick up ticks/frame; "
                     "if series differ by marker shape, read the marker centres by hand from --preview")
    return out, warns


# ---------------------------------------------------------------- output
def densify(pts, step):
    """Insert points along straight page-space segments so no two neighbours are more than
    `step` points apart. Exact: a PDF line segment is straight on the page, and a straight
    page segment maps to the same straight segment in data space (or a straight segment in
    log space on a log axis). CIVITA rejects curves with x gaps over 20% of the range."""
    out = [pts[0]] if pts else []
    for a, b in zip(pts[:-1], pts[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        k = int(d // step)
        for i in range(1, k + 1):
            t = i / (k + 1)
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        out.append(b)
    return out


def thin(pts, n):
    """At most n of pts, spread evenly along the path's length; the two ends always stay."""
    if len(pts) <= n:
        return list(pts)
    if n < 2:
        return [pts[0], pts[-1]][:max(n, 1)]
    P = np.asarray(pts, float)
    s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
    if s[-1] <= 0:
        return [pts[0], pts[-1]]
    idx = np.searchsorted(s, np.linspace(0, s[-1], n))
    idx = np.clip(idx, 0, len(pts) - 1)
    idx[0], idx[-1] = 0, len(pts) - 1
    return [pts[i] for i in sorted(set(int(i) for i in idx))]


def cap_pieces(pieces, n):
    """Share a budget of n points among a curve's pieces by length; each piece keeps both
    ends. Returns (pieces, over) where over is True when the ends alone exceed n."""
    total = sum(len(pc) for pc in pieces)
    if total <= n:
        return pieces, False
    lens = [max(_plen(pc), 1e-9) for pc in pieces]
    L = sum(lens)
    k = [min(len(pc), max(min(2, len(pc)), int(round(n * li / L)))) for pc, li in zip(pieces, lens)]
    while sum(k) > n:
        i = max(range(len(k)), key=lambda j: k[j])
        if k[i] <= 2:
            break
        k[i] -= 1
    return [thin(pc, ki) for pc, ki in zip(pieces, k)], sum(k) > n


def overlay(page, clip, curves, cal, path):
    from PIL import Image, ImageDraw
    img, zoom = render(page, clip, 200)
    im = Image.fromarray(img).convert("RGB")
    dr = ImageDraw.Draw(im)
    # 12 well separated hues; dots for lines, squares for scatter
    marks = [(0, 200, 0), (255, 0, 255), (255, 140, 0), (0, 170, 255), (130, 0, 210), (230, 0, 0),
             (0, 140, 130), (170, 120, 0), (0, 0, 255), (255, 80, 150), (110, 190, 0), (0, 90, 60)]
    for i, c in enumerate(curves):
        col = marks[i % len(marks)]
        X = invert_axis(cal["x"], [p[0] for p in c["points"]])
        Y = invert_axis(cal["y"], [p[1] for p in c["points"]])
        sq = c.get("kind") == "scatter"
        for x, y in zip(X, Y):
            px, py = (x - clip.x0) * zoom, (y - clip.y0) * zoom
            r = 4 if sq else 2.5
            (dr.rectangle if sq else dr.ellipse)([px - r, py - r, px + r, py + r], outline=col, width=1)
        dr.text((8, 8 + 14 * i), "%s  %s %s (%d pts)" % ("[]" if sq else "o", c["legend"], c.get("kind", ""),
                                                         len(c["points"])), fill=col)
    for ax in ("x", "y"):
        for pos, val in cal[ax]["ticks"]:
            if ax == "x":
                px, py = (pos - clip.x0) * zoom, im.height - 6
            else:
                px, py = 6, (pos - clip.y0) * zoom
            dr.line([px - 5, py, px + 5, py], fill=(255, 0, 0), width=2)
            dr.line([px, py - 5, px, py + 5], fill=(255, 0, 0), width=2)
    im.save(path)


def preview(page, clip, path, step=None):
    from PIL import Image, ImageDraw
    img, zoom = render(page, clip, 200)
    im = Image.fromarray(img).convert("RGB")
    dr = ImageDraw.Draw(im)
    step = step or max(5, round(min(clip.width, clip.height) / 10 / 5) * 5)
    x = math.ceil(clip.x0 / step) * step
    while x <= clip.x1:
        px = (x - clip.x0) * zoom
        dr.line([px, 0, px, im.height], fill=(0, 170, 255), width=1)
        dr.text((px + 2, 2), "%g" % x, fill=(0, 120, 220))
        x += step
    y = math.ceil(clip.y0 / step) * step
    while y <= clip.y1:
        py = (y - clip.y0) * zoom
        dr.line([0, py, im.width, py], fill=(255, 120, 0), width=1)
        dr.text((2, py + 2), "%g" % y, fill=(220, 90, 0))
        y += step
    im.save(path)


AXIS_TYPES = {("linear", "linear"): "linear_linear", ("log", "linear"): "log_linear",
              ("linear", "log"): "linear_log", ("log", "log"): "log_log"}


def _sig(v):
    return float("%.6g" % v)


def open_page(pdf, page_no):
    doc = open_pdf(pdf)
    if not 1 <= page_no <= len(doc):
        raise SystemExit("page %d is outside 1..%d of %s" % (page_no, len(doc), pdf))
    return doc[page_no - 1]


def digitize(pdf, page_no, crop, route="auto", calib=None, colors=None, max_points=150, include_black=False,
             box_arg=None):
    page = open_page(pdf, page_no)
    clip = rect_from_arg(page, crop)
    warns = []
    if box_arg:
        box = box_arg if isinstance(box_arg, dict) else box_from_arg(box_arg)
    else:
        box = find_axes_box(page, clip)
    if route == "auto":
        colored = [d for d in page.get_drawings() if _touches(clip, d["rect"])
                   and (d.get("color") or d.get("fill")) and not _achromatic(d.get("color") or d.get("fill"))]
        # --include-black means "the curves are black vector paths": take the vector route
        route = "vector" if colored or include_black else "raster"
    elif include_black and route == "raster":
        warns.append("--include-black only applies to the vector route; on the raster route use --colors black")
    img = zoom = None
    if route == "raster" or box is None:
        img, zoom = render(page, clip, 300)
        if box is None:
            box = raster_axes_box(img, zoom, clip)
            if route == "vector":
                warns.append("no vector axis lines found: the axes box was read from the rendered picture - "
                             "check the overlay, or pass --box")
            if box and box_cover(box, clip) < 0.3:
                warns.append("the axes box found in the picture covers only %.0f%% of the crop (x %.0f..%.0f, "
                             "y %.0f..%.0f pt): unless the crop is much larger than the plot, it is not the plot "
                             "frame - crop tighter or pass --box x0,y0,x1,y1 (PDF points, from --preview)"
                             % (100 * box_cover(box, clip), box["y_axis_x"], box["right"], box["top"], box["x_axis_y"]))
    if calib:
        cal = manual_calibration(calib)
    else:
        words = text_words(page, clip)
        # a scan's hidden text layer (OCR done by the scanner) is often wrong or misplaced
        scanned = image_cover(page, clip) >= 0.8
        if scanned or not any(parse_number(w["text"]) is not None for w in words) or digits_in_text_layer(page) == 0:
            words = ocr_words(page, clip)
        ticks = raster_ticks(img, zoom, clip, box) if img is not None else vector_ticks(page, clip, box)
        cal = auto_calibration(page, clip, box, words, ticks)
    for ax in ("x", "y"):
        r = cal[ax]["resid_pct"]
        if r is not None and r > 1.0:
            warns.append("%s-axis ticks do not fit a %s scale well (worst tick %.1f%% of span off) - check the "
                         "tick reading or pass --calib" % (ax, cal[ax]["scale"], r))
    if route == "vector":
        raw, w2 = vector_curves(page, clip, box, include_black, cal)
    else:
        cols = parse_colors(colors) if colors else auto_colors(img)
        if not cols:
            raise ValueError("no coloured curves found; pass --colors (e.g. --colors black)")
        raw, w2 = raster_curves(img, zoom, clip, box, cols)
    warns += w2
    curves = []
    step = max(clip.width, clip.height) / 50
    for c in raw:
        pieces = c["page_pieces"]
        if c["kind"] == "line":
            if route == "vector":  # straight PDF segments: densify inside each piece only, never across a gap
                pieces = [densify(pc, step) for pc in pieces]
            pieces, over = cap_pieces(pieces, max_points)
            if over:
                warns.append("%s: %d pieces need %d end points, more than --max-points %d"
                             % (c["color"], len(pieces), sum(len(pc) for pc in pieces), max_points))
        starts, P = [], []
        for pc in pieces:
            starts.append(len(P))
            P += pc
        X = apply_axis(cal["x"], [p[0] for p in P])
        Y = apply_axis(cal["y"], [p[1] for p in P])
        cv = {"legend": c["color"], "color": c["color"], "kind": c["kind"],
              "ordering": "path" if c["kind"] == "line" else "xy",
              "points": [[float(x), float(y)] for x, y in zip(X, Y)],
              "pieces": c["pieces"], "dropped_short_pieces": c["dropped_short_pieces"],
              "markers_stripped": c["markers_stripped"]}
        if c["kind"] == "line" and len(starts) > 1:
            cv["piece_starts"] = starts  # index of each piece's first point; no data between pieces
        curves.append(cv)
    if not curves:
        warns.append("no curves found in the crop" + (" (--include-black forces the vector route; for a scanned "
                                                      "plot use --colors black instead)" if include_black else ""))
    res = {"page": page_no, "crop": [clip.x0, clip.y0, clip.x1, clip.y1], "route": route,
           "calibration": cal, "axes_box": box,
           "axis_type": AXIS_TYPES[(cal["x"]["scale"], cal["y"]["scale"])]}
    if box:
        xs = apply_axis(cal["x"], [box["y_axis_x"], box["right"]])
        ys = apply_axis(cal["y"], [box["x_axis_y"], box["top"]])
        res["axis_bounds"] = {"x_min": _sig(min(xs)), "x_max": _sig(max(xs)), "y_min": _sig(min(ys)), "y_max": _sig(max(ys))}
    else:
        warns.append("no axes box found: axis_bounds is missing - read x_min, x_max, y_min, y_max from the "
                     "plot's axes by hand")
    res["curves"] = curves
    res["warnings"] = warns
    return page, clip, res


def _mkparent(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--crop")
    ap.add_argument("--route", default="auto", choices=["auto", "vector", "raster"])
    ap.add_argument("--calib")
    ap.add_argument("--colors")
    ap.add_argument("--include-black", action="store_true", help="vector route: also take black/gray paths as curves")
    ap.add_argument("--box", help="axes box x0,y0,x1,y1 in PDF points (left, top, right, bottom of the plotted "
                                  "area); overrides the detected one")
    ap.add_argument("--max-points", type=int, default=150, help="most points per line curve (default 150)")
    ap.add_argument("--out")
    ap.add_argument("--overlay")
    ap.add_argument("--preview")
    a = ap.parse_args(argv)
    if a.max_points < 2:
        ap.error("--max-points must be at least 2")
    if a.preview:
        page = open_page(a.pdf, a.page)
        _mkparent(a.preview)
        try:
            preview(page, rect_from_arg(page, a.crop), a.preview)
        except ValueError as e:
            print("Could not make the preview: %s" % e, file=sys.stderr)
            return 1
        print("preview grid (PDF points) -> " + a.preview)
        if not a.out:
            return 0
    if not a.out:
        ap.error("--out is required unless only --preview is asked for")
    try:
        page, clip, res = digitize(a.pdf, a.page, a.crop, a.route, a.calib, a.colors, a.max_points, a.include_black,
                                   a.box)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as e:
        print("Could not digitize: %s" % e, file=sys.stderr)
        return 1
    _mkparent(a.out)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    if a.overlay and res["curves"]:
        _mkparent(a.overlay)
        overlay(page, clip, res["curves"], res["calibration"], a.overlay)
    cal = res["calibration"]
    print("page %d, %s route, calibration %s (x %s, y %s)" % (res["page"], res["route"], cal["method"],
                                                               cal["x"]["scale"], cal["y"]["scale"]))
    if "axis_bounds" in res:
        b = res["axis_bounds"]
        print("  axis bounds x %g..%g, y %g..%g (%s)" % (b["x_min"], b["x_max"], b["y_min"], b["y_max"], res["axis_type"]))
    for c in res["curves"]:
        xs = [p[0] for p in c["points"]]
        ys = [p[1] for p in c["points"]]
        print("  %-8s %-7s %4d pts  x %.4g..%.4g  y %.4g..%.4g" % (c["color"], c["kind"], len(xs), min(xs), max(xs), min(ys), max(ys)))
    for w in res["warnings"]:
        print("WARNING: " + w)
    if a.overlay:
        print("overlay -> %s  (open it: points must sit on the printed curves)" % a.overlay)
    return 0


if __name__ == "__main__":
    sys.exit(main())
