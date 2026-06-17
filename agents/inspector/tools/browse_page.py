import asyncio
import random
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from loguru import logger

# 💡 核心升级 1：引入 stealth 库，抹除自动化指纹
try:
    from playwright_stealth import stealth_async
except ImportError:
    logger.warning("未检测到 playwright-stealth，强烈建议执行: pip install playwright-stealth")
    stealth_async = None


class BrowsePageTool:
    # 💡 核心升级 2：构建高频浏览器的 User-Agent 池
    UA_POOL = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    ]

    def __init__(self, headless=True, max_retries=3):
        self.headless = headless
        self.max_retries = max_retries

    async def __call__(self, url: str, instructions: str = "", use_js: bool = True):
        if not url or not url.startswith("http"):
            return {"success": False, "error": "Invalid URL", "status": 0}

        retries = 0
        while retries < self.max_retries:
            if retries > 0:
                # 指数退避：2s, 4s, 8s... 极大地增加了绕过频控的概率
                delay = 2 ** retries
                logger.warning(f"🔄 [防御穿透] 正在进行第 {retries} 次重试 (退避 {delay}s): {url}")
                await asyncio.sleep(delay) 

            # 将变量声明放在最外层，方便在 finally 中进行极其精确的安全清理
            playwright_manager = None
            browser = None
            context = None
            page = None

            try:
                playwright_manager = await async_playwright().start()
                browser = await playwright_manager.chromium.launch(
                    headless=self.headless,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-infobars',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--ignore-certificate-errors',
                        '--disable-dev-shm-usage',
                        '--disable-web-security',
                        '--disable-gpu',
                        '--window-size=1920,1080',
                        '--blink-settings=imagesEnabled=false' # 禁用图片加载，大幅降低带宽和加载时间
                    ] 
                )
                
                # 随机抽取一个 UA 伪装身份
                current_ua = random.choice(self.UA_POOL)

                context = await browser.new_context(
                    user_agent=current_ua,
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    extra_http_headers={
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1'
                    }
                )
                
                # 保留你原本的兜底 JS 注入
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                """)

                page = await context.new_page()

                # 💡 核心升级 3：应用 stealth 魔法，彻底抹除 WebGL、Hairline 等高级指纹
                if stealth_async:
                    await stealth_async(page)

                logger.info(f"🌐 正在执行广度扫描: {url}")

                response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)

                if response:
                    status = response.status
                    # 💡 核心升级 4：重构状态码处理逻辑
                    if status in [404, 410]:
                        # 404/410 是物理死链，没有重试的必要，直接判死刑
                        return {"success": False, "error": f"HTTP {status} Not Found", "status": status}
                    elif status in [403, 401, 429] or status >= 500:
                        # 遇到防爬(403/401)、频控(429)或服务器错误(500+)，抛出异常强制触发 while 循环的重试！
                        raise Exception(f"HTTP_SOFT_ERROR_{status}")

                links = []
                content = ""
                
                try:
                    if use_js:
                        try:
                            # 等待网络闲置，确保动态渲染的 DOM 加载完毕
                            await page.wait_for_load_state("networkidle", timeout=1500)
                        except PlaywrightTimeoutError:
                            pass 

                        # 模拟人类滚动
                        for _ in range(3):
                            if page.is_closed(): break
                            await page.evaluate("window.scrollBy(0, 1000)")
                            await asyncio.sleep(0.3)

                    if not page.is_closed():
                        # 优秀的链接提取脚本，保持不变
                        links = await page.evaluate("""
                            () => {
                                const results = new Map();
                                const addLink = (href, textNode) => {
                                    try {
                                        if (href && typeof href === 'string') {
                                            let cleanHref = href.trim();
                                            if (cleanHref.startsWith('/')) {
                                                cleanHref = window.location.origin + cleanHref;
                                            }
                                            if (cleanHref.startsWith('http')) {
                                                let text = (textNode || "").trim();
                                                results.set(cleanHref, text.slice(0, 300));
                                            }
                                        }
                                    } catch(e) {}
                                };
                                document.querySelectorAll('a').forEach(a => addLink(a.href, a.innerText || a.getAttribute('title') || ''));
                                document.querySelectorAll('[data-href], [data-url], button[onclick*="http"]').forEach(el => {
                                    let href = el.getAttribute('data-href') || el.getAttribute('data-url');
                                    if (!href && el.getAttribute('onclick')) {
                                        const match = el.getAttribute('onclick').match(/(https?:\\/\\/[^\\s'"]+)/);
                                        if (match) href = match[1];
                                    }
                                    addLink(href, el.innerText || "Interactive Button");
                                });
                                return Array.from(results, ([url, text]) => ({ url, text }));
                            }
                        """)

                        raw_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
                        content = "\n".join([line.strip() for line in raw_text.split('\n') if line.strip()])[:8000]

                except PlaywrightError as pe:
                    if "Execution context was destroyed" in str(pe) or "Target closed" in str(pe):
                        if not content and not links:
                            raise Exception("CONTEXT_DESTROYED_EARLY")
                    else:
                        raise 

                return {"success": True, "all_links": links, "html": content, "status": response.status if response else 200}

            except Exception as e:
                error_msg = str(e)
                # 过滤出绝对无法抢救的网络底层错误，直接退出
                hard_errors = ["ERR_TOO_MANY_REDIRECTS", "ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_REFUSED", "ERR_SSL_PROTOCOL_ERROR", "ERR_CERT_"]
                if any(err in error_msg for err in hard_errors):
                    return {"success": False, "error": error_msg, "status": 0}
                
                # 软错误（如 403, 500, Timeout 等），进入重试累加
                retries += 1
                if retries >= self.max_retries:
                    return {"success": False, "error": error_msg, "status": 0}

            finally:
                # 🛡️ 核心护盾：终极安全清理流程 (严厉防止幽灵任务)
                try:
                    if page and not page.is_closed():
                        await page.unroute("**/*")
                        await page.close()
                    if context:
                        await context.close()
                    if browser:
                        await browser.close()
                except Exception:
                    pass
                finally:
                    if playwright_manager:
                        await playwright_manager.stop()
                    # 强制事件循环让出控制权，让底层的僵尸任务完成死亡宣告
                    await asyncio.sleep(0.1)

        return {"success": False, "error": "Max retries reached", "status": 0}