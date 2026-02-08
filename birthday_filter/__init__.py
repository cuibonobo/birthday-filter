import configparser
import json
import re
import shutil
import subprocess
from typing import Any

import birthday_filter.config as cfg


def log(msg):
    print(f"[birthday-filter] {msg}")


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
    log("Extracting list of starred contacts")
    with open(card_dir / "Default" / "vips.vcf") as f:
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
    for event_uuid, (ct_name, ct_month, ct_day) in birthdays.items():
        with open(cal_dir / cfg.BIRTHDAY_CALENDAR_ID / f"{event_uuid}.ics", "w") as f:
            f.write("BEGIN:VCALENDAR\n")
            f.write("VERSION:2.0\n")
            f.write("CALSCALE:GREGORIAN\n")
            f.write("BEGIN:VEVENT\n")
            f.write(f"UID:{event_uuid}\n")
            f.write("SEQUENCE:0\n")
            f.write(f"DTSTAMP:2000{ct_month:02d}{ct_day:02d}T000000Z\n")
            f.write(f"DTSTART;VALUE=DATE:2000{ct_month:02d}{ct_day:02d}\n")
            f.write("DURATION:P1D\n")
            f.write("PRIORITY:0\n")
            f.write(f"SUMMARY:🎂 {ct_name}\n")
            f.write("RRULE:FREQ=YEARLY\n")
            f.write("STATUS:CONFIRMED\n")
            f.write("END:VEVENT\n")
            f.write("END:VCALENDAR\n")
    log("Uploading birthday events to CalDAV using curl")
    # Upload each .ics file individually using curl (pimsync has issues with Fastmail)
    success_count = 0
    error_count = 0

    for event_uuid, (ct_name, ct_month, ct_day) in birthdays.items():
        ics_file = cal_dir / cfg.BIRTHDAY_CALENDAR_ID / f"{event_uuid}.ics"
        event_url = f"{cfg.CALDAV.url}dav/calendars/user/{cfg.CALDAV.username}/{cfg.BIRTHDAY_CALENDAR_ID}/{event_uuid}.ics"

        result = subprocess.run(
            [
                "curl", "-X", "PUT",
                "-u", f"{cfg.CALDAV.username}:{cfg.CALDAV.password}",
                "-H", "Content-Type: text/calendar; charset=utf-8",
                "--data-binary", f"@{ics_file}",
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

        # Check for success (201 Created or 204 No Content)
        if http_code in ["201", "204"]:
            success_count += 1
        else:
            error_count += 1
            log(f"  Failed to upload {ct_name} (HTTP {http_code})")
            if result.stderr.strip():
                log(f"    Error: {result.stderr.strip()}")

    log(f"Upload complete: {success_count} successful, {error_count} failed")
