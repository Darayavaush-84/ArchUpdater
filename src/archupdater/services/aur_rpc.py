from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from archupdater.domain.packages import PackageUpdate
from archupdater.services.io_limits import read_limited


@dataclass
class AurRpcClient:
    opener: Callable[..., Any] = urllib.request.urlopen
    AUR_RPC_TIMEOUT_SECONDS = 10
    AUR_RPC_CHUNK_SIZE = 100
    AUR_RPC_MAX_BYTES = 2 * 1024 * 1024

    def fetch_metadata(self, packages: list[PackageUpdate]) -> dict[str, dict[str, object]]:
        names = [package.name for package in packages]
        if not names:
            return {}
        metadata: dict[str, dict[str, object]] = {}
        for chunk in self._chunks(names, self.AUR_RPC_CHUNK_SIZE):
            payload = self.fetch_chunk(chunk)
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list):
                continue
            for item in results:
                if isinstance(item, dict) and item.get("Name"):
                    metadata[str(item["Name"])] = item
        return metadata

    def fetch_chunk(self, names: list[str]) -> dict[str, object]:
        body = urllib.parse.urlencode([("arg[]", name) for name in names]).encode("utf-8")
        request = urllib.request.Request(
            "https://aur.archlinux.org/rpc/v5/info",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.AUR_RPC_TIMEOUT_SECONDS) as response:
                payload = json.loads(
                    self._read_limited_response(response).decode("utf-8", errors="replace")
                )
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _read_limited_response(self, response) -> bytes:  # noqa: ANN001
        try:
            return read_limited(response, self.AUR_RPC_MAX_BYTES)
        except ValueError as exc:
            raise OSError("AUR RPC response is too large.") from exc

    def _chunks(self, values: list[str], size: int) -> list[list[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]
