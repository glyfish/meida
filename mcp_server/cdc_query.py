"""Turn named, typed tool arguments into SoQL, so no SoQL crosses the MCP wire.

The MCP client sends canonical tokens under the *same names the catalog uses as
metadata keys* -- ``race``, ``sex``, ``age``, ``state``, ``drug``, ``rate_type``,
``period``. This module resolves those against
:mod:`mcp_server.cdc_datasets` and emits the ``$select``/``$where`` pair, which
is the only place dataset-specific column names and literals appear.

That indirection is not ceremony: the same facet is a different column in every
dataset. ``race`` is the column ``race`` on w9j2-ggv5, the pair
``group``/``subgroup`` on w26f-tf3h, ``stratificationcategory1``/
``stratification1`` on hksd-2xuw, and a composed ``stub_label`` on 9j2v-jamp.
A caller cannot be expected to know that, which is exactly why the old raw-SoQL
tool was the wrong interface.

Unknown tokens raise :class:`CdcQueryError` naming the values that *are* valid
for that dataset, because the tool's enums are the union across datasets and a
token valid for one dataset is often absent from another.
"""
from __future__ import annotations

from typing import Any, Literal, Mapping

from .cdc_datasets import (
    MONTH_NUMBER, REGISTRY, STATES, STUB, VSRR, Spec, _eq, _select,
)

#: Facet parameters the tool accepts. These names are also the catalog's
#: ``facets`` metadata keys -- deliberately identical, so a value read off a
#: discovered series can be passed straight back in under the same name.
FACET_PARAMS = ("state", "race", "sex", "age", "drug", "rate_type", "period")


def _union(facet: str) -> tuple[str, ...]:
    """Every token any dataset defines for one facet.

    Derived from the registry rather than written out, so the enum the tool
    advertises and the literals the builder can actually resolve are the same
    set by construction -- a hand-maintained copy would drift the first time a
    dataset is added.
    """
    out: set[str] = set()
    for spec in REGISTRY:
        cross = spec.facets.get(facet)
        if cross and not cross.dynamic:
            out |= set(cross.values)
        breakdown = spec.breakdowns.get(facet)
        if breakdown:
            out |= set(breakdown.values)
        if facet == "rate_type" and spec.rate_type:
            out |= set(spec.rate_type.values)
    out |= set(STUB.values.get(facet, {}))
    if facet == "sex":
        out |= set(VSRR.sex_columns)
    if facet == "rate_type":
        out |= set(VSRR.rates)
    if facet == "period":
        out |= {"12mo_ending"}
    return tuple(sorted(out))


DATASET_IDS = tuple(sorted({s.dataset_id for s in REGISTRY} |
                           {STUB.dataset_id, VSRR.dataset_id}))
CONCEPTS = tuple(sorted({s.concept for s in REGISTRY} | {STUB.concept} | set(VSRR.causes)))
RACES, SEXES, AGES = _union("race"), _union("sex"), _union("age")
DRUGS, RATE_TYPES, PERIODS = _union("drug"), _union("rate_type"), _union("period")

# Exposed as JSON Schema ``enum`` on the tool, so a client sees the accepted
# vocabulary without reading prose. These are the union across datasets: no
# dataset defines all of them, which ``vocabulary()`` and the errors report.
DatasetId = Literal[DATASET_IDS]
Concept = Literal[CONCEPTS]
State = Literal[STATES]
Race = Literal[RACES]
Sex = Literal[SEXES]
Age = Literal[AGES]
Drug = Literal[DRUGS]
RateTypeToken = Literal[RATE_TYPES]
Period = Literal[PERIODS]

#: The alias every recipe selects the time column as. Socrata resolves a
#: ``$select`` alias inside ``$where``, so the range predicate can use it even
#: when no such column exists (489q-934x has no ``year`` column).
TIME_ALIAS = "year"


class CdcQueryError(ValueError):
    """A facet value that this dataset does not define."""


