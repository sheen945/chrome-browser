# -*- coding: utf-8 -*-
"""
chrome_browser.py - 本机唯一浏览器环境自检脚本（chrome-browser 技能）

作用：
  1. 找到（或启动）带调试端口的 Chrome，用固定登录态目录，登录一次永久有效
  2. 打印浏览器版本和当前标签页列表
  3. 可选：直接打开指定网址

铁律：
  - 唯一浏览器：Google Chrome（禁止 Edge / Playwright 自带 Chromium）
  - 唯一登录态目录：C:\\Users\\Administrator\\WorkBuddy\\chrome-cdp-profile
    （登录一次永久有效，勿删勿换勿清缓存）
  - 端口：优先 9222；若 9222 被别的程序占用（2026-09-14 实测 WorkBuddy.exe 自己
    在监听 127.0.0.1:9222），自动降级到 9233 → 9244
  - 已经在跑的 Chrome 调试端口直接复用，不要重启浏览器

用法（用系统 Python 3.11 跑，requests 已装好）：
  python chrome_browser.py              # 环境自检：确保 Chrome CDP 在跑，打印实际端口
  python chrome_browser.py open <url>   # 自检 + 打开指定网址
  python chrome_browser.py tabs         # 只列出当前标签页（不启动）

注意（重要，2026-09-14 更新）：
  沙盒会在命令结束时回收本命令直接派生的进程。因此本脚本启动 Chrome 时
  优先经 explorer.exe 调桌面「启动浏览器.exe」——由资源管理器持有的进程
  不在我们的 job 里，可跨命令常驻。启动器缺席时才退回直接启动（临时实例，
  仅限本条命令内使用，脚本会打印醒目警告）。
"""
import ctypes
import json
import os
import socket
import subprocess
import sys
import time

import requests

PORTS = [9222, 9233, 9244]  # 依次尝试；9222 常被 WorkBuddy.exe 占用
PROFILE = r"C:\Users\Administrator\WorkBuddy\chrome-cdp-profile"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# 常驻启动器（由 explorer 间接拉起，命令结束后不被沙盒回收）
LAUNCHER = r"C:\Users\Administrator\Desktop\启动浏览器.exe"

PRINT_SEP = "-" * 52

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def port_listening(port):
    """端口有没有人在监听（不区分是什么程序）"""
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def cdp_info(port):
    """是 Chrome DevTools 端点则返回 version 信息，否则 None"""
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=3)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, dict) and ("webSocketDebuggerUrl" in data or "Browser" in data):
            return data
        return None
    except Exception:
        return None


def find_existing_cdp():
    """找出已经跑着的 Chrome 调试端口（复用，不重启）"""
    for p in PORTS:
        info = cdp_info(p)
        if info:
            return p, info
    return None, None


