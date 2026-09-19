"""Helpers for Clio-Infra at historical borders, from DataverseNL.

The same indicators as ``notebooks/clio``, deposited on DataverseNL with a
different geography: one row per **historical border period** (GeaCron before
1946, CShapes after) rather than one per modern country. The main site files
Ottoman wages under Turkey; this keeps the Ottoman Empire.

DataverseNL refuses automated clients outright -- headless Brave was denied on
sight -- so there is no fetch. Datasets are downloaded by hand and filed with
:func:`accept.accept`, which records the DOI, the deposit version and the
download date. Updating is manual and per dataset, which suits data that is
almost entirely historical.

    accept          file a hand-downloaded dataset folder under data/raw/
    workbook        read the Data sheet: title, unit, border periods, values
    documentation   read the .docx working paper into its numbered sections
    xlsx            stdlib worksheet reader, copied from notebooks/clio
"""
