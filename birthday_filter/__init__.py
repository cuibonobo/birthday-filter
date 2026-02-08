import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict

import birthday_filter.config as cfg
from birthday_filter.dav_upload import upload_to_dav


def log(msg):
    print(f"[birthday-filter] {msg}")


def load_cache(cache_file: Path) -> Dict[str, str]:
    """Load the event cache from disk.

    Returns a dict mapping event UUID to content hash.
    """
    if not cache_file.exists():
        return {}

    try:
        with open(cache_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        log(f"Warning: Failed to load cache ({e}), starting fresh")
        return {}


def save_cache(cache_file: Path, cache: Dict[str, str]) -> None:
    """Save the event cache to disk."""
    with open(cache_file, "w") as f:
        json.dump(cache, f, indent=2)


def hash_content(content: str) -> str:
    """Calculate SHA256 hash of content."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def download_vips_file(vips_file: Path) -> bool:
    """Download the VIP group file from CardDAV server via curl.

    Returns True if successful, False otherwise.
    """
    log("Downloading VIP group from CardDAV server...")
    vips_url = f"{cfg.CARDDAV.url}dav/addressbooks/user/{cfg.CARDDAV.username}/Default/vips.vcf"

    result = subprocess.run(
        [
            "curl", "-X", "GET",
            "-u", f"{cfg.CARDDAV.username}:{cfg.CARDDAV.password}",
            "-w", "\nHTTP_CODE:%{http_code}",
            "-s",
            vips_url
        ],
        capture_output=True,
        text=True
    )

    # Parse HTTP response code
    http_code = None
    output = result.stdout
    if "HTTP_CODE:" in output:
        parts = output.split("HTTP_CODE:")
        if len(parts) == 2:
            http_code = parts[1].strip()
            output = parts[0]

    if http_code == "200":
        # Save the downloaded vips.vcf
        with open(vips_file, "w") as f:
            f.write(output)
        log("VIP group downloaded successfully")
        return True
    elif http_code == "404":
        log("No VIP group found on server")
        return False
    else:
        log(f"Warning: Failed to download VIP group (HTTP {http_code})")
        return False


def main():
    log("Doing initial setup")
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Create one directory to read the cards (it is read-only) and
    # then two directories to read and write the calendar (it is
    # read-write).
    card_dir = cfg.DATA_DIR / "pimsync-cards"
    cal_dir = cfg.DATA_DIR / "pimsync-cal"
    vd_cfg_file = cfg.DATA_DIR / "pimsync-config"
    vd_status_file = cfg.DATA_DIR / "pimsync-status"
    with open(vd_cfg_file, "w") as f:
        f.write(f"""
status_path {vd_status_file}

storage cards {{
  type vdir/vcard
  path {card_dir}
}}

storage carddav {{
  type carddav
  url {cfg.CARDDAV.url}
  username {cfg.CARDDAV.username}
  password {cfg.CARDDAV.password}
  read_only
}}

pair card_download {{
  storage_a cards
  storage_b carddav
  collections from b
  conflict_resolution keep b
}}
        """.strip() + "\n")
    (card_dir / "Default").mkdir(parents=True, exist_ok=True)
    log("Running pimsync to download cards")
    run_vd = lambda *args: subprocess.run(
        ["pimsync", "-c", str(vd_cfg_file), *args], check=True
    )
    run_vd("sync", "card_download")

    # Remove vips.vcf from pimsync directory if it was downloaded
    # (we manage this separately via curl to avoid pimsync 403 errors)
    pimsync_vips = card_dir / "Default" / "vips.vcf"
    if pimsync_vips.exists():
        pimsync_vips.unlink()
        log("Removed vips.vcf from pimsync directory (managed separately)")

    # Download VIP group directly from server via curl (bypasses pimsync)
    vips_file = cfg.DATA_DIR / "vips.vcf"
    if not download_vips_file(vips_file):
        log("Error: Could not download VIP group, cannot continue")
        return

    log("Extracting list of starred contacts")
    with open(vips_file) as f:
        contact_uuids = set()
        for line in f:
            if not (m := re.match(r"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:(.+)$", line)):
                continue
            contact_uuids.add(m.group(1))
    birthdays = {}
    for contact_uuid in sorted(contact_uuids):
        with open(card_dir / "Default" / f"{contact_uuid}.vcf") as f:
            ct_name = None
            ct_month = None
            ct_day = None
            for line in f:
                if m := re.match(r"FN:(.+)$", line):
                    ct_name = m.group(1)
                    continue
                if m := re.match(r"BDAY[;:].*[0-9]{4}-([0-9]{2})-([0-9]{2})$", line):
                    ct_month = int(m.group(1))
                    ct_day = int(m.group(2))
                    continue
        if not (ct_name and ct_month and ct_day):
            log(f"Skipping {ct_name or contact_uuid} as data was not found in card")
            continue
        log(f"Registering {ct_name} with birthday {ct_month:02d}-{ct_day:02d}")
        birthdays[f"bf-{contact_uuid}"] = (ct_name, ct_month, ct_day)
    log(f"Total birthday count: {len(birthdays)}")
    log("Generating birthday calendar")
    try:
        shutil.rmtree(cal_dir / cfg.BIRTHDAY_CALENDAR_ID)
    except FileNotFoundError:
        pass
    (cal_dir / cfg.BIRTHDAY_CALENDAR_ID).mkdir(parents=True)

    # Load cache to track what was previously uploaded
    cache_file = cfg.DATA_DIR / "birthday_cache.json"
    old_cache = load_cache(cache_file)
    new_cache = {}
    # Generate .ics files and calculate hashes
    for event_uuid, (ct_name, ct_month, ct_day) in birthdays.items():
        # Build the event content
        content = (
            "BEGIN:VCALENDAR\n"
            "VERSION:2.0\n"
            "CALSCALE:GREGORIAN\n"
            "BEGIN:VEVENT\n"
            f"UID:{event_uuid}\n"
            "SEQUENCE:0\n"
            f"DTSTAMP:2000{ct_month:02d}{ct_day:02d}T000000Z\n"
            f"DTSTART;VALUE=DATE:2000{ct_month:02d}{ct_day:02d}\n"
            "DURATION:P1D\n"
            "PRIORITY:0\n"
            f"SUMMARY:🎂 {ct_name}\n"
            "RRULE:FREQ=YEARLY\n"
            "STATUS:CONFIRMED\n"
            "END:VEVENT\n"
            "END:VCALENDAR\n"
        )

        # Write to file
        with open(cal_dir / cfg.BIRTHDAY_CALENDAR_ID / f"{event_uuid}.ics", "w") as f:
            f.write(content)

        # Calculate and store hash for change detection
        new_cache[event_uuid] = hash_content(content)
    # Determine what changed
    events_to_upload = []
    events_to_delete = []

    for event_uuid, (ct_name, ct_month, ct_day) in birthdays.items():
        if event_uuid not in old_cache:
            # New event
            events_to_upload.append((event_uuid, ct_name, "new"))
        elif old_cache[event_uuid] != new_cache[event_uuid]:
            # Modified event
            events_to_upload.append((event_uuid, ct_name, "modified"))
        # else: unchanged, skip upload

    # Find events to delete (in old cache but not in new set)
    for event_uuid in old_cache:
        if event_uuid not in new_cache:
            events_to_delete.append(event_uuid)

    # Report what will be synced
    if not events_to_upload and not events_to_delete:
        log("No changes detected, skipping upload")
    else:
        log(f"Changes detected: {len(events_to_upload)} to upload, {len(events_to_delete)} to delete")

        # Upload changed/new events
        if events_to_upload:
            log("Uploading changed/new events to CalDAV...")
            upload_success = 0
            upload_error = 0

            for event_uuid, ct_name, change_type in events_to_upload:
                ics_file = cal_dir / cfg.BIRTHDAY_CALENDAR_ID / f"{event_uuid}.ics"
                event_url = f"{cfg.CALDAV.url}dav/calendars/user/{cfg.CALDAV.username}/{cfg.BIRTHDAY_CALENDAR_ID}/{event_uuid}.ics"

                success, http_code, error_msg = upload_to_dav(
                    url=event_url,
                    username=cfg.CALDAV.username,
                    password=cfg.CALDAV.password,
                    file_path=ics_file,
                    content_type="text/calendar"
                )

                if success:
                    upload_success += 1
                    log(f"  ✓ {ct_name} ({change_type})")
                else:
                    upload_error += 1
                    log(f"  ✗ {ct_name} (HTTP {http_code})")
                    if error_msg:
                        log(f"    {error_msg}")

            log(f"Upload complete: {upload_success} successful, {upload_error} failed")

        # Delete removed events
        if events_to_delete:
            log("Deleting removed events from CalDAV...")
            delete_success = 0
            delete_error = 0

            for event_uuid in events_to_delete:
                event_url = f"{cfg.CALDAV.url}dav/calendars/user/{cfg.CALDAV.username}/{cfg.BIRTHDAY_CALENDAR_ID}/{event_uuid}.ics"

                result = subprocess.run(
                    [
                        "curl", "-X", "DELETE",
                        "-u", f"{cfg.CALDAV.username}:{cfg.CALDAV.password}",
                        "-w", "\nHTTP_CODE:%{http_code}",
                        "-s",
                        event_url
                    ],
                    capture_output=True,
                    text=True
                )

                # Parse HTTP response code
                http_code = None
                output = result.stdout
                if "HTTP_CODE:" in output:
                    parts = output.split("HTTP_CODE:")
                    if len(parts) == 2:
                        http_code = parts[1].strip()

                # Check for success (204 No Content or 404 Not Found - already deleted)
                if http_code in ["204", "404"]:
                    delete_success += 1
                    log(f"  ✓ Deleted {event_uuid}")
                else:
                    delete_error += 1
                    log(f"  ✗ Failed to delete {event_uuid} (HTTP {http_code})")

            log(f"Delete complete: {delete_success} successful, {delete_error} failed")

    # Save updated cache
    save_cache(cache_file, new_cache)
    log("Cache updated")
