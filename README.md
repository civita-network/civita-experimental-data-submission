# CIVITA Experimental Data Submission

Tools for preparing experimental concrete research data for the CIVITA database. This repository includes the **CIVITA v9.02 browser application** and the **digitize skill**, a supplement to **Personal AI and Direct JSON submission** for extracting tables and plot data from research papers.


## Start here

| What you want to do | Where to start |
| --- | --- |
| Enter data or review an existing dataset | [CIVITA v9.02 application](CIVITA-v9.02/) |
| Use your own AI coding assistant for Personal AI and Direct JSON submission | [Supplementary digitize skill](digitize-skill/README.md) |
| Upload AI-generated JSON for validation and submission | Open CIVITA and choose **Personal AI and Direct JSON submission** |
| Explore an example dataset | [DEMO_GapTest](DEMO_GapTest/) |
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

## 2. Supplementary digitize skill for Personal AI and Direct JSON submission

The [digitize skill](digitize-skill/) supplements the **Personal AI and Direct JSON submission** option. It helps you prepare `concrete_database.json` with your own AI tools, then bring the results into CIVITA. It contains instructions, a data schema, and Python scripts for PDF inspection, table extraction, curve digitization, and database-file generation. Use an AI coding assistant that can read local files and run Python commands. See the [skill README](digitize-skill/README.md) for tool-specific setup and limitations.

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

## 3. Keep backups and stable record IDs

- Keep one skill output folder per paper and reuse it for corrections.
- Keep **`digitize_state.json`**: it preserves record IDs across rebuilds. It is not the submission file.
- Keep original PDFs, extraction drafts, CSV/Excel files, and overlay images for checking.
- Save CIVITA work regularly. Extract `concrete_database.json` from the saved ZIP to restore it with **Load**. Browser storage belongs to the current browser and origin; opening a local file and a hosted site does not share that storage. Transfer work through an exported JSON file.
- After delivering a dataset, follow the skill's instructions for marking it as sent. If previously submitted records change, tell the coordinator that the new file is a correction; importing JSON does not silently overwrite conflicting records.

Contributor names, institutions, and emails are included in generated data. The skill uses a readable form of the contributor email in record IDs. Review the files before sharing them. Keep research submissions and source papers out of GitHub unless you intend to publish them; uploading application code is separate from submitting research data.

## Example dataset: DEMO_GapTest

[DEMO_GapTest](DEMO_GapTest/) is an **example dataset** showing how experimental records and their attachments are organized in a CIVITA export package.

It includes one source, 5 geometries, 5 specimens, 13 tests, 89 data records, and 67 attachment entries, together with table CSVs and a file manifest.

To explore it:

1. Download and extract the repository ZIP, or use your local clone.
2. Save your current CIVITA work before loading the example. If another source is already loaded, clear that working dataset after saving it.
3. Open CIVITA v9.02 and choose **Load**, then select `DEMO_GapTest/concrete_database.json`. This JSON includes the attachments and imported values needed to restore the example.
4. Browse its tables and attached files. Loading the example does not submit it to the central database.

The `tables/` folder contains spreadsheet-friendly CSVs. The `attachments/` folder contains original files and imported values; `manifest.json` links those files to their records. See the [example package notes](DEMO_GapTest/README.txt). Use the example for learning and testing rather than submitting it as a new research contribution.

## Repository contents

```text
DEMO_GapTest/
  concrete_database.json           Example dataset with embedded attachments
  tables/                          Exported table CSVs
  attachments/                     Original files and imported values
  manifest.json                    Attachment-to-record links
  README.txt                       Package notes
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