def _reject(facet: str, value: str, valid: Mapping[str, Any] | list) -> None:
    options = ", ".join(sorted(valid)) or "(none)"
    raise CdcQueryError(
        f"{facet}={value!r} is not valid for this dataset; valid values: {options}"
    )


def _spec_for(dataset_id: str, concept: str | None) -> Spec:
    matches = [s for s in REGISTRY if s.dataset_id == dataset_id]
    if not matches:
        known = sorted({s.dataset_id for s in REGISTRY} | {STUB.dataset_id, VSRR.dataset_id})
        raise CdcQueryError(f"unknown dataset_id {dataset_id!r}; known: {', '.join(known)}")
    if concept:
        matches = [s for s in matches if s.concept == concept]
        if not matches:
            avail = sorted({s.concept for s in REGISTRY if s.dataset_id == dataset_id})
            raise CdcQueryError(
                f"dataset {dataset_id} has no concept {concept!r}; available: {', '.join(avail)}"
            )
    if len(matches) > 1:
        avail = sorted(s.concept for s in matches)
        raise CdcQueryError(
            f"dataset {dataset_id} serves several concepts -- pass concept: {', '.join(avail)}"
        )
    return matches[0]


def _facet_names(spec: Spec) -> frozenset[str]:
    """The facet keys one spec exposes, ignoring their values."""
    names = set(spec.facets) | set(spec.breakdowns)
    if spec.location_col:
        names.add("state")
    if spec.rate_type:
        names.add("rate_type")
    return frozenset(names)


def _shared_spec(dataset_id: str) -> Spec:
    """Resolve a dataset without a concept, when every concept agrees.

    Only raises when the concepts genuinely differ -- demanding a concept that
    cannot change the answer is friction, not precision.
    """
    matches = [s for s in REGISTRY if s.dataset_id == dataset_id]
    if not matches:
        return _spec_for(dataset_id, None)      # reuse its error message
    if len({_facet_names(s) for s in matches}) > 1:
        avail = sorted(s.concept for s in matches)
        raise CdcQueryError(
            f"dataset {dataset_id} publishes different facets per concept -- "
            f"pass concept: {', '.join(avail)}"
        )
    return matches[0]


def _cross(spec: Spec, given: dict[str, str]) -> list[str]:
    """Independent columns: each facet contributes one equality."""
    where: list[str] = []
    for name, value in given.items():
        facet = spec.facets.get(name)
        if facet is None:
            _reject(name, value, sorted(spec.facets))
        literal = value if facet.dynamic else facet.values.get(value)
        if literal is None:
            _reject(name, value, facet.values)
        where.append(_eq(facet.column, literal))
    return where


def _stratified(spec: Spec, given: dict[str, str]) -> list[str]:
    """One active stratification per row -- so at most one breakdown applies.

    These datasets publish age *or* race *or* sex, never crossed, so asking for
    two at once describes a series that was never published.
    """
    where: list[str] = []
    if spec.location_col and "state" in given:
        where.append(_eq(spec.location_col, given.pop("state")))

    rate = given.pop("rate_type", None)
    active = {k: v for k, v in given.items() if k in spec.breakdowns}
    unknown = set(given) - set(spec.breakdowns)
    if unknown:
        name = sorted(unknown)[0]
        _reject(name, given[name], sorted(spec.breakdowns) + ["state", "rate_type"])
    if len(active) > 1:
        raise CdcQueryError(
            f"this dataset stratifies one dimension at a time; got "
            f"{', '.join(sorted(active))} -- pass only one"
        )

    if active:
        (name, value), = active.items()
        breakdown = spec.breakdowns[name]
        literal = breakdown.values.get(value)
        if literal is None:
            _reject(name, value, breakdown.values)
        where += [_eq(spec.strat_category_col, breakdown.category),
                  _eq(spec.strat_value_col, literal)]
        if breakdown.crude_only and rate == "age_adjusted":
            raise CdcQueryError(f"{name} breakdowns are published crude only")
    elif spec.overall:
        where += [_eq(spec.strat_category_col, spec.overall[0]),
                  _eq(spec.strat_value_col, spec.overall[1])]

    if spec.rate_type:
        token = rate or spec.rate_type.default
        literal = spec.rate_type.values.get(token)
        if literal is None:
            _reject("rate_type", token, spec.rate_type.values)
        where.append(_eq(spec.rate_type.column, literal))
    return where


