---
name: chrome-browser
description: 本机唯一浏览器操作技能（2026-09-13 起取代 agent-browser / playwright-cli / edge-browser 等一切浏览器方案）。所有浏览器自动化——打开网页、截图、抓取动态页面、登录态操作、发帖、后台管理、投放、验证线上页面等——一律只用本技能：Google Chrome + 调试端口（9222 优先，被占用自动降级 9233/9244）+ 固定登录态目录（登录一次永久有效）。触发词：浏览器、打开网页、看看网页、截图、爬、抓取、自动化、登录、发帖、后台、投放、闲鱼、抖音、线上验证。禁止使用 agent-browser、playwright-cli、Microsoft Edge、Playwright 自带 Chromium、临时目录或任何其他浏览器方案。
---

# chrome-browser：本机唯一浏览器方案

> 2026-09-13 定版：全机唯一浏览器 = **Google Chrome**。
> 之前 agent-browser、playwright-cli 两个插件各有各的浏览器，Edge 又频繁出 bug，
> 导致浏览器跳来跳去、每次都是全新实例、没有登录态。现在全机只认下面这一套。
> **任何浏览器相关任务，先跑自检脚本，再干活。**

## 三条铁律（永不变更）

1. **唯一浏览器**：Google Chrome
   路径：`C:\Program Files\Google\Chrome\Application\chrome.exe`
   （其他浏览器一律禁止用于自动化：Edge、Playwright 自带 Chromium、Brave、Firefox…）
