"""The File Upload Destination's stored configuration (ADR 0025, ticket 01).

Three protocol shapes plus which one is active — read once per cycle, the
same reasoning :func:`arichds.dataout.destination.load_config` gives for its
own frozen snapshot: the ``PUT`` can land at any moment, and a cycle (ticket
02) must not have the settings change underneath it mid-run.

Ticket 01 only reads and writes these rows through the API
(:mod:`arichds.api.file_upload`); nothing here talks to a server yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from arichds.db.app_settings import (
    FILEUPLOAD_ACTIVE_PROTOCOL_DEFAULT,
    FILEUPLOAD_ACTIVE_PROTOCOL_KEY,
    FILEUPLOAD_FTPS_HOST_DEFAULT,
    FILEUPLOAD_FTPS_HOST_KEY,
    FILEUPLOAD_FTPS_PASSWORD_DEFAULT,
    FILEUPLOAD_FTPS_PASSWORD_KEY,
    FILEUPLOAD_FTPS_PORT_DEFAULT,
    FILEUPLOAD_FTPS_PORT_KEY,
    FILEUPLOAD_FTPS_REMOTE_ROOT_DEFAULT,
    FILEUPLOAD_FTPS_REMOTE_ROOT_KEY,
    FILEUPLOAD_FTPS_USERNAME_DEFAULT,
    FILEUPLOAD_FTPS_USERNAME_KEY,
    FILEUPLOAD_HTTPS_REMOTE_ROOT_DEFAULT,
    FILEUPLOAD_HTTPS_REMOTE_ROOT_KEY,
    FILEUPLOAD_HTTPS_TOKEN_DEFAULT,
    FILEUPLOAD_HTTPS_TOKEN_KEY,
    FILEUPLOAD_HTTPS_URL_DEFAULT,
    FILEUPLOAD_HTTPS_URL_KEY,
    FILEUPLOAD_SFTP_HOST_DEFAULT,
    FILEUPLOAD_SFTP_HOST_KEY,
    FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_DEFAULT,
    FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY,
    FILEUPLOAD_SFTP_KEY_PASSPHRASE_DEFAULT,
    FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY,
    FILEUPLOAD_SFTP_KEY_PATH_DEFAULT,
    FILEUPLOAD_SFTP_KEY_PATH_KEY,
    FILEUPLOAD_SFTP_PASSWORD_DEFAULT,
    FILEUPLOAD_SFTP_PASSWORD_KEY,
    FILEUPLOAD_SFTP_PORT_DEFAULT,
    FILEUPLOAD_SFTP_PORT_KEY,
    FILEUPLOAD_SFTP_REMOTE_ROOT_DEFAULT,
    FILEUPLOAD_SFTP_REMOTE_ROOT_KEY,
    FILEUPLOAD_SFTP_USERNAME_DEFAULT,
    FILEUPLOAD_SFTP_USERNAME_KEY,
    get_setting,
)


@dataclass(frozen=True, slots=True)
class SftpConfig:
    """The SFTP tab's stored settings.

    Attributes:
        host: `""` means the tab has never been saved.
        port: 22 by default.
        username: The account to authenticate as.
        password: Stored in the clear, the same footing as `db_dest_password`
            — never returned by the API (write-only).
        key_path: A private-key file's path on this machine. Read at connect
            time (ticket 04); the file's contents never reach the database.
        key_passphrase: The key file's passphrase, stored in the clear like
            *password*, and equally never returned.
        remote_root: Where under the server's own filesystem this machine's
            tree (`export/`, `captures/<Meter Serial>/`) is rooted.
        host_key_fingerprint: The pinned host key, empty until ticket 04's
            first successful connection writes it.
    """

    host: str
    port: int
    username: str
    password: str
    key_path: str
    key_passphrase: str
    remote_root: str
    host_key_fingerprint: str


@dataclass(frozen=True, slots=True)
class FtpsConfig:
    """The FTPS tab's stored settings — explicit TLS, port 21 by default
    (never 990, the implicit-FTPS port ADR 0025 excludes)."""

    host: str
    port: int
    username: str
    password: str
    remote_root: str


@dataclass(frozen=True, slots=True)
class HttpsConfig:
    """The HTTPS tab's stored settings — a URL and a Bearer token, the same
    shape the Central Push's own configuration uses."""

    url: str
    token: str
    remote_root: str


