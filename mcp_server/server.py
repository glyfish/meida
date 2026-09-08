from __future__ import annotations
from typing import Annotated, Any, Awaitable, Callable, Mapping
from lib.logger import get_logger

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from clients import BisClient, BlsClient, CdcClient, FredClient, TiingoClient

from . import cdc_query
from clients.models.bis import BisDataResponse
from clients.models.cdc import CdcDataset

from .responses.bis import BisDataflowList, BisDataStructureView, from_datastructure
from .responses.bls import (
    BlsSeriesData, BlsSurveyInfo, BlsSurveyList,
    from_bls_series_response, from_bls_survey_response, from_bls_surveys_response,
)
from .responses.fred import (
    FredCategoryList, FredObservationList, FredReleaseList, FredSeriesList,
    from_category_response, from_observations_response, from_releases_response,
    from_series_response,
)
from .responses.tiingo import (
    TiingoPriceSeries, TiingoSeriesInfo, from_tiingo_meta, from_tiingo_price_series,
)
from .responses.cdc import CdcCategoryList, CdcDatasetList, CdcTagList
from .series_catalog import SeriesCatalogClient
from .series_catalog_models import (
    CatalogConcept, CatalogConceptList, CatalogEntry, CatalogSearchResult,
)
from .timeseries_source import TimeSeriesSourceClient
from .timeseries_source_models import TimeSeriesRecord, TimeSeriesRefList


logger = get_logger("meida.mcp")

server = FastMCP(
    name="mcp-server",
    instructions=(
        "Curated economic, financial and public-health data: FRED (Federal Reserve), "
        "BLS, BIS, Tiingo end-of-day prices, CDC Socrata, and stored series from "
        "CDC WONDER and NVSR."
    ),
    host="0.0.0.0",
    port=8080,
)


async def _call_fred(handler: Callable[[FredClient], Awaitable[Any]]) -> Any:
    """Create a FredClient and invoke the handler.

    Returns the navi payload unflattened; the tool maps it to meida's own
    response model, which is what FastMCP builds the output schema from.
    """
    async with FredClient() as client:
        return await handler(client)


async def _call_tiingo(handler: Callable[[TiingoClient], Awaitable[Any]]) -> Any:
    """Create a TiingoClient and invoke the handler.

    Returns the navi payload unflattened; the tool maps it to meida's own
    response model, which is what FastMCP builds the output schema from.
    """
    async with TiingoClient() as client:
        return await handler(client)


async def _call_bls(handler: Callable[[BlsClient], Awaitable[Any]]) -> Any:
    """Create a BlsClient and invoke the handler.

    Returns the navi payload unflattened; the tool maps it to meida's own
    response model, which is what FastMCP builds the output schema from.
    """
    async with BlsClient() as client:
        return await handler(client)


async def _call_bis(handler: Callable[[BisClient], Awaitable[Any]]) -> Any:
    """Create a BisClient and invoke the handler.

    The payload is returned unflattened -- each tool declares its response model
    as its return annotation, which is what FastMCP builds the output schema
    from, so serialization is FastMCP's job rather than this helper's.
    """
    async with BisClient() as client:
        return await handler(client)


async def _call_cdc(handler: Callable[[CdcClient], Awaitable[Any]]) -> Any:
    """Create a CdcClient and invoke the handler.

    The payload is returned unflattened -- each tool declares its response model
    as its return annotation, which is what FastMCP builds the output schema
    from, so serialization is FastMCP's job rather than this helper's.
    """
    async with CdcClient() as client:
        return await handler(client)


async def _call_timeseries_source(
    handler: Callable[[TimeSeriesSourceClient], Awaitable[Any]],
) -> Any:
    """Create a TimeSeriesSourceClient and invoke the handler.

    Unlike the other helpers this one may get a *list* of models back, which it
    wraps in :class:`TimeSeriesRefList`: FastMCP derives a tool's output schema
    from its return annotation, and a bare list yields no ``structuredContent``
    at all.
    """
    async with TimeSeriesSourceClient() as client:
        payload = await handler(client)
    return TimeSeriesRefList(series=payload) if isinstance(payload, list) else payload