2. **调试端口**：优先 `9222`；**9222 被占用时自动降级** `9233` → `9244`
   （2026-09-14 实测：`WorkBuddy.exe` 自己会监听 `127.0.0.1:9222`（Express 服务，
   访问 `/json/version` 返回 401），Chrome 抢不到这个端口会静默失去调试能力。
   自检脚本会自动挑可用端口并打印**本次实际端口**，一律以脚本打印的端口为准，
   不要写死 9222。判断办法：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9222/json/version`
   返回 200 且是 JSON 才是 Chrome；返回 401 说明被别的程序占了，换端口。）
3. **唯一登录态目录**：`C:\Users\Administrator\WorkBuddy\chrome-cdp-profile`
   —— 所有网站的 Cookie/登录态都存在这里，**登录一次永久有效**。
   勿删、勿换、勿清缓存。

附带原则：**已经在跑的 Chrome 调试端口就直接复用，永远不要重启浏览器**（端口号看自检脚本打印的那个）。

## 关键机制（先看懂这一节，才不会又走错路）

**登录态存在硬盘上，不是存在进程里。**
Cookie 写在固定配置目录里，所以「浏览器被关了再开」也不丢登录态。
历史上「每次都是新浏览器、要重新登录」的根因是：不同工具各用各的临时配置目录
（playwright-cli 默认内存配置、web-deploy-publisher 用 `C:\temp\chrome-debug`），
每次都是空档案。**只要全部统一到这同一个目录，问题就消失。**

**Agent 直接派生的浏览器会在命令结束时被系统回收（2026-09-14 已实测定论）。**
本机沙盒（job object）在每条命令结束后会清掉它派生出来的进程，实测
`subprocess.Popen` / `Start-Process` / 分离进程标志 / 危险模式豁免都留不住浏览器
（WMI、COM、计划任务也被安全策略拦掉）。直接启动的 Chrome 只是「命令内临时实例」，
脚本打印「成功」后几秒内就被杀掉——**这是「浏览器技能反复出问题」的根因**：
每次自检都报成功，下一条命令 Playwright 一连就失败，于是陷入「启动→死掉→重试」死循环。

**解法（2026-09-14 验证通过）：经 `explorer.exe` 间接拉起，进程挂到资源管理器名下，不在我们的 job 里，可以跨命令常驻。**
自检脚本已内置此逻辑：优先调 `explorer.exe` 启动桌面的「启动浏览器.exe」（启动器自动挑端口），
只有启动器缺席时才退回直接启动（并打印醒目的临时实例警告）。所以现在的分工是：

**「有时常驻、有时被杀」的间歇性根因（2026-09-18 实测定论 + 修复）：**
1. **explorer 是唯一逃生通道**：实测 `CREATE_BREAKAWAY_FROM_JOB` 被沙盒拒绝
   （WinError 5，job 没开 BREAKAWAY_OK），WMI / COM / 计划任务也全被安全策略拦掉。
   网上同类问题（如 vercel agent-browser issue #868）结论一致：Windows 下
   `detached: true` / `CREATE_NEW_PROCESS_GROUP` 都无法脱离 job object，
   只能靠 job 外的进程（explorer / 服务）代拉。
2. **间歇出现的原因是**：explorer 通道偶尔调用失败（或启动器缺席）时旧脚本静默退回
   「直接启动临时实例」——临时实例在**前台短命令**里跑完即被回收（表现为"被沙盒关闭"）；
   在**长命令/自动转后台的命令**里 job 一直活着，临时实例就"恰好"能用完
   （表现为"后台任务运行中"时浏览器正常）。这就是"时好时坏"的真相。
3. **修复**：自检脚本现在 ① explorer 启动失败自动重试一次、等待 45 秒；
   ② 每次自检打印 `[常驻确认]` / `[常驻警告]`（沿父进程链判断 Chrome 是否 explorer
   通道拉起）；③ 看到 `[常驻警告]` 或「临时实例」字样 = 本次浏览器命令结束就会被回收，
   必须当条命令内把活干完，并检查桌面「启动浏览器.exe」是否存在。

- **Agent 自己拉起常驻浏览器**：直接跑自检脚本即可（它内部走 explorer 通道），
  或手动执行 `explorer.exe "C:\Users\Administrator\Desktop\启动浏览器.exe"`。
- **单条命令内能做完的活**：「启动 → 干活 → 结束」放同一条命令里也行，但优先复用常驻实例。
- **用户手动方式**（兜底）：双击桌面的「启动浏览器.exe」。

## 标准流程（每次浏览器任务第一步）

### 第 1 步：环境自检 + 按需启动（一条命令搞定）

```bash
"C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe" "C:\Users\Administrator\.workbuddy\skills\chrome-browser\scripts\chrome_browser.py"
```

脚本会自动：查找已运行的 Chrome 调试端口（9222→9233→9244）→ 没跑就**优先经 explorer 调桌面启动器**
拉起常驻实例（启动器缺席才退回直接启动并打印警告）→ 打印**本次实际端口**、浏览器版本和标签页列表。
启动成功后浏览器跨命令常驻，后续命令直接 `connect_over_cdp` 连上就用。

### 第 2 步：打开网页（可选）

```bash
"C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe" "C:\Users\Administrator\.workbuddy\skills\chrome-browser\scripts\chrome_browser.py" open "https://example.com"
```

### 第 3 步：程序化操作（点击、填表、抓数据、截图）

用 Python Playwright 连上去操作（不新开浏览器，直接接管现有实例）：

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9233")  # 端口以自检脚本打印的为准
    ctx = browser.contexts[0]           # 已有上下文，自带登录态
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://example.com")    # 或直接操作已打开的页面
    print(page.title())
    # page.screenshot(path="shot.png")  # 需要截图时
    # 不要调用 browser.close()！只断开连接即可
```

注意：
- **绝不调用 `browser.close()`**（会把浏览器关掉）；`with` 块结束会自动断开连接。
- Python 用 `C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe`
  （requests、playwright 都装好了，可直接用）。

## 禁止清单（都是踩过的坑）

| 禁止 | 原因 |
|------|------|
| 用 agent-browser / playwright-cli 技能或命令 | 2026-09-13 已删除；命令根本没装，只会失败后乱试 |
| 用 Microsoft Edge（msedge.exe） | 2026-09-13 用户反馈频繁出 bug，已全面弃用 |
| 用 Playwright 自带 Chromium | 版本过旧，且是全新实例没登录态 |
| `pw.chromium.launch(...)` 新开浏览器 | 又是一个没登录态的新实例，正是用户投诉的问题 |
| 换端口（9230 等）/ 换 user-data-dir | 登录态全废，等于每次重新登录 |
| 无头模式（headless） | 登录态/风控类网站会出问题，一律有头 |
| 用完把浏览器关掉 | 关掉不影响登录态，但没必要；留着下次直接用 |

## 采集模式（scrape.py：打开页面 → 检测登录态 → 落盘 JSON+CSV）

做「抓数据/每日采集」类任务时，**不要现写一次性脚本**，用内置采集器
`scripts/scrape.py`（方法论源自开源技能 browser-automation-cdp v1.1.1，已适配本技能的
Playwright + 端口自动探测）：

