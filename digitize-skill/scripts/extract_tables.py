"""Read a table from a PDF page into a grid of cells, with a flag column for anything doubtful.

Usage:
  python extract_tables.py PAPER.pdf --page 4 [--crop x0,y0,x1,y1] [--mode auto|text|ocr]
                           --out table_p4.csv [--min-conf 0.90]

How it works (lessons from digitizing ~70,000 cells of scanned fire-test reports):
  - Check the text layer for DIGITS, not for text. Scans often carry captions in a text
    layer but no data values; then the page goes to OCR.
  - Cells are placed in columns by their x-position (column anchors found from all rows),
    never by reading a row left-to-right as a sequence: a blank cell would shift every
    later value one column left without any error. Here a blank simply stays blank.
  - Nothing is corrected automatically. Doubtful cells are flagged in the output.

Output CSV: the grid as printed (row 1 is usually the header), plus <out>.flags.csv
listing every flagged cell (row, column, text, reason) and <out>.cells.json with the
position and OCR confidence of every cell.
"""
import argparse
import csv
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_util import digits_in_text_layer, ocr_words, open_pdf, parse_number, rect_from_arg, text_words, image_cover  # noqa: E402


def cluster_1d(values, gap):
    """Group sorted values whose neighbours are closer than gap; returns group means."""
    if not values:
        return []
    vs = sorted(values)
    groups = [[vs[0]]]
    for v in vs[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [sum(g) / len(g) for g in groups]


def words_to_grid(words):
    if not words:
        return [], []
    heights = [w["y1"] - w["y0"] for w in words]
    h = statistics.median(heights)
    # rows: cluster by vertical centre
    words = sorted(words, key=lambda w: (w["y0"] + w["y1"]) / 2)
    rows = []
    for w in words:
        yc = (w["y0"] + w["y1"]) / 2
        if rows and abs(yc - rows[-1]["yc"]) <= 0.5 * h:
            rows[-1]["w"].append(w)
            rows[-1]["yc"] = sum((x["y0"] + x["y1"]) / 2 for x in rows[-1]["w"]) / len(rows[-1]["w"])
        else:
            rows.append({"yc": yc, "w": [w]})
    # merge words that belong to one cell (gap smaller than ~0.6 of a character height)
    for r in rows:
        r["w"].sort(key=lambda w: w["x0"])
        merged = []
        for w in r["w"]:
            if merged and w["x0"] - merged[-1]["x1"] < 0.6 * h and not _both_numbers(merged[-1]["text"], w["text"]):
                m = merged[-1]
                m["text"] += " " + w["text"]
                m["x1"] = max(m["x1"], w["x1"])
                m["conf"] = min(m["conf"], w["conf"])
            else:
                merged.append(dict(w))
        r["w"] = merged
    # column anchors from right edges of numbers (numbers are usually right- or centre-aligned)
    centres = [(w["x0"] + w["x1"]) / 2 for r in rows for w in r["w"]]
    anchors = cluster_1d(centres, gap=1.2 * h)
    grid, cells = [], []
    for ri, r in enumerate(rows):
        line = [""] * len(anchors)
        for w in r["w"]:
            xc = (w["x0"] + w["x1"]) / 2
            ci = min(range(len(anchors)), key=lambda k: abs(anchors[k] - xc))
            if line[ci]:
                line[ci] += " " + w["text"]
                cells.append({"row": ri + 1, "col": ci + 1, "text": w["text"], "conf": w["conf"],
                              "bbox": [w["x0"], w["y0"], w["x1"], w["y1"]], "flag": "two values fell in one column"})
            else:
                line[ci] = w["text"]
                cells.append({"row": ri + 1, "col": ci + 1, "text": w["text"], "conf": w["conf"],
                              "bbox": [w["x0"], w["y0"], w["x1"], w["y1"]], "flag": ""})
        grid.append(line)
    return grid, cells


def _both_numbers(a, b):
    return parse_number(a) is not None and parse_number(b) is not None


def flag_cells(grid, cells, min_conf):
    """Generic checks only. Domain checks (monotonic furnace curves, unit magnitudes) belong
    to the person who knows the data; list them in the skill run, never auto-fix."""
    flags = []
    for c in cells:
        if c["flag"]:
            flags.append((c["row"], c["col"], c["text"], c["flag"]))
        if c["conf"] < min_conf:
            flags.append((c["row"], c["col"], c["text"], "OCR confidence %.2f" % c["conf"]))
    ncol = max((len(r) for r in grid), default=0)
    body = grid[1:] if len(grid) > 1 else grid
    for ci in range(ncol):
        col = [(ri + 2, r[ci]) for ri, r in enumerate(body) if ci < len(r) and r[ci].strip()]
        filled = [ri for ri, _ in col]
        if len(body) >= 5 and len(col) >= 0.8 * len(body):
            # a blank in a column that is otherwise full is either a real blank (dead sensor,
            # "-" in the paper) or a value OCR dropped: a person has to look
            for ri in range(2, len(body) + 2):
                r = body[ri - 2]
                if ri not in filled and sum(parse_number(x) is not None for x in r) >= 3:
                    flags.append((ri, ci + 1, "", "blank in a column that is otherwise filled - check the page"))
        nums = [(ri, parse_number(t), t) for ri, t in col]
        numeric = [n for n in nums if n[1] is not None]
        if len(numeric) >= 3 and len(numeric) >= 0.7 * len(col):
            for ri, v, t in nums:
                if v is None:
                    flags.append((ri, ci + 1, t, "not a number in a numeric column"))
            mags = [abs(v) for _, v, _ in numeric if v != 0]
            if mags:
                med = statistics.median(mags)
                for ri, v, t in numeric:
                    if med > 0 and v != 0 and (abs(v) > 10 * med or abs(v) < med / 10):
                        flags.append((ri, ci + 1, t, "magnitude far from the column (median %g)" % med))
                decs = [len(t.split(".")[1]) if "." in t else 0 for _, _, t in numeric]
                common = statistics.mode(decs)
                for (ri, v, t), d in zip(numeric, decs):
                    if d != common:
                        flags.append((ri, ci + 1, t, "decimals differ from the column (%d vs %d) - possible lost decimal point" % (d, common)))
    return sorted(set(flags))


def extract(pdf, page_no, crop=None, mode="auto", min_conf=0.90):
    doc = open_pdf(pdf)
    if not 1 <= page_no <= len(doc):
        raise SystemExit("page %d is outside 1..%d" % (page_no, len(doc)))
    page = doc[page_no - 1]
    clip = rect_from_arg(page, crop)
    use = mode
    note = ""
    if mode == "auto":
        if image_cover(page, clip) >= 0.8:
            # A scanned page often carries a hidden OCR text layer made by the scanner software.
            # It is usually worse than a fresh OCR (split numbers like "1 02", "31 .O", lost rows),
            # so a scan always goes to OCR. Use --mode text to force the hidden layer.
            use = "ocr"
            if digits_in_text_layer(page) >= 20:
                note = "scanned page with a hidden text layer: ignored it and ran OCR (force with --mode text)"
        else:
            use = "text" if digits_in_text_layer(page) >= 20 and any(
                ch.isdigit() for w in text_words(page, clip) for ch in w["text"]) else "ocr"
    words = text_words(page, clip) if use == "text" else ocr_words(page, clip)
    grid, cells = words_to_grid(words)
    flags = flag_cells(grid, cells, min_conf)
    return {"page": page_no, "crop": [clip.x0, clip.y0, clip.x1, clip.y1], "mode": use,
            "grid": grid, "cells": cells, "flags": flags, "note": note}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--crop")
    ap.add_argument("--mode", default="auto", choices=["auto", "text", "ocr"])
    ap.add_argument("--min-conf", type=float, default=0.90)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    try:
        res = extract(a.pdf, a.page, a.crop, a.mode, a.min_conf)
    except ValueError as e:
        print("Could not read the table: %s" % e, file=sys.stderr)
        return 1
    if not res["grid"]:
        print("ZERO rows read from page %d (%s mode). A page that yields nothing is invisible to every "
              "later check: look at the page, fix the crop, or try --mode ocr." % (a.page, res["mode"]), file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(res["grid"])
    base = a.out.rsplit(".", 1)[0]
    with open(base + ".flags.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["row", "col", "text", "reason"])
        w.writerows(res["flags"])
    with open(base + ".cells.json", "w", encoding="utf-8") as f:
        json.dump({k: res[k] for k in ("page", "crop", "mode", "cells")}, f, indent=1)
    print("page %d (%s): %d rows x %d columns, %d flagged cell(s) -> %s"
          % (a.page, res["mode"], len(res["grid"]), max(len(r) for r in res["grid"]), len(res["flags"]), a.out))
    if res.get("note"):
        print("NOTE: " + res["note"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
