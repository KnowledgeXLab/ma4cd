import asyncio
import os
import random
import time
from urllib.parse import urlparse
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
        self.total_timeout_sec = float(os.getenv("MA4CD_BROWSE_TOTAL_TIMEOUT", "90"))
        self.attempt_timeout_sec = float(os.getenv("MA4CD_BROWSE_ATTEMPT_TIMEOUT", "45"))

    @staticmethod
    async def _safe_teardown(page, context, browser, playwright_manager) -> None:
        """Best-effort cleanup; must not block on CancelledError / Target closed."""
        async def _close() -> None:
            if page:
                try:
                    if not page.is_closed():
                        await page.close()
                except (PlaywrightError, asyncio.CancelledError):
                    pass
            if context:
                try:
                    await context.close()
                except (PlaywrightError, asyncio.CancelledError):
                    pass
            if browser:
                try:
                    await browser.close()
                except (PlaywrightError, asyncio.CancelledError):
                    pass
            if playwright_manager:
                try:
                    await playwright_manager.stop()
                except (PlaywrightError, asyncio.CancelledError):
                    pass

        try:
            await asyncio.wait_for(_close(), timeout=8.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass

    async def browse_resilient(self, url: str, instructions: str = "", use_js: bool = True):
        """
        Normalize known-bad hosts, browse, and on DTIC 403 try discover.dtic.mil fallbacks.
        """
        from agents.miner.tools.browse_url_resolve import (
            dtic_403_fallback_urls,
            is_dtic_host,
            is_noise_browse_url,
            normalize_browse_url,
            should_attempt_dtic_fallback,
        )

        if is_noise_browse_url(url):
            logger.warning(f"⏭️ [Browse] 跳过噪声/探针 URL: {url}")
            return {
                "success": False,
                "error": "skipped_noise_url",
                "status": 0,
                "requested_url": url,
                "browse_url": url,
            }

        original_url = url
        resolved_url, remapped = normalize_browse_url(url)
        if remapped:
            logger.info(f"🔗 [Browse] 域名映射: {original_url} -> {resolved_url}")

        tried = set()
        queue = [resolved_url]
        last_result = {"success": False, "error": "No browse attempt", "status": 0}
        deadline = time.monotonic() + self.total_timeout_sec

        while queue:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    f"⏱️ [Browse] 总超时 ({self.total_timeout_sec}s)，放弃: {original_url}"
                )
                break

            attempt_url = queue.pop(0)
            if attempt_url in tried:
                continue
            tried.add(attempt_url)

            try:
                result = await asyncio.wait_for(
                    self(url=attempt_url, instructions=instructions, use_js=use_js),
                    timeout=min(remaining, self.attempt_timeout_sec),
                )
            except asyncio.TimeoutError:
                result = {
                    "success": False,
                    "error": f"browse_attempt_timeout_{self.attempt_timeout_sec}s",
                    "status": 0,
                }
            except asyncio.CancelledError:
                raise

            result["requested_url"] = original_url
            result["browse_url"] = attempt_url
            if remapped and attempt_url == resolved_url:
                result["host_remapped_from"] = urlparse(original_url).netloc

            if result.get("success"):
                if attempt_url != resolved_url:
                    logger.info(
                        f"✅ [Browse] DTIC 回退成功: {original_url} -> {attempt_url}"
                    )
                return result

            last_result = result
            if should_attempt_dtic_fallback(result) and is_dtic_host(resolved_url):
                for fallback in dtic_403_fallback_urls(resolved_url):
                    if fallback not in tried and fallback not in queue:
                        queue.append(fallback)

        last_result["requested_url"] = original_url
        last_result["browse_url"] = resolved_url
        if should_attempt_dtic_fallback(last_result):
            last_result["access_denied"] = True
        return last_result

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
                await self._safe_teardown(page, context, browser, playwright_manager)
                await asyncio.sleep(0.05)

        return {"success": False, "error": "Max retries reached", "status": 0}

