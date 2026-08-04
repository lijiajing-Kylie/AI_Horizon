from .model import *  # noqa: F401,F403
from .base import WxGather  # noqa: F401


def search_Biz(kw: str = "", limit=5, offset=0):
    return WxGather().search_Biz(kw, limit, offset)
