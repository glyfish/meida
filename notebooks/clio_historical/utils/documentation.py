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
import json
import re
import zipfile
from pathlib import Path

_PARAGRAPH = re.compile(r"<w:p(?:\s[^>]*)?>(.*?)</w:p>", re.S)
_RUN = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)
_SECTION = re.compile(r"^(\d{1,2}[a-z]?)\.\s+(.+?)\s*$")


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


# --- the template, field by field ---------------------------------------------
#
# 53 papers read. Eight headings appear in all of them; the rest vary in wording
# ("Keywords (5)" / "Keywords", "Data collector" / "Data collectors"), and
# section 17, "Text", is the full working paper -- whose own chapters are
# numbered too ("2. INCOME INEQUALITY IN THE POST-1945 PERIOD"). So a numbered
# paragraph is a section only when its name is one of these; anything else is
# body text of the section it sits in.

FIELDS: dict[str, tuple[str, ...]] = {
    "title": ("title", "title of the dataset"),
    "authors": ("author(s)", "author", "authors"),
    "production_date": ("production date",),
    "paper_version": ("version",),
    "variable_group": ("variable group(s)", "variable group"),
    "variables": ("variable(s)", "variables", "variable"),
    "unit_of_analysis": ("unit of analysis",),
    # four papers split section 7: 7a analysis (always "Country"), 7b measurement
    "unit_of_measurement": ("unit of measurement",),
    "keywords": ("keywords (5)", "keywords (2)", "keywords"),
    "abstract": ("abstract (200 words)", "abstract (ca. 200 words)",
                 "abstract (200 words) taken from wikipedia:", "abstract"),
    "time_period": ("time period",),
    "geographical_coverage": ("geographical coverage",),
    "methodology": ("methodologies used for data collection and processing",),
    "data_quality": ("data quality", "data quality (multiple possibilities)"),
    "period_of_collection": ("period of collection", "date of collection"),
    "data_collectors": ("data collectors", "data collector"),
    "sources": ("sources",),
    "citation": ("citation (that should be used for this dataset)",),
    "text": ("text",),
}
_HEADING_TO_FIELD = {name: field for field, names in FIELDS.items() for name in names}


def _field(heading: str) -> str | None:
    return _HEADING_TO_FIELD.get(" ".join(heading.split()).casefold())


def metadata(path: Path) -> dict[str, object]:
    """The working paper as named fields, plus what the parse had to decide.

    ``paper_version`` is the **authors'** revision of the dataset -- "1st
    version", "2", "Version 1.0" -- not the DataverseNL deposit version (1.1),
    which appears in none of these files. ``version_number`` normalises it.
    ``abstract_source`` is ``wikipedia`` where the heading says the abstract was
    taken from there, as four papers' do.
    """
    out: dict[str, list[str]] = {}
    current = None
    headings = []
    for text in paragraphs(path):
        m = _SECTION.match(text)
        field = _field(m.group(2)) if m and len(m.group(2)) < 80 else None
        if field:
            current = field
            headings.append(m.group(2).strip())
            out.setdefault(field, [])
        elif current:
            out[current].append(text.lstrip("-–• ").strip())
    fields: dict[str, object] = {k: "\n".join(v).strip() or None for k, v in out.items()}
    if fields.get("keywords"):
        fields["keywords"] = [k.strip(" .") for k in re.split(r"[,;\n]", fields["keywords"]) if k.strip(" .")]
    version = fields.get("paper_version") or ""
    number = re.search(r"\d+(?:\.\d+)?", version)
    ordinal = re.search(r"\b(1st|2nd|3rd)\b", version, re.I)
    fields["version_number"] = (re.sub(r"\.0$", "", number.group(0)) if number
                                else {"1st": "1", "2nd": "2", "3rd": "3"}[ordinal.group(1).lower()] if ordinal
                                else None)
    fields["abstract_source"] = ("wikipedia" if any("wikipedia" in h.casefold() for h in headings)
                                 else "paper" if fields.get("abstract") else None)
    fields["unit"], fields["unit_source"] = _unit(fields)
    return fields


#: What "Unit of analysis" says when it names the thing observed rather than how
#: it is measured -- 19 of 49 papers write "Country" there.
_OBSERVED = {"country", "countries", "country-year", "country-years", "nation"}


def _unit(fields: dict) -> tuple[str | None, str | None]:
    """The unit a value is measured in, and which section it came from.

    Section 7 is used two ways. Where a paper splits it, 7b is the unit. Where
    it does not, "Unit of analysis" is the unit unless it names the observed
    thing -- "Country" -- in which case the paper states no unit and the
    workbook's row 2 has to be asked instead.
    """
    measured = (fields.get("unit_of_measurement") or "").strip()
    if measured:
        return measured.split("\n")[0].rstrip("."), "unit_of_measurement"
    analysis = (fields.get("unit_of_analysis") or "").strip()
    first = analysis.split("\n")[0].rstrip(".").strip()
    if first and first.casefold() not in _OBSERVED:
        return first, "unit_of_analysis"
    return None, None


# --- every filed paper, into one file ------------------------------------------

