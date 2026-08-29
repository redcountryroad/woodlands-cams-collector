#!/usr/bin/env python3
"""Continuously poll the Motorist SG Woodlands Checkpoint traffic camera page
and save the camera images to disk with metadata logging."""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

PAGE_URL = "https://www.motorist.sg/embed/cameras/woodlands-checkpoint"
EXPECTED_CAMERA_IDS = {"22", "21", "3034", "3122", "1151", "1251", "2841"}
IMAGES_ROOT = Path("images")
METADATA_PATH = IMAGES_ROOT / "metadata.jsonl"
MIN_IMAGE_BYTES = 2 * 1024
SGT = ZoneInfo("Asia/Singapore")
USER_AGENT = (
    "Mozilla/5.0 (compatible; WoodlandsCamCollector/1.0; "
    "+https://www.motorist.sg/embed/cameras/woodlands-checkpoint)"
)

IMAGE_ID_RE = re.compile(r"/traffic_camera/image/(\d+)/")

log = logging.getLogger("collector")


class Camera:
    __slots__ = ("camera_id", "name", "image_url")

    def __init__(self, camera_id: str, name: str, image_url: str):
        self.camera_id = camera_id
        self.name = name
        self.image_url = image_url


def fetch_with_retry(url: str, session: requests.Session, retries: int = 2,
                      backoff_seconds: float = 5.0, **kwargs) -> requests.Response:
    """Attempt an HTTP GET, retrying on network errors with a fixed backoff."""
    attempts = retries + 1
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(url, timeout=15, **kwargs)
            resp.raise_for_status()
            return resp
        except (requests.RequestException, OSError) as exc:
            last_exc = exc
            log.warning(
                "Request failed (attempt %d/%d) for %s: %s", attempt, attempts, url, exc
            )
            if attempt < attempts:
                time.sleep(backoff_seconds)
    raise last_exc


def parse_cameras(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    cameras = []
    for card in soup.select("div.traffic-camera-item"):
        img = card.select_one("img.rewards-image")
        if img is None or not img.get("src"):
            log.warning("Skipping camera card with no image src")
            continue
        src = img["src"]
        match = IMAGE_ID_RE.search(src)
        if not match:
            log.warning("Could not extract camera id from src: %s", src)
            continue
        camera_id = match.group(1)

        name_tag = card.select_one("p.press-name")
        if name_tag and name_tag.get_text(strip=True):
            name = name_tag.get_text(strip=True)
        else:
            meta_name = card.select_one('meta[itemprop="name"]')
            name = meta_name["content"].strip() if meta_name else f"camera-{camera_id}"

        cameras.append(Camera(camera_id, name, src))

    found_ids = {c.camera_id for c in cameras}
    if len(cameras) != 7 or found_ids != EXPECTED_CAMERA_IDS:
        log.warning(
            "Expected 7 cameras with ids %s, found %d with ids %s",
            sorted(EXPECTED_CAMERA_IDS, key=int),
            len(cameras),
            sorted(found_ids, key=int),
        )
    return cameras


def save_camera_image(camera: Camera, session: requests.Session) -> bool:
    """Download, validate, and save one camera's image plus metadata. Returns True on success."""
    resp = fetch_with_retry(camera.image_url, session)
    content = resp.content

    if len(content) < MIN_IMAGE_BYTES:
        log.warning(
            "Image for camera %s (%s) is only %d bytes (< %d), rejecting",
            camera.camera_id, camera.name, len(content), MIN_IMAGE_BYTES,
        )
        return False

    now = datetime.now(SGT)
    date_dir = now.strftime("%Y-%m-%d")
    ts_compact = now.strftime("%Y%m%d_%H%M%S")

    out_dir = IMAGES_ROOT / date_dir / camera.camera_id
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{camera.camera_id}_{ts_compact}.jpg"
    out_path = out_dir / filename

    out_path.write_bytes(content)

    md5_hash = hashlib.md5(content).hexdigest()
    saved_path = str(out_path)

    record = {
        "fetch_time": now.isoformat(),
        "camera_id": camera.camera_id,
        "camera_name": camera.name,
        "source_url": camera.image_url,
        "saved_path": saved_path,
        "md5_hash": md5_hash,
        "file_size_bytes": len(content),
    }
    with METADATA_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    log.info(
        "Saved camera %s (%s) -> %s (%d bytes)",
        camera.camera_id, camera.name, saved_path, len(content),
    )
    return True


def run_cycle(session: requests.Session) -> tuple:
    """Run one poll cycle. Returns (success_count, total_count)."""
    resp = fetch_with_retry(PAGE_URL, session)
    cameras = parse_cameras(resp.text)
    log.info("Parsed %d camera(s) from page", len(cameras))

    success = 0
    for camera in cameras:
        try:
            if save_camera_image(camera, session):
                success += 1
        except Exception as exc:
            log.exception(
                "Failed to process camera %s (%s): %s", camera.camera_id, camera.name, exc
            )
    return success, len(cameras)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit")
    parser.add_argument("--loop", action="store_true", help="Run forever, polling repeatedly")
    parser.add_argument(
        "--interval", type=int, default=300, help="Seconds between cycles in --loop mode (default 300)"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    parser.add_argument(
        "--output-dir", type=str, default="./images", help="Directory to save images and metadata to (default ./images)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    if not args.once and not args.loop:
        log.info("No mode specified, defaulting to --once")
        args.once = True

    global IMAGES_ROOT, METADATA_PATH
    IMAGES_ROOT = Path(args.output_dir)
    METADATA_PATH = IMAGES_ROOT / "metadata.jsonl"

    IMAGES_ROOT.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    total_success = 0
    total_seen = 0
    cycles = 0

    try:
        if args.once:
            success, seen = run_cycle(session)
            total_success += success
            total_seen += seen
            cycles += 1
        else:
            while True:
                cycle_start = time.monotonic()
                try:
                    success, seen = run_cycle(session)
                    total_success += success
                    total_seen += seen
                except Exception:
                    log.exception("Cycle failed unexpectedly")
                    success, seen = 0, 0
                cycles += 1
                elapsed = time.monotonic() - cycle_start
                sleep_for = max(0, args.interval - elapsed)
                log.info(
                    "Cycle %d complete: %d/%d cameras saved. Sleeping %.0fs",
                    cycles, success, seen, sleep_for,
                )
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        log.info("Interrupted by user, shutting down after current save completes")
    finally:
        log.info(
            "Summary: %d cycle(s) run, %d/%d camera image(s) saved successfully",
            cycles, total_success, total_seen,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