@server.tool(
    name="fred_category_children",
    description="List the child categories for a FRED category.",
)
async def list_category_children(category_id: int) -> FredCategoryList:
    async def handler(client: FredClient) -> Any:
        # the typed client method, not the private _get it used to reach past it for
        return await client.get_category_children(category_id)

    return from_category_response(await _call_fred(handler))


@server.tool(
    name="fred_category_series",
    description="List the series contained within a FRED category.",
)
async def list_category_series(
    category_id: int,
    limit: int | None = None,
    order_by: str | None = None,
) -> FredSeriesList:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {"category_id": category_id}
        if limit is not None:
            params["limit"] = limit
        if order_by:
            params["order_by"] = order_by
        return await client.get_category_series(**params)

    return from_series_response(await _call_fred(handler))


@server.tool(
    name="fred_series_info",
    description="Fetch metadata for a single FRED series.",
)
async def get_series_info(series_id: str) -> FredSeriesList:
    async def handler(client: FredClient) -> Any:
        return await client.get_series(series_id)

    return from_series_response(await _call_fred(handler))


@server.tool(
    name="fred_series_observations",
    description="Return observations for a series (limit defaults to 100).",
)
async def get_series_observations(
    series_id: str,
    limit: int | None = 100,
    offset: int | None = 0,
    frequency: str | None = None,
    units: str | None = None,
) -> FredObservationList:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {"series_id": series_id}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if frequency:
            params["frequency"] = frequency
        if units:
            params["units"] = units

        response = await client.get_series_observations(**params)
        total = response.count or 0
        returned = len(response.observations)
        effective_limit = limit if limit is not None else total
        effective_offset = offset or 0

        if (effective_offset + returned) < total:
            logger.warning(
                "Incomplete observations for %s (offset=%s, limit=%s, returned=%s, total=%s)",
                series_id,
                effective_offset,
                effective_limit,
                returned,
                total,
            )
        return response

    return from_observations_response(
        await _call_fred(handler), series_id=series_id
    )


@server.tool(
    name="fred_series_updates",
    description="Return recently updated FRED series.",
)
async def get_series_updates(limit: int | None = 100, offset: int | None = 0) -> FredSeriesList:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        return await client.get_series_updates(**params)

    return from_series_response(await _call_fred(handler))


@server.tool(
    name="list_releases",
    description=(
        "List FRED releases — the publications data arrives in, such as the "
        "Employment Situation or the H.15 selected interest rates. Returns the "
        "release ids that fred_release_series takes."
    ),
)
async def list_releases(limit: int | None = 100, order_by: str | None = None) -> FredReleaseList:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if order_by:
            params["order_by"] = order_by
        return await client.get_releases(**params)

    return from_releases_response(await _call_fred(handler))


@server.tool(
    name="fred_release_series",
    description="List the series that belong to a FRED release.",
)
async def list_release_series(release_id: int, limit: int | None = 100) -> FredSeriesList:
    async def handler(client: FredClient) -> Any:
        params: dict[str, Any] = {"release_id": release_id}
        if limit is not None:
            params["limit"] = limit
        return await client.get_release_series(**params)

    return from_series_response(await _call_fred(handler))


@server.tool(
    name="tiingo_series_info",
    description="Fetch metadata for a Tiingo ticker (ETF, mutual fund, or stock), including its available date range.",
)
async def get_tiingo_series_info(ticker: str) -> TiingoSeriesInfo:
    async def handler(client: TiingoClient) -> Any:
        return await client.get_meta(ticker)

    return from_tiingo_meta(await _call_tiingo(handler))


