"""Common utilities for uploading to CardDAV/CalDAV servers via curl.

This module provides a workaround for pimsync's issues with Fastmail's
DAV servers by using curl for direct HTTP PUT uploads.
"""

import subprocess
from pathlib import Path
from typing import Tuple


def upload_to_dav(
    url: str,
    username: str,
    password: str,
    file_path: Path,
    content_type: str
) -> Tuple[bool, str, str]:
    """Upload a file to a CardDAV/CalDAV server using curl.

    Args:
        url: Full URL to the resource (e.g., .../vips.vcf or .../event.ics)
        username: DAV server username
        password: DAV server password (app-specific password recommended)
        file_path: Path to the local file to upload
        content_type: MIME type (e.g., "text/vcard" or "text/calendar")

    Returns:
        Tuple of (success, http_code, error_message):
        - success: True if HTTP 201 or 204, False otherwise
        - http_code: HTTP response code as string (e.g., "201", "403")
        - error_message: Error details if failed, empty string if successful
    """
    result = subprocess.run(
        [
            "curl", "-X", "PUT",
            "-u", f"{username}:{password}",
            "-H", f"Content-Type: {content_type}; charset=utf-8",
            "--data-binary", f"@{file_path}",
            "-w", "\nHTTP_CODE:%{http_code}",
            "-s",  # Silent mode (no progress bar)
            url
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
    success = http_code in ["201", "204"]

    # Build error message if failed
    error_message = ""
    if not success:
        error_parts = []
        if output.strip():
            error_parts.append(f"Response: {output.strip()}")
        if result.stderr.strip():
            error_parts.append(f"Error: {result.stderr.strip()}")
        error_message = " | ".join(error_parts) if error_parts else "Unknown error"

    return success, http_code or "unknown", error_message
