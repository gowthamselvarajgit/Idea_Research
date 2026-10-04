"""Unit tests for AntigravityAIClient with mocked subprocess execution."""

import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.problems.ai_client import (
    AIClientError,
    AIClientExecutableError,
    AIClientInputError,
    AIClientProcessError,
    AIClientResponseError,
    AIClientTimeoutError,
    AntigravityAIClient,
    _build_combined_prompt,
)


class TestAntigravityAIClient(unittest.TestCase):
    """Test suite for AntigravityAIClient without making real CLI/AI calls."""

    def setUp(self) -> None:
        """Create a default client instance."""
        self.client = AntigravityAIClient(
            model="gemini-3.8-flash-low",
            executable="agy",
            timeout_seconds=120,
        )

    @patch("subprocess.run")
    def test_successful_response_returns_only_payload_response(self, mock_run: MagicMock) -> None:
        """Successful CLI execution parses JSON wrapper and returns only payload['response']."""
        mock_payload = {
            "conversation_id": "test-uuid-123",
            "status": "SUCCESS",
            "response": '{"problem_title": "Interfacial Delamination"}',
            "duration_seconds": 1.25,
            "usage": {"total_tokens": 100},
        }
        mock_run.return_value = subprocess.CompletedProcess(
            args=["agy"],
            returncode=0,
            stdout=json.dumps(mock_payload),
            stderr="",
        )

        result = self.client.generate(
            system_prompt="System instructions here.",
            user_prompt="Patent disclosure context here.",
        )

        self.assertEqual(result, '{"problem_title": "Interfacial Delamination"}')

    @patch("subprocess.run")
    def test_correct_executable_model_and_cli_arguments_passed(self, mock_run: MagicMock) -> None:
        """CLI is invoked with exact expected flags and no shell=True."""
        mock_payload = {"status": "SUCCESS", "response": "ok"}
        mock_run.return_value = subprocess.CompletedProcess(
            args=["agy"],
            returncode=0,
            stdout=json.dumps(mock_payload),
            stderr="",
        )

        custom_client = AntigravityAIClient(
            model="gemini-3.7-flash-high",
            executable="custom-agy",
            timeout_seconds=45,
        )
        custom_client.generate(
            system_prompt="Sys Prompt",
            user_prompt="User Prompt",
        )

        mock_run.assert_called_once()
        cmd, kwargs = mock_run.call_args[0][0], mock_run.call_args[1]

        self.assertEqual(cmd[0], "custom-agy")
        self.assertEqual(cmd[1], "--model")
        self.assertEqual(cmd[2], "gemini-3.7-flash-high")
        self.assertEqual(cmd[3], "--print")
        self.assertEqual(cmd[5], "--output-format")
        self.assertEqual(cmd[6], "json")

        self.assertEqual(kwargs.get("timeout"), 45)
        self.assertFalse(kwargs.get("shell", False))
        self.assertTrue(kwargs.get("capture_output"))
        self.assertEqual(kwargs.get("encoding"), "utf-8")

    @patch("subprocess.run")
    def test_system_and_user_prompts_are_both_included(self, mock_run: MagicMock) -> None:
        """The combined prompt sent to CLI contains both system instructions and user input."""
        mock_payload = {"status": "SUCCESS", "response": "ok"}
        mock_run.return_value = subprocess.CompletedProcess(
            args=["agy"],
            returncode=0,
            stdout=json.dumps(mock_payload),
            stderr="",
        )

        self.client.generate(
            system_prompt="UNIQUE_SYSTEM_INSTRUCTION_TOKEN",
            user_prompt="UNIQUE_USER_PATENT_CONTEXT_TOKEN",
        )

        cmd = mock_run.call_args[0][0]
        combined_arg = cmd[4]

        self.assertIn("UNIQUE_SYSTEM_INSTRUCTION_TOKEN", combined_arg)
        self.assertIn("UNIQUE_USER_PATENT_CONTEXT_TOKEN", combined_arg)
        self.assertIn("=== SYSTEM INSTRUCTIONS ===", combined_arg)
        self.assertIn("=== USER INPUT ===", combined_arg)

    @patch("subprocess.run")
    def test_empty_system_prompt_rejected(self, mock_run: MagicMock) -> None:
        """Empty or whitespace-only system prompts are rejected without calling subprocess."""
        bad_prompts = ["", "   ", "\n\t  "]

        for bad in bad_prompts:
            with self.assertRaises(AIClientInputError):
                self.client.generate(system_prompt=bad, user_prompt="Valid user prompt")

        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_empty_user_prompt_rejected(self, mock_run: MagicMock) -> None:
        """Empty or whitespace-only user prompts are rejected without calling subprocess."""
        bad_prompts = ["", "   ", "\n\t  "]

        for bad in bad_prompts:
            with self.assertRaises(AIClientInputError):
                self.client.generate(system_prompt="Valid system prompt", user_prompt=bad)

        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_nonzero_process_exit_raises_process_error(self, mock_run: MagicMock) -> None:
        """Non-zero process exit codes raise AIClientProcessError."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["agy"],
            returncode=1,
            stdout="",
            stderr="Fatal error: API rate limit exceeded",
        )

        with self.assertRaises(AIClientProcessError) as ctx:
            self.client.generate("Sys", "User")

        self.assertIn("code 1", str(ctx.exception))
        self.assertIn("API rate limit exceeded", str(ctx.exception))

    @patch("subprocess.run")
    def test_executable_not_found_raises_executable_error(self, mock_run: MagicMock) -> None:
        """FileNotFoundError from missing CLI executable raises AIClientExecutableError."""
        mock_run.side_effect = FileNotFoundError("[WinError 2] The system cannot find the file specified")

        with self.assertRaises(AIClientExecutableError) as ctx:
            self.client.generate("Sys", "User")

        self.assertIn("not found on system PATH", str(ctx.exception))

    @patch("subprocess.run")
    def test_subprocess_timeout_raises_timeout_error(self, mock_run: MagicMock) -> None:
        """subprocess.TimeoutExpired raises AIClientTimeoutError."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["agy"], timeout=120)

        with self.assertRaises(AIClientTimeoutError) as ctx:
            self.client.generate("Sys", "User")

        self.assertIn("timed out after 120 seconds", str(ctx.exception))

    @patch("subprocess.run")
    def test_invalid_stdout_json_raises_response_error(self, mock_run: MagicMock) -> None:
        """Non-JSON stdout raises AIClientResponseError."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["agy"],
            returncode=0,
            stdout="Error: Something crashed before JSON output",
            stderr="",
        )

        with self.assertRaises(AIClientResponseError) as ctx:
            self.client.generate("Sys", "User")

        self.assertIn("Failed to parse AI CLI stdout as JSON", str(ctx.exception))

    @patch("subprocess.run")
    def test_cli_status_not_success_raises_response_error(self, mock_run: MagicMock) -> None:
        """CLI JSON payload with status other than SUCCESS raises AIClientResponseError."""
        mock_payload = {
            "status": "ERROR",
            "error_message": "Model context exceeded",
        }
        mock_run.return_value = subprocess.CompletedProcess(
            args=["agy"],
            returncode=0,
            stdout=json.dumps(mock_payload),
            stderr="",
        )

        with self.assertRaises(AIClientResponseError) as ctx:
            self.client.generate("Sys", "User")

        self.assertIn("non-success status: 'ERROR'", str(ctx.exception))

    @patch("subprocess.run")
    def test_missing_response_field_raises_response_error(self, mock_run: MagicMock) -> None:
        """CLI JSON payload missing 'response' field raises AIClientResponseError."""
        mock_payload = {
            "status": "SUCCESS",
            "duration_seconds": 1.0,
        }
        mock_run.return_value = subprocess.CompletedProcess(
            args=["agy"],
            returncode=0,
            stdout=json.dumps(mock_payload),
            stderr="",
        )

        with self.assertRaises(AIClientResponseError) as ctx:
            self.client.generate("Sys", "User")

        self.assertIn("missing 'response' field", str(ctx.exception))

    @patch("subprocess.run")
    def test_non_string_response_field_raises_response_error(self, mock_run: MagicMock) -> None:
        """CLI JSON payload with non-string 'response' field raises AIClientResponseError."""
        mock_payload = {
            "status": "SUCCESS",
            "response": {"nested": "dict"},
        }
        mock_run.return_value = subprocess.CompletedProcess(
            args=["agy"],
            returncode=0,
            stdout=json.dumps(mock_payload),
            stderr="",
        )

        with self.assertRaises(AIClientResponseError) as ctx:
            self.client.generate("Sys", "User")

        self.assertIn("'response' field must be a string", str(ctx.exception))

    def test_deterministic_prompt_construction(self) -> None:
        """_build_combined_prompt constructs consistent, formatted prompt text."""
        sys = "Analyze the patent."
        usr = "Patent: US11223344B2"

        prompt1 = _build_combined_prompt(sys, usr)
        prompt2 = _build_combined_prompt(sys, usr)

        self.assertEqual(prompt1, prompt2)
        expected = (
            "=== SYSTEM INSTRUCTIONS ===\n"
            "Analyze the patent.\n\n"
            "=== USER INPUT ===\n"
            "Patent: US11223344B2"
        )
        self.assertEqual(prompt1, expected)

    def test_constructor_validation(self) -> None:
        """Constructor validates model, executable, and timeout arguments."""
        with self.assertRaises(AIClientInputError):
            AntigravityAIClient(model="")

        with self.assertRaises(AIClientInputError):
            AntigravityAIClient(executable="")

        with self.assertRaises(AIClientInputError):
            AntigravityAIClient(timeout_seconds=0)

        with self.assertRaises(AIClientInputError):
            AntigravityAIClient(timeout_seconds=-10)


if __name__ == "__main__":
    unittest.main()
