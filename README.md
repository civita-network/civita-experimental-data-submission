# CIVITA Experimental Data Submission

Tools for preparing experimental concrete research data for the CIVITA database. This repository includes the **CIVITA v9.02 browser application** and the **digitize skill** for extracting tables and plot data from research papers.

Authors: M.Z. Naser, Gianluca Cusatis, and Jiaqi Liu.

## Start here

| What you want to do | Where to start |
| --- | --- |
| Enter data or review an existing dataset | [CIVITA v9.02 application](CIVITA-v9.02/) |
| Extract tables and curves using your own AI coding assistant | [Digitize skill](digitize-skill/README.md) |
| Upload AI-generated JSON for validation and submission | Open CIVITA and choose **Personal AI and Direct JSON submission** |
| Read the full application instructions | [CIVITA user guide](CIVITA-v9.02/docs/USER-GUIDE.md) |

## 1. Download and open CIVITA

1. On this repository's main GitHub page, choose **Code → Download ZIP**.
2. Extract the ZIP. Keep the `CIVITA-v9.02` and `digitize-skill` folders.
3. Open `CIVITA-v9.02/index.html` in a modern browser. You can also open `CIVITA-v9.02/CIVITA-ExpSubmit-v9.02.html`; both HTML files contain the same application.

No installation or build step is needed for the browser application. Internet access is needed to load its external chart, PDF, and OCR libraries, access GitHub, call AI providers, or submit to a configured database. GitHub's file view shows HTML source; download the file or use a configured GitHub Pages site to run it.

Select an entry option, enter your institution, full name, and email, then press **Start**. The four options appear in a 2×2 layout on desktop and a single column on small screens.

| Entry option | Use it when |
| --- | --- |
| **Manual data extraction and digitization** | You want to read papers, enter values yourself, and optionally digitize figures by hand. |
| **Manual entry of existing datasets** | You already have results and want to enter them through guided forms. |
| **Local AI data extraction** | You want CIVITA's built-in AI extraction; select a model and supply your own provider API key. |
| **Personal AI and Direct JSON submission** | You want to use your own AI tools and upload the resulting JSON for validation and review. No provider API key is required in CIVITA for this mode. |

?Local AI? is the name of the built-in extraction option. It calls the selected external AI provider using your API key; the AI model does not run on your computer.

### Save, load, and submit

- **Save** stores work in the browser and downloads `CIVITA-package.zip` containing dataset JSON, table CSVs, attachments, imported values, and record links.
- **Load** accepts `concrete_database.json`. To restore a saved ZIP package, extract that JSON file first; ZIP files cannot be loaded directly.
- **Submit** is visible in the toolbar and uses the existing central-database submission flow. If a database is not configured, it explains that configuration is missing.
- The separate toolbar **Export** and **Validate** buttons have been removed. Internal validation remains active, and **Validate JSON** remains available in the Personal AI portal.
- The separate **JSON** and **CSVs** download controls remain available.

## 2. Extract data with the digitize skill

The [digitize skill](digitize-skill/) contains instructions, a data schema, and Python scripts for PDF inspection, table extraction, curve digitization, and database-file generation. Use an AI coding assistant that can read local files and run Python commands. See the [skill README](digitize-skill/README.md) for tool-specific setup and limitations.

### Set up the Python tools

Python 3.9 or newer is required; the skill documents testing with Python 3.11. From the repository root, install the dependencies:

```sh
python -m pip install -r digitize-skill/requirements.txt
```

Use `python3` if that is your Python command. Installation needs internet access. The Python extraction scripts run locally after dependencies are installed; the AI assistant's own data handling depends on the tool you choose.

### Ask your assistant to extract a paper

Give the assistant the local path to the skill folder and PDF. For example:

```text
Read digitize-skill/SKILL.md and follow its workflow.
Digitize Figure 3 and Table 2 from my paper.pdf.
Prepare concrete_database.json, CSV, Excel, and overlay check images.
Ask me for my contributor information and use one persistent output folder for this paper.
```

The skill asks which plots or tables to extract, which additional output formats you want, your contributor information, and where to save the output.

The assistant prepares `draft.json`, then uses the builder to create the submission file. For example, with `paper_digitized` as the output folder:

```sh
python digitize-skill/scripts/build_output.py paper_digitized/draft.json paper_digitized --formats json,csv,xlsx
```

