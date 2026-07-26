from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Callable, ContextManager, Optional

from rope.base.taskhandle import BaseJobSet, BaseTaskHandle

from rols._utils import throttle
from rols.workspace import Workspace

log = logging.getLogger(__name__)
Report = Callable[[str, int], None]


class PylspJobSet(BaseJobSet):
    count: int = 0
    done: int = 0
    _reporter: Report
    _report_iter: Optional[ContextManager]
    job_name: str = ""

    def __init__(
        self,
        count: int | None,
        report_iter: ContextManager,
        stopped: threading.Event,
    ) -> None:
        if count is not None:
            self.count = count
        self._reporter = report_iter.__enter__()
        self._report_iter = report_iter
        self._stopped = stopped

    def started_job(self, name: str | None) -> None:
        self.check_status()
        if name:
            self.job_name = name

    def finished_job(self) -> None:
        self.done += 1
        percent = self.get_percent_done()
        if percent is not None and int(percent) >= 100:
            if self._report_iter is None:
                return
            self._report_iter.__exit__(None, None, None)
            self._report_iter = None
        else:
            self._report()

    def check_status(self) -> None:
        if self._stopped.is_set():
            from rope.base.exceptions import InterruptedTaskError

            raise InterruptedTaskError()

    def get_percent_done(self) -> float | None:
        if self.count == 0:
            return 0
        return (self.done / self.count) * 100

    def increment(self) -> None:
        """
        Increment the number of tasks to complete.

        This is used if the number is not known ahead of time.
        """
        self.count += 1
        self._report()

    @throttle(1)
    def _report(self) -> None:
        percent_done = self.get_percent_done()
        percent = int(percent_done) if percent_done is not None else 0
        message = f"{self.job_name} {self.done}/{self.count}"
        log.debug(f"Reporting {message} {percent}%")
        self._reporter(message, percent)


class PylspTaskHandle(BaseTaskHandle):
    name: str
    observers: list
    job_sets: list[PylspJobSet]
    stopped: bool
    workspace: Workspace
    _report: Callable[[str, str], None]

    def __init__(self, workspace: Workspace, stopped: threading.Event) -> None:
        self.workspace = workspace
        self._stopped = stopped
        self.job_sets = []
        self.observers = []

    def create_jobset(self, name="JobSet", count: int | None = None):
        report_iter = self.workspace.report_progress(
            name, None, None, skip_token_initialization=True
        )
        result = PylspJobSet(count, report_iter, self._stopped)
        self.job_sets.append(result)
        self._inform_observers()
        return result

    def stop(self) -> None:
        self._stopped.set()

    def current_jobset(self) -> BaseJobSet | None:
        return self.job_sets[-1] if self.job_sets else None

    def add_observer(self) -> None:
        pass

    def is_stopped(self) -> bool:
        return self._stopped.is_set()

    def get_jobsets(self) -> Sequence[BaseJobSet]:
        return self.job_sets

    def _inform_observers(self) -> None:
        for observer in self.observers:
            observer()
