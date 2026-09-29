"""应用异常。"""


class SyncError(Exception):
    pass


class LoginRequired(SyncError):
    pass
