"""Meida's own MCP response models -- the shapes this server publishes.

Every tool declares one of these as its return annotation, which is what FastMCP
derives the tool's ``outputSchema`` from. Before this package existed, all tools
were annotated ``Mapping[str, Any]`` and advertised ``{"result": {"type":
"object"}}`` -- a consumer was told an object came back and nothing else.

**Why these are not navi's models.** navi is a client library shared by meida,
yada and alef; its models should mirror each vendor's API faithfully, so they
carry the vendor's HTTP envelope (``status``, ``responseTime``,
``realtime_start``, ``sort_order``) and the vendor's spelling, via pydantic
aliases like ``seriesID``/``periodName``/``adjClose``. Those aliases exist so
navi can *parse* the wire format -- but ``model_json_schema()`` emits by alias,
so passing navi's models straight through would publish Tiingo's camelCase and
BLS's ``Results`` as meida's contract, next to the snake_case that
``timeseries_source_data`` and ``cdc_series_data`` already use. It would also
put meida's published contract in a different repo, where a change made for
yada's benefit would silently reshape this server's schema.

So the boundary is: navi models the vendor, meida models the interface.

Not every source needs a translation. ``bis.py`` and ``cdc.py`` are thin --
those navi models are already snake_case, alias-free and envelope-free, so they
are passed through, and only list wrappers (a bare list yields no
``structuredContent``) and BIS's reshaped datastructure view live here. FRED,
BLS and Tiingo get full models because they are the ones that leak.

Conventions these modules share:

* snake_case field names, no aliases anywhere.
* HTTP transport dropped (``status``, ``responseTime``, ``realtime_*``,
  ``order_by``, ``sort_order``, ``offset``, ``limit``); ``count`` is kept, since
  it is how a caller detects truncation. BLS's ``message`` is kept too, as
  ``notices`` -- on a successful response it is the *only* signal that a result
  was truncated, so it is data rather than transport.
* Observations use the house shape set by ``timeseries_source_models`` --
  ``date`` as an ISO string, ``value`` as a string with ``None`` for a missing
  point, and the row retained so the series calendar stays intact.
* Mappers are pure and total: ``from_*(payload)`` never performs I/O, and a
  ``None`` payload maps to an empty record rather than raising at the tool
  boundary. They read mappings by key as well as by attribute, because a dict
  that misses every ``getattr`` would map to a silently empty result.
* Every model and non-obvious field carries a description -- it is published.
"""
