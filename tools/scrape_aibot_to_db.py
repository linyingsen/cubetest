#!/usr/bin/env python3
"""抓取 ai-bot.cn 全量导航数据，生成可在 SQL Server 执行的 SQL 文件。

增强点：
1) 抓取首页主分类 / 二级分类
2) 自动发现并抓取“更多”页面
3) 自动抓取分页页面（如 page/2, page/3 ...）
4) 去重后输出 MERGE UPSERT SQL

目标表结构：
- name
- the_class
- old_url
- detail_url
- logo_url
- the_memo

依赖：beautifulsoup4, lxml
安装：pip install beautifulsoup4 lxml
"""
from __future__ import annotations

import argparse
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

BASE_URL = "https://ai-bot.cn/"
BASE_HOST = "ai-bot.cn"


@dataclass
class AiUrl:
    name: str
    the_class: str
    old_url: str
    detail_url: str
    logo_url: str
    the_memo: str


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    # 忽略 hash，保留 query（有些站点分页可能带参数）
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))


def same_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == BASE_HOST or host.endswith("." + BASE_HOST)


def is_listing_like_url(url: str) -> bool:
    if not same_host(url):
        return False
    path = (urlparse(url).path or "").lower()
    if not path:
        return True
    # 排除详情页、静态资源
    if re.search(r"/sites/\d+\.html$", path):
        return False
    if re.search(r"\.(png|jpg|jpeg|gif|webp|svg|ico|css|js|pdf|zip)$", path):
        return False
    return True


def fetch_html(url: str, timeout: int = 30) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def card_to_row(card, category_name: str) -> AiUrl | None:
    title_el = card.select_one("strong")
    desc_el = card.select_one("p")
    icon_el = card.select_one(".url-img img")

    name = clean(title_el.get_text(" ")) if title_el else ""
    the_memo = clean(desc_el.get_text(" ")) if desc_el else ""
    old_url = clean(card.get("data-url") or card.get("href") or "")
    detail_url = clean(card.get("href") or "")
    logo_url = clean((icon_el.get("data-src") or icon_el.get("src") or "") if icon_el else "")

    old_url = urljoin(BASE_URL, old_url)
    detail_url = urljoin(BASE_URL, detail_url) if detail_url else ""
    logo_url = urljoin(BASE_URL, logo_url) if logo_url else ""

    if not name or not old_url:
        return None

    return AiUrl(
        name=name,
        the_class=category_name,
        old_url=old_url,
        detail_url=detail_url,
        logo_url=logo_url,
        the_memo=the_memo,
    )


def extract_rows_from_cards(soup, category_name: str) -> list[AiUrl]:
    rows: list[AiUrl] = []
    for card in soup.select("div.url-card a.card[href]"):
        row = card_to_row(card, category_name)
        if row:
            rows.append(row)
    return rows


def infer_category_from_page(soup, fallback: str = "未命名分类") -> str:
    breadcrumb_last = soup.select_one(".breadcrumb li.active, .breadcrumb .active")
    if breadcrumb_last:
        text = clean(breadcrumb_last.get_text(" "))
        if text:
            return text
    h1 = soup.select_one("h1")
    if h1:
        text = clean(h1.get_text(" "))
        if text:
            return text
    title = soup.select_one("title")
    if title:
        text = clean(title.get_text(" ")).split("-")[0].strip()
        if text:
            return text
    return fallback


def discover_more_and_paging_links(soup, base_url: str) -> list[tuple[str, str]]:
    """从页面中发现需要继续抓取的列表页链接。

    返回 (url, category_hint)
    """
    discovered: list[tuple[str, str]] = []
    for a in soup.select("a[href]"):
        href = clean(a.get("href") or "")
        if not href:
            continue
        full = normalize_url(urljoin(base_url, href))
        if not is_listing_like_url(full):
            continue

        txt = clean(a.get_text(" "))
        cls = " ".join(a.get("class", []))
        path = (urlparse(full).path or "").lower()

        # 重点抓：更多入口、收藏分类页、分页页
        is_more = "更多" in txt or "more" in txt.lower() or "more" in cls.lower()
        is_favorites = "/favorites/" in path
        is_paged = re.search(r"/page/\d+/?$", path) is not None or "page=" in (urlparse(full).query or "").lower()
        if not (is_more or is_favorites or is_paged):
            continue

        # 通过附近标题推测类别
        near_title = ""
        near_h = a.find_previous(["h1", "h2", "h3", "h4"])
        if near_h:
            near_title = clean(near_h.get_text(" "))
        discovered.append((full, near_title or "未命名分类"))
    return discovered


