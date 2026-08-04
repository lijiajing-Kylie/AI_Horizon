"""Article status constants (extracted from we-mp-rss ``core/models/base.py``
so the bundled core needs no SQLAlchemy)."""


class DataStatus:
    DELETED: int = 1000
    ACTIVE: int = 1
    INACTIVE: int = 2
    PENDING: int = 3
    COMPLETED: int = 4
    FAILED: int = 5
    FETCHING: int = 6  # 正在获取内容（锁定状态，防止多节点重复获取）


DATA_STATUS = DataStatus()