'''
import asyncio
import random
import html2text
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
        # 初始化 html2text 转换器配置
        self.html_cleaner = html2text.HTML2Text()
        self.html_cleaner.ignore_links = False    # 🚨 重要：保留链接，方便大模型关联上下文
        self.html_cleaner.ignore_images = True    # 过滤图片，节省 Token
        self.html_cleaner.ignore_tables = False   # 🚨 重要：保留表格，军工/科研数据多以表格存在
        self.html_cleaner.body_width = 0          # 不限制行宽，防止 URL 强制断行
        self.html_cleaner.protect_links = True    # 保护链接不被转义

    async def __call__(self, url: str, instructions: str = "", use_js: bool = True):
        if not url or not url.startswith("http"):
            return {"success": False, "error": "Invalid URL", "status": 0}

        retries = 0
        while retries < self.max_retries:
            if retries > 0:
                delay = 2 ** retries
                logger.warning(f"🔄 [防御穿透] 正在进行第 {retries} 次重试 (退避 {delay}s): {url}")
                await asyncio.sleep(delay) 

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
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--ignore-certificate-errors',
                        '--disable-dev-shm-usage',
                        '--disable-web-security',
                        '--disable-gpu',
                        '--blink-settings=imagesEnabled=false' 
                    ] 
                )
                
                current_ua = random.choice(self.UA_POOL)
                context = await browser.new_context(
                    user_agent=current_ua,
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US'
                )
                
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """)

                page = await context.new_page()

                if stealth_async:
                    await stealth_async(page)

                logger.info(f"🌐 正在执行广度扫描: {url}")
                response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)

                if response:
                    status = response.status
                    if status in [404, 410]:
                        return {"success": False, "error": f"HTTP {status} Not Found", "status": status}
                    elif status in [403, 401, 429] or status >= 500:
                        raise Exception(f"HTTP_SOFT_ERROR_{status}")

                links = []
                markdown_content = ""
                
                try:
                    if use_js:
                        try:
                            await page.wait_for_load_state("networkidle", timeout=2000)
                        except PlaywrightTimeoutError:
                            pass 

                        for _ in range(2):
                            if page.is_closed(): break
                            await page.evaluate("window.scrollBy(0, 800)")
                            await asyncio.sleep(0.2)

                    if not page.is_closed():
                        # 1. 提取所有链接（保持你原有的强大 JS 逻辑）
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
                                return Array.from(results, ([url, text]) => ({ url, text }));
                            }
                        """)

                        # 💡 核心优化：获取 HTML 并通过 html2text 转换为 Markdown
                        # 使用 page.content() 获取包含 JS 渲染后的完整 DOM
                        full_html = await page.content()
                        
                        # 由于 html2text 是 CPU 密集型操作，使用 to_thread 防止阻塞异步主线程
                        markdown_content = await asyncio.to_thread(self.html_cleaner.handle, full_html)
                        
                        # 限制长度，防止 LLM 上下文溢出 (12000 字符通常对应 3k-4k Token)
                        markdown_content = markdown_content[:12000]

                except PlaywrightError as pe:
                    if "Execution context was destroyed" in str(pe) or "Target closed" in str(pe):
                        if not markdown_content and not links:
                            raise Exception("CONTEXT_DESTROYED_EARLY")
                    else:
                        raise 

                return {
                    "success": True, 
                    "all_links": links, 
                    "html": markdown_content,  # 这里的键名保留为 'html' 以兼容你现有的 Miner 逻辑
                    "status": response.status if response else 200
                }

            except Exception as e:
                error_msg = str(e)
                hard_errors = ["ERR_TOO_MANY_REDIRECTS", "ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION_REFUSED", "ERR_SSL_PROTOCOL_ERROR"]
                if any(err in error_msg for err in hard_errors):
                    return {"success": False, "error": error_msg, "status": 0}
                
                retries += 1
                if retries >= self.max_retries:
                    return {"success": False, "error": error_msg, "status": 0}

            finally:
                try:
                    if page and not page.is_closed(): await page.close()
                    if context: await context.close()
                    if browser: await browser.close()
                except Exception: pass
                finally:
                    if playwright_manager: await playwright_manager.stop()
                    await asyncio.sleep(0.1)

        return {"success": False, "error": "Max retries reached", "status": 0}'''