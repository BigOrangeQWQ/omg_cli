class UnreachableException(Exception):
    """Error raised when an unreachable code path is executed."""

    pass


class RevertException(Exception):
    """Error raised to signal a revert operation."""

    checkpoint: str

    def __init__(self, checkpoint: str) -> None:
        self.checkpoint = checkpoint
        super().__init__(f"Revert to checkpoint: {checkpoint}")


class FinishException(Exception):
    """Error raised to signal the finish of a process."""

    pass
