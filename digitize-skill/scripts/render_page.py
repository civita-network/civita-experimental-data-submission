"""Render a PDF page (or a crop of it) to a PNG, to look at a table or figure.

Usage: python render_page.py PAPER.pdf --page 14 --out p14.png [--crop x0,y0,x1,y1] [--dpi 200]

--page is 1-based. --crop is in PDF points, or fractions of the page (all values <= 1),
measured on the page as it is displayed. Very large renders are scaled down to stay
under about 60 megapixels.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdf_util import open_pdf, rect_from_arg, render  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--crop")
    ap.add_argument("--dpi", type=int, default=200)
    a = ap.parse_args(argv)
    if not 36 <= a.dpi <= 900:
        ap.error("--dpi must be between 36 and 900")
    doc = open_pdf(a.pdf)
    if not 1 <= a.page <= len(doc):
        print("page %d is outside 1..%d" % (a.page, len(doc)), file=sys.stderr)
        return 1
    page = doc[a.page - 1]
    try:
        clip = rect_from_arg(page, a.crop)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    from PIL import Image
    img, zoom = render(page, clip, a.dpi)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    Image.fromarray(img).save(a.out)
    print("page %d -> %s (%dx%d px, %.0f dpi)" % (a.page, a.out, img.shape[1], img.shape[0], zoom * 72))
    return 0


if __name__ == "__main__":
    sys.exit(main())
