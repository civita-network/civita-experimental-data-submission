# Changelog

## v9.02

- Named the entry screen CIVITA Experimental Data Submission.
- Restored built-in AI-assisted extraction and API-key/model setup.
- Added Personal AI and Direct JSON submission as a fourth option.
- Arranged the front-page choices in a responsive 2x2 grid.
- Added local JSON validation, guarded loading, workspace review, and a separate central submission action.
- Added instructions for personal AI workflows and a single skill-download link to the repository's existing `digitize-skill` directory.
- Merged printing updates from `CIVITA-v9.01-2.html`: flow rate in mm³/s, hose length in mm, descriptive nozzle orientation, separate nozzle length and diameter, and removal of the active delivery-method field.
- Added migration of older printing values at restore/import and extraction boundaries, preservation of original values in JSON metadata, and warnings for conversions needing manual review.
- Updated printing form labels, embedded help, AI extraction instructions, and the JSON portal's migration/validation compatibility.
- Preserved the existing Geometries, Specimens, and Tests schemas and the guided form rendering logic.

No Supabase SQL or live database changes are included. Live AI calls, hosted deployment, and central submission have not been tested as part of this local release preparation.