@server.tool(
    name="tiingo_price_series",
    description=(
        "Return the end-of-day price series (OHLCV plus split/dividend-adjusted prices) for a "
        "Tiingo ticker. Provide start_date/end_date as YYYY-MM-DD for a range; omit for the latest day."
    ),
)
async def get_tiingo_price_series(
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
    resample_freq: str | None = None,
) -> TiingoPriceSeries:
    async def handler(client: TiingoClient) -> Any:
        return await client.get_prices(
            ticker,
            start_date=start_date,
            end_date=end_date,
            resample_freq=resample_freq,
        )

    return from_tiingo_price_series(await _call_tiingo(handler))


@server.tool(
    name="bls_series_data",
    description=(
        "Fetch observations for one or more BLS series IDs (up to 50). Optionally "
        "restrict to a start_year/end_year range and enable catalog metadata, net/"
        "percent-change calculations, annual averages, and aspects."
    ),
)
async def bls_series_data(
    series_ids: list[str],
    start_year: int | None = None,
    end_year: int | None = None,
    catalog: bool = False,
    calculations: bool = False,
    annualaverage: bool = False,
    aspects: bool = False,
) -> BlsSeriesData:
    async def handler(client: BlsClient) -> Any:
        return await client.get_series_data(
            series_ids,
            start_year=start_year,
            end_year=end_year,
            catalog=catalog,
            calculations=calculations,
            annualaverage=annualaverage,
            aspects=aspects,
        )

    return from_bls_series_response(await _call_bls(handler))


@server.tool(
    name="bls_series_latest",
    description="Return the single most-recent datapoint for a BLS series.",
)
async def bls_series_latest(series_id: str) -> BlsSeriesData:
    async def handler(client: BlsClient) -> Any:
        return await client.get_series_latest(series_id)

    return from_bls_series_response(await _call_bls(handler))


@server.tool(
    name="bls_popular_series",
    description="List the 25 most popular BLS series IDs, optionally within a survey (e.g. 'LA').",
)
async def bls_popular_series(survey: str | None = None) -> BlsSeriesData:
    async def handler(client: BlsClient) -> Any:
        return await client.get_popular_series(survey)

    return from_bls_series_response(await _call_bls(handler))


@server.tool(
    name="bls_all_surveys",
    description="List all BLS surveys (abbreviation and name).",
)
async def bls_all_surveys() -> BlsSurveyList:
    async def handler(client: BlsClient) -> Any:
        return await client.get_all_surveys()

    return from_bls_surveys_response(await _call_bls(handler))


@server.tool(
    name="bls_survey_info",
    description="Fetch metadata for a single BLS survey by its abbreviation (e.g. 'TU').",
)
async def bls_survey_info(survey_abbreviation: str) -> BlsSurveyInfo:
    async def handler(client: BlsClient) -> Any:
        return await client.get_survey(survey_abbreviation)

    return from_bls_survey_response(await _call_bls(handler))


@server.tool(
    name="bis_dataflows",
    description=(
        "List the BIS statistical dataflows (datasets) available, such as total "
        "credit, policy rates, property prices, and banking statistics. Each entry "
        "gives the dataflow id used by the other BIS tools."
    ),
)
async def bis_dataflows(agency: str = "BIS") -> BisDataflowList:
    async def handler(client: BisClient) -> Any:
        return BisDataflowList(dataflows=await client.get_dataflows(agency))

    return await _call_bis(handler)


@server.tool(
    name="bis_datastructure",
    description=(
        "Describe a BIS dataflow's structure: the ordered dimensions that make up "
        "a series key and the codelist that decodes each one. Set include_codes=true "
        "to also return every code/label pair — some codelists have 1000+ entries, "
        "so it is off by default."
    ),
)
async def bis_datastructure(
    dsd_id: str,
    agency: str = "BIS",
    include_codes: bool = False,
) -> BisDataStructureView:
    async def handler(client: BisClient) -> Any:
        structure = await client.get_datastructure(dsd_id, agency)
        return from_datastructure(structure, include_codes=include_codes)

    return await _call_bis(handler)


