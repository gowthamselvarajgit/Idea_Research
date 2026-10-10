"""AI client implementation interfacing with the local Antigravity CLI runtime."""

import json
import logging
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AIClientError(Exception):
    """Base exception for all AI client execution errors."""
    pass


class AIClientInputError(AIClientError, ValueError):
    """Raised when provided prompts or configuration inputs are invalid."""
    pass


class AIClientExecutableError(AIClientError):
    """Raised when the specified AI CLI executable cannot be found on PATH."""
    pass


class AIClientTimeoutError(AIClientError):
    """Raised when AI process execution exceeds the configured timeout."""
    pass


class AIClientProcessError(AIClientError):
    """Raised when the AI CLI process terminates with a non-zero exit code."""
    pass


class AIClientResponseError(AIClientError):
    """Raised when the AI CLI response payload is malformed or invalid."""
    pass


def _build_combined_prompt(system_prompt: str, user_prompt: str) -> str:
    """Deterministically assemble system instructions and user context.

    Args:
        system_prompt: System-level extraction guidelines and constraints.
        user_prompt: Specific patent disclosure text and context.

    Returns:
        str: Structured prompt separating instructions from user input.
    """
    return (
        "=== SYSTEM INSTRUCTIONS ===\n"
        f"{system_prompt.strip()}\n\n"
        "=== USER INPUT ===\n"
        f"{user_prompt.strip()}"
    )


class AntigravityAIClient:
    """AI client invoking the local authenticated Antigravity CLI executable."""

    def __init__(
        self,
        model: str = "gemini-3.8-flash-low",
        executable: str = "agy",
        timeout_seconds: int = 120,
        max_retries: int = 2,
        retry_backoff_seconds: float = 2.0,
    ) -> None:
        """Initialize the client.

        Args:
            model: Model identifier supported by agy (default: gemini-3.8-flash-low).
            executable: CLI executable command or path (default: agy).
            timeout_seconds: Subprocess execution timeout in seconds (default: 120).
            max_retries: Additional retry attempts on transient process failure (default: 2).
            retry_backoff_seconds: Base backoff sleep time in seconds between retries (default: 2.0).

        Raises:
            AIClientInputError: If configuration arguments are invalid.
        """
        if not model or not model.strip():
            raise AIClientInputError("model must be a non-empty string.")
        if not executable or not executable.strip():
            raise AIClientInputError("executable must be a non-empty string.")
        if timeout_seconds <= 0:
            raise AIClientInputError("timeout_seconds must be a positive integer.")
        if max_retries < 0:
            raise AIClientInputError("max_retries must be a non-negative integer.")
        if retry_backoff_seconds < 0:
            raise AIClientInputError("retry_backoff_seconds must be non-negative.")

        self.model = model.strip()
        self.executable = executable.strip()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Invoke the AI model via the Antigravity CLI and return generated text.

        Retries on transient subprocess failures (timeouts and non-zero process exits).

        Args:
            system_prompt: Non-empty system instructions string.
            user_prompt: Non-empty user prompt string.

        Returns:
            str: Raw generated response text from the model.

        Raises:
            AIClientInputError: If prompts are invalid.
            AIClientExecutableError: If the CLI executable is missing.
            AIClientTimeoutError: If execution exceeds timeout across all attempts.
            AIClientProcessError: If process exits with non-zero return code across all attempts.
            AIClientResponseError: If JSON or response payload is invalid.
        """
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise AIClientInputError("system_prompt must be a non-empty string.")
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise AIClientInputError("user_prompt must be a non-empty string.")

        combined_prompt = _build_combined_prompt(system_prompt, user_prompt)

        cmd = [
            self.executable,
            "--model",
            self.model,
            "--print",
            combined_prompt,
            "--output-format",
            "json",
        ]

        total_attempts = 1 + self.max_retries

        for attempt in range(1, total_attempts + 1):
            logger.debug(
                "Executing AI command (attempt %d/%d): %s (model=%s)",
                attempt,
                total_attempts,
                self.executable,
                self.model,
            )

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as err:
                if getattr(err, "winerror", None) == 206:
                    raise AIClientError(
                        f"Prompt command length ({len(combined_prompt)} chars) exceeded Windows limit (WinError 206)."
                    ) from err
                # Missing executable is non-retryable
                raise AIClientExecutableError(
                    f"AI CLI executable '{self.executable}' not found on system PATH."
                ) from err
            except subprocess.TimeoutExpired as err:
                if attempt < total_attempts:
                    logger.warning(
                        "AI process timed out on attempt %d/%d. Retrying in %.1fs...",
                        attempt,
                        total_attempts,
                        self.retry_backoff_seconds,
                    )
                    time.sleep(self.retry_backoff_seconds)
                    continue
                raise AIClientTimeoutError(
                    f"AI process execution timed out after {self.timeout_seconds} seconds."
                ) from err
            except Exception as err:
                raise AIClientError(f"Unexpected error executing AI process: {err}") from err

            if proc.returncode != 0:
                stderr_clean = proc.stderr.strip() if proc.stderr else ""
                if attempt < total_attempts:
                    logger.warning(
                        "AI process exited with code %d on attempt %d/%d (stderr: %s). Retrying in %.1fs...",
                        proc.returncode,
                        attempt,
                        total_attempts,
                        stderr_clean,
                        self.retry_backoff_seconds,
                    )
                    time.sleep(self.retry_backoff_seconds)
                    continue
                raise AIClientProcessError(
                    f"AI process exited with code {proc.returncode}. Stderr: {stderr_clean}"
                )

            # Successfully completed subprocess: parse output wrapper (non-retryable on output structure)
            try:
                payload = json.loads(proc.stdout)
            except (json.JSONDecodeError, UnicodeDecodeError) as err:
                raise AIClientResponseError(
                    f"Failed to parse AI CLI stdout as JSON: {err}"
                ) from err

            if not isinstance(payload, dict):
                raise AIClientResponseError(
                    f"Expected JSON object from AI CLI, got {type(payload).__name__}."
                )

            status = payload.get("status")
            if status != "SUCCESS":
                raise AIClientResponseError(
                    f"AI CLI returned non-success status: '{status}'."
                )

            response = payload.get("response")
            if response is None:
                raise AIClientResponseError("AI CLI JSON output missing 'response' field.")

            if not isinstance(response, str):
                raise AIClientResponseError(
                    f"AI CLI 'response' field must be a string, got {type(response).__name__}."
                )

            return response
