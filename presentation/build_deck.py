"""Build BatchGuard's seven-slide, evidence-bounded hackathon pitch PDF."""
from pathlib import Path
from reportlab.lib.colors import HexColor, Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "presentation" / "BatchGuard_Pitch_Deck.pdf"
W, H = 960, 540
BG, INK, MUTED = "#F7F8F6", "#152A35", "#63737A"
TEAL, TEAL_LIGHT, LINE = "#087E86", "#DDF0EE", "#DCE4E1"
ORANGE, ORANGE_LIGHT, WHITE = "#DF7650", "#F9E9E1", "#FFFFFF"
font_path = ROOT / "app" / "fonts" / "Geist.woff2"
try:
    font = TTFont("GeistPitch", str(font_path))
    font.face.name = "GeistPitch"
    pdfmetrics.registerFont(font)
    FACE = "GeistPitch"
except Exception:
    FACE = "Helvetica"


def color(hex_value):
    return HexColor(hex_value)


def txt(c, x, y, text, size=16, fill=INK, face=FACE):
    c.setFillColor(color(fill))
    c.setFont(face, size)
    c.drawString(x, y, str(text))


def wrapped(c, x, y, text, width, size=15, fill=INK, leading=None, face=FACE):
    leading = leading or size * 1.42
    lines = simpleSplit(text, face, size, width)
    for i, line in enumerate(lines):
        txt(c, x, y - i * leading, line, size, fill, face)
    return y - len(lines) * leading


def rr(c, x, y, w, h, fill=WHITE, stroke=LINE, r=16, sw=1):
    c.setLineWidth(sw)
    c.setFillColor(color(fill))
    c.setStrokeColor(color(stroke))
    c.roundRect(x, y, w, h, r, fill=1, stroke=1)


def line(c, x1, y1, x2, y2, stroke=LINE, sw=1):
    c.setStrokeColor(color(stroke))
    c.setLineWidth(sw)
    c.line(x1, y1, x2, y2)


def base(c, n, section, title, subtitle=None):
    c.setFillColor(color(BG))
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(color(TEAL))
    c.rect(0, H - 7, W, 7, fill=1, stroke=0)
    txt(c, 54, 501, "BATCHGUARD   /   " + section.upper(), 10, TEAL)
    txt(c, 54, 459, title, 29, INK)
    if subtitle:
        txt(c, 54, 432, subtitle, 12, MUTED)
    line(c, 54, 35, 906, 35)
    txt(c, 54, 18, "Make the next inspection count.", 9, MUTED)
    txt(c, 875, 18, f"{n:02d} / 07", 9, MUTED)


def pill(c, x, y, label, fill=TEAL_LIGHT, ink=TEAL, width=None):
    width = width or pdfmetrics.stringWidth(label, FACE, 10) + 24
    c.setFillColor(color(fill))
    c.roundRect(x, y, width, 25, 12, fill=1, stroke=0)
    txt(c, x + 12, y + 8, label, 10, ink)


