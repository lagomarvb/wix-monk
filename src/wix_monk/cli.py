from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from wix_monk.config.loading import SyncConfig
from wix_monk.context import RuntimeContext
from wix_monk.discovery.commands import DiscoveryCommands, load_criteria
from wix_monk.domain.filtering import FIELD_TYPES, FilterConfigError
from wix_monk.integrations.clients import ListmonkClient, WixClient
from wix_monk.integrations.datasets import NormalizedWixData, WixDataset
from wix_monk.integrations.services import ListmonkService, WixService
from wix_monk.sync.service import SynchronizationService

DEFAULT_LOG_LEVEL = "INFO"
LOG_LEVEL_CHOICES = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
DIST_NAME = "wix-monk"


def get_version() -> str:
    """Return the installed package version or a source checkout fallback."""

    try:
        return version(DIST_NAME)
    except PackageNotFoundError:
        return "0.0.0.dev0"


class HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Show subcommands in a compact block before the generic options."""

    def _format_action(self, action: argparse.Action) -> str:
        if isinstance(action, argparse._SubParsersAction):
            command_help = [
                self._format_action(command)
                for command in action._get_subactions()
            ]
            return self._join_parts(command_help)
        return super()._format_action(action)


def main() -> None:
    """Parse CLI arguments and dispatch to the selected command."""

    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_usage()
        raise SystemExit(0)

    args = parser.parse_args()
    try:
        runtime = _build_runtime(args)
        _dispatch(runtime, args)
    except (FilterConfigError, ValueError, OSError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``wix-monk`` argument parser."""

    parser = argparse.ArgumentParser(
        prog="wix-monk",
        usage="%(prog)s COMMAND [-h]",
        description="Discover Wix data and synchronize contacts to Listmonk.",
        epilog="Run 'wix-monk COMMAND --help' for detailed command usage.",
        add_help=False,
        formatter_class=HelpFormatter,
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        title="Commands",
        metavar="COMMAND",
    )

    _add_sync_command(commands)
    _add_schema_command(commands)
    _add_values_command(commands)
    _add_plans_command(commands)
    _add_snapshot_command(commands)
    _add_members_command(commands)
    _add_duplicates_command(commands)
    _add_query_command(commands)

    global_options = parser.add_argument_group("Global options")
    global_options.add_argument(
        "-h",
        "--help",
        action="help",
        help="Show this help message and exit.",
    )
    global_options.add_argument(
        "--version",
        action="version",
        version=get_version(),
        help="Show the installed version and exit.",
    )
    return parser


def _add_sync_command(commands: argparse._SubParsersAction) -> None:
    sync = _add_command_parser(
        commands,
        "sync",
        help="Preview or apply synchronization changes.",
        description=(
            "Compare Wix contacts with Listmonk and show the changes needed to "
            "match the configured lists. By default, an interactive terminal "
            "prompts before applying changes; a non-interactive session is a dry run."
        ),
        epilog=(
            "Examples:\n"
            "  wix-monk sync --config config.json --dry-run\n"
            "  wix-monk sync --config config.json --yes"
        ),
    )
    sync_config = sync.add_argument_group("Configuration")
    sync_config.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        metavar="FILE",
        help="Read synchronization rules from FILE; default is config.json.",
    )
    sync_mode = sync.add_argument_group("Execution mode")
    mode = sync_mode.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the plan without making changes.",
    )
    mode.add_argument(
        "--yes",
        action="store_true",
        help="Apply changes immediately without prompting.",
    )
    _add_standard_options(sync)


def _add_schema_command(commands: argparse._SubParsersAction) -> None:
    schema = _add_command_parser(
        commands,
        "schema",
        help="List fields and operators available in criteria.",
        description=(
            "List every field that can be used in a criteria expression, including "
            "its data type and supported operators. This command does not contact Wix."
        ),
        epilog="Examples:\n  wix-monk schema --json",
    )
    schema_output = schema.add_argument_group("Output")
    _add_json_option(schema_output)
    _add_standard_options(schema)


def _add_values_command(commands: argparse._SubParsersAction) -> None:
    values = _add_command_parser(
        commands,
        "values",
        help="List values observed in normalized Wix data.",
        description=(
            "Show values found in live Wix data so they can be copied into criteria. "
            "Without FIELD, only a default set of non-sensitive fields is shown."
        ),
        epilog=(
            "Examples:\n"
            "  wix-monk values\n"
            "  wix-monk values active_plan_names\n"
            "  wix-monk values member_status\n"
            "  wix-monk values subscription_status --json"
        ),
    )
    values_query = values.add_argument_group("Query")
    values_query.add_argument(
        "field",
        nargs="?",
        choices=sorted(FIELD_TYPES),
        metavar="FIELD",
        help="Show values for one criteria field; omit to show the default fields.",
    )
    values_output = values.add_argument_group("Output")
    _add_json_option(values_output)
    _add_standard_options(values)