@dataclass(frozen=True, slots=True)
class FileUploadConfig:
    """The whole File Upload Destination — which protocol is active, plus
    all three tabs' stored settings (the other two keep what they hold even
    while inactive, ADR 0025 decision 1)."""

    active_protocol: str
    sftp: SftpConfig
    ftps: FtpsConfig
    https: HttpsConfig


def _parse_port(session: Session, key: str, default: str) -> int:
    """Parse a stored port, falling back to *default* on an unparseable
    value — reachable only by hand-editing the database, and a background
    reader must not die on it (the same guard
    :func:`arichds.dataout.destination.load_config` applies to `db_dest_port`).
    """
    try:
        return int(get_setting(session, key, default))
    except ValueError:
        return int(default)


def load_config(session: Session) -> FileUploadConfig:
    """Read every File Upload Destination row into a :class:`FileUploadConfig`."""
    sftp = SftpConfig(
        host=get_setting(session, FILEUPLOAD_SFTP_HOST_KEY, FILEUPLOAD_SFTP_HOST_DEFAULT),
        port=_parse_port(session, FILEUPLOAD_SFTP_PORT_KEY, FILEUPLOAD_SFTP_PORT_DEFAULT),
        username=get_setting(session, FILEUPLOAD_SFTP_USERNAME_KEY, FILEUPLOAD_SFTP_USERNAME_DEFAULT),
        password=get_setting(session, FILEUPLOAD_SFTP_PASSWORD_KEY, FILEUPLOAD_SFTP_PASSWORD_DEFAULT),
        key_path=get_setting(session, FILEUPLOAD_SFTP_KEY_PATH_KEY, FILEUPLOAD_SFTP_KEY_PATH_DEFAULT),
        key_passphrase=get_setting(session, FILEUPLOAD_SFTP_KEY_PASSPHRASE_KEY, FILEUPLOAD_SFTP_KEY_PASSPHRASE_DEFAULT),
        remote_root=get_setting(session, FILEUPLOAD_SFTP_REMOTE_ROOT_KEY, FILEUPLOAD_SFTP_REMOTE_ROOT_DEFAULT),
        host_key_fingerprint=get_setting(
            session, FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_KEY, FILEUPLOAD_SFTP_HOSTKEY_FINGERPRINT_DEFAULT
        ),
    )
    ftps = FtpsConfig(
        host=get_setting(session, FILEUPLOAD_FTPS_HOST_KEY, FILEUPLOAD_FTPS_HOST_DEFAULT),
        port=_parse_port(session, FILEUPLOAD_FTPS_PORT_KEY, FILEUPLOAD_FTPS_PORT_DEFAULT),
        username=get_setting(session, FILEUPLOAD_FTPS_USERNAME_KEY, FILEUPLOAD_FTPS_USERNAME_DEFAULT),
        password=get_setting(session, FILEUPLOAD_FTPS_PASSWORD_KEY, FILEUPLOAD_FTPS_PASSWORD_DEFAULT),
        remote_root=get_setting(session, FILEUPLOAD_FTPS_REMOTE_ROOT_KEY, FILEUPLOAD_FTPS_REMOTE_ROOT_DEFAULT),
    )
    https = HttpsConfig(
        url=get_setting(session, FILEUPLOAD_HTTPS_URL_KEY, FILEUPLOAD_HTTPS_URL_DEFAULT),
        token=get_setting(session, FILEUPLOAD_HTTPS_TOKEN_KEY, FILEUPLOAD_HTTPS_TOKEN_DEFAULT),
        remote_root=get_setting(session, FILEUPLOAD_HTTPS_REMOTE_ROOT_KEY, FILEUPLOAD_HTTPS_REMOTE_ROOT_DEFAULT),
    )
    active_protocol = get_setting(session, FILEUPLOAD_ACTIVE_PROTOCOL_KEY, FILEUPLOAD_ACTIVE_PROTOCOL_DEFAULT)
    return FileUploadConfig(active_protocol=active_protocol, sftp=sftp, ftps=ftps, https=https)
