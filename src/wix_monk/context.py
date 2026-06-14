from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True)
class RuntimeContext:
    """Runtime values needed to execute one CLI command."""

    stdout: TextIO
    stderr: TextIO
    logger: logging.Logger
    wix_api_key: str
    wix_site_id: str
    wix_account_id: str
    listmonk_url: str
    listmonk_username: str
    listmonk_password: str
