"""应用异常。"""


class SyncError(Exception):
    pass


class LoginRequired(SyncError):
    pass


class SyncCancelled(SyncError):
    """The calling agent stopped an in-flight eLearning operation."""
