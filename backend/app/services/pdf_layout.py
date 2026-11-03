"""Styled GDD PDFs: 'pro' (studio document) and 'gamebook' (game manual).

Pure fpdf2 (no system dependency, identical output in tests and prod).
render_gdd_pdf() never raises: failures return (None, french-error).
"""

import io
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

try:
    from fpdf import FPDF  # type: ignore

    HAS_FPDF = True
except ImportError:
    FPDF = None  # type: ignore
    HAS_FPDF = False

try:
    from PIL import Image  # type: ignore

    HAS_PIL = True
except ImportError:
    Image = None  # type: ignore
    HAS_PIL = False

logger = logging.getLogger(__name__)

STYLES = ("pro", "gamebook")

_REPLACEMENTS = {
    "…": "...",
    "→": "->",
    "←": "<-",
    "—": "-",
    "–": "-",
    "«": '"',
    "»": '"',
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "•": "-",
    "✓": "OK",
    "✗": "X",
    "⚡": "*",
    "🎮": "",
    "📄": "",
    "💻": "",
    "🎨": "",
}


def _t(value: Any) -> str:
    """Sanitize to latin-1 (fpdf2 core fonts). Never raises."""
    s = "" if value is None else str(value)
    for old, new in _REPLACEMENTS.items():
        s = s.replace(old, new)
    return s.encode("latin-1", "replace").decode("latin-1")


_LEVEL_ALIASES = {
    "level_name": ("level_name", "name", "level", "title"),
    "progression_focus": ("progression_focus", "focus", "description", "objective"),
    "mechanics_introduced": ("mechanics_introduced", "mechanics"),
    "enemies_introduced": ("enemies_introduced", "enemies"),
    "estimated_play_time": ("estimated_play_time", "playtime", "play_time", "time", "duration"),
}


def _level_field(lvl: Dict[str, Any], keys: tuple) -> Any:
    for key in keys:
        value = lvl.get(key)
        if value:
            return value
    return None


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def _blocks(gdd: Dict[str, Any]) -> List[tuple]:
    """Shared content model: (kind, payload) blocks. Kinds: h1,h2,p,bullets,kv,table."""
    doc_type = str(gdd.get("document_type") or "")
    scoped = doc_type in ("one_sheet", "ten_pager", "beat_chart", "full_gdd")
    want_beat = (not scoped) or doc_type in ("beat_chart", "full_gdd")
    want_ten = (not scoped) or doc_type in ("ten_pager", "full_gdd")
    want_full = (not scoped) or doc_type == "full_gdd"
    out: List[tuple] = []
    sheet = gdd.get("one_sheet") or {}
    if not isinstance(sheet, dict):
        sheet = {}
    out.append(("h1", "One-Sheet"))
    if sheet.get("story_summary"):
        out.append(("p", str(sheet["story_summary"])))
    meta = []
    if sheet.get("target_systems"):
        meta.append(("Systems", ", ".join(str(x) for x in sheet["target_systems"])))
    if sheet.get("target_age"):
        meta.append(("Target age", str(sheet["target_age"])))
    if sheet.get("esrb_rating"):
        meta.append(("ESRB", str(sheet["esrb_rating"])))
    if sheet.get("gameplay_modes"):
        meta.append(("Modes", ", ".join(str(x) for x in sheet["gameplay_modes"])))
    if sheet.get("competitive_products"):
        meta.append(("Competitors", ", ".join(str(x) for x in sheet["competitive_products"])))
    if meta:
        out.append(("kv", meta))
    if sheet.get("usps"):
        out.append(("h2", "USPs"))
        out.append(("bullets", [str(u) for u in sheet["usps"]]))
    beat = gdd.get("beat_chart") or []
    if want_beat and isinstance(beat, list) and beat:
        out.append(("h1", "Beat Chart"))
        rows = []
        for lvl in beat:
            # LLM-regenerated docs (fix agent) don't always keep the exact
            # level schema: accept renamed keys and bare-string levels.
            if isinstance(lvl, str):
                lvl = {"level_name": lvl}
            if not isinstance(lvl, dict):
                continue
            rows.append(
                [
                    str(_level_field(lvl, _LEVEL_ALIASES["level_name"]) or "?"),
                    str(_level_field(lvl, _LEVEL_ALIASES["progression_focus"]) or ""),
                    ", ".join(_as_str_list(_level_field(lvl, _LEVEL_ALIASES["mechanics_introduced"]))),
                    ", ".join(_as_str_list(_level_field(lvl, _LEVEL_ALIASES["enemies_introduced"]))),
                    str(_level_field(lvl, _LEVEL_ALIASES["estimated_play_time"]) or "?"),
                ]
            )
        if rows:
            out.append(("table", ["Level", "Focus", "Mechanics", "Enemies", "Time"], rows))
    ten = gdd.get("ten_pager") or {}
    if want_ten and isinstance(ten, dict) and any(ten.values()):
        out.append(("h1", "Ten-Pager (3C)"))
        rows3c = []
        if ten.get("camera"):
            rows3c.append(("Camera", str(ten["camera"])))
        if ten.get("character"):
            rows3c.append(("Character", str(ten["character"])))
        if ten.get("controls"):
            rows3c.append(("Controls", str(ten["controls"])))
        if ten.get("core_loop"):
            rows3c.append(("Core loop", str(ten["core_loop"])))
        if ten.get("menu_flow"):
            rows3c.append(("Menu flow", str(ten["menu_flow"])))
        if rows3c:
            out.append(("kv", rows3c))
    full = gdd.get("full_gdd") or {}
    if want_full and isinstance(full, dict) and any(full.values()):
        out.append(("h1", "Full GDD"))
        if full.get("lore"):
            out.append(("h2", "Lore"))
            out.append(("p", str(full["lore"])))
        if full.get("level_design"):
            out.append(("h2", "Level Design"))
            out.append(("p", str(full["level_design"])))
        if full.get("features"):
            out.append(("h2", "Features"))
            out.append(("bullets", [str(x) for x in full["features"]]))
        tech = []
        if full.get("ai_type"):
            tech.append(("AI", str(full["ai_type"])))
        if full.get("physics_engine"):
            tech.append(("Physics", str(full["physics_engine"])))
        if tech:
            out.append(("kv", tech))
    if gdd.get("visual_style_prompt"):
        out.append(("h1", "Visual Style"))
        out.append(("p", str(gdd["visual_style_prompt"])))
    return out


