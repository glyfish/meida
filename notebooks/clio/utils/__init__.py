"""Helpers for the Clio-Infra notebooks.

Mirrors ``notebooks/cdc/utils`` and ``notebooks/voteview/utils``: fetchers and
builders as importable modules, the notebooks only drive them.

    fetch       the index, 87 workbooks and 86 description pages
    xlsx        a stdlib worksheet reader -- openpyxl is not in meida's env
    inventory   what the download holds, measured against the index

Nothing here talks to the MCP server yet. Clio is not stored or served; the
MCP helpers arrive with the series build, the way Voteview's did.
"""
