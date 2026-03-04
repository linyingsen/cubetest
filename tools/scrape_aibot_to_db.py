#!/usr/bin/env python3
"""抓取 ai-bot.cn 全量导航数据，生成可在 SQL Server 执行的 SQL 文件。

分类规则（严格）：
1) 一级分类 the_class：严格取自 ai-bot 首页的一级分类名称
2) 二级分类 second_class：若存在则取首页二级分类 tab 名称，否则为空
3) 通过首页“更多”入口建立列表页与一/二级分类的映射，并在后续分页抓取中沿用映射

去重规则：
- 以 old_url 为唯一键，同一工具出现在多个分类时，保留最先抓到的那条。

目标表结构：
- name
- the_class
- second_class
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
    second_class: str
    old_url: str
    detail_url: str
    logo_url: str
    the_memo: str


@dataclass
class CategoryCtx:
    first: str
    second: str = ""


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
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


def row_from_card(card, ctx: CategoryCtx) -> AiUrl | None:
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
        the_class=ctx.first,
        second_class=ctx.second,
        old_url=old_url,
        detail_url=detail_url,
        logo_url=logo_url,
        the_memo=the_memo,
    )


def extract_rows_from_scope(scope, ctx: CategoryCtx) -> list[AiUrl]:
    rows: list[AiUrl] = []
    for card in scope.select("div.url-card a.card[href]"):
        row = row_from_card(card, ctx)
        if row:
            rows.append(row)
    return rows


def detect_more_links(scope, base_url: str) -> list[str]:
    links: list[str] = []
    for a in scope.select("a[href]"):
        text = clean(a.get_text(" "))
        cls = " ".join(a.get("class", []))
        href = clean(a.get("href") or "")
        if not href:
            continue
        full = normalize_url(urljoin(base_url, href))
        if not is_listing_like_url(full):
            continue

        path = (urlparse(full).path or "").lower()
        is_more = ("更多" in text) or ("more" in text.lower()) or ("more" in cls.lower())
        is_fav = "/favorites/" in path
        is_page = re.search(r"/page/\d+/?$", path) is not None or "page=" in (urlparse(full).query or "").lower()
        if is_more or is_fav or is_page:
            links.append(full)

    # 保序去重
    out = []
    seen = set()
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_homepage_structured(soup) -> tuple[list[AiUrl], dict[str, CategoryCtx], list[tuple[str, CategoryCtx]]]:
    """解析首页主/二级分类，返回：
    - 首页卡片行
    - 页面URL到分类上下文映射（用于严格分类）
    - 待抓取列表页队列种子
    """
    content_layout = soup.select_one(".content-layout")
    if not content_layout:
        return [], {}, []

    children = [node for node in content_layout.children if getattr(node, "name", None)]
    rows: list[AiUrl] = []
    page_ctx_map: dict[str, CategoryCtx] = {}
    seeds: list[tuple[str, CategoryCtx]] = []

    def add_seed(url: str, ctx: CategoryCtx):
        nurl = normalize_url(url)
        if not is_listing_like_url(nurl):
            return
        # 首页建立的映射优先级最高，后续不覆盖
        if nurl not in page_ctx_map:
            page_ctx_map[nurl] = CategoryCtx(ctx.first, ctx.second)
        seeds.append((nurl, CategoryCtx(ctx.first, ctx.second)))

    i = 0
    while i < len(children):
        node = children[i]
        cls = set(node.get("class", []))
        is_top = node.name == "div" and {"d-flex", "flex-fill", "align-items-center", "mb-4"}.issubset(cls)
        if not is_top:
            i += 1
            continue

        h4 = node.select_one("h4")
        first_class = clean(h4.get_text(" ")) if h4 else "未命名分类"
        first_ctx = CategoryCtx(first=first_class, second="")

        i += 1
        while i < len(children):
            cur = children[i]
            cur_cls = set(cur.get("class", []))
            next_is_top = cur.name == "div" and {"d-flex", "flex-fill", "align-items-center", "mb-4"}.issubset(cur_cls)
            if next_is_top:
                break

            # 一级分类普通卡片块
            if cur.name == "div" and {"row", "io-mx-n2"}.issubset(cur_cls):
                rows.extend(extract_rows_from_scope(cur, first_ctx))
                for u in detect_more_links(cur, BASE_URL):
                    add_seed(u, first_ctx)

            # 二级分类块
            is_sub = cur.name == "h4" and {"text-gray", "text-lg"}.issubset(cur_cls)
            if is_sub:
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
                        second = clean(tab.get_text(" "))
                        second_ctx = CategoryCtx(first=first_class, second=second)
                        pane = tab_content.select_one(tab.get("href"))
                        if pane:
                            rows.extend(extract_rows_from_scope(pane, second_ctx))
                            for u in detect_more_links(pane, BASE_URL):
                                add_seed(u, second_ctx)

                    for u in detect_more_links(tab_content, BASE_URL):
                        add_seed(u, first_ctx)

            for u in detect_more_links(cur, BASE_URL):
                add_seed(u, first_ctx)
            i += 1

    # 首页自身作为兜底列表页
    add_seed(BASE_URL, CategoryCtx("首页", ""))
    return rows, page_ctx_map, seeds


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

    home_rows, page_ctx_map, seeds = parse_homepage_structured(home_soup)

    # 去重：同一 old_url 保留最先出现的
    by_old_url: dict[str, AiUrl] = {}
    for r in home_rows:
        if r.old_url not in by_old_url:
            by_old_url[r.old_url] = r

    q = deque()
    seen_pages: set[str] = set()
    for url, ctx in seeds:
        if url not in seen_pages:
            seen_pages.add(url)
            q.append((url, ctx))

    crawled = 0
    while q and crawled < max_pages:
        page_url, ctx = q.popleft()
        crawled += 1

        try:
            html = fetch_html(page_url, timeout=timeout)
        except Exception:
            continue

        soup = BeautifulSoup(html, "lxml")
        # 分类严格优先使用首页映射，其次使用当前传递上下文
        effective_ctx = page_ctx_map.get(page_url, ctx)

        for row in extract_rows_from_scope(soup, effective_ctx):
            if row.old_url not in by_old_url:
                by_old_url[row.old_url] = row

        for next_url in detect_more_links(soup, page_url):
            nurl = normalize_url(next_url)
            if nurl in seen_pages or not is_listing_like_url(nurl):
                continue
            seen_pages.add(nurl)
            # 分页/更多页面继承当前分类，且首次发现时写入映射
            if nurl not in page_ctx_map:
                page_ctx_map[nurl] = CategoryCtx(effective_ctx.first, effective_ctx.second)
            q.append((nurl, page_ctx_map[nurl]))

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
        {sql_quote(row.second_class)} AS second_class,
        {sql_quote(row.logo_url)} AS logo_url,
        {sql_quote(row.the_memo)} AS the_memo
) AS source
ON target.old_url = source.old_url
WHEN MATCHED THEN
    UPDATE SET
        name = source.name,
        the_class = source.the_class,
        second_class = source.second_class,
        detail_url = source.detail_url,
        logo_url = source.logo_url,
        the_memo = source.the_memo
WHEN NOT MATCHED THEN
    INSERT (name, the_class, second_class, old_url, detail_url, logo_url, the_memo)
    VALUES (source.name, source.the_class, source.second_class, source.old_url, source.detail_url, source.logo_url, source.the_memo);
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
        second_class NVARCHAR(500) NULL,
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
    header += """
IF COL_LENGTH('dbo.ai_url', 'second_class') IS NULL
BEGIN
    ALTER TABLE dbo.ai_url ADD second_class NVARCHAR(500) NULL;
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