@server.tool(
    name="bis_series_data",
    description=(
        "Return observations for a BIS dataflow. 'key' is the dot-joined series key "
        "in dimension order (e.g. 'M.US' for monthly/United States); omit a position "
        "to wildcard it ('M..A'), use '+' for alternatives ('M.US+GB'), or 'all' for "
        "every series. Dimension values come back as codes — use bis_datastructure "
        "to decode them."
    ),
)
async def bis_series_data(
    flow: str,
    key: str = "all",
    start_period: str | None = None,
    end_period: str | None = None,
) -> BisDataResponse:
    async def handler(client: BisClient) -> Any:
        return await client.get_data(
            flow, key, start_period=start_period, end_period=end_period
        )

    return await _call_bis(handler)


@server.tool(
    name="cdc_discover",
    description=(
        "Search the CDC open-data (Socrata) catalog for datasets by keyword "
        "(e.g. 'life expectancy', 'drug overdose') and/or a 'category' from "
        "cdc_categories. Returns dataset ids + names for the other CDC tools."
    ),
)
async def cdc_discover(
    query: str = "", category: str | None = None, limit: int = 20
) -> CdcDatasetList:
    async def handler(client: CdcClient) -> Any:
        return CdcDatasetList(
            datasets=await client.discover(query, category=category, limit=limit))

    return await _call_cdc(handler)


@server.tool(
    name="cdc_categories",
    description=(
        "List the CDC catalog's categories with dataset counts (e.g. 'National "
        "Center for Health Statistics', 'Behavioral Risk Factors') — the topic map "
        "for browsing. Pass a category to cdc_discover to list its datasets."
    ),
)
async def cdc_categories() -> CdcCategoryList:
    async def handler(client: CdcClient) -> Any:
        return CdcCategoryList(categories=await client.categories())

    return await _call_cdc(handler)


@server.tool(
    name="cdc_tags",
    description=(
        "List the CDC catalog's tags with dataset counts (e.g. 'mortality', "
        "'covid-19', 'prevalence') — finer-grained topics for search."
    ),
)
async def cdc_tags() -> CdcTagList:
    async def handler(client: CdcClient) -> Any:
        return CdcTagList(tags=await client.tags())

    return await _call_cdc(handler)


@server.tool(
    name="cdc_dataset_columns",
    description=(
        "Describe a CDC dataset's columns (field name, type, label) from its id — "
        "use it to see which fields to filter/select in cdc_series_data. CDC "
        "datasets have inconsistent schemas, so check columns before querying."
    ),
)
async def cdc_dataset_columns(dataset_id: str) -> CdcDataset:
    async def handler(client: CdcClient) -> Any:
        return await client.columns(dataset_id)

    return await _call_cdc(handler)


class CdcSeriesPoint(BaseModel):
    """One observation. Socrata returns every value as a string."""

    year: str
    value: str | None = None


class CdcSeriesResponse(BaseModel):
    """A CDC series, plus the SoQL it was resolved to.

    ``where`` is reported for provenance -- it is an output, never an input.
    """

    dataset_id: str
    concept: str | None = None
    where: str
    row_count: int
    rows: list[CdcSeriesPoint]


