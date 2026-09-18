"""Base repository class holding the SQLiteStore reference."""


class BaseRepository:
    def __init__(self, store):
        self.store = store
