# -*- coding: utf-8 -*-
"""最小可用的 py 源探针：只回答一个问题——这个播放器到底跑不跑 py 源。

要点（这是很多自写 py 源失败的真因）：
  1. 电视端内核是把 py 文件当插件加载，标准写法必须先
         sys.path.append('..')
         from base.spider import Spider
     然后 `class Spider(Spider)` 继承它。只写 `class Spider(object)` 时，
     内核拿不到基类里的东西（extend、regStr、fetch 等），源会整片空白。
  2. 六个方法签名要对：init / homeContent / homeVideoContent /
     categoryContent / searchContent / detailContent / playerContent。
  3. 不要把异常抛出去，异常就等于「源坏了」。

本文件不联网、不读文件、不用第三方库，所以任何正常 py 引擎都应该显示内容。
"""
import sys

try:
    sys.path.append('..')
    from base.spider import Spider as _Base   # noqa: F401  (内核提供)
except Exception:                              # 本地/无基类时降级，仍然能跑
    class _Base(object):
        def __init__(self):
            pass


class Spider(_Base):

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.name = "py-probe"

    def getName(self):
        return self.name

    def init(self, extend=""):
        return None

    def _env(self):
        try:
            return "python %s | %s" % (sys.version.split()[0], sys.platform)
        except Exception:
            return "python ?"

    def _row(self, title, remark=""):
        return {
            "vod_id": "1",
            "vod_name": title,
            "vod_pic": "",
            "vod_remarks": remark,
            "vod_content": self._env(),
        }

    def homeContent(self, filter=True):
        return {
            "class": [{"type_id": "ok", "type_name": "PY-OK"}],
            "filters": {},
            "list": [self._row("PY 引擎正常")],
        }

    def homeVideoContent(self):
        return {"list": [self._row("PY 引擎正常", self._env()),
                         self._row("看到这两条 = py 源能跑", "probe")]}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        return {"list": [self._row("PY 引擎正常", "分类 " + str(tid))],
                "page": 1, "pagecount": 1, "limit": 20, "total": 1}

    def searchContent(self, key, quick=False, pg="1"):
        return {"list": [self._row("PY 引擎正常", "搜索 " + str(key))],
                "page": 1, "pagecount": 1, "limit": 20, "total": 1}

    def detailContent(self, ids):
        return {"list": [{
            "vod_id": "1",
            "vod_name": "PY 引擎正常",
            "vod_pic": "",
            "vod_content": self._env(),
            "vod_play_from": "probe",
            "vod_play_url": "测试$http://127.0.0.1/probe.m3u8",
        }]}

    def playerContent(self, flag, id, vipFlags=None):
        return {"parse": 0, "playUrl": "", "url": id,
                "header": {"User-Agent": "ok"}, "jx": 0, "time": 0}
