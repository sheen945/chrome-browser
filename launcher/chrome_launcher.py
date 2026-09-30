# -*- coding: utf-8 -*-
"""
启动浏览器.exe 的源码
=====================
作用：双击后启动一个「带 Chrome 调试端口 + 固定登录态目录」的 Chrome 实例。
为什么需要它：由我的沙盒启动的浏览器会在命令结束时被系统回收；
由桌面双击启动的浏览器，父进程是资源管理器，不会被回收，可以一直挂着。
登录态（Cookie）存在固定目录里，所以这个实例关了再开也不丢登录态。

端口：优先 9222；9222 被别的程序占用时自动降级 9233 → 9244
（2026-09-14 实测 WorkBuddy.exe 自己会监听 127.0.0.1:9222，所以这个降级必须有）

配套技能：C:\\Users\\Administrator\\.workbuddy\\skills\\chrome-browser
打包命令：见同目录 build.txt
"""
import ctypes
import os
import socket
import subprocess
import sys

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = r"C:\Users\Administrator\WorkBuddy\chrome-cdp-profile"
START_URL = "about:blank"
PORTS = [9222, 9233, 9244]

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def message_box(text, title="启动浏览器", flags=0x40):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        pass


def port_listening(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def pick_port():
    """挑一个没人占用的端口：9222 优先，被占用就依次退到 9233 / 9244"""
    for p in PORTS:
        if not port_listening(p):
            return p
    return None


def main():
    if not os.path.exists(CHROME):
        message_box(
            "找不到 Chrome，请确认安装路径：\n" + CHROME,
            flags=0x10,
        )
        return 1

    os.makedirs(PROFILE, exist_ok=True)

    port = pick_port()
    if port is None:
        message_box(
            "端口 9222 / 9233 / 9244 都被占用了，没能启动浏览器。\n"
            "请先关掉占用端口的程序再试。",
            flags=0x10,
        )
        return 1

    args = [
        CHROME,
        "--remote-debugging-port=%d" % port,
        "--remote-allow-origins=*",
        "--user-data-dir=" + PROFILE,
        "--no-first-run",
        "--no-default-browser-check",
        START_URL,
    ]
    try:
        subprocess.Popen(
            args,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        message_box("启动 Chrome 失败：\n%s" % exc, flags=0x10)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