def _cover_png(raw: Optional[bytes]) -> Optional[bytes]:
    """Normalize any image bytes to PNG (capped size). None on any failure."""
    if not raw or not HAS_PIL or Image is None:
        return None
    try:
        if len(raw) > 6 * 1024 * 1024:
            return None
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")
        img.thumbnail((1200, 1200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


class _BaseDoc(FPDF):  # type: ignore
    title_text = ""
    footer_text = ""

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-15)
        self.set_font(self.footer_font, "", 8)
        self.set_text_color(*self.footer_color)
        self.cell(0, 10, _t(self.footer_text).format(n=self.page_no()), align="C")


class _ProDoc(_BaseDoc):
    footer_font = "helvetica"
    footer_color = (100, 116, 139)


class _BookDoc(_BaseDoc):
    footer_font = "times"
    footer_color = (122, 31, 31)

    def header(self):
        # Parchment background on every page (cover included).
        self.set_fill_color(243, 233, 210)
        self.rect(0, 0, 210, 297, style="F")


def _render_blocks(pdf: FPDF, blocks: List[tuple], style: str) -> None:  # type: ignore
    is_pro = style == "pro"
    body_font = "helvetica" if is_pro else "times"
    head_color = (37, 99, 235) if is_pro else (122, 31, 31)
    ink = (15, 23, 42) if is_pro else (43, 32, 24)
    for block in blocks:
        kind = block[0]
        if kind == "h1":
            pdf.ln(4)
            pdf.set_font(body_font, "B", 16)
            pdf.set_text_color(*head_color)
            pdf.start_section(_t(block[1]))
            pdf.cell(0, 10, _t(block[1]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(*head_color)
            pdf.set_line_width(0.6)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            if not is_pro:
                pdf.ln(1)
                pdf.set_line_width(0.2)
                pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)
        elif kind == "h2":
            pdf.ln(2)
            pdf.set_font(body_font, "B", 12)
            pdf.set_text_color(*head_color)
            pdf.cell(0, 8, _t(block[1]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif kind == "p":
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*ink)
            pdf.multi_cell(0, 5.5, _t(block[1]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "bullets":
            pdf.set_font(body_font, "", 10)
            pdf.set_text_color(*ink)
            for item in block[1]:
                pdf.cell(6, 5.5, "-")
                pdf.multi_cell(0, 5.5, _t(item), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "kv":
            pdf.set_font(body_font, "", 10)
            for key, val in block[1]:
                pdf.set_text_color(*head_color)
                pdf.set_font(body_font, "B", 10)
                pdf.write(5.5, _t(key) + ":  ")
                pdf.set_text_color(*ink)
                pdf.set_font(body_font, "", 10)
                pdf.multi_cell(0, 5.5, _t(val), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "table":
            _headers, rows = block[1], block[2]
            pdf.set_font(body_font, "", 8)
            pdf.set_text_color(*ink)
            widths = (32, 62, 40, 36, 20)
            with pdf.table(
                col_widths=widths,
                first_row_as_headings=True,
                line_height=5,
                text_align="LEFT",
            ) as table:
                head = table.row()
                for h in _headers:
                    head.cell(_t(h))
                for row in rows:
                    tr = table.row()
                    for cell in row:
                        tr.cell(_t(cell))
            pdf.ln(3)


def render_gdd_pdf(
    gdd: Dict[str, Any], style: str, cover_bytes: Optional[bytes] = None
) -> Tuple[Optional[bytes], Optional[str]]:
    """Render a styled PDF. Returns (pdf_bytes, None) or (None, french-error)."""
    if style not in STYLES:
        return None, "Style PDF inconnu (pro ou gamebook)."
    if not HAS_FPDF or FPDF is None:
        logger.warning("fpdf2 missing: cannot render styled PDF.")
        return None, "PDF indisponible : dépendance fpdf2 manquante."
    if not isinstance(gdd, dict) or not gdd:
        return None, "Le document PDF ne peut pas être vide."
    try:
        is_pro = style == "pro"
        pdf = _ProDoc() if is_pro else _BookDoc()
        sheet = gdd.get("one_sheet") or {}
        if not isinstance(sheet, dict):
            sheet = {}
        title = _t(sheet.get("title") or "Untitled Game")
        doc_type = _t(gdd.get("document_type") or "")
        pdf.title_text = title
        pdf.set_title(title)
        pdf.set_author("MultiModal-GameArchitect")
        pdf.footer_text = f"{title}  |  {{n}}" if is_pro else "- {{n}} -"
        # Cover page.
        pdf.add_page()
        if is_pro:
            pdf.set_fill_color(15, 23, 42)
            pdf.rect(0, 0, 210, 120, style="F")
            pdf.set_y(30)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("helvetica", "B", 30)
            pdf.multi_cell(0, 12, title, align="C")
            pdf.ln(4)
            pdf.set_font("helvetica", "", 13)
            pdf.set_text_color(147, 197, 253)
            pdf.cell(0, 8, doc_type, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(100, 116, 139)
            pdf.set_font("helvetica", "", 10)
            pdf.cell(0, 7, date.today().isoformat(), align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_y(132)
        else:
            pdf.set_y(40)
            pdf.set_text_color(122, 31, 31)
            pdf.set_font("times", "B", 34)
            pdf.multi_cell(0, 13, title, align="C")
            pdf.ln(3)
            pdf.set_draw_color(122, 31, 31)
            pdf.set_line_width(0.8)
            pdf.line(60, pdf.get_y(), 150, pdf.get_y())
            pdf.ln(5)
            pdf.set_font("times", "I", 13)
            pdf.set_text_color(90, 60, 40)
            pdf.cell(0, 8, doc_type, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("times", "", 10)
            pdf.cell(0, 7, date.today().isoformat(), align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(6)
        cover = _cover_png(cover_bytes)
        if cover is not None:
            try:
                y = pdf.get_y()
                if y < 220:
                    pdf.image(io.BytesIO(cover), x=25, y=y, w=160)
            except Exception:
                logger.warning("Cover image skipped (unusable bytes).")
        pdf.add_page()
        _render_blocks(pdf, _blocks(gdd), style)
        return bytes(pdf.output()), None
    except Exception:
        logger.exception("Styled PDF render failed.")
        return None, "Génération PDF impossible."


__all__ = ["render_gdd_pdf", "HAS_FPDF", "STYLES"]