def scrape_home_with_structure(soup) -> tuple[list[AiUrl], list[tuple[str, str]]]:
    """优先使用首页结构解析主分类/二级分类，并顺带收集更多链接。"""
    content_layout = soup.select_one(".content-layout")
    if not content_layout:
        return [], discover_more_and_paging_links(soup, BASE_URL)

    children = [node for node in content_layout.children if getattr(node, "name", None)]
    rows: list[AiUrl] = []
    links: list[tuple[str, str]] = []

    i = 0
    while i < len(children):
        node = children[i]
        cls = set(node.get("class", []))
        is_top_cat = node.name == "div" and {"d-flex", "flex-fill", "align-items-center", "mb-4"}.issubset(cls)
        if not is_top_cat:
            i += 1
            continue

        h4 = node.select_one("h4")
        main_cat = clean(h4.get_text(" ")) if h4 else "未命名分类"

        i += 1
        while i < len(children):
            cur = children[i]
            cur_cls = set(cur.get("class", []))

            if cur.name == "div" and {"d-flex", "flex-fill", "align-items-center", "mb-4"}.issubset(cur_cls):
                break

            if cur.name == "div" and {"row", "io-mx-n2"}.issubset(cur_cls):
                rows.extend(extract_rows_from_cards(cur, main_cat))

            # 检测二级分类 + tab 内容
            is_sub_title = cur.name == "h4" and {"text-gray", "text-lg"}.issubset(cur_cls)
            if is_sub_title:
                sub_heading = clean(cur.get_text(" "))
                tab_wrap = children[i + 1] if i + 1 < len(children) else None
                tab_content = children[i + 2] if i + 2 < len(children) else None
                tab_ok = (
                    tab_wrap
                    and tab_content
                    and tab_content.name == "div"
                    and {"tab-content", "mt-4"}.issubset(set(tab_content.get("class", [])))
                )
                if tab_ok:
                    for tab in tab_wrap.select(".slider_menu a[href^='#']"):
                        sub_cat = clean(tab.get_text(" "))
                        pane = tab_content.select_one(tab.get("href"))
                        if pane:
                            rows.extend(extract_rows_from_cards(pane, f"{main_cat} / {sub_cat}"))

                    # 从二级区块里提取更多链接
                    links.extend(discover_more_and_paging_links(tab_content, BASE_URL))
                else:
                    # 没有 tab 时也尝试发现“更多”
                    links.extend(discover_more_and_paging_links(cur, BASE_URL))

                # 给二级分类一个兜底类别提示
                if sub_heading:
                    links.append((BASE_URL, f"{main_cat} / {sub_heading}"))

            links.extend(discover_more_and_paging_links(cur, BASE_URL))
            i += 1

    # 全页兜底发现更多/分页
    links.extend(discover_more_and_paging_links(soup, BASE_URL))
    return rows, links


