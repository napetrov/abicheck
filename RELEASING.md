# Releasing abicheck

## One-time PyPI setup (first release only)

1. Publish a placeholder release to PyPI manually (required before Trusted Publishing can be configured):
   ```bash
   pip install build twine
   python -m build
   twine upload dist/*  # uses username/password or API token, one time only
   ```
2. Go to https://pypi.org/manage/project/abicheck/settings/publishing/
3. Add a **Trusted Publisher**:
   - Owner: `napetrov`
   - Repository: `abicheck`
   - Workflow filename: `publish.yml`
   - Environment: `pypi`
4. Create a GitHub Environment named `pypi` in repo **Settings → Environments**
   - Recommended: add yourself as a required reviewer for extra protection

---

## Release checklist

### 1. Bump version
Edit `pyproject.toml`:
```toml
version = "X.Y.Z"
```

### 2. Update CHANGELOG.md
Move items from `[Unreleased]` to a new `[X.Y.Z] - YYYY-MM-DD` section.

### 3. Commit and push
```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to X.Y.Z"
git push origin main
```

### 4. Dry-run (optional but recommended)
Go to **Actions → Publish to PyPI → Run workflow**:
- Leave `dry_run` checked ✅
- Click **Run workflow**

This builds sdist + wheel and runs `twine check` + wheel smoke test — without publishing.

### 5. Create GitHub Release
Go to **Releases → Draft a new release**:
- Tag: `vX.Y.Z` (must match `pyproject.toml` version, e.g. `v0.2.0`)
- Title: `vX.Y.Z`
- Body: copy from CHANGELOG.md
- Click **Publish release**

The `publish.yml` workflow triggers automatically and publishes to PyPI.

### 6. Verify
- https://pypi.org/project/abicheck/
- `pip install abicheck==X.Y.Z && python -c "import abicheck; print(abicheck.__version__)"`

---

## If publish fails

1. Check Actions log for the failing step
2. If `publish` job failed after `build` succeeded: re-run the workflow manually via **Actions → Re-run failed jobs**
3. If the package was partially uploaded: PyPI does not allow re-uploading the same version. Yank the broken release and bump to `X.Y.Z+1`
4. If OIDC fails (403): verify the Trusted Publisher config on PyPI matches exactly (repo name, workflow filename, environment name)
