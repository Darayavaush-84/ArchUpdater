# Publishing a release

Releases are built and published by the **Release** workflow when a `vX.Y.Z` tag is pushed.
It runs CI, builds the wheel and source archive, attests the wheel and creates a GitHub
release with the wheel, source archive, attestation bundle and SHA256 checksums. It uses
GitHub's short-lived workflow identity: no signing key or extra secret is needed.

## Steps

1. Set the new `X.Y.Z` version in `pyproject.toml` and `src/archupdater/__init__.py`, and
   update the version badge in `README.md`.
2. Add a `## [X.Y.Z] - YYYY-MM-DD` section at the top of `CHANGELOG.md`, plus its link at the
   bottom. The workflow publishes exactly this section as the release notes, which the app
   also shows before a self-update; the release fails if the section is missing.
3. Run the checks from the README's development section and commit the tested changes.
4. Push the commit, wait for CI to pass, then push a **new** annotated tag:

   ```bash
   git tag -a vX.Y.Z -m "ArchUpdater X.Y.Z"
   git push origin vX.Y.Z
   ```

## Rules

- Never move an existing release tag or replace its assets. The self-updater accepts only a
  strictly newer stable version, and publishing an already existing release fails.
- The attestation binds the wheel to this repository, the release workflow and the exact tag.
  Releases without one are offered for manual installation only.
- Release notes can be edited afterwards with `gh release edit vX.Y.Z --notes-file <file>`
  without touching the tag or its assets.
