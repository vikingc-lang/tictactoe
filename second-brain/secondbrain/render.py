"""Render generated content to files: Markdown, Word (.docx) and PowerPoint (.pptx)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field


class Slide(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    speaker_notes: str = ""


class Deck(BaseModel):
    title: str
    subtitle: str = ""
    slides: list[Slide]


_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


def _add_runs(paragraph, text: str) -> None:
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            paragraph.add_run(part[1:-1]).italic = True
        else:
            paragraph.add_run(part)


def markdown_to_docx(markdown: str, path: Path, template: Path | None = None) -> Path:
    import docx

    doc = docx.Document(str(template)) if template else docx.Document()
    table_rows: list[list[str]] = []

    def flush_table() -> None:
        if not table_rows:
            return
        rows = [r for r in table_rows if not all(set(c) <= set("-: ") for c in r)]
        table = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
        table.style = "Table Grid" if "Table Grid" in [s.name for s in doc.styles] else None
        for i, row in enumerate(rows):
            for j, cell in enumerate(row):
                table.cell(i, j).text = cell
        table_rows.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("|") and line.endswith("|"):
            table_rows.append([c.strip() for c in line.strip("|").split("|")])
            continue
        flush_table()
        if not line.strip():
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading:
            # "# " becomes the document title; "## " Heading 1, "### " Heading 2, ...
            doc.add_heading(heading.group(2), level=len(heading.group(1)) - 1)
        elif re.match(r"^\s*[-*+]\s+", line):
            _add_runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^\s*[-*+]\s+", "", line))
        elif re.match(r"^\s*\d+[.)]\s+", line):
            _add_runs(doc.add_paragraph(style="List Number"), re.sub(r"^\s*\d+[.)]\s+", "", line))
        elif line.startswith(">"):
            _add_runs(doc.add_paragraph(style="Quote" if "Quote" in [s.name for s in doc.styles] else None),
                      line.lstrip("> "))
        else:
            _add_runs(doc.add_paragraph(), line)
    flush_table()
    doc.save(str(path))
    return path


def deck_to_pptx(deck: Deck, path: Path, sources: list[str] | None = None, template: Path | None = None) -> Path:
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation(str(template)) if template else Presentation()
    title_layout = prs.slide_layouts[0]
    content_layout = prs.slide_layouts[1] if len(prs.slide_layouts) > 1 else prs.slide_layouts[0]

    s = prs.slides.add_slide(title_layout)
    s.shapes.title.text = deck.title
    if len(s.placeholders) > 1:
        s.placeholders[1].text = deck.subtitle

    def content_slide(title: str, bullets: list[str], notes: str = "") -> None:
        slide = prs.slides.add_slide(content_layout)
        slide.shapes.title.text = title
        body = next((p for p in slide.placeholders if p.placeholder_format.idx == 1), None)
        if body is not None:
            tf = body.text_frame
            tf.clear()
            for i, bullet in enumerate(bullets):
                para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                level = (len(bullet) - len(bullet.lstrip(" "))) // 2
                para.text = bullet.strip().lstrip("-• ").strip()
                para.level = min(level, 4)
                for run in para.runs:
                    run.font.size = Pt(20 if level == 0 else 16)
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    for sl in deck.slides:
        content_slide(sl.title, sl.bullets, sl.speaker_notes)
    if sources:
        content_slide("Sources", sources[:12])
    prs.core_properties.title = deck.title
    prs.save(str(path))
    return path
