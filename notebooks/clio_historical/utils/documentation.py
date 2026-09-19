"""Read the ``.docx`` working paper each DataverseNL deposit carries.

A fixed template of numbered sections -- ``1. Title`` through ``16. Sources``
-- and the only place two things are written down at all:

* ``7. Unit of analysis`` -- "number of subsistence baskets"
* ``13. Data quality`` -- a four-tier grading (central statistical agencies,
  historical reconstructions, estimates, conjectures) and which periods fall
  in which

A ``.docx`` is a zip; the text is in ``word/document.xml`` as ``<w:t>`` runs
inside ``<w:p>`` paragraphs. The run pattern must not match ``<w:tab/>``,
which shares the prefix -- a first attempt did, and leaked raw XML.
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

_PARAGRAPH = re.compile(r"<w:p(?:\s[^>]*)?>(.*?)</w:p>", re.S)
_RUN = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)
_SECTION = re.compile(r"^(\d{1,2})\.\s+(.+?)\s*$")


def paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    out = []
    for body in _PARAGRAPH.findall(xml):
        text = html.unescape("".join(_RUN.findall(body))).strip()
        if text:
            out.append(text)
    return out


def sections(path: Path) -> dict[str, str]:
    """``{"7. Unit of analysis": "number of subsistence baskets.", ...}``.

    A paragraph that opens with a number and a heading starts a section;
    everything until the next one is its body, joined with newlines, with the
    template's leading dash removed.
    """
    out: dict[str, list[str]] = {}
    current = None
    for text in paragraphs(path):
        m = _SECTION.match(text)
        if m and len(m.group(2)) < 60:
            current = f"{m.group(1)}. {m.group(2)}"
            out[current] = []
        elif current:
            out[current].append(text.lstrip("-– ").strip())
    return {k: "\n".join(v).strip() for k, v in out.items()}