@server.tool(
    name="cdc_series_data",
    description=(
        "Return one CDC time series, selected by naming its facets. Facet names and "
        "tokens are the catalog's metadata keys, so a value read off a discovered "
        "series passes straight back in. Enums are the union across datasets — see "
        "cdc_dataset_facets for what one dataset actually defines. Several "
        "datasets stratify one demographic at a time, so age and race together is "
        "usually a series that was never published."
    ),
)
async def cdc_series_data(
    dataset_id: cdc_query.DatasetId,
    concept: Annotated[cdc_query.Concept | None, Field(
        description="Required where one dataset serves several: w9j2-ggv5 is "
                    "life_expectancy or mortality; 489q-934x is suicide, "
                    "drug_overdose or chronic_liver_mortality.")] = None,
    state: Annotated[cdc_query.State | None, Field(
        description="Two-letter postal code. 'US' is the national rollup and 'YC' is "
                    "New York City, which BRFSS reports separately from NY.")] = None,
    race: Annotated[cdc_query.Race | None, Field(
        description="Vocabularies differ by dataset — w9j2-ggv5 has only "
                    "all/black/white, and 'asian_pi' is 9j2v-jamp's older combined "
                    "category, not interchangeable with 'asian'.")] = None,
    sex: cdc_query.Sex | None = None,
    age: Annotated[cdc_query.Age | None, Field(
        description="Bands differ by dataset: hksd-2xuw uses 18-44/45-64/65+, the "
                    "suicide datasets use 10-14/15-19/... . Age is published crude "
                    "only on some datasets.")] = None,
    drug: cdc_query.Drug | None = None,
    rate_type: cdc_query.RateTypeToken | None = None,
    period: cdc_query.Period | None = None,
    year_start: Annotated[int | None, Field(description="Inclusive lower bound.")] = None,
    year_end: Annotated[int | None, Field(description="Inclusive upper bound.")] = None,
    limit: int = 1000,
) -> CdcSeriesResponse:
    query = cdc_query.build(
        dataset_id, concept,
        state=state, race=race, sex=sex, age=age, drug=drug,
        rate_type=rate_type, period=period,
        year_start=year_start, year_end=year_end, limit=limit,
    )

    async def handler(client: CdcClient) -> Any:
        return await client.query(**query)

    payload = await _call_cdc(handler)
    rows = [CdcSeriesPoint(**row) for row in payload.rows]
    return CdcSeriesResponse(
        dataset_id=dataset_id, concept=concept, where=query["where"],
        row_count=len(rows), rows=rows,
    )


class CdcFacetVocabulary(BaseModel):
    dataset_id: str
    concept: str | None = None
    facets: dict[str, list[str]]


@server.tool(
    name="cdc_dataset_facets",
    description=(
        "The facet tokens one CDC dataset actually defines — the per-dataset subset "
        "of cdc_series_data's union enums. Use it to check what is available before "
        "querying, or after an unsupported-token error."
    ),
)
async def cdc_dataset_facets(
    dataset_id: cdc_query.DatasetId, concept: cdc_query.Concept | None = None
) -> CdcFacetVocabulary:
    return CdcFacetVocabulary(
        dataset_id=dataset_id, concept=concept,
        facets=cdc_query.vocabulary(dataset_id, concept),
    )


@server.tool(
    name="timeseries_source_list",
    description=(
        "List stored time series held in meida's database — sources that cannot be "
        "fetched per request, currently CDC WONDER (cause-of-death rates: alcohol, "
        "drug, suicide, homicide, firearm, chronic liver, deaths of despair) and CDC "
        "NVSR (life expectancy / life tables). Returns identity and coverage without "
        "observations, as {'series': [...]}. Optional 'source' filters to cdc_wonder or cdc_nvsr."
    ),
)
async def timeseries_source_list(source: str | None = None) -> TimeSeriesRefList:
    async def handler(client: TimeSeriesSourceClient) -> Any:
        return await client.list_series(source=source)

    return await _call_timeseries_source(handler)


@server.tool(
    name="timeseries_source_data",
    description=(
        "Return one stored time series in full, with its observations, from meida's "
        "database (CDC WONDER cause-of-death rates, CDC NVSR life expectancy). "
        "'source' is cdc_wonder or cdc_nvsr and 'native_id' is the series identifier "
        "from timeseries_source_list. Pass 'frequency' only if an id is ambiguous. "
        "Observation values are strings — cast as needed."
    ),
)
async def timeseries_source_data(
    source: str,
    native_id: str,
    frequency: str | None = None,
) -> TimeSeriesRecord:
    async def handler(client: TimeSeriesSourceClient) -> Any:
        return await client.get_series(source, native_id, frequency=frequency)

    return await _call_timeseries_source(handler)


