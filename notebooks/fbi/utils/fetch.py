"""Pull crime and law-enforcement series from the FBI Crime Data Explorer.

The CDE API is the successor to the retired ``crime/fbi/sapi`` service, which
now 404s -- anything written against the old ``/api/estimates/...`` paths is
dead. The live base is ``https://api.usa.gov/crime/fbi/cde``, and the key is
the shared **api.data.gov** key (``DATA_GOV_KEY``), not an FBI one: the same
key opens every service behind that gateway. It goes in the query string as
``API_KEY`` -- capitalised, since the CDE routes ignore the lowercase
``api_key`` that other api.data.gov services accept.

What the API actually serves, probed rather than read off the documentation
(the docs page is a JavaScript app and the published Swagger describes the
retired service):

``summarized/{national|state/ST}/{offense}``
    Offence counts and rates, **monthly**, from 1985. Ten offence slugs, all
    verified: violent-crime, homicide, rape, robbery, aggravated-assault,
    property-crime, burglary, larceny, motor-vehicle-theft, arson.

``pe/agency/{ORI}``
    Officer and civilian counts by sex, **annual, 1985 onward**. The capacity
    half of the enforcement node.

``agency/byStateAbbr/{ST}``
    Every agency in a state with its ORI, county and NIBRS status -- the
    enumeration route, and the only way to discover an ORI.

**Three traps, each verified by probing:**

1. ``summarized/agency/{ORI}/{offense}`` **silently returns state data.** Ask
   for NYPD homicides and the payload is titled "New York Offenses"; ask for a
   Texas agency and it is "Texas Offenses". The numbers are plausible and for
   the wrong geography. Offences are national or state only.
2. ``pe/national`` and ``pe/state/{ST}`` answer 200 with the full response
   shape and **every value null**. Employment is agency-level only; a national
   series has to be aggregated from agencies, or taken from Census ASPEP.
3. The ``rates`` block of ``pe`` divides by a "Participated Population" that is
   wrong or zero for some agencies -- one Texas ORI reports 35 employees per
   1,000 in 1985 and 274 in 2018. **Use ``actuals`` and bring your own
   denominator.**

Year ranges are validated server-side: ``pe`` refuses a ``from`` earlier than
1985 with a 400 rather than clamping.

``DEMO_KEY`` works for roughly thirty calls an hour and then returns
``OVER_RATE_LIMIT``; it is enough to probe an endpoint and not enough to build
a series. With a real key the limit is 1,000 an hour, and :data:`PAUSE` keeps a
full pull inside it without thinking about it.

**The NIBRS discontinuity.** Agencies moved from Summary UCR to NIBRS through
2021, and many stopped reporting during the transition; national and state
aggregates in that window reflect who reported as much as what happened. Series
crossing 2020-2022 need that stated, not smoothed.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_MEIDA_ROOT = str(Path(__file__).resolve().parents[3])
if _MEIDA_ROOT not in sys.path:
    sys.path.insert(0, _MEIDA_ROOT)

from environment import get_data_gov_key, get_fbi_base_url

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
RAW = DATA_DIR / "raw"

#: Seconds between requests. The limit is 1,000/hour with a real key; one
#: request a second is a quarter of that and leaves room for anything else
#: using the same key.
PAUSE = 1.0

#: Offence slugs the summarized endpoints take. Verified against the API by
#: ``probe()`` rather than trusted -- the UI's labels and the API's slugs do
#: not always agree.
OFFENSES = (
    "violent-crime", "homicide", "rape", "robbery", "aggravated-assault",
    "property-crime", "burglary", "larceny", "motor-vehicle-theft", "arson",
)


class FBIError(RuntimeError):
    """The CDE API refused a request."""


def _get(path: str, **params: Any) -> Any:
    """One GET against the CDE API, keyed and paced. Returns parsed JSON."""
    params["API_KEY"] = get_data_gov_key()
    url = f"{get_fbi_base_url()}/{path.lstrip('/')}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        if exc.code == 429:
            raise FBIError(f"rate limited -- {detail}") from exc
        raise FBIError(f"{exc.code} on {path}: {detail}") from exc
    time.sleep(PAUSE)
    if body[:1] not in (b"{", b"["):                 # the 404 page is HTML
        raise FBIError(f"{path}: not JSON -- {body[:120]!r}")
    return json.loads(body)


def summarized(offense: str, *, state: str | None = None,
               start: str = "01-1985", end: str = "12-2024") -> dict[str, Any]:
    """Monthly offence counts and rates, nationally or for one state.

    Dates are ``MM-YYYY``. *state* is a two-letter code; omit it for national.
    """
    scope = f"state/{state}" if state else "national"
    return _get(f"summarized/{scope}/{offense}", **{"from": start, "to": end})


def agencies(state: str) -> dict[str, Any]:
    """Every agency in a state, keyed by county: ORI, name, NIBRS status."""
    return _get(f"agency/byStateAbbr/{state}")


def police_employment(ori: str, *, start: str = "1985",
                      end: str = "2024") -> dict[str, Any]:
    """Officer and civilian counts for one agency, annual.

    *ori* is the agency's ORI code, from :func:`agencies`. Dates are ``YYYY``
    and ``start`` cannot precede 1985 -- the API returns 400, not a clamp.
    There is no national or state equivalent: those routes answer with nulls.
    """
    return _get(f"pe/agency/{ori}", **{"from": start, "to": end})


def officers(payload: dict[str, Any]) -> dict[int, int]:
    """Sworn officers per year from a :func:`police_employment` payload.

    Male plus female officers from ``actuals``, ignoring the ``rates`` block,
    whose denominator is unreliable. Years where either is missing are skipped
    rather than treated as zero.
    """
    actuals = payload.get("actuals", {})
    male, female = actuals.get("Male Officers", {}), actuals.get("Female Officers", {})
    return {int(year): int(male[year]) + int(female[year])
            for year in sorted(male)
            if male.get(year) is not None and female.get(year) is not None}


def probe(offenses: tuple[str, ...] = OFFENSES) -> dict[str, str]:
    """Check which offence slugs and scopes the API actually serves.

    One call per slug, so mind the hourly limit. Returns slug -> ``ok`` or the
    error, and writes the result to ``data/raw/probe.json`` as the record of
    what this source supports.
    """
    out: dict[str, str] = {}
    for offense in offenses:
        try:
            payload = summarized(offense, start="01-2019", end="12-2019")
            rates = payload.get("offenses", {}).get("rates", {})
            out[offense] = f"ok, {len(rates)} series" if rates else "ok, empty"
        except FBIError as exc:
            out[offense] = str(exc)[:120]
    try:
        listing = agencies("DC")
        out["agency/byStateAbbr"] = f"ok, {sum(len(v) for v in listing.values())} agencies in DC"
    except FBIError as exc:
        out["agency/byStateAbbr"] = str(exc)[:120]
    try:
        counts = officers(police_employment("DCMPD0000"))
        out["pe/agency"] = (f"ok, {len(counts)} years, {min(counts)}-{max(counts)}, "
                            f"latest {counts[max(counts)]} officers")
    except FBIError as exc:
        out["pe/agency"] = str(exc)[:120]
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "probe.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    for name, result in probe().items():
        print(f"{name:24} {result}")
