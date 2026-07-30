"""The interface every ingestion source implements."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


class SourceError(Exception):
    """The source is configured but could not be read (auth, network, missing file)."""


@dataclass
class TableRead:
    """A header row plus lazily-produced windows of data rows.

    Windows exist so a 40k-row tab can be streamed in batches rather than held in
    memory all at once.
    """

    header: Sequence[object]
    windows: Iterable[Sequence[Sequence[Any]]]
    tab: str


class SheetSource(abc.ABC):
    name: str = "unknown"

    @abc.abstractmethod
    def read_table(self, table: str) -> TableRead | None:
        """Return the rows for one analytics table, or None if the tab is absent.

        Returning None is how a source reports honest unavailability. Raise
        SourceError for anything that is a genuine failure to read.
        """

    def close(self) -> None:
        """Release any handles. Called after every refresh."""