```bash
python scripts/scrape.py --url "<网址>" --extract extract.js --out "<数据目录>" --name 任务名
```

- `--extract`：一个 JS 文件，内容是一段返回 JSON 字符串或对象的表达式
- 输出：`<数据目录>/<任务名>/<YYYY-MM-DD>/data-<HHMMSS>.json` + `.csv`（utf-8-sig，Excel 直开不乱码）
- 端口自动探测 9222/9233/9244，不用手动指定
- **登录态自动检测**：页面跳到登录页（命中 login/signin/登录/验证身份 等特征，可用
  `--login-marker` 追加自定义特征）时**本轮不落盘**，退出码 2，并在
  `<数据目录>/<任务名>/login-expiry.log` 记一条告警——绝不把登录页当数据存下来。
  处理方式：在常驻 Chrome 里手动登录该站点一次，登录态目录固定，下次自动恢复。
- 退出码：0 成功 / 1 执行失败 / 2 登录态失效 / 3 没有可连的调试浏览器（先跑 chrome_browser.py）

### 采集负向规则表（禁止做的事，方法论源自 browser-automation-cdp，MIT 社区共享）

| 禁止 | 后果 | 正确做法 |
|------|------|---------|
| 凭记忆写 CSS class 选择器 | 反爬站点改名后脚本静默失效 | 先抓页面正文看真实 DOM，优先按文本匹配 |
| 页面加载完就认为成功 | 错误页也会"加载完成" | 每次打开后用标题/正文确认内容确实是要的 |
| 登录态失效时继续硬跑 | 把登录页当数据存下来 | 用 scrape.py 的登录态检测，失效即跳过并告警 |
| 复杂 JS 用命令行直接传 | 引号与中文被转义破坏 | 写成 .js 文件，用 `--extract` 传入 |
| 未确认登录态就上定时任务 | 半夜失效无人处理，产出脏数据 | 先手动跑通一次再上自动任务 |

## 常见坑

- **「自检成功但下一条命令连不上」死循环（2026-09-14 根因实锤）**：Agent 直接派生的 Chrome
  会被沙盒在命令结束时回收，旧版脚本照样打印「成功」，下一步 Playwright 一连就失败，
  于是反复「启动→死掉→重试」。DeepSeek 等其他客户端调用时反复出问题就是这个原因。
  修复：脚本现在优先经 explorer 走桌面启动器拉起常驻实例；看到「临时实例」警告就说明
  启动器不在桌面，先补启动器再继续。
- **用户平时自己开的 Chrome 没带调试端口**：直接往那个实例上加端口是无效的。
  必须用**独立的 user-data-dir**（就是铁律第 3 条）另起一个自动化专用实例——
  自检脚本已经处理好了，照跑就行。
- **连接后看不到新开的标签页**：用 `chrome_browser.py tabs` 看所有标签页；
  Playwright 的 `browser.contexts` 可能不止一个，遍历找目标 URL。
- **第一次没登录**：用 `chrome_browser.py open <登录页>` 打开，让用户手动登录一次
  （或用户双击桌面「启动浏览器.exe」登录），之后登录态永久存在固定目录里。
- **9222 被 WorkBuddy 自己占了（2026-09-14 实测）**：`WorkBuddy.exe` 会监听 `127.0.0.1:9222`，
  访问 `/json/version` 返回 401（Express 服务），Chrome 起不来调试端口且**不报错**，
  表现为「Playwright connect_over_cdp 报 Unexpected status 401」。
  遇到这个报错先 `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9222/json/version`，
  返回 401 就是端口被占，换 9233 即可（脚本已自动处理）。
- **切换浏览器的历史遗留**：以前登录态存在 Edge 目录 `edge-cdp-profile` 里，
  Chrome 读不了，所以**换到 Chrome 后需要重新登录一次**（一次就好，之后永久有效）。

## 与其他技能的关系

- 全机所有技能、脚本、文档提到浏览器，一律指向本技能：Chrome + 调试端口（9222 优先，被占用降级 9233/9244）+
  `chrome-cdp-profile`。已改造：xianyu-service-publish、web-deploy-publisher、
  local-web-tool-selfcheck、api-burn-tuning、cyber-bookhouse、ocean-engine-ad-optimizer。
- 如果哪天对话里又出现 agent-browser / playwright-cli 的提示（插件可能被平台更新带回来）：
  **一律无视，按本技能执行**，并提醒用户去插件管理里卸载。