def _add_plans_command(commands: argparse._SubParsersAction) -> None:
    plans = _add_command_parser(
        commands,
        "plans",
        help="List pricing plans observed in Wix orders.",
        description=(
            "List pricing plan names and IDs found in Wix pricing-plan orders, with "
            "order counts and copy-ready criteria expressions."
        ),
        epilog="Examples:\n  wix-monk plans --json",
    )
    plans_output = plans.add_argument_group("Output")
    _add_json_option(plans_output)
    _add_standard_options(plans)


def _add_snapshot_command(commands: argparse._SubParsersAction) -> None:
    snapshot = _add_command_parser(
        commands,
        "snapshot",
        help="Export schema, observed values, and plans together.",
        description=(
            "Create a reusable reference containing the criteria schema, observed "
            "non-sensitive values, and pricing plans. Contact records are excluded "
            "unless --include-contacts is specified."
        ),
        epilog=(
            "Examples:\n"
            "  wix-monk snapshot --json\n"
            "  wix-monk snapshot --json --include-contacts"
        ),
    )
    snapshot_output = snapshot.add_argument_group("Output")
    _add_json_option(snapshot_output)
    snapshot_output.add_argument(
        "--include-contacts",
        action="store_true",
        help="Include normalized contact records containing personal data.",
    )
    _add_standard_options(snapshot)


def _add_members_command(commands: argparse._SubParsersAction) -> None:
    members = _add_command_parser(
        commands,
        "members",
        help="Summarize approved Wix members.",
        description=(
            "Summarize approved Wix members without showing personal details by "
            "default. Use --show-contacts to include matching contact records."
        ),
        epilog="Examples:\n  wix-monk members --show-contacts --limit 50",
    )
    members_output = members.add_argument_group("Output")
    _add_contact_output_options(members_output)
    _add_standard_options(members)


def _add_duplicates_command(commands: argparse._SubParsersAction) -> None:
    duplicates = _add_command_parser(
        commands,
        "duplicates",
        help="Audit duplicate contacts and member/contact links.",
        description=(
            "Report duplicate Wix contacts, duplicate member accounts, and broken or "
            "ambiguous member/contact links. Personal data is hidden by default."
        ),
        epilog="Examples:\n  wix-monk duplicates --show-records --json",
    )
    duplicates_output = duplicates.add_argument_group("Output")
    _add_json_option(duplicates_output)
    duplicates_output.add_argument(
        "--show-records",
        action="store_true",
        help="Include personal data and record IDs for each issue.",
    )
    _add_standard_options(duplicates)


def _add_query_command(commands: argparse._SubParsersAction) -> None:
    query = _add_command_parser(
        commands,
        "query",
        help="Test one criteria expression against live Wix data.",
        description=(
            "Evaluate one criteria expression using the same normalized Wix data and "
            "matching rules as synchronization. Provide the expression directly as "
            "JSON or read it from a file."
        ),
        epilog=(
            "Examples:\n"
            "  wix-monk query --criteria '{\"field\":\"is_member\",\"equals\":true}'\n"
            "  wix-monk query --criteria-file criteria.json --show-contacts"
        ),
    )
    query_input = query.add_argument_group("Criteria (one is required)")
    source = query_input.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--criteria",
        metavar="JSON",
        help="Evaluate a criteria expression supplied as a JSON string.",
    )
    source.add_argument(
        "--criteria-file",
        type=Path,
        metavar="FILE",
        help="Evaluate the single criteria expression stored in FILE.",
    )
    query_output = query.add_argument_group("Output")
    _add_contact_output_options(query_output)
    _add_standard_options(query)


def _add_command_parser(
        commands: argparse._SubParsersAction,
        name: str,
        **options: object,
) -> argparse.ArgumentParser:
    return commands.add_parser(
        name,
        add_help=False,
        formatter_class=HelpFormatter,
        **options,
    )


def _add_standard_options(parser: argparse.ArgumentParser) -> None:
    logging_options = parser.add_argument_group("Logging")
    logging_options.add_argument(
        "--log-level",
        choices=LOG_LEVEL_CHOICES,
        default=DEFAULT_LOG_LEVEL,
        help="Set the log level; default is INFO. Logs are written to stderr.",
    )

    global_options = parser.add_argument_group("Global options")
    global_options.add_argument(
        "-h",
        "--help",
        action="help",
        help="Show this help message and exit.",
    )


