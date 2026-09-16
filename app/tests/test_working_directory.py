"""The process runs in a writable working directory (ui-audit ticket 06).

The vendored Gurux reader opens ``logFile.txt`` relative to the working
directory and is never edited (CLAUDE.md), so the application moves itself
into the data dir's ``logs`` folder at startup — under the installed service
the inherited directory is ``Program Files``, where that open raised
``PermissionError`` on every poll.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from gurux_common.enums import TraceLevel

from arichds.config import Settings
from arichds.vendor.gurux.GXDLMSReader import GXDLMSReader


class TestStartupChangesTheWorkingDirectory:
    def test_the_cwd_is_under_the_data_dir_after_startup(
        self, unlicensed_client: TestClient, settings: Settings
    ) -> None:
        cwd = Path(os.getcwd()).resolve()
        assert cwd == settings.log_dir.resolve()
        assert settings.data_dir.resolve() in cwd.parents

    def test_the_gurux_readers_log_file_lands_under_the_data_dir(
        self, unlicensed_client: TestClient, settings: Settings
    ) -> None:
        """The one known relative write: construct the vendored reader exactly
        as the driver does (client/media unused at construction) and look at
        where its ``logFile.txt`` opened."""
        reader = GXDLMSReader(None, None, TraceLevel.ERROR, None)
        try:
            log_path = Path(reader.logFile.name).resolve()
        finally:
            reader.logFile.close()
        assert log_path.parent == settings.log_dir.resolve()
        assert log_path.name == "logFile.txt"
        log_path.unlink(missing_ok=True)
