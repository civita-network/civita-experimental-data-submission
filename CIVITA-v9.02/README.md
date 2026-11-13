# CIVITA Experimental Data Submission

CIVITA is a browser-based workbench for entering, extracting, validating, and submitting experimental concrete research data. This release is **v9.02**.

Authors: M.Z. Naser, Gianluca Cusatis, and Jiaqi Liu. See [LICENSE](LICENSE).

## Open the app

Open [index.html](index.html), or open `CIVITA-ExpSubmit-v9.02.html` locally in a modern browser. The two HTML files are identical. No installation or build step is required. Internet access is needed to load the Chart.js, PDF.js, and Tesseract.js libraries, use AI providers, access GitHub, or submit to a configured central database.

The front page has four options in a 2x2 layout, switching to a single column on small screens:

1. **Manual data extraction and data submission** — read papers and enter data yourself, with optional hand digitization.
2. **AI-assisted data extraction and submission** — select a model and provide your own provider API key.
3. **Manual data submission from existing datasets** — enter existing results through guided forms.
4. **Personal AI and Direct JSON submission** — extract data using your own AI tools, upload JSON, validate, load, review, and submit separately.

## Instructions

- [User guide](docs/USER-GUIDE.md)
- [GitHub upload and Pages instructions](docs/GITHUB-UPLOAD.md)
- [v9.02 changes](CHANGELOG.md)
- [Current data schema](docs/civita-schema-v9.02.json)
- [Digitize skill on GitHub](https://github.com/civita-network/civita-experimental-data-submission/tree/main/digitize-skill)

## What is included

| File | Purpose |
| --- | --- |
| `index.html` | Default GitHub Pages entry point |
| `CIVITA-ExpSubmit-v9.02.html` | Named release copy of the same application |
| `README.md` | Project overview |
| `docs/` | Usage, upload instructions, and matching schema |
| `CHANGELOG.md` | Changes and compatibility notes |
| `LICENSE` | Original MIT license and attribution |
| `scripts/test-*.mjs` | Regression checks for this release |
| `.nojekyll` | Serves static files directly on GitHub Pages |

The HTML contains the application styles, scripts, and embedded images. The local `docs` and `scripts` folders are not required at runtime. Keep the repository's existing `digitize-skill` folder: the app links to it on GitHub.

## Data and validation

Work is held in browser storage and memory; Save/Export creates a backup you can keep. Moving between a local file and GitHub Pages changes the browser origin: use an exported JSON file to transfer your dataset rather than expecting browser storage to move with the app.

The app works on one source paper at a time. Save/export current work before clearing or switching to a different source. JSON validation checks structure, required fields, controlled vocabularies, and record links. It does not establish scientific correctness; review the extracted values against the source.

Central submission is available only when a database has been configured. This release ships with the existing empty database configuration; this release does not include or apply database changes. Local entry, validation, loading, and export remain available.

## Developer checks

With Node.js installed, run:

```sh
node scripts/test-personal-portal.mjs
node scripts/test-single-source.mjs
node scripts/test-attachment-workflow.mjs
```

These checks cover JavaScript syntax, portal validation, printing migration, single-source behavior, and attachment workflows. They do not replace a browser review or exercise live AI/provider or central-database requests.

When editing a release, keep `index.html` identical to `CIVITA-ExpSubmit-v9.02.html` and regenerate `docs/civita-schema-v9.02.json` if table fields change.
