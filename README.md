# chrome-browser

> 本机唯一浏览器操作技能：用固定登录态的常驻 Chrome + CDP 调试端口，接管一切浏览器自动化任务。

## 简介

chrome-browser 是一个 WorkBuddy / Claude Code 技能（Skill），为本机所有浏览器自动化需求提供唯一、标准的操作通道：打开网页、截图、抓取动态页面、登录态操作、发帖、后台管理、投放、验证线上页面等，一律通过本技能完成，禁止另起 Playwright / agent-browser / edge-browser 等其他浏览器方案。

它解决的核心问题是：**AI Agent 沙盒里启动的浏览器会在命令结束时被系统回收**（Windows job object 机制），导致登录态和调试连接无法保留。本技能通过「桌面资源管理器间接拉起常驻 Chrome + 固定登录态目录 + CDP 调试端口」的组合，让浏览器实例长期挂着、登录一次永久有效、Agent 随时接管。

适合：需要在 Windows 本机做浏览器自动化的 WorkBuddy / Claude Code 用户，尤其是需要保持网站登录态、反复采集页面数据、操作各类后台的场景。

## 功能特性

- **唯一通道约定**：所有浏览器操作只走本技能的 Google Chrome 实例，避免多个浏览器方案互相打架、登录态分散。
- **常驻浏览器机制**：通过 `explorer.exe` 间接拉起 Chrome（父进程是资源管理器而非沙盒进程），浏览器在 Agent 命令结束后不被系统回收，可一直挂着。
- **端口自动降级**：调试端口优先 9222，被占用时自动降级 9233 → 9244（实测 WorkBuddy.exe 自己会监听 127.0.0.1:9222，该降级逻辑是必需的）。
- **固定登录态目录**：用户数据目录固定为 `C:\Users\Administrator\WorkBuddy\chrome-cdp-profile`，Cookie / 登录态持久保存，浏览器关了再开也不丢登录，登录一次永久有效。
- **Playwright 接管**：Agent 用 `playwright.chromium.connect_over_cdp()` 连上已运行的 Chrome 实例进行操作，复用现有标签页与登录态。
- **一键自检脚本**：`scripts/chrome_browser.py` 自动完成端口探测、实例拉起、连接验证，一条命令确认环境就绪。
- **通用页面采集器**：`scripts/scrape.py` 连接常驻 Chrome → 打开网址 → 登录态检测 → 执行自定义 JS 抽取脚本 → 落盘 JSON + CSV（utf-8-sig，Excel 直接打开不乱码）。
- **登录态失效防护**：采集时自动检测是否被跳转到登录页（命中 login / signin / 登录 / 验证身份 / passport 等特征串），失效则本轮不落盘数据、写告警日志并以退出码 2 返回，绝不把登录页当数据。
- **明确的退出码约定**：0 成功；1 执行失败；2 登录态失效（需人工重新登录）；3 没有可连的调试浏览器。

## 工作原理 / 技术栈

- **Chrome DevTools Protocol (CDP)**：Chrome 以 `--remote-debugging-port` 启动后暴露 HTTP 调试接口（`/json/version` 等），Playwright 通过 `connect_over_cdp("http://127.0.0.1:<port>")` 接管整个浏览器实例。
- **Windows 进程树与沙盒回收**：Agent 沙盒以 job object 运行，其直接子进程会在命令结束时被一并回收；由 `explorer.exe`（桌面双击或间接调用）拉起的进程父进程是资源管理器，不受回收影响。
- **分离进程启动**：`launcher/chrome_launcher.py` 使用 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` 标志启动 Chrome，stdin/stdout/stderr 全部指向 DEVNULL，彻底脱离调用方生命周期。
- **技术栈**：Python 3、`playwright`（连接与操作）、`requests`（CDP 端口探测）、标准库（socket / subprocess / ctypes / argparse / csv / json）。

## 安装与使用

### 安装技能

将整个仓库目录复制到技能目录：

```bash
# WorkBuddy / CodeBuddy（用户级）
cp -r chrome-browser ~/.workbuddy/skills/

# 或 Claude Code
cp -r chrome-browser ~/.claude/skills/
```

项目级使用则复制到项目的 `.workbuddy/skills/` 目录。依赖安装：`pip install playwright requests`。

### 标准流程

1. **先跑自检脚本**（自动探测端口、必要时拉起实例、验证连接）：

   ```bash
   python scripts/chrome_browser.py
   ```

2. **Agent 用 Playwright 连接常驻实例**：

   ```python
   from playwright.sync_api import sync_playwright

   with sync_playwright() as pw:
       browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
       context = browser.contexts[0] if browser.contexts else browser.new_context()
       page = context.pages[0] if context.pages else context.new_page()
       page.goto("https://example.com")
       # ... 操作页面 ...
       # 绝不调用 browser.close()——浏览器是常驻的，关掉就全没了
   ```

3. **页面数据采集**（scrape.py）：

   ```bash
   python scripts/scrape.py --url "<网址>" --extract extract.js --out "<数据目录>"
   python scripts/scrape.py --url "<网址>" --extract extract.js --out data --name 价格 --wait 8
   python scripts/scrape.py --url "<网址>" --extract extract.js --out data --login-marker "重新登录"
   ```

   输出结构：`<out>/<任务名>/<YYYY-MM-DD>/data-<HHMMSS>.json`（机读）+ 同名 `.csv`（人读）+ `login-expiry.log`（登录过期告警）。

### 首次使用

在常驻 Chrome 里手动登录目标网站一次（登录态目录固定，下次自动恢复）；如需桌面双击启动器，可用 `launcher/chrome_launcher.py` 打包为 exe（打包命令见该目录 build.txt 说明）。

## 项目结构

```
chrome-browser/
├── SKILL.md                      # 技能定义（frontmatter + 三条铁律 + 标准流程）
├── README.md                     # 本文件（中文详细版）
├── README_EN.md                  # 英文详细版
├── launcher/
│   └── chrome_launcher.py        # 常驻浏览器启动器源码（可打包为桌面双击 exe）
└── scripts/
    ├── chrome_browser.py         # 环境自检脚本：端口探测 / 拉起实例 / 连接验证
    └── scrape.py                 # 通用页面采集器：登录态检测 + JS 抽取 + JSON/CSV 落盘
```

## 注意事项

- **平台限定**：目前为 Windows 设计，Chrome 路径硬编码为 `C:\Program Files\Google\Chrome\Application\chrome.exe`，登录态目录硬编码为 `C:\Users\Administrator\WorkBuddy\chrome-cdp-profile`，换机器需对应调整。
- **绝不调用 `browser.close()`**：浏览器是常驻共享实例，关闭后所有登录态会话和后续任务都会中断；操作完只关自己开的 page 或干脆不关。
- **9222 端口冲突**：WorkBuddy.exe 自身会监听 127.0.0.1:9222 并返回 401，这不是 Chrome——务必走自动降级逻辑，连不上时先跑自检脚本确认真实端口。
- **禁止另起方案**：不要使用 agent-browser / playwright-cli / edge-browser 等其他浏览器技能，不要新建临时 profile，不要换调试端口约定。
- **登录态失效处理**：scrape.py 返回退出码 2 时，在常驻 Chrome 里手动重新登录该站点一次即可，不要尝试绕过登录页抓数据。
- **依赖**：需要本机已安装 Google Chrome，Python 环境需有 `playwright` 和 `requests`。

## License

MIT

## 作者

sheen945
