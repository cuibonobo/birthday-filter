#!/usr/bin/env python3
"""
Backup script for CardDAV contacts.

Downloads all contacts from CardDAV and saves them to a timestamped
backup directory. Run this before using mark_vips.py or the main
birthday filter to ensure you have a backup of your contact data.
"""

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import birthday_filter.config as cfg


def log(msg):
    print(f"[backup-contacts] {msg}")


def backup_contacts(backup_dir: Path = None):
    """
    Download and backup all CardDAV contacts.

    Args:
        backup_dir: Optional custom backup directory. If not provided,
                   creates a timestamped backup in ./backups/
    """
    # Setup directories
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = cfg.DATA_DIR / "pimsync-backup-temp"
    vd_cfg_file = cfg.DATA_DIR / "pimsync-backup-config"
    vd_status_file = cfg.DATA_DIR / "pimsync-backup-status"

    # Create backup directory with timestamp
    if backup_dir is None:
        backups_root = Path.cwd() / "backups"
        backups_root.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = backups_root / f"contacts_{timestamp}"

    backup_dir.mkdir(parents=True, exist_ok=True)

    log(f"Creating backup in: {backup_dir}")

    # Create pimsync config for backup (read-only)
    log("Setting up pimsync configuration")
    with open(vd_cfg_file, "w") as f:
        f.write(f"""
status_path {vd_status_file}

storage local {{
  type vdir/vcard
  path {temp_dir}
}}

storage carddav {{
  type carddav
  url {cfg.CARDDAV.url}
  username {cfg.CARDDAV.username}
  password {cfg.CARDDAV.password}
  read_only
}}

pair backup {{
  storage_a local
  storage_b carddav
  collections from b
  conflict_resolution keep b
}}
        """.strip() + "\n")

    # Download contacts
    log("Downloading contacts from CardDAV...")
    try:
        subprocess.run(
            ["pimsync", "-c", str(vd_cfg_file), "sync", "backup"],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        log(f"Error downloading contacts: {e}")
        log(f"stdout: {e.stdout}")
        log(f"stderr: {e.stderr}")
        raise

    # Count downloaded contacts
    if not temp_dir.exists():
        log("Warning: No contacts directory created")
        return backup_dir

    contact_count = 0
    for collection in temp_dir.iterdir():
        if collection.is_dir():
            vcf_files = list(collection.glob("*.vcf"))
            contact_count += len(vcf_files)
            log(f"Collection '{collection.name}': {len(vcf_files)} contacts")

    log(f"Total contacts downloaded: {contact_count}")

    # Copy to backup directory
    log("Copying contacts to backup directory...")
    if temp_dir.exists():
        for item in temp_dir.iterdir():
            if item.is_dir():
                shutil.copytree(item, backup_dir / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, backup_dir / item.name)

    # Clean up temp directory
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    # Create a backup info file
    info_file = backup_dir / "backup_info.txt"
    with open(info_file, "w") as f:
        f.write(f"Backup created: {datetime.now().isoformat()}\n")
        f.write(f"CardDAV URL: {cfg.CARDDAV.url}\n")
        f.write(f"Total contacts: {contact_count}\n")
        f.write(f"\nTo restore: Copy the .vcf files back to your CardDAV server\n")
        f.write(f"or import them through your email client interface.\n")

    log(f"Backup completed successfully!")
    log(f"Backup location: {backup_dir}")
    log(f"Total contacts backed up: {contact_count}")

    return backup_dir


def main():
    try:
        backup_dir = backup_contacts()

        # Suggest creating a compressed archive
        print()
        print("Tip: To save space, you can compress this backup:")
        print(f"  tar -czf {backup_dir.name}.tar.gz -C {backup_dir.parent} {backup_dir.name}")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        log(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
