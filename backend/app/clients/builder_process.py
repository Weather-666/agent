from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import ApiError


class BuilderProcess:
    def __init__(self, settings: Settings) -> None:
        self.executable = settings.builder_executable
        self.timeout_seconds = settings.runtime_operation_timeout_seconds

    async def build(
        self,
        *,
        input_path: Path,
        assets_dir: Path,
        output_dir: Path,
        expert_id: str,
        runtime_type: str,
    ) -> dict[str, Any]:
        executable = self._executable_path()
        try:
            process = await asyncio.create_subprocess_exec(
                str(executable),
                "build",
                "--input",
                str(input_path),
                "--assets-dir",
                str(assets_dir),
                "--output",
                str(output_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await self._communicate(
                process,
                code="EXPERT_BUILDER_TIMEOUT",
                message="Expert Builder timed out",
                runtime_type=runtime_type,
            )
        except OSError as exc:
            raise ApiError(
                502,
                "EXPERT_BUILDER_FAILED",
                "Expert Builder could not be started",
                {"runtimeType": runtime_type},
            ) from exc
        if process.returncode != 0:
            raise ApiError(
                502,
                "EXPERT_BUILDER_FAILED",
                "Expert Builder failed",
                {"runtimeType": runtime_type, "exitCode": process.returncode},
            )
        try:
            result = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(
                502,
                "EXPERT_BUILDER_INVALID_RESULT",
                "Expert Builder returned invalid JSON",
                {"runtimeType": runtime_type},
            ) from exc
        expected_output = str(output_dir.resolve())
        if (
            not isinstance(result, dict)
            or result.get("status") != "passed"
            or result.get("expertId") != expert_id
            or result.get("runtimeType") != runtime_type
            or result.get("output") != expected_output
        ):
            raise ApiError(
                502,
                "EXPERT_BUILDER_INVALID_RESULT",
                "Expert Builder result does not match the requested build",
                {"runtimeType": runtime_type},
            )
        return result

    async def validate(self, output_dir: Path, *, runtime_type: str) -> dict[str, Any]:
        executable = self._executable_path()
        try:
            process = await asyncio.create_subprocess_exec(
                str(executable),
                "validate",
                str(output_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await self._communicate(
                process,
                code="EXPERT_BUILDER_VALIDATE_TIMEOUT",
                message="Expert Builder validation timed out",
                runtime_type=runtime_type,
            )
        except OSError as exc:
            raise ApiError(
                502,
                "EXPERT_BUILDER_VALIDATE_FAILED",
                "Expert Builder validation could not be started",
                {"runtimeType": runtime_type},
            ) from exc
        if process.returncode != 0:
            raise ApiError(
                502,
                "EXPERT_BUILDER_VALIDATE_FAILED",
                "Expert Builder validation failed",
                {"runtimeType": runtime_type, "exitCode": process.returncode},
            )
        try:
            result = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(
                502,
                "EXPERT_BUILDER_INVALID_RESULT",
                "Expert Builder validation returned invalid JSON",
                {"runtimeType": runtime_type},
            ) from exc
        if (
            not isinstance(result, dict)
            or result.get("status") != "passed"
            or result.get("runtimeType") != runtime_type
            or result.get("output") != str(output_dir.resolve())
        ):
            raise ApiError(
                502,
                "EXPERT_BUILDER_INVALID_RESULT",
                "Expert Builder validation result does not match the requested Runtime",
                {"runtimeType": runtime_type},
            )
        return result

    async def _communicate(
        self,
        process: asyncio.subprocess.Process,
        *,
        code: str,
        message: str,
        runtime_type: str,
    ) -> tuple[bytes, bytes]:
        try:
            return await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            await _terminate(process)
            raise ApiError(
                504,
                code,
                message,
                {"runtimeType": runtime_type},
            ) from exc
        except BaseException:
            await _terminate(process)
            raise

    def _executable_path(self) -> Path:
        if not self.executable:
            raise ApiError(
                503,
                "EXPERT_BUILDER_UNCONFIGURED",
                "Expert Builder executable is not configured",
            )
        path = Path(self.executable).expanduser()
        if not path.is_absolute():
            raise ApiError(
                503,
                "EXPERT_BUILDER_INVALID",
                "Expert Builder executable must be an absolute path",
            )
        if not path.is_file():
            raise ApiError(
                503,
                "EXPERT_BUILDER_UNAVAILABLE",
                "Expert Builder executable does not exist",
            )
        return path


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()
    await process.communicate()
