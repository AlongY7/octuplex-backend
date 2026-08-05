"""
网页爬取与浏览器自动化技能
功能：网页访问、内容爬取、数据提取、页面解析
"""
import httpx
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup


class WebScraperSkill:
    """网页爬取技能"""

    @staticmethod
    async def fetch_page(url: str, timeout: int = 30) -> dict:
        """获取网页内容"""
        try:
            # 验证URL格式
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return {"error": "无效的URL格式"}

            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Octuplex/1.0)"
                })
                response.raise_for_status()

                return {
                    "success": True,
                    "url": str(response.url),
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                    "text": response.text[:100000]  # 限制100KB
                }
        except Exception as e:
            return {"error": f"网页获取失败: {str(e)}"}

    @staticmethod
    def extract_text(html: str) -> dict:
        """从HTML中提取纯文本"""
        soup = BeautifulSoup(html, "lxml")
        # 移除脚本和样式
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        # 压缩多余空行
        text = re.sub(r'\n\s*\n', '\n', text)

        return {
            "success": True,
            "text": text[:50000],
            "title": soup.title.string if soup.title else ""
        }

    @staticmethod
    def extract_links(html: str, base_url: str = "") -> dict:
        """提取页面中的所有链接"""
        soup = BeautifulSoup(html, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            links.append({"url": href, "text": text[:200]})

        return {"success": True, "links": links, "count": len(links)}

    @staticmethod
    def extract_table(html: str, table_index: int = 0) -> dict:
        """提取HTML表格数据"""
        soup = BeautifulSoup(html, "lxml")
        tables = soup.find_all("table")

        if table_index >= len(tables):
            return {"error": f"表格索引 {table_index} 超出范围，共 {len(tables)} 个表格"}

        table = tables[table_index]
        rows = []
        for tr in table.find_all("tr"):
            row = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if row:
                rows.append(row)

        return {"success": True, "rows": rows, "count": len(rows)}


# 技能入口函数
async def execute(action: str, params: dict) -> dict:
    """技能执行入口"""
    skill = WebScraperSkill()

    if action == "fetch":
        return await skill.fetch_page(**params)
    elif action == "extract_text":
        return skill.extract_text(**params)
    elif action == "extract_links":
        return skill.extract_links(**params)
    elif action == "extract_table":
        return skill.extract_table(**params)
    else:
        return {"error": f"不支持的操作: {action}"}