def slide1(c):
    c.setFillColor(color(BG)); c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(color(TEAL)); c.rect(0, H-7, W, 7, fill=1, stroke=0)
    txt(c, 60, 476, "REAL-TIME AI FOR CRITICAL DECISIONS  /  IBM Z DATATHON", 11, TEAL)
    txt(c, 60, 405, "BatchGuard", 52, INK)
    wrapped(c, 62, 359, "Make the next inspection count.", 520, 22, MUTED, 30)
    pill(c, 62, 298, "INSPECTOR DECISION SUPPORT")
    txt(c, 62, 224, "12 batches.", 36, INK)
    txt(c, 62, 177, "4 inspection slots.", 36, INK)
    txt(c, 62, 119, "Which four—and why?", 24, TEAL)
    # Twelve candidate cards and four finite slots.
    for i in range(12):
        x = 620 + (i % 4) * 64
        y = 343 - (i // 4) * 57
        rr(c, x, y, 50, 42, WHITE, LINE, 10)
        txt(c, x + 17, y + 15, f"{i+1:02d}", 12, MUTED)
    txt(c, 620, 135, "INSPECTION CAPACITY", 10, MUTED)
    for i in range(4):
        rr(c, 620 + i*70, 80, 58, 38, TEAL_LIGHT, TEAL_LIGHT, 10)
        txt(c, 638 + i*70, 94, "NEXT", 9, TEAL)
    txt(c, 60, 30, "Illustrative capacity scenario · human review remains in control", 9, MUTED)
    txt(c, 875, 30, "01 / 07", 9, MUTED)
    c.showPage()


def slide2(c):
    base(c, 2, "Who benefits", "Make evidence easier to act on.", "A clearer handoff from a shortlist to a documented human review.")
    cards = [
        ("01", "Drug inspectors", "See what to review first, why it ranked, and which source report supports the case.", TEAL_LIGHT, TEAL),
        ("02", "Review teams", "Trace recommendation context and keep reviewer actions attached to the case.", "#E8EEF4", "#536D83"),
        ("03", "Lab coordinators", "Receive the report and scan context behind a proposed sample.", ORANGE_LIGHT, ORANGE),
    ]
    for i, (num, name, desc, fill, accent) in enumerate(cards):
        x = 54 + i * 286
        rr(c, x, 212, 266, 182, WHITE, LINE, 18)
        pill(c, x + 20, 350, num, fill, accent, 42)
        txt(c, x + 20, 316, name, 20, INK)
        wrapped(c, x + 20, 286, desc, 222, 13, MUTED, 19)
    rr(c, 54, 88, 852, 76, INK, INK, 16)
    txt(c, 78, 132, "EXPECTED VALUE", 10, "#8DD2CC")
    txt(c, 78, 105, "Prioritize with evidence. Explain the choice. Record the decision.", 17, WHITE)
    txt(c, 56, 52, "Intended workflow value; time savings, clinical outcomes and adoption are not yet measured.", 10, MUTED)
    c.showPage()


def slide3(c):
    base(c, 3, "Dataset", "Real reports. Simulated scans.", "The two evidence streams stay separate and visibly labelled.")
    # headline metrics
    for x, value, label in [(54, "2,551", "analytical records"), (337, "14 months", "Jul 2025 – Aug 2026"), (620, "2,451", "match captured official fields")]:
        rr(c, x, 340, 260, 76, WHITE, LINE, 14)
        txt(c, x+18, 379, value, 25, TEAL)
        txt(c, x+18, 357, label, 11, MUTED)
    rr(c, 54, 125, 408, 178, "#FFFFFF", LINE, 16)
    pill(c, 75, 260, "REAL · CDSCO REPORTS")
    txt(c, 75, 224, "Product, batch, maker text", 17, INK)
    txt(c, 75, 196, "Reported quality findings", 14, MUTED)
    txt(c, 75, 171, "Workbook, sheet and row references", 14, MUTED)
    txt(c, 75, 143, "100 records flagged for review", 11, ORANGE)
    rr(c, 498, 125, 408, 178, "#FFFFFF", LINE, 16)
    pill(c, 519, 260, "SIMULATED · PACK SCANS", ORANGE_LIGHT, ORANGE)
    txt(c, 519, 224, "Pack IDs, readers, times", 17, INK)
    txt(c, 519, 196, "Scripted location conflicts and bursts", 14, MUTED)
    txt(c, 519, 171, "Used to exercise pipeline behavior", 14, MUTED)
    txt(c, 519, 143, "Not field accuracy or counterfeit proof", 11, ORANGE)
    txt(c, 56, 79, "Report recurrence is not a medicine-safety label. Maker text is not verified legal identity.", 11, MUTED)
    c.showPage()


def slide4(c):
    base(c, 4, "Solution", "An inspection queue you can explain.", "History model ranks report recurrence; explicit rules flag unusual scan patterns.")
    # Chart: report records captured on same budget.
    chart_x, chart_y, chart_h = 114, 132, 210
    line(c, chart_x, chart_y, chart_x + 360, chart_y, LINE, 1)
    for tick in (0, 5, 10, 15, 20, 25):
        y = chart_y + tick / 25 * chart_h
        line(c, chart_x, y, chart_x + 350, y, "#E8ECEA", 0.6)
        txt(c, chart_x - 28, y - 3, str(tick), 8, MUTED)
    for x, val, label, fill in [(177, 13.06, "Best baseline", "#A7B6BA"), (331, 21, "BatchGuard", TEAL)]:
        bh = val / 25 * chart_h
        c.setFillColor(color(fill)); c.roundRect(x, chart_y, 92, bh, 8, fill=1, stroke=0)
        txt(c, x+12, chart_y+bh+10, f"{val:g}", 18, INK)
        txt(c, x-6, chart_y-22, label, 11, MUTED)
    txt(c, 114, 373, "Later report records captured", 13, MUTED)
    rr(c, 576, 187, 300, 174, TEAL_LIGHT, TEAL_LIGHT, 18)
    txt(c, 603, 312, "+61%", 43, TEAL)
    wrapped(c, 603, 275, "more later report records captured at the same ranking budget", 242, 16, INK, 23)
    pill(c, 603, 205, "BUDGET: 25 MAKER TEXTS / MONTH")
    wrapped(c, 114, 88, "History-only test, July–August 2026. Baseline: recent report counts. This compares report recurrence, not unsafe batches found. Separate from the simulated scan demo.", 745, 10, MUTED, 14)
    c.showPage()


def slide5(c):
    base(c, 5, "Workflow", "One input. One traceable review.", "A simulated case shows how a new signal changes the queue.")
    labels = [("1", "CSV input"), ("2", "Validate"), ("3", "Score"), ("4", "Rank"), ("5", "Open evidence"), ("6", "Record review")]
    widths = [116, 106, 100, 96, 142, 138]
    x = 54; y = 335
    for i, ((num, label), width) in enumerate(zip(labels, widths)):
        rr(c, x, y, width, 78, WHITE, LINE, 15)
        pill(c, x+14, y+43, num, TEAL_LIGHT, TEAL, 28)
        txt(c, x+14, y+18, label, 12, INK)
        x += width + 19
        if i < len(labels)-1:
            c.setStrokeColor(color(TEAL)); c.setLineWidth(2)
            c.line(x-17, y+39, x-6, y+39)
            c.line(x-6, y+39, x-11, y+43)
            c.line(x-6, y+39, x-11, y+35)
    rr(c, 54, 148, 388, 128, INK, INK, 18)
    txt(c, 78, 239, "SCRIPTED DEMO · CSV INPUT", 10, "#8DD2CC")
    txt(c, 78, 190, "Rank 12  →  Rank 4", 29, WHITE)
    txt(c, 78, 166, "Inside four available slots", 12, "#CFD9DA")
    rr(c, 470, 148, 436, 128, ORANGE_LIGHT, ORANGE_LIGHT, 18)
    txt(c, 494, 239, "WHAT CHANGES THE RANK?", 10, ORANGE)
    wrapped(c, 494, 209, "A simulated same-pack location conflict triggers a review rule. Removing the conflict makes the scripted check fail.", 382, 15, INK, 22)
    txt(c, 56, 98, "The demo exercises the pipeline; it does not validate counterfeit detection in the field.", 11, MUTED)
    c.showPage()


def slide6(c):
    base(c, 6, "IBM Z run", "Executed on IBM LinuxONE.", "A real s390x deployment run—not a hardware-acceleration claim.")
    rr(c, 54, 172, 440, 238, INK, INK, 20)
    pill(c, 80, 360, "IBM LINUXONE · s390x", "#27434C", "#9BE0D9", 180)
    txt(c, 80, 311, "Models retrained", 24, WHITE)
    txt(c, 80, 278, "on the host's scikit-learn 1.9.0", 15, "#CFD9DA")
    line(c, 80, 253, 454, 253, "#46616A")
    txt(c, 80, 224, "Preflight passed", 15, "#9BE0D9")
    txt(c, 80, 196, "Service health returned HTTP 200", 13, "#CFD9DA")
    rr(c, 536, 172, 370, 238, WHITE, LINE, 20)
    txt(c, 564, 365, "What LinuxONE does here", 18, INK)
    for i, item in enumerate(["Hosts the central Python service", "Runs model inference and queue ranking", "Keeps review state with the service"]):
        c.setFillColor(color(TEAL)); c.circle(572, 323-i*42, 4, fill=1, stroke=0)
        txt(c, 587, 319-i*42, item, 13, INK)
    rr(c, 564, 194, 314, 42, ORANGE_LIGHT, ORANGE_LIGHT, 10)
    txt(c, 579, 209, "Standard CPU · NNPA not used or measured", 10, ORANGE)
    wrapped(c, 56, 119, "The model is portable; it does not require IBM Z. The demonstrated value is running the shared decision service on the LinuxONE host.", 815, 12, MUTED, 18)
    c.showPage()


def slide7(c):
    base(c, 7, "Research & references", "A decision that can be inspected.", "Sources and limits are part of the product.")
    items = [
        ("PUBLIC DATA", "CDSCO NSQ and spurious-drug reports; original source references retained.", "https://cdscoonline.gov.in"),
        ("EVALUATION", "Chronological report-recurrence test, compared with a recent-count baseline.", "July–August 2026 · top 25 / month"),
        ("PLATFORM", "LinuxONE s390x run verified; no NNPA or hardware speedup claimed.", "IBM LinuxONE · IBM Snap ML"),
        ("MAP", "Natural Earth 1:10m India point-of-view geometry; contextual map only.", "naturalearthdata.com/downloads/10m-cultural-vectors/"),
    ]
    for i, (tag, desc, ref) in enumerate(items):
        y = 355-i*72
        pill(c, 58, y, tag, TEAL_LIGHT if i != 2 else "#E8EEF4", TEAL if i != 2 else "#536D83", 134)
        txt(c, 212, y+8, desc, 12, INK)
        txt(c, 690, y+8, ref, 10, MUTED)
        line(c, 58, y-16, 900, y-16)
    rr(c, 58, 65, 842, 48, INK, INK, 13)
    txt(c, 80, 83, "BatchGuard prioritizes review. Inspectors and laboratories determine what happens next.", 13, WHITE)
    c.showPage()


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUT), pagesize=(W, H), pageCompression=1)
    c.setTitle("BatchGuard — IBM Z Datathon Pitch")
    c.setAuthor("BatchGuard Team")
    c.setSubject("Seven-slide pitch: explainable medicine inspection prioritization")
    for page in (slide1, slide2, slide3, slide4, slide5, slide6, slide7):
        page(c)
    c.save()
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
