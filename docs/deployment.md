# Deployment

Do these after pushing to GitHub. The workflows are in `.github/workflows`.

## 1. Enable GitHub Pages

Go to **Settings > Pages**. Under **Build and deployment**, set **Source** to **GitHub Actions**.
The site is built by `refresh.yml` and uploaded as an artifact, so no branch is selected.

The site will be at `https://<owner>.github.io/oss-pulse/`. The base path comes from
`dashboard/observablehq.config.js`. If the repository has another name, set `DASHBOARD_BASE`.

## 2. Set Actions permissions

Go to **Settings > Actions > General**.

- Under **Actions permissions**, allow actions, including those from GitHub and verified creators.
  The workflows use `actions/*` and `astral-sh/setup-uv`.
- Under **Workflow permissions**, select **Read and write permissions**, so that `refresh.yml` can
  push to the `data` branch.

## 3. Run the first refresh

Go to **Actions > refresh > Run workflow**. The first run has no cached partitions, so it ingests
the full seven days. That takes about 10 to 15 minutes. Later runs ingest one day.

The `data` branch is created on the first run. Its commits look like `data: refresh 2026-11-05`.
The schedule is daily at 03:30 UTC. GitHub can disable scheduled workflows on repositories with no
recent activity, so check the Actions tab if refreshes stop.

## 4. Add the dashboard link

Replace the placeholder under the title in `README.md` with the Pages URL.

## Secrets

No secrets need adding. `refresh.yml` uses the built-in `GITHUB_TOKEN` for enrichment, limited to
1,000 REST calls an hour for each repository, which is enough for 500 repositories.

## Limits

- **Disk and memory:** each hour is streamed and its download deleted, and seven days of bronze is
  under 1 GB. DuckDB is capped at 4 GB on the runner.
- **Actions cache:** partitions persist in `actions/cache`. If the cache is evicted, the run rebuilds
  the window from GH Archive, so it is slower but still correct.
- **Volume:** if GH Archive file sizes return to their earlier levels, seven days becomes about
  16 GB of downloads. Each hour is still deleted after processing, so disk stays manageable, but the
  run takes much longer.
