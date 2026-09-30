#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape.py —— 通用页面采集：连上常驻 Chrome → 打开网址 → 登录态检测 → 执行抽取脚本 → 落盘 JSON + CSV。

采集方法论源自开源技能 browser-automation-cdp（v1.1.1），已适配本技能的 Playwright + 端口自动探测方案。

用法：
    python scripts/scrape.py --url "<网址>" --extract extract.js --out "<数据目录>"
    python scripts/scrape.py --url "<网址>" --extract extract.js --out data --name 价格 --wait 8
    python scripts/scrape.py --url "<网址>" --extract extract.js --out data --login-marker "重新登录"

参数：
    --url            目标网址（必填）
    --extract        抽取脚本路径（必填，内容为一段返回 JSON 字符串或对象的 JS 表达式）
    --out            数据输出根目录（必填）
    --name           任务名，用于区分子目录，默认 default
    --wait           导航后额外等待秒数，默认 5
    --login-marker   登录页特征串，可重复传入；默认 login / signin / 登录 / 验证身份 / passport
    --no-csv         只写 JSON

输出结构：
    <out>/<任务名>/<YYYY-MM-DD>/data-<HHMMSS>.json   机读
    <out>/<任务名>/<YYYY-MM-DD>/data-<HHMMSS>.csv    人读（utf-8-sig，Excel 直接打开不乱码）
    <out>/<任务名>/login-expiry.log                  登录过期告警

退出码：0 成功；1 执行失败；2 登录态失效（需人工重新登录，本轮不落盘）；3 没有可连的调试浏览器。
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

PORTS = [9222, 9233, 9244]
DEFAULT_MARKERS = ["login", "signin", "sign-in", "登录", "验证身份", "passport"]


def _reconfigure():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def find_cdp_port():
    """依次探测调试端口，返回第一个活着的；返回 None 表示没有可连的。"""
    for p in PORTS:
        try:
            r = requests.get(f"http://127.0.0.1:{p}/json/version", timeout=3)
            if r.status_code == 200:
                return p
        except Exception:
            pass
    return None


def write_csv(path, records):
    if not records:
        return 0
    if isinstance(records, dict):
        records = [records]
    if isinstance(records[0], dict):
        keys = []
        for r in records:
            for k in r.keys():
                if k not in keys:
                    keys.append(k)
    else:
        keys = ["value"]
        records = [{"value": r} for r in records]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in keys})
    return len(records)


def main(argv=None):
    _reconfigure()
    parser = argparse.ArgumentParser(prog="scrape.py", description="通用页面采集（Playwright + CDP）")
    parser.add_argument("--url", required=True)
    parser.add_argument("--extract", required=True, help="抽取 JS 文件路径")
    parser.add_argument("--out", required=True, help="数据输出根目录")
    parser.add_argument("--name", default="default")
    parser.add_argument("--wait", type=float, default=5.0)
    parser.add_argument("--login-marker", action="append", default=None)
    parser.add_argument("--no-csv", action="store_true")
    args = parser.parse_args(argv)

    js_path = Path(args.extract)
    if not js_path.exists():
        print(f"错误：抽取脚本不存在：{js_path}")
        return 1
    expression = js_path.read_text(encoding="utf-8")

    port = find_cdp_port()
    if port is None:
        print("CDP 不可达：9222/9233/9244 都没有调试浏览器在监听。")
        print("请先运行：python scripts/chrome_browser.py")
        return 3
    print(f"连接调试端口：{port}")

    out_root = Path(args.out) / args.name / time.strftime("%Y-%m-%d")
    out_root.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        except Exception as exc:
            print(f"连接失败：{exc}")
            return 3
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(args.url, wait_until="load", timeout=30000)
            except Exception:
                print("警告：页面 30 秒内未加载完成，仍继续尝试抽取。")
            if args.wait:
                time.sleep(args.wait)

            final_url = page.url or ""
            title = page.title() or ""
            print(f"最终 URL：{final_url}")
            print(f"页面标题：{title}")

            # 登录态检测：命中特征即本轮跳过，绝不把登录页当数据
            markers = args.login_marker or DEFAULT_MARKERS
            body_head = ""
            try:
                body_head = page.evaluate(
                    "() => (document.body ? document.body.innerText : '').slice(0, 1500)"
                ) or ""
            except Exception:
                pass
            haystack = (final_url + " " + title + " " + body_head).lower()
            hit = [m for m in markers if m.lower() in haystack]
            if hit:
                log_path = Path(args.out) / args.name / "login-expiry.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write("%s\t登录态失效\t命中特征=%s\tURL=%s\n" % (
                        time.strftime("%Y-%m-%d %H:%M:%S"), ",".join(hit), final_url))
                print(f"LOGIN_EXPIRED：疑似跳转到登录页（命中：{','.join(hit)}）。本轮不落盘数据。")
                print("处理方式：在常驻 Chrome 里手动登录该站点一次（登录态目录固定，下次自动恢复）。")
                print(f"告警已记录：{log_path}")
                return 2

            raw = page.evaluate(expression)
            if raw is None:
                print("错误：抽取脚本未返回任何内容。请确认脚本以 return 返回字符串或对象。")
                return 1
            if isinstance(raw, str):
                try:
                    records = json.loads(raw)
                except json.JSONDecodeError:
                    records = {"text": raw}
            else:
                records = raw

            stamp = time.strftime("%H%M%S")
            json_path = out_root / f"data-{stamp}.json"
            json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"已写入：{json_path}")

            if not args.no_csv:
                csv_path = out_root / f"data-{stamp}.csv"
                n = write_csv(csv_path, records)
                print(f"已写入：{csv_path}（{n} 行）")

            count = len(records) if isinstance(records, list) else 1
            print(f"SCRAPE_OK：共 {count} 条记录。")
            return 0
        except Exception as exc:
            print(f"错误：{exc}")
            return 1


if __name__ == "__main__":
    sys.exit(main())
