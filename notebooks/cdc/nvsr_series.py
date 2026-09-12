"""Build normalized life-expectancy series from the downloaded NVSR life tables.

NVSR publishes annual life tables as Excel workbooks on an FTP tree, with no
programmatic year -> volume-directory mapping, so the files are downloaded by
hand into ``data/nvsr/`` and parsed here. This is the only channel NCHS
publishes life expectancy through -- CDC WONDER has none, and no public API
carries it by race after 2020.

Two traps make this parser look stranger than it is:

**The value is at a fixed position, not a labelled one.** Age-0 ``e0`` lives at
**row 4, column G** in every workbook. Column A holds legend text through row
24 and only becomes age labels at row 25, so searching for the "0-1" row finds
a later, wrong one -- that mistake returns 56.2 for 2021 instead of 76.4, a
plausible number with nothing to flag it. Position is checked against the
published values in :func:`verify_national`.

**The files do not say who they are about.** ``Table07.xlsx`` carries no title
cell and its sheet is named "Table 1"; the demographic group exists only in the
report's captions. :data:`NATIONAL_TABLES` encodes that mapping, verified
against NVSR 75-05's Table A. Getting it wrong silently relabels one
population as another.

State files add a third: ``{ST}4`` is a **standard-error** table, not a life
table, so a jurisdiction contributes three series, not four.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterator

DATA_DIR = Path(__file__).parent / "data" / "nvsr"
SOURCE = "cdc_nvsr"
UNITS = "years"
TTL_DAYS = 365

#: Age-0 life expectancy: row 4, column G. Never search by label -- see module docstring.
E0_ROW = 4
E0_COL = "G"

#: TableNN -> (race, sex), from NVSR 75-05's "Life table for ..." captions.
#: 6 origin/race groups x 3 sexes; the file itself identifies neither.
NATIONAL_TABLES: dict[int, tuple[str, str]] = {
    1: ("all", "both"),        2: ("all", "male"),        3: ("all", "female"),
    4: ("hispanic", "both"),   5: ("hispanic", "male"),   6: ("hispanic", "female"),
    7: ("aian_nh", "both"),    8: ("aian_nh", "male"),    9: ("aian_nh", "female"),
    10: ("asian_nh", "both"), 11: ("asian_nh", "male"),  12: ("asian_nh", "female"),
    13: ("black_nh", "both"), 14: ("black_nh", "male"),  15: ("black_nh", "female"),
    16: ("white_nh", "both"), 17: ("white_nh", "male"),  18: ("white_nh", "female"),
}

#: {ST}1/2/3 are life tables; {ST}4 is standard errors and is skipped.
STATE_TABLES: dict[int, str] = {1: "both", 2: "male", 3: "female"}

RACE_LABELS = {
    "all": "all races", "hispanic": "Hispanic", "aian_nh": "American Indian and Alaska Native, non-Hispanic",
    "asian_nh": "Asian, non-Hispanic", "black_nh": "Black, non-Hispanic", "white_nh": "White, non-Hispanic",
}
SEX_LABELS = {"both": "both sexes", "male": "male", "female": "female"}

#: Data year -> the NVSR volume directory on ftp.cdc.gov that published it.
#: There is no programmatic mapping -- the FTP tree is named by volume-number,
#: not data year, so this is transcribed from the NVSS life-expectancy page and
#: is what a refresh needs in order to find next year's files.
US_VOLUMES: dict[int, str] = {
    2018: "69-12", 2019: "70-19", 2020: "71-01",
    2021: "72-12", 2022: "74-02", 2023: "74-06", 2024: "75-05",
}
STATE_VOLUMES: dict[int, str] = {
    2018: "70-01", 2019: "70-18", 2020: "71-02", 2021: "73-07", 2022: "74-12",
}

#: Published national e0, for the guard in :func:`verify_national`.
PUBLISHED_E0 = {2021: 76.4, 2022: 77.5, 2023: 78.4, 2024: 79.0}


class NvsrSeriesError(RuntimeError):
    """Raised when a life table cannot be read or fails its check."""


def read_cell(xlsx: Path, row: int, col: str) -> float | None:
    """Read one numeric cell straight from the workbook XML.

    An .xlsx is a zip of XML; pulling the single cell avoids adding openpyxl
    for what is a four-line job.
    """
    try:
        with zipfile.ZipFile(xlsx) as z:
            sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise NvsrSeriesError(f"cannot read {xlsx}: {exc}") from exc

    match = re.search(rf'<c r="{col}{row}"[^>]*>(?:<v>([^<]*)</v>)?', sheet)
    if not match or match.group(1) is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def life_expectancy_at_birth(xlsx: Path) -> float | None:
    """Age-0 life expectancy from one life table."""
    return read_cell(xlsx, E0_ROW, E0_COL)


def _national_files(data_dir: Path) -> Iterator[tuple[int, int, Path]]:
    """Yield ``(year, table_number, path)`` for the national workbooks."""
    for year_dir in sorted((data_dir / "us").glob("[0-9][0-9][0-9][0-9]")):
        for path in sorted(year_dir.glob("*.xlsx")):
            m = re.fullmatch(r"[Tt]able(\d+)\.xlsx", path.name)
            if m:
                yield int(year_dir.name), int(m.group(1)), path


def _state_files(data_dir: Path) -> Iterator[tuple[int, str, int, Path]]:
    """Yield ``(year, state, table_number, path)`` for the state workbooks."""
    for year_dir in sorted((data_dir / "state").glob("[0-9][0-9][0-9][0-9]")):
        for path in sorted(year_dir.glob("*.xlsx")):
            m = re.fullmatch(r"([A-Z]{2})(\d)\.xlsx", path.name)
            if m:
                yield int(year_dir.name), m.group(1), int(m.group(2)), path


def verify_national(data_dir: Path = DATA_DIR) -> dict[int, float]:
    """Check parsed total-population e0 against the published figures.

    The guard for the row-4 trap: a label-based reading returns a plausible
    wrong number, so every run re-checks Table01 for each year and raises
    rather than emitting quietly-wrong series.
    """
    got: dict[int, float] = {}
    for year, table, path in _national_files(data_dir):
        if table != 1:
            continue
        value = life_expectancy_at_birth(path)
        if value is None:
            raise NvsrSeriesError(f"no e0 at {E0_COL}{E0_ROW} in {path}")
        got[year] = value
        expected = PUBLISHED_E0.get(year)
        if expected is not None and round(value, 1) != expected:
            raise NvsrSeriesError(
                f"{year}: parsed e0 {value:.4f} rounds to {round(value, 1)}, "
                f"published {expected} -- check {E0_COL}{E0_ROW} in {path.name}"
            )
    return got


def verify_state(data_dir: Path = DATA_DIR) -> dict[int, int]:
    """Check the state parse structurally. Returns ``{year: jurisdictions}``.

    There is no state equivalent of :data:`PUBLISHED_E0` -- NVSR publishes 51
    jurisdictions per year, too many to transcribe -- so this guard is weaker
    than :func:`verify_national` by necessity. It leans on three facts that a
    misread cell or a shuffled ``{ST}N`` mapping cannot satisfy:

    * ``female > both > male`` holds in every US state life table ever
      published, so it catches a row offset and a sex mislabelling alike;
    * ``e0`` sits between 60 and 95 years in all of them;
    * where the matching national table is on disk, the national ``e0`` falls
      inside the state range -- a systematic offset moves the states off it.
    """
    by_year: dict[int, dict[str, dict[str, float]]] = {}
    for year, state, table, path in _state_files(data_dir):
        sex = STATE_TABLES.get(table)
        if sex is None:                       # {ST}4 -- standard errors
            continue
        value = life_expectancy_at_birth(path)
        if value is None:
            raise NvsrSeriesError(f"no e0 at {E0_COL}{E0_ROW} in {path}")
        if not 60.0 <= value <= 95.0:
            raise NvsrSeriesError(
                f"{year} {state} {sex}: e0 {value:.2f} outside 60-95 -- "
                f"check {E0_COL}{E0_ROW} in {path.name}"
            )
        by_year.setdefault(year, {}).setdefault(state, {})[sex] = value

    national = {year: life_expectancy_at_birth(path)
                for year, table, path in _national_files(data_dir) if table == 1}

    for year, states in sorted(by_year.items()):
        for state, sexes in sorted(states.items()):
            if set(sexes) != set(STATE_TABLES.values()):
                missing = sorted(set(STATE_TABLES.values()) - set(sexes))
                raise NvsrSeriesError(f"{year} {state}: missing {', '.join(missing)}")
            if not sexes["female"] > sexes["both"] > sexes["male"]:
                raise NvsrSeriesError(
                    f"{year} {state}: e0 not female > both > male "
                    f"({sexes['female']:.2f}, {sexes['both']:.2f}, {sexes['male']:.2f}) "
                    f"-- the {{ST}}1/2/3 mapping or the cell is wrong"
                )
        us = national.get(year)
        if us is not None:
            both = [s["both"] for s in states.values()]
            if not min(both) <= us <= max(both):
                raise NvsrSeriesError(
                    f"{year}: national e0 {us:.2f} outside the state range "
                    f"{min(both):.2f}-{max(both):.2f}"
                )

    return {year: len(states) for year, states in sorted(by_year.items())}


def _record(native_id: str, title: str, facets: dict[str, str],
            points: list[tuple[int, float]]) -> dict[str, Any]:
    points.sort()
    observations = [
        {"date": f"{year:04d}-01-01", "value": f"{value:.4f}".rstrip("0").rstrip(".")}
        for year, value in points
    ]
    start, end = observations[0]["date"], observations[-1]["date"]
    return {
        "source": SOURCE,
        "native_id": native_id,
        "title": title,
        "frequency": "Annual",
        "units": UNITS,
        "observation_start": start,
        "observation_end": end,
        "observation_count": len(observations),
        "ttl_days": TTL_DAYS,
        "metadata": {
            "observation_count": len(observations),
            "units": UNITS,
            SOURCE: {
                "concept": ["life_expectancy"],
                "measure": ["life expectancy at birth"],
                "definition": ["NCHS decennial-method period life table (NVSR United States Life Tables)"],
                **{k: [v] for k, v in facets.items()},
                "observation_start_int": [int(start[:4] + "0101")],
                "observation_end_int": [int(end[:4] + "0101")],
            },
        },
        "observations": observations,
    }


def build_national(data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    """One series per (race, sex), with an observation per published year."""
    points: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for year, table, path in _national_files(data_dir):
        group = NATIONAL_TABLES.get(table)
        if group is None:
            continue
        value = life_expectancy_at_birth(path)
        if value is not None:
            points.setdefault(group, []).append((year, value))

    return [
        _record(
            native_id=f"cdc/life_expectancy/nvsr/race={race}/sex={sex}",
            title=(f"Life expectancy at birth, United States "
                   f"({RACE_LABELS[race]}, {SEX_LABELS[sex]})"),
            facets={"race": race, "sex": sex, "geography": "United States"},
            points=pts,
        )
        for (race, sex), pts in sorted(points.items())
    ]


def build_state(data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    """One series per (state, sex). ``{ST}4`` is standard errors -- skipped."""
    points: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for year, state, table, path in _state_files(data_dir):
        sex = STATE_TABLES.get(table)
        if sex is None:                       # {ST}4 -- standard errors, not a life table
            continue
        value = life_expectancy_at_birth(path)
        if value is not None:
            points.setdefault((state, sex), []).append((year, value))

    return [
        _record(
            native_id=f"cdc/life_expectancy/nvsr/state={state}/sex={sex}",
            title=f"Life expectancy at birth, {state} ({SEX_LABELS[sex]})",
            facets={"state": state, "sex": sex, "geography": state},
            points=pts,
        )
        for (state, sex), pts in sorted(points.items())
    ]


def build_all(data_dir: Path = DATA_DIR, *, verify: bool = True) -> list[dict[str, Any]]:
    """Build national and state series, checking the parse first by default."""
    if verify:
        verify_national(data_dir)
        verify_state(data_dir)
    return build_national(data_dir) + build_state(data_dir)
