"""The Upload Manifest (ADR 0025 decision 2; CONTEXT.md — *Upload Manifest*)
— plain JSON the server holds at the remote root, naming every file this
machine has ever sent and its digest. A cycle (:mod:`arichds.fileupload.cycle`)
reads it first; a missing or unreadable one means "send everything". The
machine itself remembers nothing (ADR 0008) — this is the server's memory,
not ours, and it is deliberately human-readable (SPEC story 27: "a support
engineer wants the manifest to be plain JSON a human can open on the
server").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

#: Bumped only if the shape of a manifest entry changes. ADR 0025 names no
#: negotiation scheme beyond "read whichever version is there" — today there
#: is exactly one.
MANIFEST_VERSION = 1

#: The manifest's own filename at the remote root (ADR 0025 decision 4:
#: ``<remote_root>/arichds-manifest.json``).
MANIFEST_FILENAME = "arichds-manifest.json"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One file's last-known state at the server, keyed by its relative path
    in :attr:`Manifest.files`.

    Attributes:
        sha256: The file's digest as of *uploaded_at*.
        size: The file's size in bytes as of *uploaded_at*.
        uploaded_at: When this entry was last written — UTC and
            timezone-aware.
    """

    sha256: str
    size: int
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class Manifest:
    """What a remote root holds, or what a cycle is about to write there.

    Attributes:
        version: :data:`MANIFEST_VERSION` this manifest was written with.
        machine_id: This machine's Machine ID — informational only, never
            read back for anything a cycle decides (ADR 0025: "no
            Machine-ID layer" — several machines may share one remote root).
        files: Relative path -> its last-known digest/size/upload time.
            **An entry is never removed** — a file that no longer exists
            locally still keeps its entry here (ADR 0025 decision 3: "never
            delete remotely").
    """

    version: int
    machine_id: str
    files: dict[str, ManifestEntry] = field(default_factory=dict)


def encode_manifest(manifest: Manifest) -> bytes:
    """Render *manifest* as indented, human-readable UTF-8 JSON (SPEC story
    27). Every real transport (tickets 03-05) writes exactly these bytes;
    the in-memory transport the cycle tests use holds :class:`Manifest`
    objects directly and never calls this."""
    payload = {
        "version": manifest.version,
        "machine_id": manifest.machine_id,
        "files": {
            path: {"sha256": entry.sha256, "size": entry.size, "uploaded_at": entry.uploaded_at.isoformat()}
            for path, entry in manifest.files.items()
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def decode_manifest(data: bytes) -> Manifest:
    """The inverse of :func:`encode_manifest`.

    Raises:
        ValueError: On anything not shaped like a manifest. A transport
            catches this itself and answers :meth:`Transport.read_manifest`
            with ``None`` — ADR 0025: "a missing or unreadable manifest
            means 'send everything'" — never lets a malformed remote file
            reach the cycle as a crash.
    """
    try:
        payload = json.loads(data)
        files = {
            str(path): ManifestEntry(
                sha256=str(entry["sha256"]),
                size=int(entry["size"]),
                uploaded_at=datetime.fromisoformat(entry["uploaded_at"]),
            )
            for path, entry in payload["files"].items()
        }
        return Manifest(version=int(payload["version"]), machine_id=str(payload["machine_id"]), files=files)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("not a valid Upload Manifest") from exc


__all__ = ["MANIFEST_FILENAME", "MANIFEST_VERSION", "Manifest", "ManifestEntry", "decode_manifest", "encode_manifest"]