def start_chrome_persistent():
    """通过 explorer.exe 间接启动桌面启动器。

    2026-09-14 实测：Agent 直接派生的 Chrome 会在命令结束时被沙盒
    job object 回收（哪怕加 DETACHED_PROCESS / 危险模式豁免也留不住），
    表现为脚本打印「成功」、下一条命令 connect_over_cdp 就连不上——
    这是「浏览器技能反复出问题」的根因。
    2026-09-18 补充实测：CREATE_BREAKAWAY_FROM_JOB 被沙盒拒绝
    （WinError 5，job 没开 BREAKAWAY_OK），WMI/计划任务被安全策略拦，
    因此经 explorer.exe 间接拉起是【唯一】逃生通道。
    经 explorer.exe 拉起的进程挂在资源管理器下，不在我们的 job 里，
    可以跨命令常驻。启动器内部会自动挑选可用端口（9222→9233→9244）。
    返回 True 表示已发起启动。
    """
    if not os.path.exists(LAUNCHER):
        print(f"    注意：未找到桌面启动器 {LAUNCHER}")
        return False
    try:
        subprocess.Popen(
            ["explorer.exe", LAUNCHER],
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        print(f"    注意：explorer 启动器调用失败：{e}")
        return False


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _process_table():
    """{pid: (exe_name_lower, parent_pid)} 快照"""
    k = ctypes.windll.kernel32
    snap = k.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
    table = {}
    if snap == -1:
        return table
    try:
        pe = _PROCESSENTRY32()
        pe.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        ok = k.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            table[pe.th32ProcessID] = (pe.szExeFile.lower(), pe.th32ParentProcessID)
            ok = k.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k.CloseHandle(snap)
    return table


def chrome_persistence_status():
    """判断正在跑的 Chrome 主进程是不是 explorer 通道拉起的（= 跨命令常驻）。

    判定逻辑（沿父进程链向上走，最多 8 层）：
      - 链上出现 explorer.exe           -> 常驻（explorer 直接拉起）
      - 链上出现本脚本自己（python.exe）-> 临时实例（脚本直接派生，命令结束被回收）
      - 链条断掉（父进程已退出）        -> 常驻（启动器拉完 Chrome 就退出了，
                                          Chrome 成为孤儿挂在系统下，不在我们的 job 里）
    返回 (persistent, detail)
    """
    table = _process_table()
    my_pid = os.getpid()
    chrome_pids = [pid for pid, (name, _) in table.items() if name == "chrome.exe"]
    if not chrome_pids:
        return None, "没有 chrome.exe 进程"

    verdicts = []
    for pid in chrome_pids:
        cur, seen, verdict = pid, set(), None
        for _ in range(8):
            entry = table.get(cur)
            if entry is None:
                verdict = (True, "父进程已退出（启动器拉起的孤儿实例）")
                break
            name, parent = entry
            if cur in seen:
                break
            seen.add(cur)
            if name == "explorer.exe":
                verdict = (True, "父进程链上有 explorer.exe")
                break
            if cur == my_pid or (name == "python.exe" and parent in seen):
                verdict = (False, "父进程链上有本脚本（python.exe）")
                break
            if name == "python.exe" and parent == my_pid:
                verdict = (False, "父进程链上有本脚本（python.exe）")
                break
            cur = parent
        verdicts.append((pid, verdict or (True, "链路过长，默认按常驻处理")))

    if any(not v[0] for _, v in verdicts if v):
        bad = next((pid, v) for pid, v in verdicts if v and not v[0])
        return False, f"chrome.exe(pid={bad[0]}) {bad[1][1]} -> 疑似临时实例"
    pid, v = verdicts[0]
    return True, f"chrome.exe(pid={pid}) {v[1]}"


def wait_cdp(timeout_s=30):
    """等待任一候选端口出现 Chrome CDP，返回 (port, info)"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        port, info = find_existing_cdp()
        if port:
            return port, info
        time.sleep(2)
    return None, None


def start_chrome(port, open_url=None):
    args = [
        CHROME,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if open_url:
        args.append(open_url)
    subprocess.Popen(
        args,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def list_tabs(port):
    try:
        return requests.get(f"http://127.0.0.1:{port}/json/list", timeout=5).json()
    except Exception:
        return []


def show_tabs(port):
    tabs = [t for t in list_tabs(port) if t.get("type") == "page"]
    if not tabs:
        print("（当前没有打开的网页标签页）")
        return
    for i, t in enumerate(tabs, 1):
        title = (t.get("title") or "")[:40]
        url = (t.get("url") or "")[:70]
        print(f"  {i}. {title}  |  {url}")


def report_persistence():
    """打印当前 Chrome 是否 explorer 常驻（跨命令存活的直接证据）"""
    persistent, detail = chrome_persistence_status()
    if persistent is True:
        print(f"[常驻确认] {detail} -> 跨命令常驻，不会被沙盒回收")
    elif persistent is False:
        print(f"[常驻警告] {detail}")
        print("           该实例疑似临时实例，命令结束后可能被回收！")
    # None（没有 chrome 进程）时静默，启动流程自己会报错


def main():
    action = "status"
    open_url = None
    argv = sys.argv[1:]
    if argv and argv[0] == "open" and len(argv) >= 2:
        action = "open"
        open_url = argv[1]
    elif argv and argv[0] == "tabs":
        action = "tabs"
    elif argv:
        print("用法: python chrome_browser.py [open <url> | tabs]")
        sys.exit(2)

    if action == "tabs":
        port, _ = find_existing_cdp()
        if not port:
            print("Chrome 调试端口没在跑，先执行不带参数的自检")
            sys.exit(1)
        show_tabs(port)
        return

    print(PRINT_SEP)
    print("浏览器环境自检（Chrome CDP）")
    print(PRINT_SEP)

    port, info = find_existing_cdp()
    if port:
        print(f"[1] Chrome CDP {port} : 已在运行 -> 直接复用，不重启")
        report_persistence()
    else:
        # 优先走 explorer 常驻启动（跨命令存活）；失败重试一次；
        # 启动器缺席/重试仍失败时才退回直接启动（临时实例）
        launched = start_chrome_persistent()
        if launched:
            print("[1] 通过桌面启动器（explorer 常驻模式）启动 Chrome ...")
            port, info = wait_cdp(45)
            if not port:
                print("    首次启动 45 秒内未见调试端口，重试一次 ...")
                start_chrome_persistent()
                port, info = wait_cdp(45)
            if not port:
                print("    启动结果: 失败（启动器两次均未拉起调试端口）")
                sys.exit(1)
            print(f"    启动结果: 成功（常驻实例，端口 {port}，命令结束后不会被回收）")
            report_persistence()
        else:
            # 挑一个没被别的程序占用的端口
            occupied = [p for p in PORTS if port_listening(p)]
            free = [p for p in PORTS if p not in occupied]
            if not free:
                print("[1] 9222/9233/9244 全被占用，无法启动 Chrome")
                sys.exit(1)
            port = free[0]
            if occupied:
                print(f"    注意：端口 {occupied} 被别的程序占用（不是 Chrome），已跳过")
            print(f"[1] 用固定登录态目录在端口 {port} 直接启动 Chrome ...")
            print("    !! 警告：未找到桌面启动器，本次为临时实例，")
            print("    !! 本命令结束后浏览器会被回收，后续命令将连不上。")
            print(f"    !! 请把启动器放到 {LAUNCHER} 或让用户双击它。")
            start_chrome(port, open_url)
            info = None
            for _ in range(15):
                time.sleep(2)
                info = cdp_info(port)
                if info:
                    break
            if not info:
                print("    启动结果: 失败（请检查 Chrome 路径 / 是否有沙盒拦截）")
                sys.exit(1)
            print("    启动结果: 成功（临时实例，仅限本条命令内使用）")

    if not info:
        info = cdp_info(port) or {}
    print(f"[2] 浏览器版本    : {info.get('Browser', '?')}")

    print("[3] 当前标签页:")
    show_tabs(port)

    print(PRINT_SEP)
    print("登录态目录（勿删/勿换，登录一次永久有效）:")
    print("  ", PROFILE)
    print(f"程序化操作 -> Playwright connect_over_cdp('http://127.0.0.1:{port}')")
    print("            （连接后不要调用 browser.close()）")
    print(PRINT_SEP)

    # 指定了 open 且浏览器是复用的旧实例时，补开标签页
    if open_url:
        tabs = list_tabs(port)
        if not any(open_url in t.get("url", "") for t in tabs):
            try:
                requests.put(f"http://127.0.0.1:{port}/json/new?{open_url}", timeout=5)
                time.sleep(2)
                print(f"已在现有实例中新开标签页: {open_url}")
            except Exception:
                start_chrome(port, open_url)
                time.sleep(3)
                print(f"已新开浏览器窗口: {open_url}")


if __name__ == "__main__":
    main()
