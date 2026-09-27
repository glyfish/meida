"""Helpers for the FBI Crime Data Explorer notebooks.

    fetch    the CDE API: monthly offences, annual police employment
    catalog  harvest and export the series catalogue for the document store
    arrest_harvest  the arrest catalogue's harvest as a resumable CLI: three
             hours of requests, checkpointed pair by pair so a kill costs one
    mcp      the FBI tools over MCP, and a first, simpler filing rule
    filing   the filing rule both analysis notebooks apply, and its readers
    nibrs    NIBRS incident files: clearance by reason, by month and offence

Mirrors the other sources: fetchers and builders as importable modules, the
notebooks only drive them.
"""