def _stub(given: dict[str, str]) -> tuple[str, list[str]]:
    """9j2v-jamp: a scheme name plus a label composed from the active facets."""
    rate = given.pop("rate_type", None) or "age_adjusted"
    unit = STUB.values["rate_type"].get(rate)
    if unit is None:
        _reject("rate_type", rate, STUB.values["rate_type"])

    unknown = set(given) - {"sex", "race", "age"}
    if unknown:
        name = sorted(unknown)[0]
        _reject(name, given[name], ["sex", "race", "age", "rate_type"])

    scheme = STUB.schemes.get(frozenset(given))
    if scheme is None:
        combos = sorted("+".join(sorted(k)) or "(none)" for k in STUB.schemes)
        raise CdcQueryError(
            f"9j2v-jamp publishes only these facet combinations: {', '.join(combos)}"
        )

    if not given:
        label = STUB.total_label
    else:
        parts = []
        for name in STUB.label_order:
            if name not in given:
                continue
            literal = STUB.values[name].get(given[name])
            if literal is None:
                _reject(name, given[name], STUB.values[name])
            parts.append(literal)
        label = ": ".join(parts)

    where = [_eq(STUB.category_col, scheme), _eq(STUB.label_col, label),
             _eq(STUB.rate_col, unit)]
    return f"{STUB.time_field} AS {TIME_ALIAS}, {STUB.value_field} AS value", where


def _vsrr(concept: str | None, given: dict[str, str]) -> tuple[str, list[str]]:
    """489q-934x: sex picks a wide value column rather than filtering rows."""
    if not concept:
        raise CdcQueryError(
            f"489q-934x needs a concept: {', '.join(sorted(VSRR.causes))}"
        )
    cause = VSRR.causes.get(concept)
    if cause is None:
        _reject("concept", concept, VSRR.causes)

    rate = given.pop("rate_type", None) or "age_adjusted"
    rate_lit = VSRR.rates.get(rate)
    if rate_lit is None:
        _reject("rate_type", rate, VSRR.rates)

    given.pop("period", None)          # only one period is published
    sex = given.pop("sex", None) or "both"
    column = VSRR.sex_columns.get(sex)
    if column is None:
        _reject("sex", sex, VSRR.sex_columns)
    if given:
        name = sorted(given)[0]
        _reject(name, given[name], ["sex", "rate_type", "period"])

    where = [_eq(VSRR.cause_col, cause), _eq(VSRR.rate_col, rate_lit),
             _eq(VSRR.period_col, VSRR.period_literal)]
    return f"{VSRR.time_field} AS {TIME_ALIAS}, {column} AS value", where


