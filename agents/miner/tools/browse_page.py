import asyncio
from playwright.async_api import async_playwright
from loguru import logger

class BrowsePageTool:
    def __init__(self, headless=True, max_retries=3):
        self.headless = headless
        self.max_retries = max_retries  # 最大重试次数

    async def __call__(self, url: str, instructions: str = "", use_js: bool = True):
        if not url or not url.startswith("http"):
            return {"success": False, "error": "Invalid URL"}

        retries = 0
        while retries < self.max_retries:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
                )
                page = await context.new_page()

                try:
                    logger.info(f"🌐 正在执行广度扫描: {url}")

                    # 增加等待时间，确保基础框架加载
                    await page.goto(url, wait_until="networkidle", timeout=60000)  # 60秒超时，适合动态内容

                    if use_js:
                        # 模拟多次滚动，确保触发所有 Infinite Scroll 加载
                        for _ in range(5): 
                            await page.evaluate("window.scrollBy(0, 1000)")
                            await asyncio.sleep(1)  # 等待数据渲染

                    # 提取所有可见链接及其文本，不做任何关键词剔除
                    links = await page.evaluate("""
                        () => {
                            const results = [];
                            document.querySelectorAll('a').forEach(a => {
                                const href = a.href;
                                if (href && href.startsWith('http')) {
                                    // 抓取链接文本，如果文本为空则抓取其 title 或 alt 属性作为补充
                                    let text = a.innerText.trim() || a.getAttribute('title') || '';
                                    results.push({ url: href, text: text });
                                }
                            });
                            return results;
                        }
                    """)

                    content = await page.content()
                    await browser.close()
                    return {
                        "success": True,
                        "all_links": links,
                        "html": content[:50000]  # 截取前50KB的HTML内容
                    }

                except Exception as e:
                    logger.error(f"浏览失败: {e}")
                    await browser.close()

                    # 重试机制，增加重试次数
                    retries += 1
                    if retries < self.max_retries:
                        logger.warning(f"尝试重新加载页面 {url}, 重试次数: {retries}/{self.max_retries}")
                    else:
                        return {"success": False, "error": str(e)}

        return {"success": False, "error": "Max retries reached, failed to load the page."}
