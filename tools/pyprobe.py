# -*- coding: utf-8 -*-
# 最小 Python 源：只用来回答一个问题 —— 你的播放器到底能不能跑 py 源。
# 不联网、不读文件、不用第三方库，任何正常的 py 引擎都应该秒出结果。

import sys


class Spider(object):
    def __init__(self):
        self.name = "py-probe"

    def init(self, extend=""):
        return None

    def _env(self):
        return "python %s | %s" % (sys.version.split()[0], sys.platform)

    def _row(self, name, remarks=""):
        return {"vod_id": "1", "vod_name": name, "vod_pic": "", "vod_remarks": remarks,
                "vod_content": self._env()}

    def homeContent(self, filter=True):
        return {"class": [{"type_id": "ok", "type_name": "PY-OK", "type_flag": "1"}],
                "filters": {}, "list": [self._row("PY 引擎正常")]}

    def homeVideoContent(self):
        return {"list": [self._row("PY 引擎正常", self._env()),
                         self._row("如果看到这张，py 源没问题")]}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        return {"list": [self._row("PY 引擎正常", "分类 " + str(tid))],
                "page": 1, "pagecount": 1, "limit": 20, "total": 1}

    def searchContent(self, key, quick=False, pg="1"):
        return {"list": [self._row("PY 引擎正常", "搜索 " + str(key))],
                "page": 1, "pagecount": 1, "limit": 20, "total": 1}

    def detailContent(self, ids):
        return {"list": [{"vod_id": "1", "vod_name": "PY 引擎正常", "vod_pic": "",
                          "vod_content": self._env(),
                          "vod_play_from": "probe", "vod_play_url": "测试$http://127.0.0.1/probe.m3u8"}]}

    def playerContent(self, flag, id, vipFlags=None):
        return {"parse": 0, "playUrl": "", "url": id,
                "header": {"User-Agent": "ok"}, "jx": 0, "time": 0}
