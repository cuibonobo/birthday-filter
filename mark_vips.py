#!/usr/bin/env python3
"""
Interactive script to mark contacts as VIPs.

This script downloads your contacts, presents them in an interactive interface,
and lets you quickly mark which ones should be VIPs for birthday tracking.
"""

import curses
import re
import subprocess
import sys
from typing import Dict, List, Set, Tuple

import birthday_filter.config as cfg


def log(msg):
    print(f"[mark-vips] {msg}")


class ContactSelector:
    def __init__(self):
        self.contacts: Dict[str, str] = {}  # uuid -> name
        self.vips: Set[str] = set()  # uuids marked as VIP
        self.cursor_pos = 0  # Position within current page (0-indexed)
        self.current_page = 0
        self.page_size = 20
        self.search_term = ""
        self.message = ""  # Status message to display
        self.card_dir = cfg.DATA_DIR / "pimsync-cards"
        # Store vips.vcf outside pimsync directory to avoid sync conflicts
        self.vips_file = cfg.DATA_DIR / "vips.vcf"
        self.vd_cfg_file = cfg.DATA_DIR / "pimsync-config"
        self.vd_status_file = cfg.DATA_DIR / "pimsync-status"

    def setup_pimsync(self):
        """Create pimsync configuration and download contacts."""
        log("Setting up pimsync configuration")
        cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)

        with open(self.vd_cfg_file, "w") as f:
            f.write(f"""
status_path {self.vd_status_file}

storage cards {{
  type vdir/vcard
  path {self.card_dir}
}}

storage carddav {{
  type carddav
  url {cfg.CARDDAV.url}
  username {cfg.CARDDAV.username}
  password {cfg.CARDDAV.password}
}}

pair card_sync {{
  storage_a cards
  storage_b carddav
  collections from b
  conflict_resolution keep b
}}
            """.strip() + "\n")

        (self.card_dir / "Default").mkdir(parents=True, exist_ok=True)

    def download_contacts(self):
        """Download all contacts from CardDAV."""
        log("Downloading contacts from CardDAV (this may take a moment)...")
        result = subprocess.run(
            ["pimsync", "-c", str(self.vd_cfg_file), "sync", "card_sync"],
            capture_output=True,
            text=True
        )

        # Display pimsync output
        if result.stdout:
            for line in result.stdout.splitlines():
                log(f"  {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                log(f"  {line}")

        # Check for errors
        if result.returncode != 0:
            raise RuntimeError(f"pimsync sync failed with exit code {result.returncode}")

        log("Download complete")

        # Remove vips.vcf from pimsync directory if it was downloaded
        # (we manage this separately via curl to avoid pimsync 403 errors)
        pimsync_vips = self.card_dir / "Default" / "vips.vcf"
        if pimsync_vips.exists():
            pimsync_vips.unlink()
            log("Removed vips.vcf from pimsync directory (managed separately)")

    def download_vips(self):
        """Download existing VIP group from server via curl (bypasses pimsync)."""
        log("Checking for existing VIP group on server...")

        # Construct full CardDAV URL for vips.vcf
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
            with open(self.vips_file, "w") as f:
                f.write(output)
            log("Existing VIP group downloaded from server")
        elif http_code == "404":
            log("No VIP group found on server (will create new one)")
        else:
            log(f"Warning: Unexpected response (HTTP {http_code}) when checking for VIP group")

    def load_contacts(self):
        """Load all contacts from the downloaded vcard files."""
        log("Loading contacts...")
        default_dir = self.card_dir / "Default"

        for vcf_file in default_dir.glob("*.vcf"):
            if vcf_file.name == "vips.vcf":
                continue

            uuid = vcf_file.stem
            name = None

            with open(vcf_file) as f:
                for line in f:
                    if m := re.match(r"FN:(.+)$", line):
                        name = m.group(1).strip()
                        break

            if name:
                self.contacts[uuid] = name

        log(f"Loaded {len(self.contacts)} contacts")

    def load_existing_vips(self):
        """Load currently marked VIPs if they exist."""
        if not self.vips_file.exists():
            log("No existing VIPs found")
            return

        with open(self.vips_file) as f:
            for line in f:
                if m := re.match(r"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:(.+)$", line):
                    uuid = m.group(1).strip()
                    if uuid in self.contacts:
                        self.vips.add(uuid)

        log(f"Loaded {len(self.vips)} existing VIPs")

    def get_filtered_contacts(self) -> List[Tuple[str, str]]:
        """Get contacts filtered by search term, sorted by name."""
        filtered = []
        search_lower = self.search_term.lower()

        for uuid, name in self.contacts.items():
            if not search_lower or search_lower in name.lower():
                filtered.append((uuid, name))

        return sorted(filtered, key=lambda x: x[1].lower())

    def save_vips(self):
        """Save VIP list and upload to CardDAV. Returns (success, output_lines)."""
        from datetime import datetime, timezone

        output_lines = []

        # Create vips.vcf file
        with open(self.vips_file, "w") as f:
            f.write("BEGIN:VCARD\n")
            f.write("VERSION:3.0\n")
            f.write("UID:vips\n")
            f.write("N:VIPs\n")
            f.write("FN:VIPs\n")
            f.write("X-ADDRESSBOOKSERVER-KIND:group\n")  # Critical: marks this as a group vCard
            for uuid in sorted(self.vips):
                f.write(f"X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:{uuid}\n")
            # Add revision timestamp (ISO 8601 format)
            rev_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            f.write(f"REV:{rev_timestamp}\n")
            f.write("END:VCARD\n")

        # Upload to CardDAV using curl (bypasses pimsync which has issues with groups)
        output_lines.append("Uploading VIP group to CardDAV server...")

        # Construct full CardDAV URL for vips.vcf
        vips_url = f"{cfg.CARDDAV.url}dav/addressbooks/user/{cfg.CARDDAV.username}/Default/vips.vcf"

        result = subprocess.run(
            [
                "curl", "-X", "PUT",
                "-u", f"{cfg.CARDDAV.username}:{cfg.CARDDAV.password}",
                "-H", "Content-Type: text/vcard; charset=utf-8",
                "--data-binary", f"@{self.vips_file}",
                "-w", "\nHTTP_CODE:%{http_code}",
                "-s",  # Silent mode (no progress bar)
                vips_url
            ],
            capture_output=True,
            text=True
        )

        # Parse HTTP response code from curl output
        http_code = None
        output = result.stdout
        if "HTTP_CODE:" in output:
            parts = output.split("HTTP_CODE:")
            if len(parts) == 2:
                http_code = parts[1].strip()
                output = parts[0]  # Remove HTTP_CODE from output

        # Check for success (201 Created or 204 No Content)
        if http_code in ["201", "204"]:
            output_lines.append(f"  HTTP {http_code}: VIP group uploaded successfully")
            return True, output_lines
        else:
            output_lines.append(f"  HTTP {http_code}: Upload failed")
            if output.strip():
                output_lines.append(f"  Response: {output.strip()}")
            if result.stderr.strip():
                output_lines.append(f"  Error: {result.stderr.strip()}")
            return False, output_lines

    def draw_screen(self, stdscr):
        """Draw the interface."""
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        filtered = self.get_filtered_contacts()
        total = len(filtered)

        # Auto-adjust page if out of bounds
        max_page = max(0, (total - 1) // self.page_size) if total > 0 else 0
        if self.current_page > max_page:
            self.current_page = max_page

        start_idx = self.current_page * self.page_size
        end_idx = min(start_idx + self.page_size, total)
        page_contacts = filtered[start_idx:end_idx]

        # Adjust cursor if out of bounds
        if self.cursor_pos >= len(page_contacts) and len(page_contacts) > 0:
            self.cursor_pos = len(page_contacts) - 1
        if self.cursor_pos < 0:
            self.cursor_pos = 0

        row = 0

        # Header
        try:
            stdscr.addstr(row, 0, "=" * min(width - 1, 80), curses.A_BOLD)
            row += 1

            title = f"CONTACT VIP SELECTOR - Page {self.current_page + 1} of {max_page + 1}"
            stdscr.addstr(row, 0, title[:width - 1], curses.A_BOLD)
            row += 1

            stats = f"Total: {total} contacts | VIPs marked: {len(self.vips)}"
            stdscr.addstr(row, 0, stats[:width - 1])
            row += 1

            if self.search_term:
                search_info = f"Search filter: '{self.search_term}'"
                stdscr.addstr(row, 0, search_info[:width - 1])
                row += 1

            stdscr.addstr(row, 0, "=" * min(width - 1, 80))
            row += 1
            row += 1

            # Display contacts
            for i, (uuid, name) in enumerate(page_contacts):
                if row >= height - 8:  # Leave room for footer
                    break

                vip_marker = "★" if uuid in self.vips else " "
                contact_line = f"  [{vip_marker}] {name}"

                if i == self.cursor_pos:
                    # Highlight current selection
                    stdscr.addstr(row, 0, contact_line[:width - 1], curses.A_REVERSE)
                else:
                    stdscr.addstr(row, 0, contact_line[:width - 1])

                row += 1

            # Footer with commands (always at bottom)
            footer_row = height - 7
            if footer_row > row:
                footer_row = row + 1

            stdscr.addstr(footer_row, 0, "-" * min(width - 1, 80))
            footer_row += 1

            stdscr.addstr(footer_row, 0, "Keys: ↑/↓ or j/k = move | Space = toggle VIP | PgUp/PgDn = change page")
            footer_row += 1
            stdscr.addstr(footer_row, 0, "      / = search | c = clear search | a = mark all | u = unmark all")
            footer_row += 1
            stdscr.addstr(footer_row, 0, "      w = save & quit | q = quit without saving")
            footer_row += 1

            stdscr.addstr(footer_row, 0, "-" * min(width - 1, 80))
            footer_row += 1

            # Status message
            if self.message:
                stdscr.addstr(footer_row, 0, self.message[:width - 1], curses.A_BOLD)

        except curses.error:
            # Ignore errors from writing outside screen bounds
            pass

        stdscr.refresh()
        return page_contacts

    def get_search_input(self, stdscr):
        """Get search input from user."""
        height, width = stdscr.getmaxyx()

        # Create a small window for input
        curses.echo()
        stdscr.addstr(height - 2, 0, " " * (width - 1))
        stdscr.addstr(height - 2, 0, "Search: ")
        stdscr.refresh()

        # Get input
        try:
            search = stdscr.getstr(height - 2, 8, width - 9).decode('utf-8')
        except Exception:
            search = ""

        curses.noecho()
        return search.strip()

    def run_curses(self, stdscr):
        """Run the curses interface."""
        # Setup curses
        curses.curs_set(0)  # Hide cursor
        stdscr.keypad(True)  # Enable special keys
        stdscr.timeout(-1)  # Blocking input

        if len(self.contacts) == 0:
            stdscr.addstr(0, 0, "No contacts found!")
            stdscr.addstr(1, 0, "Press any key to exit...")
            stdscr.refresh()
            stdscr.getch()
            return

        while True:
            page_contacts = self.draw_screen(stdscr)

            if not page_contacts:
                self.message = "No contacts match filter. Press 'c' to clear search."
                self.draw_screen(stdscr)

            key = stdscr.getch()

            # Clear message after keypress
            self.message = ""

            # Navigation
            if key in [curses.KEY_UP, ord('k')]:
                if self.cursor_pos > 0:
                    self.cursor_pos -= 1
                elif self.current_page > 0:
                    # Move to previous page
                    self.current_page -= 1
                    self.cursor_pos = self.page_size - 1

            elif key in [curses.KEY_DOWN, ord('j')]:
                if self.cursor_pos < len(page_contacts) - 1:
                    self.cursor_pos += 1
                else:
                    # Move to next page
                    filtered = self.get_filtered_contacts()
                    max_page = max(0, (len(filtered) - 1) // self.page_size)
                    if self.current_page < max_page:
                        self.current_page += 1
                        self.cursor_pos = 0

            elif key in [curses.KEY_PPAGE]:  # Page Up
                if self.current_page > 0:
                    self.current_page -= 1
                    self.cursor_pos = 0

            elif key in [curses.KEY_NPAGE]:  # Page Down
                filtered = self.get_filtered_contacts()
                max_page = max(0, (len(filtered) - 1) // self.page_size)
                if self.current_page < max_page:
                    self.current_page += 1
                    self.cursor_pos = 0

            # Toggle VIP
            elif key in [ord(' ')]:
                if page_contacts and 0 <= self.cursor_pos < len(page_contacts):
                    uuid = page_contacts[self.cursor_pos][0]
                    if uuid in self.vips:
                        self.vips.remove(uuid)
                    else:
                        self.vips.add(uuid)

            # Search
            elif key == ord('/'):
                self.search_term = self.get_search_input(stdscr)
                self.current_page = 0
                self.cursor_pos = 0

            # Clear search
            elif key == ord('c'):
                self.search_term = ""
                self.current_page = 0
                self.cursor_pos = 0

            # Mark all on page
            elif key == ord('a'):
                for uuid, _ in page_contacts:
                    self.vips.add(uuid)
                self.message = f"Marked {len(page_contacts)} contacts as VIP"

            # Unmark all on page
            elif key == ord('u'):
                for uuid, _ in page_contacts:
                    self.vips.discard(uuid)
                self.message = f"Unmarked {len(page_contacts)} contacts"

            # Save and quit
            elif key == ord('w'):
                stdscr.addstr(0, 0, f"Saving {len(self.vips)} VIPs and uploading to CardDAV...")
                stdscr.refresh()
                success, output = self.save_vips()
                return (True, success, output)

            # Quit without saving
            elif key == ord('q'):
                # Simple confirmation
                height, _ = stdscr.getmaxyx()
                stdscr.addstr(height - 1, 0, "Quit without saving? (y/n): ")
                stdscr.refresh()
                confirm = stdscr.getch()
                if confirm in [ord('y'), ord('Y')]:
                    return (False, None, [])

    def run(self):
        """Run the interactive contact selector."""
        self.setup_pimsync()
        self.download_contacts()
        self.download_vips()  # Download VIP group separately via curl
        self.load_contacts()
        self.load_existing_vips()

        # Run curses interface
        try:
            result = curses.wrapper(self.run_curses)
            if result:
                saved, success, output = result
                # Display pimsync output after curses exits
                for line in output:
                    log(line)

                if saved:
                    if success:
                        log("VIP list saved successfully!")
                    else:
                        log("ERROR: Failed to sync VIPs to CardDAV server!")
                        sys.exit(1)
                else:
                    log("Exited without saving")
        except KeyboardInterrupt:
            log("Interrupted by user")


def main():
    try:
        selector = ContactSelector()
        selector.run()
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
