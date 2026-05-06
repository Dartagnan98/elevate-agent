from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


class BrowserUseHarnessError(RuntimeError):
    """Raised when the upstream browser-use/browser-harness command fails."""


@dataclass(slots=True)
class BrowserUseHarness:
    """Thin Elevate adapter around browser-use/browser-harness.

    The upstream harness is the browser control layer. Elevate keeps durable job
    state, redaction, approvals, source snapshots, and real-estate workflows on
    top of it.
    """

    command: str = "browser-harness"
    cdp_url: str | None = None
    name: str | None = None
    timeout: int = 120

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def run_code(self, code: str) -> str:
        if not self.available():
            raise BrowserUseHarnessError(
                f"{self.command!r} is not installed. Install https://github.com/browser-use/browser-harness first."
            )

        env = os.environ.copy()
        if self.cdp_url:
            env["BU_CDP_URL"] = self.cdp_url
        if self.name:
            env["BU_NAME"] = self.name

        proc = subprocess.run(
            [self.command, "-c", code],
            env=env,
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()
            raise BrowserUseHarnessError(err or f"{self.command} exited {proc.returncode}")
        return proc.stdout.strip()

    def page_info(self) -> dict[str, Any]:
        output = self.run_code("import json\nprint(json.dumps(page_info()))")
        # browser-harness can print update banners before command output. Parse
        # the last JSON-looking line instead of assuming stdout is only JSON.
        for line in reversed(output.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                return json.loads(line)
        raise BrowserUseHarnessError(f"No JSON page_info output found: {output[:500]}")
