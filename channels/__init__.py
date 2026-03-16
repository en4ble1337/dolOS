from typing import Protocol

class Channel(Protocol):
    """Protocol defining the interface for all communication channels."""

    async def start(self) -> None:
        """Starts the channel's main message-processing loop."""
        ...
