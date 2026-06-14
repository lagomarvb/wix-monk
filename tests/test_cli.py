import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

from wix_monk.cli import build_parser, get_version, main


class CliTests(unittest.TestCase):
    def test_log_level_is_accepted_after_command(self):
        args = build_parser().parse_args(["sync", "--log-level", "DEBUG"])
        self.assertEqual(args.log_level, "DEBUG")
        self.assertEqual(args.command, "sync")

    def test_log_level_is_rejected_before_command(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--log-level", "DEBUG", "sync"])

    def test_log_level_defaults_to_info(self):
        args = build_parser().parse_args(["sync"])
        self.assertEqual(args.log_level, "INFO")

    def test_top_level_help_lists_commands_before_global_options(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit):
            build_parser().parse_args(["--help"])

        help_text = output.getvalue()
        self.assertIn("usage: wix-monk COMMAND [-h]", help_text)
        self.assertLess(help_text.index("Commands:"), help_text.index("Global options:"))
        self.assertNotIn("\n  COMMAND\n", help_text)
        self.assertNotIn("--log-level", help_text)

    def test_each_command_has_detailed_help(self):
        commands = (
            "sync",
            "schema",
            "values",
            "plans",
            "snapshot",
            "members",
            "duplicates",
            "query",
        )

        for command in commands:
            with self.subTest(command=command):
                output = StringIO()
                with redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
                    build_parser().parse_args([command, "--help"])

                self.assertEqual(exit_context.exception.code, 0)
                self.assertIn(f"usage: wix-monk {command}", output.getvalue())
                self.assertIn("Examples:", output.getvalue())

    def test_no_arguments_prints_top_level_help(self):
        stdout = StringIO()
        stderr = StringIO()
        with patch("sys.argv", ["wix-monk"]), redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as exit_context:
            main()

        self.assertEqual(exit_context.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), "usage: wix-monk COMMAND [-h]")
        self.assertEqual(stderr.getvalue(), "")

    def test_sync_help_explains_config_and_execution_modes(self):
        output = self._help_for("sync")

        self.assertIn("--config FILE", output)
        self.assertIn("default is", output)
        self.assertIn("config.json.", output)
        self.assertIn("--dry-run", output)
        self.assertIn("--yes", output)
        self.assertLess(output.index("Configuration:"), output.index("Global options:"))
        self.assertLess(output.index("Execution mode:"), output.index("Global options:"))
        self.assertLess(output.index("Logging:"), output.index("Global options:"))
        self.assertLess(output.index("Global options:"), output.index("Examples:"))
        self.assertNotIn("\noptions:\n", output)

    def test_query_help_explains_both_criteria_sources(self):
        output = self._help_for("query")

        self.assertIn("--criteria JSON", output)
        self.assertIn("--criteria-file FILE", output)
        self.assertIn("one is required", output)

    def test_schema_does_not_require_integration_credentials(self):
        stdout = StringIO()
        stderr = StringIO()
        with patch.dict("os.environ", {}, clear=True), patch(
            "sys.argv", ["wix-monk", "schema"]
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            main()

        self.assertIn("Fields:", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_version_option_reports_installed_version(self):
        output = StringIO()
        with patch("wix_monk.cli.get_version", return_value="9.8.7"), redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
            build_parser().parse_args(["--version"])

        self.assertEqual(exit_context.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "9.8.7")

    def test_get_version_falls_back_when_distribution_is_missing(self):
        with patch("wix_monk.cli.version", side_effect=PackageNotFoundError):
            self.assertEqual(get_version(), "0.0.0.dev0")

    def _help_for(self, command):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit):
            build_parser().parse_args([command, "--help"])
        return output.getvalue()


if __name__ == "__main__":
    unittest.main()