def build(
    dataset_id: str,
    concept: str | None = None,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = 1000,
    **facets: str | None,
) -> dict[str, Any]:
    """Resolve named facets into a ``CdcClient.query`` keyword payload."""
    given = {k: v for k, v in facets.items() if v is not None}
    unknown = set(given) - set(FACET_PARAMS)
    if unknown:
        raise CdcQueryError(
            f"unknown facet(s): {', '.join(sorted(unknown))}; "
            f"accepted: {', '.join(FACET_PARAMS)}"
        )

    if dataset_id == STUB.dataset_id:
        select, where = _stub(given)
    elif dataset_id == VSRR.dataset_id:
        select, where = _vsrr(concept, given)
    else:
        spec = _spec_for(dataset_id, concept)
        select = _select(spec)
        where = list(spec.base_where)
        where += _cross(spec, given) if spec.mode == "cross" else _stratified(spec, given)

    # Quoted on both sides: a bare number fails against a text time column, while
    # a quoted literal against a numeric column is still compared numerically.
    if year_start is not None:
        where.append(f"{TIME_ALIAS} >= '{int(year_start)}'")
    if year_end is not None:
        where.append(f"{TIME_ALIAS} <= '{int(year_end)}'")

    # A split-period dataset cannot be ordered by the server: `year` alone
    # leaves the months arbitrary, and adding `month` sorts them alphabetically
    # -- April, August, December. compose_period sorts after composing.
    month_field = getattr(_spec_or_none(dataset_id, concept), "month_field", None)
    return {
        "dataset_id": dataset_id,
        "select": select,
        "where": " AND ".join(where),
        "order": None if month_field else TIME_ALIAS,
        "limit": limit,
    }


def _spec_or_none(dataset_id: str, concept: str | None) -> Spec | None:
    """The registry Spec, or None for the two special-cased datasets."""
    if dataset_id in (STUB.dataset_id, VSRR.dataset_id):
        return None
    try:
        return _spec_for(dataset_id, concept)
    except CdcQueryError:
        return None


def compose_period(dataset_id: str, concept: str | None,
                   rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold a split period into one sortable label, and sort by it.

    Only ``xkb8-kh2a`` needs this today: it publishes monthly but splits the
    period across ``year`` and ``month``, so the raw rows carry twelve
    identical ``year`` values per year. Left alone they reach a caller as
    twelve points claiming the same period, in whatever order Socrata returned
    them -- the failure this exists to prevent.

    Rows for every other dataset pass through untouched.
    """
    spec = _spec_or_none(dataset_id, concept)
    if spec is None or not spec.month_field:
        return rows

    composed: list[dict[str, Any]] = []
    for row in rows:
        year = str(row.get(spec.time_field) or "").strip()
        month = MONTH_NUMBER.get(str(row.get(spec.month_field) or "").strip())
        if not year or month is None:
            # An unrecognised month would sort wrongly and read as a real
            # period; drop it rather than publish a label we cannot stand behind.
            continue
        composed.append({"year": f"{year}-{month}", "value": row.get("value")})
    composed.sort(key=lambda r: r["year"])
    return composed


def vocabulary(dataset_id: str, concept: str | None = None) -> dict[str, list[str]]:
    """The facet tokens this dataset actually defines -- the per-dataset subset
    of the tool's union enums.

    ``concept`` is optional here, unlike in :func:`build`. The registry is keyed
    by ``(dataset_id, concept)`` because neither is unique alone, and *fetching*
    genuinely needs both -- w9j2-ggv5's two concepts read different value
    columns. But the facet vocabulary is usually shared: of the six datasets,
    only hksd-2xuw answers differently per concept (``alcohol_consumption``
    publishes no demographic breakdowns, while ``alcohol_binge`` and
    ``chronic_liver_mortality`` publish the full set). So this asks for a
    concept only when one is actually needed to disambiguate.
    """
    if dataset_id == STUB.dataset_id:
        return {k: sorted(v) for k, v in STUB.values.items()}
    if dataset_id == VSRR.dataset_id:
        return {"concept": sorted(VSRR.causes), "sex": sorted(VSRR.sex_columns),
                "rate_type": sorted(VSRR.rates)}
    spec = _spec_for(dataset_id, concept) if concept else _shared_spec(dataset_id)
    out: dict[str, list[str]] = {}
    if spec.mode == "cross":
        for name, facet in spec.facets.items():
            out[name] = ["<any>"] if facet.dynamic else sorted(facet.values)
    else:
        for name, breakdown in spec.breakdowns.items():
            out[name] = sorted(breakdown.values)
        if spec.location_col:
            out["state"] = ["<any postal code>"]
    if spec.rate_type:
        out["rate_type"] = sorted(spec.rate_type.values)
    return out
