from __future__ import annotations

from collections.abc import Callable

from archupdater.domain.process_result import CommandProcessResult
from archupdater.application.update_session.backend import CommandRunResult


class ExecutionGateway:
    def __init__(
        self,
        *,
        translate: Callable[[str], str],
        command_available: Callable[[str], bool],
        print_command: Callable[[list[str]], None],
        run_process: Callable[..., CommandProcessResult],
        command_failure_message: Callable[[str, int, str], str],
    ) -> None:
        self._t = translate
        self._command_available = command_available
        self._print_command = print_command
        self._run_process = run_process
        self._command_failure_message = command_failure_message

    def run_command(
        self,
        command: list[str],
        *,
        failure_message: str,
        extra_env: dict[str, str] | None = None,
        success_codes: frozenset[int] = frozenset({0}),
    ) -> CommandRunResult:
        if not command:
            return CommandRunResult(
                False,
                self._command_failure_message(failure_message, 1, "empty command"),
            )
        if not self._command_available(command[0]):
            return CommandRunResult(
                False,
                self._t("{command} is not available on this system.").format(
                    command=command[0]
                ),
            )

        self._print_command(command)
        result = (
            self._run_process(command)
            if extra_env is None
            else self._run_process(command, extra_env=extra_env)
        )
        if result.return_code in success_codes:
            return CommandRunResult(True, payload={"output": result.output})
        return CommandRunResult(
            False,
            self._command_failure_message(
                failure_message,
                result.return_code,
                result.output,
            ),
        )