**Review the results before submitting.** Check overlay images against the original curves, compare extracted tables with the PDF, and resolve flagged cells and warnings. Do not treat a successful build as proof that every extracted measurement is correct.

## 3. Load the results into CIVITA

1. Open CIVITA v9.02, select **Personal AI and Direct JSON submission**, and press **Start**.
2. Choose the generated **`concrete_database.json`** file. Do not upload `draft.json`, a curve-only JSON file, or `digitize_state.json` as the submission dataset.
3. Press **Validate JSON**. Validation stays in the browser and does not submit or load the file.
4. Correct reported errors with your assistant, upload the corrected JSON, and validate again. Review warnings against the source paper.
5. Press **Load validated JSON**. The app applies its existing single-source and import-conflict checks.
6. Choose **Review workspace** to inspect the imported records. The mode chip in the header lets you return to the portal.
7. If central submission is configured, use **Submit loaded JSON to central DB** and review the confirmation. If submission is unavailable, use **Save** to keep a ZIP backup or **JSON** to download the dataset, and follow the coordinator's delivery instructions.

The submission file must contain a top-level `db` object with known table names and arrays of records. IDs must be unique and references must point to included records. Work on **one paper per dataset**; save current work before clearing it or loading another source.

## 4. Printing data in v9.02

The Geometries, Specimens, and Tests schemas are unchanged. The updated Printing Variables fields include:

| Field | Meaning |
| --- | --- |
| `volumetric_flow_rate_mm3_sec` | Volumetric flow rate in mm³/s |
| `nozzle_orientation` | Descriptive orientation, including angle units where applicable |
| `nozzle_length_mm` | Nozzle length in mm |
| `nozzle_diameter_mm` | Nozzle diameter in mm |
| `hose_length_mm` | Hose length in mm |

Older flow-rate and hose-length fields are converted when plain numeric values can be interpreted safely. Legacy values are preserved in JSON metadata, and values requiring manual conversion are flagged. Review the migration of `nozzle_size_mm` to diameter against your source; do not assume it represents nozzle length.

Use the [v9.02 schema reference](CIVITA-v9.02/docs/civita-schema-v9.02.json) for the current application fields. The skill also has its own [builder schema](digitize-skill/schema/civita_schema.json); if skill output uses older printing fields, validate it in v9.02 and review the migration warnings. See the [user guide](CIVITA-v9.02/docs/USER-GUIDE.md) for the complete conversion rules.

## 5. Keep backups and stable record IDs

- Keep one skill output folder per paper and reuse it for corrections.
- Keep **`digitize_state.json`**: it preserves record IDs across rebuilds. It is not the submission file.
- Keep original PDFs, extraction drafts, CSV/Excel files, and overlay images for checking.
- Save CIVITA work regularly. Extract `concrete_database.json` from the saved ZIP to restore it with **Load**. Browser storage belongs to the current browser and origin; opening a local file and a hosted site does not share that storage. Transfer work through an exported JSON file.
- After delivering a dataset, follow the skill's instructions for marking it as sent. If previously submitted records change, tell the coordinator that the new file is a correction; importing JSON does not silently overwrite conflicting records.

Contributor names, institutions, and emails are included in generated data. The skill uses a readable form of the contributor email in record IDs. Review the files before sharing them. Keep research submissions and source papers out of GitHub unless you intend to publish them; uploading application code is separate from submitting research data.

## Repository contents

```text
CIVITA-v9.02/
  index.html                       Browser entry point
  CIVITA-ExpSubmit-v9.02.html       Named application release
  README.md                        Application overview
  docs/                            User guide, upload guide, and schema
  scripts/                         Application regression checks
  CHANGELOG.md                     Release changes
  LICENSE                          Application license
digitize-skill/
  README.md                        Skill setup and contributor instructions
  SKILL.md                         AI extraction workflow
  requirements.txt                 Python dependencies
  schema/                          Builder data schema
  scripts/                         Extraction and output-building tools
```

For publishing instructions, see [GitHub upload and Pages](CIVITA-v9.02/docs/GITHUB-UPLOAD.md). This repository keeps the application in the `CIVITA-v9.02` subfolder: when publishing `main` from the repository root, its entry page is under `/CIVITA-v9.02/`. A root website URL requires an `index.html` at the repository root or an appropriate deployment workflow.

Application licensing and attribution are provided in [CIVITA-v9.02/LICENSE](CIVITA-v9.02/LICENSE).
