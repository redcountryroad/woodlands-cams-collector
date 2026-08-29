# Woodlands Checkpoint Camera Collector

Polls the [Motorist SG Woodlands Checkpoint traffic camera page](https://www.motorist.sg/embed/cameras/woodlands-checkpoint)
and saves the 7 camera images to disk with metadata logging.

Runs automatically every 5 minutes via GitHub Actions, pushing collected
images to the private data repo:
[redcountryroad/woodlands-cams-data](https://github.com/redcountryroad/woodlands-cams-data).

## How it works

- This repo (`woodlands-cams-collector`) holds the collector code and the
  `.github/workflows/collect.yml` workflow. It contains no image data.
- Every run (triggered on a 5-minute cadence — see
  [External scheduling](#external-scheduling-cron-joborg) below) the
  workflow checks out both this repo and the private
  `woodlands-cams-data` repo, runs `collector.py --once` writing straight
  into the data repo's checkout, then commits and pushes any new images
  there using a fine-grained PAT (`DATA_REPO_PAT`, `Contents:write` on the
  data repo only).
- Because a scheduled workflow with no other commit activity gets
  auto-disabled by GitHub after 60 days, the workflow also writes a daily
  heartbeat commit (`LAST_RUN.txt`) back to this code repo using the
  default `GITHUB_TOKEN`, keeping the cron alive indefinitely.

## Setting up GitHub Actions

1. Fork/clone this repo as `<your-username>/woodlands-cams-collector`
   (public) and create a separate private data repo,
   `<your-username>/woodlands-cams-data`.
2. Update the `repository:` field under the "Checkout data repo" step and
   the README links in this file to point at your own data repo.
3. Create a fine-grained PAT scoped **only** to the data repo, with
   **Contents: Read and write**, and add it to the code repo as a secret
   named `DATA_REPO_PAT` (Settings → Secrets and variables → Actions).
4. Confirm the workflow has `permissions: contents: write` at the top
   level (already set in `collect.yml`) — this lets the heartbeat step
   push back to the code repo using the default `GITHUB_TOKEN`, no extra
   secret needed for that part.
5. Trigger a manual run once from the Actions tab
   (`workflow_dispatch`) to confirm everything is wired up correctly
   before relying on scheduling.

## External scheduling (cron-job.org)

GitHub's native `schedule:` trigger is **best-effort, not guaranteed** —
it can be delayed or silently dropped, especially for short (5-minute)
intervals and on newly-added workflows. `collect.yml` keeps the native
`schedule:` trigger as a harmless bonus (any ticks GitHub does fire are
free extra coverage), but the actual 5-minute cadence is driven
externally by pinging the workflow's `workflow_dispatch` API endpoint
from [cron-job.org](https://cron-job.org).

**1. Create a dedicated PAT for triggering runs.** At
https://github.com/settings/tokens?type=beta, generate a new
fine-grained token:

| Field | Value |
|---|---|
| Resource owner | your account |
| Repository access | Only select repositories → `woodlands-cams-collector` |
| Repository permissions → Actions | **Read and write** |

This must be a separate token from `DATA_REPO_PAT` — different repo,
different permission. It is never stored as a GitHub secret; it lives
only in cron-job.org's job config as a request header.

**2. Create the cron-job.org job:**

- **URL**: `https://api.github.com/repos/<owner>/woodlands-cams-collector/actions/workflows/collect.yml/dispatches`
- **Method**: `POST`
- **Schedule**: every 5 minutes
- **Headers**:
  ```
  Authorization: Bearer <your PAT>
  Accept: application/vnd.github+json
  X-GitHub-Api-Version: 2022-11-28
  Content-Type: application/json
  User-Agent: woodlands-cams-cron-trigger
  ```
- **Body**: `{"ref":"main"}`

A successful call returns HTTP `204 No Content`. If you get a `403` with
`"Resource not accessible by personal access token"`, the PAT's Actions
permission is set to Read-only instead of Read and write — regenerate it
with the correct permission.

**3. Verify:** after a test run, check
`gh run list --workflow=collect.yml --event workflow_dispatch` (or the
Actions tab) for a new run, then let it run for 20–30 minutes to confirm
runs land consistently every 5 minutes.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

### Run once

Fetches the current images for all 7 cameras and exits.

```bash
python3 collector.py --once
```

### Run continuously (every 5 minutes)

Polls in a loop, sleeping `--interval` seconds (default 300 = 5 min)
between cycles. Runs until interrupted with Ctrl+C.

```bash
python3 collector.py --loop --interval 300
```

To run it in the background and keep collecting after you close the
terminal:

```bash
nohup python3 collector.py --loop --interval 300 >> collector.log 2>&1 &
```

Add `--verbose` to either mode for DEBUG-level logging. Use `--output-dir PATH`
to change where images and metadata are written (default `./images`).

## Output

- Images: `<output-dir>/<YYYY-MM-DD>/<camera_id>/<camera_id>_<timestamp>.jpg`
- Metadata: one JSON record per saved image, appended to `<output-dir>/metadata.jsonl`
