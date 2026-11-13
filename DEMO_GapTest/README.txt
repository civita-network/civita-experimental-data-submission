CIVITA package
concrete_database.json: load this file through CIVITA Load.
tables/: spreadsheet-safe CSVs with original record IDs matching the manifest (not the separately reconciled canonical CSV export).
attachments/: original files and imported values. manifest.json links files to records and reports missing attachments.
JSON preserves raw values; CSVs escape spreadsheet formulas.
The JSON embeds original files and imported values: Load it to restore records and attachments. ZIP loading is not supported.
This package does not submit files to the central database or include the separate PDF cache.
