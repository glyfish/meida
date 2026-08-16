"""Tests for navi's ``WonderClient`` (``lib/clients/wonder.py``).

WONDER needs a browser TLS fingerprint (curl_cffi) and is rate-limited, so these
tests never hit the network: they exercise the request BUILDER and the XML
``<data-table>`` PARSER against a captured live response
(``tests/fixtures/cdc/wonder/d76_alcohol_by_year.xml``) -- the national
alcohol-induced age-adjusted rate by year, which reproduces NCHS Data Brief 448.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lib.clients import WonderAPIError
from lib.clients.wonder import _build_request_xml, parse_data_table
from lib.clients.models.wonder import WonderResponse

_FIXTURE = Path(__file__).parent / "fixtures" / "cdc" / "wonder" / "d76_alcohol_by_year.xml"


def test_parse_alcohol_by_year_reproduces_data_brief_448():
    resp = parse_data_table(_FIXTURE.read_text(), "D76")

    assert isinstance(resp, WonderResponse)
    assert resp.database == "D76"
    by_year = {row.year: row for row in resp.rows}

    # Full 1999-2020 span, one row per year.
    assert min(by_year) == 1999 and max(by_year) == 2020
    assert len(resp.rows) == 22

    # Data Brief 448: age-adjusted alcohol-induced rate 2019 = 10.4, 2020 = 13.1.
    assert by_year[2019].age_adjusted_rate == 10.4
    assert by_year[2020].age_adjusted_rate == 13.1
    # Sanity on the other columns of the 2020 row.
    assert by_year[2020].deaths == 49061
    assert by_year[2020].crude_rate == 14.9
    assert by_year[2019].deaths == 39043


def test_parse_d158_extends_past_2020_and_overlaps_d76():
    """D158 (single race, 2018-2024) extends the series; its 2018-2020 overlap
    must agree with the bridged-race D76 numbers."""
    fixture = _FIXTURE.parent / "d158_alcohol_by_year.xml"
    resp = parse_data_table(fixture.read_text(), "D158")
    by_year = {row.year: row for row in resp.rows}

    assert min(by_year) == 2018 and max(by_year) == 2024
    # overlap with D76 (bridged) — single-race total should match.
    assert by_year[2019].age_adjusted_rate == 10.4
    assert by_year[2020].age_adjusted_rate == 13.1
    # the extension: 2021 peak, then decline.
    assert by_year[2021].age_adjusted_rate == 14.4
    assert by_year[2024].age_adjusted_rate == 12.1


def test_d158_skeleton_registered():
    xml = _build_request_xml("D158", ["F10"], title="t")
    params = {p.findtext("name", ""): [v.text for v in p.findall("value")]
              for p in ET.fromstring(xml)}
    assert params["O_ucd"] == ["D158.V2"]
    assert params["F_D158.V2"] == ["F10"]
    assert params["O_race"] == ["D158.V42"]     # single-race variable


def test_build_request_selects_icd_codes_and_year_grouping():
    codes = ["F10", "K70", "X45"]
    xml = _build_request_xml("D76", codes, title="test")
    root = ET.fromstring(xml)
    params = {p.findtext("name", ""): [v.text for v in p.findall("value")] for p in root}

    # Cause selected via the ICD-10 codeset finder, NOT a V25 by-variable.
    assert params["F_D76.V2"] == codes
    assert params["O_ucd"] == ["D76.V2"]
    assert params["B_1"] == ["D76.V1-level1"]     # By Year
    assert params["B_2"] == ["*None*"]            # no second grouping
    assert params["O_aar"] == ["aar_std"]         # age-adjusted
    assert params["accept_datause_restrictions"] == ["true"]
    assert params["O_title"] == ["test"]


def test_unknown_database_raises():
    with pytest.raises(WonderAPIError, match="skeleton"):
        _build_request_xml("D999", ["F10"], title="x")


def test_parse_error_message_surfaces():
    body = (
        '<?xml version="1.0"?><page><title>Processing Error</title>'
        "<message>Bad request parameters.</message></page>"
    )
    with pytest.raises(WonderAPIError, match="Bad request parameters"):
        parse_data_table(body, "D76")


def test_suppressed_cells_become_none():
    body = (
        "<page><response><data-table>"
        '<r><c l="2018"/><c v="Suppressed"/><c v="1,000"/><c v="Unreliable"/><c v="0.5"/></r>'
        "</data-table></response></page>"
    )
    resp = parse_data_table(body, "D76")
    assert len(resp.rows) == 1
    row = resp.rows[0]
    assert row.year == 2018
    assert row.deaths is None            # "Suppressed"
    assert row.population == 1000
    assert row.crude_rate is None        # "Unreliable"
    assert row.age_adjusted_rate == 0.5