@server.tool(
    name="timeseries_source_stale",
    description=(
        "List stored series that are due for an update — past their refresh horizon. "
        "These sources have no live API (CDC WONDER is throttled behind a bot filter; "
        "NVSR is a manual annual download), so refreshing is a deliberate act rather "
        "than an automatic re-fetch. Stale series are still served normally. Returns {'series': [...]}."
    ),
)
async def timeseries_source_stale(source: str | None = None) -> TimeSeriesRefList:
    async def handler(client: TimeSeriesSourceClient) -> Any:
        return await client.list_stale(source=source)

    return await _call_timeseries_source(handler)


async def _call_series_catalog(
    handler: Callable[[SeriesCatalogClient], Awaitable[Any]],
) -> Any:
    """Create a SeriesCatalogClient and invoke the handler."""
    async with SeriesCatalogClient() as client:
        return await handler(client)


@server.tool(
    name="series_catalog_search",
    description=(
        "Find which series exist, without fetching any data. Filters are exact, not "
        "fuzzy: narrow by dataset_id, concept, and facet values (e.g. "
        "{'state': 'TX', 'race': 'hispanic'}). Each result carries a 'retrieval' "
        "block naming the tool that fetches it — cdc_series_data for live Socrata "
        "series, timeseries_source_data for stored WONDER and NVSR ones — and a "
        "'facets' block whose keys are exactly the arguments cdc_series_data takes. "
        "'total' counts every match, so compare it against the entries returned to "
        "tell a complete result from a truncated one. Descriptions are shared across "
        "series that differ only by facet value, so filter on facets rather than "
        "trying to pick a series out by its prose."
    ),
)
async def series_catalog_search(
    source: str | None = None,
    dataset_id: str | None = None,
    concept: Annotated[str | None, Field(
        description="What is measured, e.g. 'alcohol_binge', 'suicide', "
                    "'life_expectancy'. See series_catalog_concepts.")] = None,
    facets: Annotated[dict[str, Any] | None, Field(
        description="Facet values to match, e.g. {'state': 'TX', 'sex': 'male'}. "
                    "Matched by containment: an entry qualifies if it carries all "
                    "of these, whatever else it also has.")] = None,
    active_only: Annotated[bool, Field(
        description="Only series still being updated, judged per vintage so "
                    "provisional data does not make final data look stale.")] = False,
    limit: int = 50,
) -> CatalogSearchResult:
    async def handler(client: SeriesCatalogClient) -> Any:
        return await client.search(
            source=source, dataset_id=dataset_id, concept=concept,
            facets=facets, active_only=active_only, limit=limit,
        )

    entries, total = await _call_series_catalog(handler)
    return CatalogSearchResult(total=total, returned=len(entries), entries=entries)


@server.tool(
    name="series_catalog_entry",
    description=(
        "Look up one catalog entry by its series_id — its coverage, units, facets, "
        "and the tool that fetches it."
    ),
)
async def series_catalog_entry(series_id: str, source: str = "cdc") -> CatalogEntry:
    async def handler(client: SeriesCatalogClient) -> Any:
        return await client.get(series_id, source=source)

    return await _call_series_catalog(handler)


@server.tool(
    name="series_catalog_concepts",
    description=(
        "What the catalog measures, with a series count per concept and dataset — "
        "the coarse map to pick a concept before searching within it. A concept "
        "served by several datasets appears once per dataset, because those are "
        "different series with different coverage and vocabularies."
    ),
)
async def series_catalog_concepts(source: str | None = None) -> CatalogConceptList:
    async def handler(client: SeriesCatalogClient) -> Any:
        return await client.concepts(source=source)

    rows = await _call_series_catalog(handler)
    return CatalogConceptList(concepts=[CatalogConcept(**r) for r in rows])


def run() -> None:
    """Start the MCP server over SSE transport."""
    logger.info("Starting meida MCP server on port %s (transport=sse)", server.settings.port)
    server.run(transport="sse")


if __name__ == "__main__":
    run()