def scrape_home_all(timeout: int = 30, max_pages: int = 1200) -> list[AiUrl]:
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少依赖 beautifulsoup4/lxml，请先安装：pip install beautifulsoup4 lxml") from exc

    try:
        home_html = fetch_html(BASE_URL, timeout=timeout)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"下载页面失败: {exc}") from exc

    home_soup = BeautifulSoup(home_html, "lxml")

    home_rows, seed_links = scrape_home_with_structure(home_soup)

    # 以 old_url 去重，确保“所有网址”只保留一条
    by_old_url: dict[str, AiUrl] = {r.old_url: r for r in home_rows}

    # BFS 抓取“更多”页和分页
    q = deque()
    seen_pages: set[str] = set()
    for url, cat_hint in seed_links:
        nurl = normalize_url(url)
        if is_listing_like_url(nurl) and nurl not in seen_pages:
            seen_pages.add(nurl)
            q.append((nurl, cat_hint or "未命名分类"))

    # 首页也加入队列做兜底，确保分类页发现逻辑完整
    home_url = normalize_url(BASE_URL)
    if home_url not in seen_pages:
        seen_pages.add(home_url)
        q.append((home_url, "首页"))

    crawled = 0
    while q and crawled < max_pages:
        page_url, cat_hint = q.popleft()
        crawled += 1

        try:
            html = fetch_html(page_url, timeout=timeout)
        except Exception:
            continue

        soup = BeautifulSoup(html, "lxml")
        page_cat = infer_category_from_page(soup, fallback=cat_hint)

        for row in extract_rows_from_cards(soup, page_cat):
            # 同一 old_url 已存在时，优先保留类别信息更具体的一条
            if row.old_url not in by_old_url:
                by_old_url[row.old_url] = row
            else:
                old = by_old_url[row.old_url]
                if old.the_class in {"未命名分类", "首页"} and row.the_class not in {"未命名分类", "首页"}:
                    by_old_url[row.old_url] = row

        for next_url, next_hint in discover_more_and_paging_links(soup, page_url):
            nurl = normalize_url(next_url)
            if nurl in seen_pages or not is_listing_like_url(nurl):
                continue
            seen_pages.add(nurl)
            q.append((nurl, next_hint or page_cat))

    print(f"页面抓取统计：已抓取列表页 {crawled} 个，发现网址 {len(by_old_url)} 条")
    return list(by_old_url.values())


def sql_quote(value: str) -> str:
    return "N'" + (value or "").replace("'", "''") + "'"


def build_merge_sql(row: AiUrl) -> str:
    return f"""
MERGE dbo.ai_url AS target
USING (
    SELECT
        {sql_quote(row.old_url)} AS old_url,
        {sql_quote(row.detail_url)} AS detail_url,
        {sql_quote(row.name)} AS name,
        {sql_quote(row.the_class)} AS the_class,
        {sql_quote(row.logo_url)} AS logo_url,
        {sql_quote(row.the_memo)} AS the_memo
) AS source
ON target.old_url = source.old_url
WHEN MATCHED THEN
    UPDATE SET
        name = source.name,
        the_class = source.the_class,
        detail_url = source.detail_url,
        logo_url = source.logo_url,
        the_memo = source.the_memo
WHEN NOT MATCHED THEN
    INSERT (name, the_class, old_url, detail_url, logo_url, the_memo)
    VALUES (source.name, source.the_class, source.old_url, source.detail_url, source.logo_url, source.the_memo);
GO
""".strip()


def generate_sql_script(rows: list[AiUrl]) -> str:
    header = """-- Auto-generated by tools/scrape_aibot_to_db.py
SET NOCOUNT ON;

IF OBJECT_ID(N'dbo.ai_url', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ai_url (
        name NVARCHAR(500) NOT NULL,
        the_class NVARCHAR(500) NOT NULL,
        old_url NVARCHAR(1000) NOT NULL PRIMARY KEY,
        detail_url NVARCHAR(1000) NULL,
        logo_url NVARCHAR(1000) NULL,
        the_memo NVARCHAR(MAX) NULL
    );
END
GO
"""
    header += """
IF COL_LENGTH('dbo.ai_url', 'detail_url') IS NULL
BEGIN
    ALTER TABLE dbo.ai_url ADD detail_url NVARCHAR(1000) NULL;
END
GO
"""
    body = "\n\n".join(build_merge_sql(row) for row in rows)
    return header + "\n" + body + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 ai-bot.cn 全量网址并生成可导入 SQL Server 的 .sql 文件")
    parser.add_argument("--sql-output", default="ai_url_import.sql", help="输出 SQL 文件路径，默认 ai_url_import.sql")
    parser.add_argument("--timeout", type=int, default=30, help="抓取超时秒数")
    parser.add_argument("--max-pages", type=int, default=1200, help="最多抓取的列表页数量，默认 1200")
    args = parser.parse_args()

    rows = scrape_home_all(timeout=args.timeout, max_pages=args.max_pages)
    sql_text = generate_sql_script(rows)

    output_path = Path(args.sql_output)
    output_path.write_text(sql_text, encoding="utf-8")

    print(f"抓取完成：共 {len(rows)} 条")
    print(f"SQL 文件已生成：{output_path.resolve()}")
    print("可在 SQL Server Management Studio 中直接执行该 .sql 文件。")


if __name__ == "__main__":
    main()
