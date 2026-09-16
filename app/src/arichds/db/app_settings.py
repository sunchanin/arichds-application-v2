"""Key/value application settings (M6b, issue #22) — the `settings` table.

Deliberately named apart from :class:`arichds.config.Settings`, which is the
environment (``ARICHDS_*`` variables, immutable for the process's life). This
module is the table an admin can edit at runtime through the API — ADR 0010's
``capture_dir`` is the first key it holds, and more arrive module by module.

A missing key is not an error: :func:`get_setting` falls back to a documented
default, so a fresh install answers ``GET /api/billing/settings`` without a
seed migration.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from arichds.db.models import Setting

#: The one key M6b introduces. `""` means "not configured" — capture is then
#: skipped with a log line rather than defaulting to a path under
#: %ProgramData% (ADR 0010; decision 16, issue #22).
CAPTURE_DIR_KEY = "capture_dir"
CAPTURE_DIR_DEFAULT = ""

#: The machine-wide display-unit setting (a CR, not part of any milestone's
#: original shape) — `"kilo"` (kW/kWh/kvar/kvarh, today's behaviour) or
#: `"base"` (W/Wh/var/varh). A missing key means `"kilo"`, so an existing
#: install is unchanged. Applied at render time only, in the web UI and the
#: capture renderers (:mod:`arichds.capture._render_shared`) — the database
#: and the API payloads never change (CLAUDE.md's write-time normalization
#: invariant).
DISPLAY_UNIT_SCALE_KEY = "display_unit_scale"
DISPLAY_UNIT_SCALE_DEFAULT = "kilo"

#: The four Export Format keys (M7 slice 3, issue #30, D-7) — machine-wide,
#: same as every key above. Defaults are v1's own (`cewe/.../core/models.py`
#: `FormatSetting`), except `export_auto_save_enabled`, which v1 also
#: defaults off.
EXPORT_DATE_FORMAT_KEY = "export_date_format"
EXPORT_DATE_FORMAT_DEFAULT = "yyyy-mm-dd HH:MM:SS"

EXPORT_CSV_FILENAME_TMPL_KEY = "export_csv_filename_tmpl"
EXPORT_CSV_FILENAME_TMPL_DEFAULT = "[meter].csv"

#: M13, issue 01 — the billing export file's own filename template. A separate
#: key rather than a suffix on the one above: the two files land in the same
#: folder, so one template rendering to one name would have them overwrite each
#: other. `export_date_format`, `export_auto_save_enabled` and
#: `export_output_dir` are deliberately NOT duplicated — one folder, one switch,
#: one date format across every export file.
EXPORT_BILLING_FILENAME_TMPL_KEY = "export_billing_filename_tmpl"
EXPORT_BILLING_FILENAME_TMPL_DEFAULT = "[meter]-billing.csv"

#: M13, issue 02 — the Energy Summary file's template. Names the *daily* file;
#: the on-demand save derives its own name from this one by inserting the range
#: before the extension, so the two can never collide and there is still only
#: one value to keep right.
EXPORT_ENERGY_FILENAME_TMPL_KEY = "export_energy_filename_tmpl"
EXPORT_ENERGY_FILENAME_TMPL_DEFAULT = "[meter]-energy.csv"

#: Stored as the literal lowercase string `"true"`/`"false"` — anything else
#: (including an absent key, via EXPORT_AUTO_SAVE_ENABLED_DEFAULT) reads as
#: False. Compared with `== "true"` at every read site, never truthy-tested.
EXPORT_AUTO_SAVE_ENABLED_KEY = "export_auto_save_enabled"
EXPORT_AUTO_SAVE_ENABLED_DEFAULT = "false"

#: `""` means "not configured" — same convention as CAPTURE_DIR_DEFAULT.
EXPORT_OUTPUT_DIR_KEY = "export_output_dir"
EXPORT_OUTPUT_DIR_DEFAULT = ""

#: The five Database Destination keys (SPEC §3.10, ADR 0016, issue #46) — the
#: connection to the customer's own MariaDB/MySQL. Machine-wide, same as every
#: key above. An empty `db_dest_host` **or** `db_dest_database` means "not
#: configured" and the sync returns immediately — the convention
#: CAPTURE_DIR_DEFAULT and EXPORT_OUTPUT_DIR_DEFAULT already set.
DB_DEST_HOST_KEY = "db_dest_host"
DB_DEST_HOST_DEFAULT = ""

#: MySQL/MariaDB's own default port. Stored as a string like every other value
#: in this table and parsed at the read site — the API's `…Out` model is what
#: declares it an `int`.
DB_DEST_PORT_KEY = "db_dest_port"
DB_DEST_PORT_DEFAULT = "3306"

DB_DEST_DATABASE_KEY = "db_dest_database"
DB_DEST_DATABASE_DEFAULT = ""

DB_DEST_USER_KEY = "db_dest_user"
DB_DEST_USER_DEFAULT = ""

#: Stored in the clear, following `block_cipher_key` / `authentication_key`
#: (`db/models.py:129-131`). The two protections are that **the API never
#: returns it** (`DatabaseDestinationOut` has no `password` field at all) and
#: that :class:`~arichds.logging_config.CredentialRedactionFilter` covers it.
#:
#: **The key name ends in the literal `password` on purpose**: the filter's
#: existing `(password\\s*[=:]\\s*)\\S+` pattern matches anywhere in a line, so
#: `db_dest_password=…` is already redacted without a new pattern. Renaming
#: this key to anything not ending in `password` would silently drop that
#: protection — `test_dataout_config_api.py` pins it.
DB_DEST_PASSWORD_KEY = "db_dest_password"
DB_DEST_PASSWORD_DEFAULT = ""

#: The two Central Push keys (ADR 0024, ticket 07) — the team's own server, a
#: **different Data-out Destination** from the customer's MySQL above (SPEC
#: §3.10 — "two transports, do not conflate them"). Machine-wide, same as
#: every key in this module.
#:
#: `""` means "not configured" — same convention as `db_dest_host`. An empty
#: URL means the push is disabled (ADR 0024, "Opting out").
CENTRAL_PUSH_URL_KEY = "central_push_url"
CENTRAL_PUSH_URL_DEFAULT = ""

#: Stored in the clear, the same footing as `db_dest_password`. **The key name
#: ends in the literal `token` on purpose**: the redaction filter's existing
#: `(token\\s*[=:]\\s*)\\S+` pattern matches anywhere in a line, so
#: `central_push_token=…` is already redacted without a new pattern. Renaming
#: this key to anything not ending in `token` would silently drop that
#: protection — `test_api_central_push.py` pins it. The API never returns it
#: (`CentralPushOut` has no `token` field at all); `token_set` is what lets
#: the form show "token set" instead of an empty box that reads as cleared.
CENTRAL_PUSH_TOKEN_KEY = "central_push_token"
CENTRAL_PUSH_TOKEN_DEFAULT = ""

#: The File Upload Destination (SPEC §3.8, ADR 0025, ticket 01) — the menu's
#: **FTP** — a **third** Data-out Destination, distinct from both keys above
#: (SPEC §3.10 — "two transports, do not conflate them" — now three). Machine
#: -wide, same as every key in this module.
#:
#: `""` means "no protocol saved yet" — the same convention `db_dest_host` and
#: `central_push_url` use, and it is what the status endpoint reads to say
#: nothing is sent. Saving one protocol tab sets this to that tab's name; the
#: other two tabs keep whatever they hold and are simply not the one read.
FILEUPLOAD_ACTIVE_PROTOCOL_KEY = "fileupload_active_protocol"
FILEUPLOAD_ACTIVE_PROTOCOL_DEFAULT = ""

#: SFTP tab (ADR 0025 — paramiko, password *or* key file, ticket 04 wires the
#: transport). `key_passphrase` and `password` both end in a word the
#: redaction filter already covers (`password` directly; `passphrase` needed
#: its own pattern, added alongside this key in `logging_config.py` — the
#: ticket's own claim that no new pattern was needed was wrong, measured by
#: `test_fileupload_config_api.py`). `host_key_fingerprint` is not a secret;
#: the row exists from ticket 01 so ticket 04 has somewhere to pin it.
FILEUPLOAD_SFTP_HOST_KEY = "fileupload_sftp_host"
FILEUPLOAD_SFTP_HOST_DEFAULT = ""
FILEUPLOAD_SFTP_PORT_KEY = "fileupload_sftp_port"
FILEUPLOAD_SFTP_PORT_DEFAULT = "22"
FILEUPLOAD_SFTP_USERNAME_KEY = "fileupload_sftp_username"
FILEUPLOAD_SFTP_USERNAME_DEFAULT = ""
FILEUPLOAD_SFTP_PASSWORD_KEY = "fileupload_sftp_password"
FILEUPLOAD_SFTP_PASSWORD_DEFAULT = ""
FILEUPLOAD_SFTP_KEY_PATH_KEY = "fileupload_sftp_key_path"
FILEUPLOAD_SFTP_KEY_PATH_DEFAULT = ""
FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY = "fileupload_sftp_key_passphrase"
FILEUPLOAD_SFTP_KEY_PASSPHRASE_DEFAULT = ""
FILEUPLOAD_SFTP_REMOTE_ROOT_KEY = "fileupload_sftp_remote_root"
FILEUPLOAD_SFTP_REMOTE_ROOT_DEFAULT = ""
FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY = "fileupload_sftp_host_key_fingerprint"
FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_DEFAULT = ""

#: FTPS tab (ADR 0025 — explicit `AUTH TLS`, standard library, ticket 05 wires
#: the transport). Port defaults to 21, the standard FTP control port — this
#: product never offers implicit FTPS (990).
FILEUPLOAD_FTPS_HOST_KEY = "fileupload_ftps_host"
FILEUPLOAD_FTPS_HOST_DEFAULT = ""
FILEUPLOAD_FTPS_PORT_KEY = "fileupload_ftps_port"
FILEUPLOAD_FTPS_PORT_DEFAULT = "21"
FILEUPLOAD_FTPS_USERNAME_KEY = "fileupload_ftps_username"
FILEUPLOAD_FTPS_USERNAME_DEFAULT = ""
FILEUPLOAD_FTPS_PASSWORD_KEY = "fileupload_ftps_password"
FILEUPLOAD_FTPS_PASSWORD_DEFAULT = ""
FILEUPLOAD_FTPS_REMOTE_ROOT_KEY = "fileupload_ftps_remote_root"
FILEUPLOAD_FTPS_REMOTE_ROOT_DEFAULT = ""

#: HTTPS tab (ADR 0025 — the same stdlib split-timeout client the Central
#: Push already has, ticket 03 wires the transport). No `username`: the HTTPS
#: file endpoints authenticate with `Authorization: Bearer <token>` alone,
#: the same shape `central_push_token` uses.
FILEUPLOAD_HTTPS_URL_KEY = "fileupload_https_url"
FILEUPLOAD_HTTPS_URL_DEFAULT = ""
FILEUPLOAD_HTTPS_TOKEN_KEY = "fileupload_https_token"
FILEUPLOAD_HTTPS_TOKEN_DEFAULT = ""
FILEUPLOAD_HTTPS_REMOTE_ROOT_KEY = "fileupload_https_remote_root"
FILEUPLOAD_HTTPS_REMOTE_ROOT_DEFAULT = ""


def get_setting(session: Session, key: str, default: str) -> str:
    """Return *key*'s stored value, or *default* if the row is absent."""
    row = session.get(Setting, key)
    if row is None or row.value is None:
        return default
    return row.value


def set_setting(session: Session, key: str, value: str) -> None:
    """Insert *key* if absent, or update it in place."""
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