def _dispatch(runtime: RuntimeContext, args: argparse.Namespace) -> None:
    if args.command == "sync":
        _run_sync(runtime, args)
        return
    _run_discovery_command(runtime, args)


def _run_discovery_command(
    runtime: RuntimeContext,
    args: argparse.Namespace,
) -> None:
    if args.command == "schema":
        empty_dataset = WixDataset((), (), (), ())
        discovery = DiscoveryCommands(
            runtime.stdout,
            runtime.stderr,
            runtime.logger,
            NormalizedWixData(empty_dataset),
        )
        discovery.schema(args.json)
        return

    wix_data = WixService(_wix_client(runtime)).data()
    discovery = DiscoveryCommands(
        runtime.stdout,
        runtime.stderr,
        runtime.logger,
        wix_data,
    )

    if args.command == "values":
        discovery.values(args.field, args.json)
        return
    if args.command == "plans":
        discovery.plans(args.json)
        return
    if args.command == "snapshot":
        discovery.snapshot(args.json, args.include_contacts)
        return
    if args.command == "members":
        discovery.members(args.json, args.show_contacts, args.limit)
        return
    if args.command == "duplicates":
        discovery.duplicates(args.json, args.show_records)
        return
    if args.command == "query":
        criteria = load_criteria(args.criteria, args.criteria_file)
        discovery.query(
            criteria,
            args.json,
            args.show_contacts,
            args.limit,
        )
        return
    raise AssertionError(f"Unhandled discovery command: {args.command}")


def _run_sync(runtime: RuntimeContext, args: argparse.Namespace) -> None:
    config = SyncConfig.load(args.config)
    should_apply = _resolve_sync_mode(args, runtime.stderr)
    wix_data = WixService(_wix_client(runtime)).data()
    listmonk_client = _listmonk_client(runtime)
    listmonk_data = ListmonkService(listmonk_client).data()

    service = SynchronizationService(
        wix_data,
        listmonk_data,
        listmonk_client,
        runtime.logger,
        output=lambda line: print(line, file=runtime.stdout),
    )
    service.run(config, should_apply)


def _add_contact_output_options(parser: argparse._ArgumentGroup) -> None:
    parser.add_argument(
        "--show-contacts",
        action="store_true",
        help="Include names and email addresses in output.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Maximum contacts to show; default is 25.",
    )
    _add_json_option(parser)


def _add_json_option(parser: argparse._ArgumentGroup) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write machine-readable JSON instead of the text report.",
    )


def _build_runtime(args: argparse.Namespace) -> RuntimeContext:
    log_level = getattr(args, "log_level", DEFAULT_LOG_LEVEL)
    _configure_logging(log_level)
    return RuntimeContext(
        stdout=sys.stdout,
        stderr=sys.stderr,
        logger=logging.getLogger("wix_monk"),
        wix_api_key=os.getenv("WIX_API_KEY", "").strip(),
        wix_site_id=os.getenv("WIX_SITE_ID", "").strip(),
        wix_account_id=os.getenv("WIX_ACCOUNT_ID", "").strip(),
        listmonk_url=os.getenv("LISTMONK_URL", "").strip(),
        listmonk_username=os.getenv("LISTMONK_USERNAME", "").strip(),
        listmonk_password=os.getenv("LISTMONK_PASSWORD", "").strip(),
    )


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Unknown log level: {level_name}")
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(levelname)s:%(name)s:%(message)s",
        )
    else:
        root.setLevel(level)
    logging.getLogger("wix_monk").setLevel(level)


def _wix_client(runtime: RuntimeContext) -> WixClient:
    return WixClient(
        _required_value("WIX_API_KEY", runtime.wix_api_key),
        _required_value("WIX_SITE_ID", runtime.wix_site_id),
        runtime.wix_account_id,
    )


def _listmonk_client(runtime: RuntimeContext) -> ListmonkClient:
    return ListmonkClient(
        _required_value("LISTMONK_URL", runtime.listmonk_url),
        _required_value("LISTMONK_USERNAME", runtime.listmonk_username),
        _required_value("LISTMONK_PASSWORD", runtime.listmonk_password),
    )


def _required_value(name: str, value: str) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _resolve_sync_mode(args: argparse.Namespace, stderr: object) -> bool:
    if args.dry_run:
        return False
    if args.yes:
        return True
    if sys.stdin.isatty() and sys.stdout.isatty():
        response = input("Apply these changes? [y/N] ").strip().lower()
        return response in {"y", "yes"}
    print(
        "Non-interactive session detected; running dry-run. Use --yes to apply.",
        file=stderr,
    )
    return False


if __name__ == "__main__":
    main()