DOCUMENTATION = "documentation.yaml"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def build(data_dir: Path | None = None) -> dict[str, object]:
    """Extract every working paper under ``data/raw/`` into ``data/documentation.yaml``.

    Keyed by indicator id -- ``labourers_real_wage`` -- the ids the Clio series
    use, so ``notebooks/clio``'s unit harvest can read this file directly. A paper is tied to its indicator and DOI
    through the workbook in the same folder, whose title row names it; folder
    names (``doi-10-72``) carry nothing. Where one folder holds two copies of a
    paper, as a re-download leaves, they are compared: identical is one entry,
    different is reported and neither is guessed between.

    Every filed indicator gets an entry, paper or not: ``workbook_unit`` is the
    workbook's row 2 in the layout that has one, and a single-file download has
    ``paper: null`` but its identity and unit all the same.

    Returns a report: papers written, folders with a workbook only, what could
    not be matched, editions resolved, and indicators filed in two folders.
    """
    import yaml
    from . import accept, workbook

    data_dir = Path(data_dir or accept.DATA_DIR)
    datasets = json.loads((data_dir / "datasets.json").read_text())
    by_title = {" ".join(d["name"].split()).casefold(): (slug, d) for slug, d in datasets.items()}
    for workbook_title, slug in WORKBOOK_ALIASES.items():
        if slug in datasets:                     # an alias for an indicator not listed is inert
            by_title[workbook_title] = (slug, datasets[slug])

    entries: dict[str, dict] = {}
    report = {"papers": 0, "workbook_only": [], "unmatched": [], "editions": [], "duplicates": []}
    for folder in sorted(p for p in (data_dir / "raw").iterdir() if p.is_dir()):
        books = sorted(folder.glob("*.xlsx"))
        papers = sorted(folder.glob("*.docx"))
        if not books:
            continue
        parsed = {paper.name: metadata(paper) for paper in papers}
        read = [workbook.read(b) for b in books]
        # The workbook's title names the indicator; the third layout has none,
        # and then the paper's own title is asked instead.
        titles = [r["title"] for r in read] + [m.get("title") or "" for m in parsed.values()]
        match = next((by_title[t] for t in (" ".join(x.split()).casefold() for x in titles if x)
                      if t in by_title), None)
        if not match:
            report["unmatched"].append((folder.name, [t for t in titles if t][:2]))
            continue
        slug, dataset = match
        key = _slug(dataset["name"])
        entry = {"indicator": dataset["name"], "clio_slug": slug, "doi": dataset["doi"],
                 "folder": folder.name, "workbook": books[0].name,
                 "workbook_unit": _workbook_unit(read, dataset["name"])}
        if parsed:
            # One deposit can carry two editions -- GDP per capita has the 2013
            # Maddison update and the 2020 "long view", version 2. The latest
            # edition is the entry; the others are kept, marked superseded.
            ranked = sorted(parsed.items(), key=_edition, reverse=True)
            name, chosen = ranked[0]
            entry.update({"paper": name, **chosen})
            older = [{"paper": n, "title": m.get("title"), "paper_version": m.get("paper_version"),
                      "production_date": m.get("production_date")}
                     for n, m in ranked[1:] if m != chosen]
            if older:
                entry["superseded"] = older
                report["editions"].append((folder.name, name, [o["paper"] for o in older]))
            report["papers"] += 1
        else:
            # A single-file download: no paper, but the workbook still names its
            # indicator and, in the usual layout, its unit.
            entry["paper"] = None
            report["workbook_only"].append(folder.name)
        if key in entries:
            report["duplicates"].append((key, entries[key]["folder"], folder.name))
            if entries[key].get("paper") and not entry.get("paper"):
                continue                         # never let a bare workbook displace a paper
        entries[key] = entry

    path = data_dir / DOCUMENTATION
    path.write_text(
        "# Extracted from the DataverseNL working papers (.docx) by\n"
        "# utils.documentation.build(). Regenerable from data/raw/, but those were\n"
        "# downloaded by hand -- see notebooks/downloads.ipynb.\n"
        "# paper_version is the authors' revision of the dataset, not DataverseNL's\n"
        "# deposit version, which none of these files states.\n"
        + yaml.safe_dump(dict(sorted(entries.items())), sort_keys=False, allow_unicode=True, width=88))
    report["path"] = str(path)
    return report


def _workbook_unit(read: list[dict], name: str) -> str | None:
    """Row 2 of the usual layout -- unless it only repeats the indicator's name.

    "CO2 Emissions per Capita" in row 2 of the CO2 per capita workbook is a
    restated title, not a unit, and would read as one if taken on trust.
    """
    for book in read:
        unit = (book.get("unit") or "").strip()
        if unit and " ".join(unit.split()).casefold() != " ".join(name.split()).casefold():
            return unit
    return None


#: Workbooks whose title row does not match the Clio index, each checked
#: against the paper beside it, which names the indicator correctly.
WORKBOOK_ALIASES = {
    "unifid democracy scores (uds)": "UnifiedDemocracyScoresUDS",     # a typo in the workbook
    "composite wellbeing index": "CompositeMeasureofWellbeing",      # paper: "Composite measure of wellbeing"
    "social transfers": "SocialSpending",                            # paper: "Social Spending and the Welfare State"
    # workbook-only, no paper to check against -- but the abbreviations are exact
    "global extreme poverty cost of basic needs": "GlobalExtremePovertyCostofBasicNeeds",   # (CBN)
    "global extreme poverty dollar a day": "GlobalExtremePovertyDollaraDay",                # (DAD)
    "wealth top 10 percent share": "WealthTop10percentshare",                               # "Top10"
}


def _edition(item: tuple[str, dict]) -> tuple:
    """Order papers newest first: version number, then production year."""
    _, m = item
    try:
        version = float(m.get("version_number") or 0)
    except ValueError:
        version = 0.0
    year = re.search(r"(1[89]|20)\d\d", m.get("production_date") or "")
    return (version, int(year.group(0)) if year else 0)
