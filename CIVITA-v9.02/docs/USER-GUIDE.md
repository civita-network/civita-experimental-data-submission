# Using CIVITA v9.02

## Begin a session

1. Open the app and select a front-page option.
2. Enter your institution, full name, and email. The app uses these to attribute records and create contributor-specific IDs.
3. For built-in AI extraction, select the provider model and supply its API key. Personal AI/JSON mode does not require an API key in CIVITA.
4. Press **Start**.

Use the mode chip in the header to return to the choice screen. In Personal AI/JSON mode it also reopens the JSON portal; close the portal to reach the choice screen or workspace.

## Existing datasets

Choose **Manual data submission from existing datasets**. Create parent records before their children, following the links shown by the form. For example, create a source, material batch, and geometry before linking specimens; link tests to their specimens. A printing record links to its source and geometry, and a specimen can link to a printing record.

The Geometries, Specimens, and Tests schemas are unchanged in v9.02. Printing fields use the updated template:

| Field | Entry convention |
| --- | --- |
| `printing_speed_mm_sec` | mm/s |
| `volumetric_flow_rate_mm3_sec` | mm³/s |
| `nozzle_orientation` | Description; include angle units where relevant |
| `nozzle_length_mm` | Nozzle length in mm |
| `nozzle_diameter_mm` | Nozzle diameter in mm |
| `hose_length_mm` | Hose length in mm |
| `hose_diameter_mm` | Hose diameter in mm |
| `extrusion_pressure_pa` | Pa |

The old `deliver_method` field is no longer active. Other unchanged printing fields remain available in the app and schema reference.

## Older saved printing data

When restoring or loading old JSON, CIVITA upgrades older printing fields:

- `volumetric_flow_rate_m3_h` becomes `volumetric_flow_rate_mm3_sec`, multiplied by 1,000,000,000 / 3,600 for plain numeric values.
- `hose_length_m` becomes `hose_length_mm`, multiplied by 1,000 for plain numeric values.
- `nozzle_size_mm` is carried into `nozzle_diameter_mm`; verify that the old value actually describes a diameter. It is not used as a nozzle length.
- `nozzle_orientation_angle_deg` becomes `nozzle_orientation` with a `deg` suffix.
- `deliver_method` is retained in legacy JSON metadata, rather than an active table column.

Original legacy values are kept in saved JSON metadata. Existing nonempty values in the new fields take precedence. Ranges or unit-bearing text that cannot be converted automatically are retained in metadata and flagged by **Validate**; enter the correct value in the new unit field. Review all conversions against your source.

## Personal AI and Direct JSON submission

1. Select the fourth option and press **Start**.
2. Use **Download skill ZIP** to open the repository's `digitize-skill` folder. From the repository main page, choose **Code → Download ZIP** and extract the `digitize-skill` folder. Follow its README and skill instructions.
3. Give your chosen AI tool the skill instructions, supporting files, and paper/data. The portal contains guidance for ChatGPT, Claude, Gemini, and other tools, plus a prompt you can copy.
4. Use [the v9.02 schema](civita-schema-v9.02.json) as the current submission field reference, especially if older skill output uses the previous printing fields.
5. Request a JSON file with a top-level `db` object mapping known table names to arrays of records. Include exactly one source paper. Keep IDs unique and all referenced records in the file.
6. Choose the JSON file and press **Validate JSON**. Validation does not send or load your dataset. Correct reported errors and upload the revised file; review warnings.
7. Press **Load validated JSON**. Import preserves the existing merge/conflict and single-source checks. Save/export other work before attempting to load a different source.
8. Select **Review workspace** to check the data. Return to the portal through the mode chip.
9. When central submission is configured, use **Submit loaded JSON to central DB** and review the app's confirmation. Uploading or validating a file alone does not submit it.

## Save and transfer

Use **Save** or JSON export regularly. Browser storage belongs to the current browser origin; the local HTML file and hosted GitHub Pages app do not share that storage. Load an exported JSON file to transfer work. Keep copies of your original source files and exported backups.
