# Woodlands Checkpoint Camera Collector

Polls the [Motorist SG Woodlands Checkpoint traffic camera page](https://www.motorist.sg/embed/cameras/woodlands-checkpoint)
and saves the 7 camera images to disk with metadata logging.

Runs automatically every 5 minutes via GitHub Actions, pushing collected
images to the private data repo:
[redcountryroad/woodlands-cams-data](https://github.com/redcountryroad/woodlands-cams-data).

## How it works

- This repo (`woodlands-cams-collector`) holds the collector code and the
  `.github/workflows/collect.yml` workflow. It contains no image data.
- Every 5 minutes (and on manual trigger via `workflow_dispatch`), the
  workflow checks out both this repo and the private
  `woodlands-cams-data` repo, runs `collector.py --once` writing straight
  into the data repo's checkout, then commits and pushes any new images
  there using a fine-grained PAT (`DATA_REPO_PAT`, `Contents:write` on the
  data repo only).
- Because a scheduled workflow with no other commit activity gets
  auto-disabled by GitHub after 60 days, the workflow also writes a daily
  heartbeat commit (`LAST_RUN.txt`) back to this code repo using the
  default `GITHUB_TOKEN`, keeping the cron alive indefinitely.

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
