# Upload v9.02 to GitHub

Target repository: https://github.com/civita-network/civita-experimental-data-submission

## Files to upload

Extract the supplied release ZIP first. Upload the **contents** of its folder to the repository root:

```text
index.html
CIVITA-ExpSubmit-v9.02.html
README.md
CHANGELOG.md
LICENSE
.nojekyll
docs/
scripts/
```

Keep the existing `digitize-skill` directory and older HTML releases. This release does not replace the digitize skill or include database changes. The new HTML runs without the documentation or test files, but uploading them gives users the instructions and developers the checks.

## Through VS Code

1. Open the local clone of `civita-experimental-data-submission`.
2. Save/commit any unrelated work, then **Pull** the latest repository changes.
3. Copy the release files and folders above into that clone. If a README already exists, review its differences before replacing it.
4. Open **Source Control**, review the changed files, and stage only this release.
5. Commit with `Release CIVITA Experimental Data Submission v9.02`.
6. **Push** or **Sync Changes**. Complete GitHub sign-in if requested.

Do not upload the release ZIP as a substitute for the extracted site files: GitHub Pages needs `index.html` at the publishing root.

## Through the GitHub website

1. Open the target repository and choose **Add file → Upload files**.
2. Drag in the extracted files and the `docs` and `scripts` folders, preserving the folder structure.
3. Add a release message and commit the changes. Include `.nojekyll` if your file picker shows it; the static HTML can still run without that optional file.

## Publish with GitHub Pages

In repository **Settings → Pages**, choose **Deploy from a branch**, select `main` and `/ (root)`, and save. After deployment completes, the expected website URL is:

https://civita-network.github.io/civita-experimental-data-submission/

Confirm the deployment and URL in the Pages settings. Uploading a file to GitHub and enabling GitHub Pages are separate steps.

## Review after upload

- The front page shows the full Experimental Data Submission title and four choices in a 2x2 layout on desktop.
- AI-assisted mode remains selectable.
- The fourth option opens its JSON portal after Start and shows one skill download link to `digitize-skill`.
- The existing-datasets form displays the new printing field names and units.
- Validate an older JSON backup and review any conversion warnings before using it.

Use a test copy of your dataset for the review. Save/export current work before clearing browser data.
