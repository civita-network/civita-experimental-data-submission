# Digitize skill — for contributors

Turns the plots and tables of a PDF paper into a `concrete_database.json` file you email
to the database coordinator. Everything runs on your computer.

## Install

You need Python 3.9 or newer (tested on 3.11), then, once (needs internet):
```
python -m pip install -r requirements.txt
```
(`python3` on Mac/Linux. `requirements-tested.txt` pins the exact tested versions.)

- **Claude Code**: copy this whole folder to `~/.claude/skills/digitize/`.
- **Codex CLI**: copy this folder to `~/.codex/skills/digitize/`, or start Codex inside this
  folder (it reads `AGENTS.md`).
- **Other coding agents** (Aider, Cline, OpenCode, Cursor, Kimi / DeepSeek / Qwen based
  tools...): the agent must be able to run shell commands and read files. Start it in this
  folder and tell it: *"Read SKILL.md and follow it"* (Aider: `/read SKILL.md`). Models
  that cannot view images can run everything, but then YOU must open the overlay images
  and table renders and check them.
- **claude.ai** (not tested yet): zip this folder and upload it under Settings →
  Capabilities → Skills. Its sandbox may not allow installing the OCR package, in which
  case scanned pages will not work there; use Claude Code or Codex instead.

## Use

Ask the assistant, e.g. *"Digitize Fig. 3 and Table 2 of paper.pdf"*. It asks what to
extract, which formats you want, and your name / university / email (once), then writes
an output folder next to the PDF.

Check the `overlays/` images: the dots must sit on the printed curves.

## What to send

Send only `concrete_database.json`. Keep the rest of the folder, especially
`digitize_state.json`: it keeps your record IDs the same if you redo the paper.

## Privacy

Your name, university and email are written into the file you send (the coordinator needs
them), and a readable form of your email starts every record ID. Nothing is sent anywhere
by the scripts.

## After sending, and corrections

Use ONE output folder per paper. After you send the file, tell the assistant "I sent it":
it marks the build as sent (`--sent`). If you later fix something, rebuild in the SAME
folder: it tells you which records changed. Changed records keep their IDs, so tell the
coordinator the new file is a correction. If you only added records, you can send
`concrete_database_additions.json` instead.
