"""网关那个 Chrome 窗口的显示开关。

背景：SpankBang 网关必须用「有头」Chrome 才能过 Cloudflare 质询，所以它会
常驻一个 chrome.exe（--remote-debugging-port=9335）。正常状态下这个窗口是
隐藏 + 移到屏幕外 + 标成 tool window（任务栏里看不到），所以点任务栏图标
不会有任何反应——不是卡死，是本来就不给点。

用法：
    python chrome_window.py status
    python chrome_window.py show     # 把窗口搬到屏幕中间，方便手动过验证码
    python chrome_window.py hide     # 再藏回去
    python chrome_window.py toggle
"""
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

CDP_PORT = int(os.environ.get("SB_CDP_PORT", "9335"))

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_HIDE = 0
SW_SHOWNORMAL = 1
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


def gateway_pid():
    """找出带 --remote-debugging-port=9335 的那个 chrome.exe。"""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -match '--remote-debugging-port=%d\\b' } | "
        "Select-Object -First 1 -ExpandProperty ProcessId" % CDP_PORT
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=25,
        ).stdout.strip()
    except Exception:
        return None
    return int(out) if out.isdigit() else None


def windows_of(pid):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid:
            buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, buf, 128)
            if buf.value.startswith("Chrome_WidgetWin"):
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, b, n + 1)
    return b.value


def show(hwnd):
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex = (ex & ~WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    user32.SetWindowPos(hwnd, 0, 160, 120, 1280, 900,
                        SWP_NOZORDER | SWP_SHOWWINDOW)
    user32.ShowWindow(hwnd, SW_SHOWNORMAL)
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def hide(hwnd):
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    user32.SetWindowPos(hwnd, 0, -2400, -2400, 0, 0,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
    user32.ShowWindow(hwnd, SW_HIDE)


def main():
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "toggle").lower()
    pid = gateway_pid()
    if not pid:
        print("没有找到网关的 Chrome（--remote-debugging-port=%d 那个）。"
              "网关没在跑，或者 Chrome 已经被闲置关闭了。" % CDP_PORT)
        return 1

    hs = windows_of(pid)
    if not hs:
        print("找到 chrome.exe pid=%d，但它还没有窗口（正在启动）。" % pid)
        return 1

    if cmd == "status":
        for h in hs:
            print("pid=%s hwnd=0x%x visible=%s title=%r"
                  % (pid, h, bool(user32.IsWindowVisible(h)), title(h)[:70]))
        return 0

    if cmd == "show":
        for h in hs:
            show(h)
        print("已显示（pid=%d，%d 个窗口）——Alt+Tab 或点任务栏就能看到它。" % (pid, len(hs)))
    elif cmd == "hide":
        for h in hs:
            hide(h)
        print("已隐藏（pid=%d）——任务栏里不会再出现它。" % pid)
    else:
        visible = any(bool(user32.IsWindowVisible(h)) for h in hs)
        for h in (hs if not visible else hs):
            hide(h) if visible else show(h)
        print("已切换为「%s」" % ("隐藏" if visible else "显示"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
