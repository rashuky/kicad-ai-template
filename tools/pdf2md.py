"""Convert a datasheet PDF to raw markdown, as the starting point for datasheet/<Part>.md.

usage: python tools/pdf2md.py datasheet/PART.pdf [-o datasheet/PART.raw.md] [--pages 1-12]

Uses pymupdf4llm (tables as markdown) when installed, else plain pymupdf text with page markers.
The output is raw. Condense it into datasheet/<Part>.md with datasheet/_TEMPLATE.md, then delete the .raw.md.
"""
import argparse, os, sys


def page_list(spec, count):
    if not spec:
        return list(range(count))
    pages = []
    for part in spec.split(","):
        a, dash, b = part.partition("-")
        end = int(b) if b else (count if dash else int(a))
        pages += range(int(a or 1) - 1, min(end, count))
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out")
    ap.add_argument("--pages", help="1-based, e.g. 1-12 or 1-3,7")
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.pdf)[0] + ".raw.md"
    try:
        import pymupdf
    except ImportError:
        sys.exit("pymupdf missing: python -m pip install --user pymupdf pymupdf4llm")
    doc = pymupdf.open(a.pdf)
    pages = page_list(a.pages, doc.page_count)
    try:
        try:
            import pymupdf.layout  # noqa: F401  better reading order, activates when imported before pymupdf4llm
        except ImportError:
            pass
        import pymupdf4llm
        md = pymupdf4llm.to_markdown(doc, pages=pages)
    except ImportError:
        md = "\n\n".join(f"<!-- page {i + 1} -->\n\n" + doc[i].get_text("text") for i in pages)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"<!-- raw conversion of {os.path.basename(a.pdf)}, {len(pages)} of {doc.page_count} pages -->\n\n{md}")
    print(f"{out}: {len(md)} chars from {len(pages)} pages")


if __name__ == "__main__":
    main()
