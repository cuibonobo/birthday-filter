# Birthday Filter

It's a simple utility for taking your Fastmail contacts and generating
a birthday calendar from them. This is a feature that's supported
natively by Fastmail, but the native feature has no ability to filter
for specific contacts (e.g. the ones you have starred), so you either
see the birthday of EVERY SINGLE PERSON YOU HAVE EVER MET, or nobody.
Personally, I don't need to be reminded every year about my third
grade math teacher whose birthday is in the contacts database for some
reason, but I also don't want to delete data just for the sake of not
having it show up on a calendar.

Hence, a very simple cron job that just grabs the contacts database,
parses out only the contacts that are starred, and creates a calendar
out of them. For both of the download and upload tasks, the existing
tool pimsync is used because there is no need to reinvent the wheel.

## Marking Contacts as VIPs

Before running the birthday filter, you need to mark which contacts
should have their birthdays tracked. This project uses Fastmail's VIP
feature (the star icon).

To efficiently mark contacts as VIPs from your contact list, use the
interactive script:

```
poetry run python mark_vips.py
```

This presents a keyboard-driven interface where you can:
- Navigate with **↑/↓** arrow keys or **j/k** (vim-style)
- Toggle VIP status with **Space**
- Search/filter contacts by pressing **/**
- Mark all visible contacts with **a**, unmark all with **u**
- Change pages with **PgUp/PgDn**
- Save and quit with **w**, quit without saving with **q**

This is much faster than clicking through each contact individually in
the Fastmail web interface.

## Usage

Install [pimsync](https://pimsync.whynothugo.nl/install.html).

Clone the repo and create `.env` file in it:

```
CALDAV_URL=
CALDAV_USERNAME=
CALDAV_PASSWORD=

CARDDAV_URL=
CARDDAV_USERNAME=
CARDDAV_PASSWORD=

BIRTHDAY_CALENDAR_ID=
```

The URL, username, and password are your CalDAV and CardDAV connection
details. If you have generated an access token that will work for both
protocols, feel free to use it for both.

* Fastmail is straightforward:
  [documentation](https://www.fastmail.help/hc/en-us/articles/1500000278342-Server-names-and-ports)
* Google has something with OAuth2...? You can try figuring it out if
  you want.
    * I have hardcoded CardDAV details for how Fastmail handles the
      VIPs (starred) collection, this might need updating if you use
      with non-Fastmail source...

The last parameter is your calendar/collection ID that will be **fully
overwritten** and populated with birthdays from the starred contacts.
You identify calendars using their CalDAV IDs, not using their display
names. On Fastmail for example, these are UUIDs and you can find them
by clicking "export" next to a calendar in the settings and noting the
UUID in the URL.

Install dependencies with [Poetry](https://python-poetry.org/) or
equivalent following the versions in `pyproject.toml`, `poetry.lock`.
Execute

```
poetry run python -m birthday_filter
```

on a cron job with the desired frequency. Your events should show up
automatically in the target calendar you specified.

## Docker Usage

The project can also be run as a container using supercronic for
scheduling.

Create a `.env` file with your credentials (see `.env.example` for
template).

Build and run with Docker Compose:

```
docker compose up -d
```

Or with Docker directly:

```
docker build -t birthday-filter .
docker run -d --name birthday-filter --env-file .env -v ./data:/data birthday-filter
```

The default schedule runs daily at 6 AM. To customize the schedule,
edit the `crontab` file before building the image.
