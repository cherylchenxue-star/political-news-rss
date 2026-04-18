#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
政治新闻聚合器 - 聚合新浪、中新网、新华网头条政治新闻
每天早上7:00自动抓取，筛选热度最高的政治新闻
"""

import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ============ 数据源配置 ============

# 新浪财经 API 获取的是财经频道（lid=2516/2515），不是政治新闻
# 因此不纳入政治新闻聚合，只保留中新网 RSS 和新华网网页抓取

RSS_SOURCES = {
    "chinanews_scroll": {
        "url": "https://www.chinanews.com.cn/rss/scroll-news.xml",
        "name": "中新网滚动",
        "weight": 0.95,
        "category": "mixed",
    },
    "chinanews_china": {
        "url": "https://www.chinanews.com.cn/rss/china.xml",
        "name": "中新网国内",
        "weight": 0.95,
        "category": "domestic",
    },
    "chinanews_world": {
        "url": "https://www.chinanews.com.cn/rss/world.xml",
        "name": "中新网国际",
        "weight": 0.9,
        "category": "international",
    },
}

WEB_SOURCES = {
    "xinhua": {
        "url": "https://www.news.cn/politics/",
        "name": "新华网时政",
        "weight": 1.0,
        "category": "domestic",
    },
    "xinhua_world": {
        "url": "https://www.news.cn/world/",
        "name": "新华网国际",
        "weight": 0.95,
        "category": "international",
    },
}


# ============ 政治新闻关键词（用于筛选） ============

POLITICAL_KEYWORDS = [
    # 国内政治
    "两会", "人大", "政协", "国务院", "总书记", "主席", "总理", "政治局",
    "常委", "反腐", "巡视", "八项规定", "深化改革", "机构改革", "依法治国",
    "政府工作报告", "中央", "党的领导", "党风廉政建设",
    # 台海
    "台湾", "台海", "两岸", "赖清德", "蔡英文", "台独", "统一", "台军",
    # 中美
    "特朗普", "拜登", "中美", "美中", "贸易战", "关税战", "芯片战", "脱钩",
    "制裁", "实体清单", "白宫", "五角大楼", "驻华大使",
    # 军事
    "解放军", "国防", "军演", "演习", "航母", "导弹", "战机", "歼", "东风",
    "核潜艇", "南海", "东海", "边境", "军费", "火箭军",
    # 外交
    "外交部", "王毅", "国事访问", "峰会", "G20", "APEC", "金砖", "上合",
    "一带一路", "联合国", "世卫组织",
    # 俄乌
    "普京", "俄罗斯", "乌克兰", "泽连斯基", "俄乌", "北约", "顿巴斯",
    "克里米亚", "和谈", "停火",
    # 中东
    "以色列", "巴勒斯坦", "加沙", "哈马斯", "伊朗", "沙特", "巴以",
    "黎巴嫩", "叙利亚", "也门", "胡塞",
    # 科技
    "芯片", "半导体", "华为", "航天", "卫星", "北斗", "空间站", "量子",
    # 港澳
    "香港", "澳门", "港府", "特首", "国安法", "一国两制",
    # 半岛
    "朝鲜", "韩国", "金正恩", "尹锡悦", "朝核",
    # 欧洲
    "欧盟", "马克龙", "朔尔茨", "脱欧", "欧央行",
    # 亚太
    "日本", "印度", "菲律宾", "东盟", "RCEP", "南海争端",
    # 其他政治
    "选举", "投票", "民意", "公投", "政变", "抗议", "示威", "罢工",
    "关税", "贸易", "制裁", "封锁", "禁运", "外交", "冲突", "战争",
    "和平", "谈判", "协议", "条约", "宣言", "决议",
]


# ============ 智能标签配置（精确匹配，避免泛滥） ============

TAG_RULES = [
    {
        "tag": "国内政治",
        "keywords": [
            "两会", "全国人大", "全国政协", "国务院", "总书记", "主席",
            "总理", "政治局", "常委", "部委", "政府工作报告",
            "中央", "党的领导", "反腐", "巡视", "八项规定",
            "党风廉政建设", "深化改革", "机构改革", "依法治国",
        ],
        "color": "#dc2626",
        "bg": "#fef2f2",
    },
    {
        "tag": "台海局势",
        "keywords": [
            "台湾", "台海", "两岸", "赖清德", "蔡英文", "台独", "统一",
            "台军", "海峡", "金门", "马祖", "澎湖",
        ],
        "color": "#b91c1c",
        "bg": "#fef2f2",
    },
    {
        "tag": "中美关系",
        "keywords": [
            "特朗普", "拜登", "中美贸易", "美中", "贸易战", "关税战",
            "芯片战", "科技战", "脱钩", "实体清单", "白宫", "五角大楼",
            "美国制裁", "对华制裁", "制裁中国", "中美关系",
        ],
        "color": "#2563eb",
        "bg": "#eff6ff",
    },
    {
        "tag": "军事国防",
        "keywords": [
            "解放军", "国防", "军演", "演习", "航母", "导弹",
            "战机", "歼-", "东风-", "核潜艇", "南海", "东海", "边境",
            "军费", "火箭军", "军事", "军队",
        ],
        "color": "#7c3aed",
        "bg": "#f5f3ff",
    },
    {
        "tag": "外交动态",
        "keywords": [
            "外交部", "王毅", "国事访问", "首脑会晤", "峰会",
            "G20", "APEC", "金砖国家", "上合组织", "一带一路",
            "联合国", "世卫组织", "气候大会", "COP",
        ],
        "color": "#0891b2",
        "bg": "#ecfeff",
    },
    {
        "tag": "俄乌冲突",
        "keywords": [
            "普京", "俄罗斯", "乌克兰", "泽连斯基", "俄乌", "北约",
            "顿巴斯", "克里米亚", "和谈", "停火", "援乌",
        ],
        "color": "#c2410c",
        "bg": "#fff7ed",
    },
    {
        "tag": "中东局势",
        "keywords": [
            "以色列", "巴勒斯坦", "加沙", "哈马斯", "伊朗", "沙特",
            "巴以", "黎巴嫩", "叙利亚", "也门", "胡塞",
        ],
        "color": "#d97706",
        "bg": "#fffbeb",
    },
    {
        "tag": "经济金融",
        "keywords": [
            "GDP", "央行", "股市", "A股", "港股", "关税", "汇率",
            "人民币", "降息", "加息", "降准", "房地产", "楼市",
            "通胀", "制造业", "产业链",
        ],
        "color": "#059669",
        "bg": "#f0fdf4",
    },
    {
        "tag": "科技前沿",
        "keywords": [
            "人工智能", "芯片", "半导体", "华为", "5G", "6G",
            "航天", "卫星", "北斗", "空间站", "量子",
        ],
        "color": "#4f46e5",
        "bg": "#eef2ff",
    },
    {
        "tag": "社会民生",
        "keywords": [
            "民生", "就业", "教育", "医疗", "养老", "社保", "医保",
            "住房", "房价", "生育", "人口", "老龄化", "食品安全",
            "环保", "灾害", "地震", "洪涝", "疫情",
        ],
        "color": "#0d9488",
        "bg": "#f0fdfa",
    },
    {
        "tag": "香港澳门",
        "keywords": [
            "香港", "澳门", "港府", "特首", "国安法", "一国两制",
        ],
        "color": "#be185d",
        "bg": "#fdf2f8",
    },
    {
        "tag": "朝鲜半岛",
        "keywords": [
            "朝鲜", "韩国", "金正恩", "尹锡悦", "朝核", "导弹试射",
        ],
        "color": "#7c2d12",
        "bg": "#fff7ed",
    },
    {
        "tag": "欧洲动态",
        "keywords": [
            "欧盟", "马克龙", "朔尔茨", "脱欧", "欧央行", "申根",
        ],
        "color": "#4338ca",
        "bg": "#eef2ff",
    },
    {
        "tag": "亚太周边",
        "keywords": [
            "日本", "印度", "菲律宾", "东盟", "RCEP", "南海争端",
        ],
        "color": "#0369a1",
        "bg": "#f0f9ff",
    },
]

HEAT_KEYWORDS = {
    "重磅": 15, "突发": 20, "头条": 12, "快讯": 8, "独家": 10,
    "首次": 8, "最新消息": 5, "紧急": 15, "危机": 10, "战争": 18,
    "冲突": 12, "制裁": 10, "反制": 10, "升级": 8, "突破": 8,
    "历史性": 10, "举世瞩目": 8, "震惊": 8, "悬念": 5, "定局": 5,
}


# ============ 核心函数 ============

def fetch_url(url: str, timeout: int = 30) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        if response.encoding == "ISO-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except Exception as e:
        logger.warning(f"获取失败 [{url}]: {e}")
        return ""


def fetch_json(url: str, timeout: int = 30) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://news.sina.com.cn/",
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        try:
            return response.json()
        except Exception:
            pass
        text = response.text
        match = re.search(r"[^(]*\((.*)\)[;\s]*$", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return {}
    except Exception as e:
        logger.warning(f"JSON 获取失败 [{url}]: {e}")
        return {}


def fetch_sina_news(config: dict) -> list[dict]:
    """从新浪 API 获取新闻"""
    items = []
    data = fetch_json(config["url"])
    if not data:
        return items

    result = data.get("result", {})
    news_list = result.get("data", []) if isinstance(result, dict) else []

    for news in news_list:
        title = news.get("title", "").strip()
        link = news.get("url", "").strip()
        title = re.sub(r"<[^>]+>", "", title)

        if not title or not link:
            continue

        ctime = news.get("ctime", "")
        pub_date = ""
        pub_timestamp = 0.0
        if ctime:
            try:
                dt = datetime.fromtimestamp(int(ctime))
                pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S +0800")
                pub_timestamp = float(ctime)
            except (ValueError, TypeError):
                pass

        keywords = news.get("keywords", "")
        media_name = news.get("media_name", "")

        items.append({
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "pub_timestamp": pub_timestamp,
            "description": keywords[:300] if keywords else "",
            "source_name": media_name or config["name"],
            "source_weight": config["weight"],
            "category": config["category"],
            "fetch_method": "sina_api",
        })

    return items


def parse_rss_items(xml_content: str, source_config: dict) -> list[dict]:
    items = []
    if not xml_content:
        return items

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.warning(f"RSS 解析错误: {e}")
        return items

    channel = root.find(".//channel")
    if channel is not None:
        for item in channel.findall(".//item"):
            news = _extract_rss_item(item, source_config)
            if news:
                items.append(news)
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        news = _extract_atom_entry(entry, source_config)
        if news:
            items.append(news)

    if not items:
        for item in root.findall(".//item"):
            news = _extract_rss_item(item, source_config)
            if news:
                items.append(news)

    return items


def _extract_rss_item(item: ET.Element, source_config: dict) -> dict | None:
    title_el = item.find("title")
    link_el = item.find("link")
    pub_date_el = item.find("pubDate")
    desc_el = item.find("description")

    title = (title_el.text or "").strip() if title_el is not None else ""
    link = (link_el.text or "").strip() if link_el is not None else ""
    pub_date = (pub_date_el.text or "").strip() if pub_date_el is not None else ""
    description = (desc_el.text or "").strip() if desc_el is not None else ""

    if not title or not link:
        return None

    description = re.sub(r"<[^>]+>", "", description)
    description = re.sub(r"\s+", " ", description).strip()[:300]

    return {
        "title": title,
        "link": link,
        "pub_date": pub_date,
        "pub_timestamp": _parse_date(pub_date),
        "description": description,
        "source_name": source_config["name"],
        "source_weight": source_config["weight"],
        "category": source_config["category"],
        "fetch_method": "rss",
    }


def _extract_atom_entry(entry: ET.Element, source_config: dict) -> dict | None:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    title_el = entry.find("atom:title", ns)
    link_el = entry.find("atom:link", ns)
    updated_el = entry.find("atom:updated", ns)
    summary_el = entry.find("atom:summary", ns)

    title = (title_el.text or "").strip() if title_el is not None else ""
    link = link_el.get("href", "").strip() if link_el is not None else ""
    pub_date = (updated_el.text or "").strip() if updated_el is not None else ""
    description = (summary_el.text or "").strip() if summary_el is not None else ""

    if not title or not link:
        return None

    description = re.sub(r"<[^>]+>", "", description)
    description = re.sub(r"\s+", " ", description).strip()[:300]

    return {
        "title": title,
        "link": link,
        "pub_date": pub_date,
        "pub_timestamp": _parse_date(pub_date),
        "description": description,
        "source_name": source_config["name"],
        "source_weight": source_config["weight"],
        "category": source_config["category"],
        "fetch_method": "rss",
    }


def _parse_date(date_str: str) -> float:
    if not date_str:
        return 0.0

    patterns = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for pattern in patterns:
        try:
            s = date_str.replace("+0000", "UTC").replace("-0000", "UTC")
            dt = datetime.strptime(s, pattern)
            return dt.timestamp()
        except ValueError:
            continue

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.timestamp()
        except ValueError:
            pass

    return 0.0


def fetch_xinhua_news(config: dict) -> list[dict]:
    items = []
    html = fetch_url(config["url"])
    if not html:
        return items

    soup = BeautifulSoup(html, "html.parser")
    seen_links = set()

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]

        if not text or len(text) < 8 or len(text) > 80:
            continue

        is_news = False
        if "news.cn/politics/" in href and re.search(r"/\d{8}/", href):
            is_news = True
        elif "news.cn/world/" in href and re.search(r"/\d{8}/", href):
            is_news = True
        elif "news.cn/photo/" in href and re.search(r"/\d{8}/", href):
            is_news = True
        elif href.startswith("/politics/") and re.search(r"/\d{8}/", href):
            href = urljoin("https://www.news.cn", href)
            is_news = True
        elif href.startswith("/world/") and re.search(r"/\d{8}/", href):
            href = urljoin("https://www.news.cn", href)
            is_news = True

        if not is_news:
            continue
        if href in seen_links:
            continue
        seen_links.add(href)

        items.append({
            "title": text,
            "link": href,
            "pub_date": "",
            "pub_timestamp": 0.0,
            "description": "",
            "source_name": config["name"],
            "source_weight": config["weight"],
            "category": config["category"],
            "fetch_method": "web",
        })

    return items[:20]


def is_political_news(title: str, description: str) -> bool:
    """判断是否为政治新闻"""
    text = (title + " " + description).lower()
    for kw in POLITICAL_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def fetch_article_summary(url: str) -> str:
    html = fetch_url(url, timeout=12)
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    article = soup.select_one("#article_content, .article-content, .article, #artibody")
    if article:
        text = article.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text[:400]

    article = soup.select_one(".detail-content, .article-content, #p-detail")
    if article:
        text = article.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text[:400]

    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 30]
    if paragraphs:
        return " ".join(paragraphs[:3])[:400]

    return ""


def auto_classify(link: str, text: str = "") -> str:
    if not link:
        return "domestic"
    link_lower = link.lower()
    intl_paths = ["/gj/", "/world/", "/intl/", "/us/", "/europe/", "/asia/"]
    for p in intl_paths:
        if p in link_lower:
            return "international"
    domestic_paths = ["/gn/", "/sh/", "/cj/", "/tp/", "/cul/", "/china/", "/politics/"]
    for p in domestic_paths:
        if p in link_lower:
            return "domestic"
    return "domestic"


def smart_tag(title: str, description: str) -> list[dict]:
    text = (title + " " + description).lower()
    tags = []
    for rule in TAG_RULES:
        for kw in rule["keywords"]:
            if kw.lower() in text:
                tags.append({
                    "name": rule["tag"],
                    "color": rule["color"],
                    "bg": rule["bg"],
                })
                break
    return tags[:3]


def calculate_heat(news: dict) -> float:
    score = 0.0
    text = (news["title"] + " " + news["description"]).lower()

    score += news["source_weight"] * 100

    for kw, bonus in HEAT_KEYWORDS.items():
        if kw.lower() in text:
            score += bonus

    ts = news.get("pub_timestamp", 0)
    if ts > 0:
        now = datetime.now().timestamp()
        hours_ago = max(0, (now - ts) / 3600)
        time_factor = max(0.3, 1.0 - (hours_ago / 120))
        score *= time_factor
    else:
        score *= 0.7

    title_len = len(news["title"])
    if 15 <= title_len <= 40:
        score += 5
    if len(news["description"]) > 50:
        score += 3

    return round(score, 2)


def deduplicate_news(news_list: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for news in news_list:
        norm = re.sub(r"[^\u4e00-\u9fff\w]", "", news["title"].lower())
        if len(norm) < 4:
            norm = news["title"].lower().strip()

        is_dup = False
        for s in seen:
            if norm in s or s in norm or _similarity(norm, s) > 0.7:
                is_dup = True
                break

        if not is_dup:
            seen.add(norm)
            unique.append(news)
    return unique


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0


def generate_rss_xml(news_list: list[dict], output_path: str) -> None:
    now = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")

    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")
    rss.set("xmlns:dc", "http://purl.org/dc/elements/1.1/")

    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "全球政治头条聚合"
    ET.SubElement(channel, "link").text = "https://cherylchenxue-star.github.io/political-news-rss/"
    ET.SubElement(channel, "description").text = (
        "每天早上自动聚合新华网、中新网、新浪新闻等权威媒体头条政治新闻，"
        "智能筛选热度最高内容"
    )
    ET.SubElement(channel, "language").text = "zh-CN"
    ET.SubElement(channel, "lastBuildDate").text = now
    ET.SubElement(channel, "generator").text = "Political News Aggregator"

    for news in news_list:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = news["title"]
        ET.SubElement(item, "link").text = news["link"]
        ET.SubElement(item, "guid", isPermaLink="true").text = news["link"]

        tags_str = ", ".join([t["name"] for t in news.get("tags", [])])
        desc = news["description"]
        if tags_str:
            desc = f"[标签: {tags_str}]\n{desc}"
        ET.SubElement(item, "description").text = desc

        cat = "国内" if news["category"] == "domestic" else "国际" if news["category"] == "international" else "综合"
        ET.SubElement(item, "category").text = cat
        ET.SubElement(item, "source").text = news["source_name"]

        if news.get("pub_date"):
            ET.SubElement(item, "pubDate").text = news["pub_date"]
        else:
            ET.SubElement(item, "pubDate").text = now

    _indent_xml(rss)
    ET.ElementTree(rss).write(output_path, encoding="utf-8", xml_declaration=True)
    logger.info(f"RSS 已生成: {output_path}")


def _indent_xml(elem: ET.Element, level: int = 0) -> None:
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for child in elem:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def generate_json_data(news_list: list[dict], output_path: str) -> None:
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(news_list),
        "domestic_count": len([n for n in news_list if n["category"] == "domestic"]),
        "international_count": len([n for n in news_list if n["category"] == "international"]),
        "news": news_list,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 数据已生成: {output_path}")


def main() -> None:
    logger.info("=" * 60)
    logger.info("政治新闻聚合器 - 开始运行")
    logger.info("=" * 60)

    all_news = []

    # 1. RSS 源（中新网）
    for key, config in RSS_SOURCES.items():
        logger.info(f"[RSS] 正在获取: {config['name']}")
        xml_content = fetch_url(config["url"])
        if not xml_content:
            logger.warning(f"  [FAIL] 获取失败")
            continue
        items = parse_rss_items(xml_content, config)
        logger.info(f"  [OK] 解析到 {len(items)} 条新闻")
        all_news.extend(items)

    # 2. 网页抓取（新华网）
    for key, config in WEB_SOURCES.items():
        logger.info(f"[网页] 正在抓取: {config['name']}")
        items = fetch_xinhua_news(config)
        logger.info(f"  [OK] 抓取到 {len(items)} 条新闻")
        all_news.extend(items)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"总计获取: {len(all_news)} 条原始新闻")
    logger.info(f"{'=' * 60}")

    # 4. 政治新闻筛选
    political_news = [n for n in all_news if is_political_news(n["title"], n["description"])]
    logger.info(f"政治新闻筛选后: {len(political_news)} 条")

    # 如果没有筛选出足够的新闻，保留原始数据
    if len(political_news) < 20:
        logger.info(f"政治新闻不足，保留所有新闻")
        political_news = all_news

    # 5. 去重
    political_news = deduplicate_news(political_news)
    logger.info(f"去重后: {len(political_news)} 条")

    # 6. mixed 自动分类
    for news in political_news:
        if news["category"] == "mixed":
            news["category"] = auto_classify(news["link"], news["title"] + " " + news["description"])

    # 7. 补充摘要
    for news in political_news[:20]:
        if len(news["description"]) < 30:
            summary = fetch_article_summary(news["link"])
            if summary:
                news["description"] = summary[:400]

    # 8. 智能标签
    for news in political_news:
        news["tags"] = smart_tag(news["title"], news["description"])

    # 9. 计算热度
    for news in political_news:
        news["heat_score"] = calculate_heat(news)

    # 10. 排序
    political_news.sort(key=lambda x: x["heat_score"], reverse=True)

    # 11. 取 top
    top_news = political_news[:40]

    # 12. 生成输出
    import os
    generate_rss_xml(top_news, "political_news_rss.xml")
    generate_json_data(top_news, "news_data.json")

    # 13. 打印结果
    logger.info(f"\n{'=' * 60}")
    logger.info("热度 TOP 20 新闻:")
    logger.info(f"{'=' * 60}")
    for i, news in enumerate(top_news[:20], 1):
        tags = ", ".join([t["name"] for t in news["tags"]])
        cat = "[国内]" if news["category"] == "domestic" else "[国际]"
        logger.info(f"\n{i}. {cat} {news['title']}")
        logger.info(f"   热度: {news['heat_score']} | 来源: {news['source_name']}")
        logger.info(f"   标签: {tags}")

    logger.info(f"\n[完成] 已生成 RSS 和前端数据文件")


if __name__ == "__main__":
    main()
