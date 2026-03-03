#!/usr/bin/env python3
"""抓取 ai-bot.cn 首页导航数据，生成可在 SQL Server 执行的 SQL 文件。

输出 SQL 会包含：
1) 若不存在则创建 dbo.ai_url 表
2) 基于 old_url 的 MERGE UPSERT 语句

目标表结构：
- name
- the_class
- old_url
- logo_url
- the_memo

依赖：beautifulsoup4, lxml
安装：pip install beautifulsoup4 lxml
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://ai-bot.cn/"


@dataclass
class AiUrl:
    name: str
    the_class: str
    old_url: str
    logo_url: str
    the_memo: str


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


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


def _extract_links(container, category_name: str, seen: set[str]) -> list[AiUrl]:
    rows: list[AiUrl] = []
    for card in container.select("div.url-card a.card[href]"):
        title_el = card.select_one("strong")
        desc_el = card.select_one("p")
        icon_el = card.select_one(".url-img img")

        name = clean(title_el.get_text(" ")) if title_el else ""
        the_memo = clean(desc_el.get_text(" ")) if desc_el else ""
        old_url = clean(card.get("data-url") or card.get("href") or "")
        logo_url = clean((icon_el.get("data-src") or icon_el.get("src") or "") if icon_el else "")

        old_url = urljoin(BASE_URL, old_url)
        logo_url = urljoin(BASE_URL, logo_url) if logo_url else ""

        if not name or not old_url:
            continue

        dedupe_key = f"{category_name}|{name}|{old_url}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        rows.append(
            AiUrl(
                name=name,
                the_class=category_name,
                old_url=old_url,
                logo_url=logo_url,
                the_memo=the_memo,
            )
        )
    return rows


def scrape_home_all(timeout: int = 30) -> list[AiUrl]:
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少依赖 beautifulsoup4/lxml，请先安装：pip install beautifulsoup4 lxml") from exc

    try:
        html = fetch_html(BASE_URL, timeout=timeout)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"下载页面失败: {exc}") from exc

    soup = BeautifulSoup(html, "lxml")
    content_layout = soup.select_one(".content-layout")
    if not content_layout:
        raise RuntimeError("页面结构变化：未找到 .content-layout")

    children = [node for node in content_layout.children if getattr(node, "name", None)]
    all_rows: list[AiUrl] = []
    seen: set[str] = set()

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

            next_is_top = cur.name == "div" and {"d-flex", "flex-fill", "align-items-center", "mb-4"}.issubset(cur_cls)
            if next_is_top:
                break

            if cur.name == "div" and {"row", "io-mx-n2"}.issubset(cur_cls):
                all_rows.extend(_extract_links(cur, main_cat, seen))

            is_sub_title = cur.name == "h4" and {"text-gray", "text-lg"}.issubset(cur_cls)
            if is_sub_title:
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
                            all_rows.extend(_extract_links(pane, f"{main_cat} / {sub_cat}", seen))
            i += 1

    return all_rows


def sql_quote(value: str) -> str:
    return "N'" + (value or "").replace("'", "''") + "'"


def build_merge_sql(row: AiUrl) -> str:
    return f"""
MERGE dbo.ai_url AS target
USING (
    SELECT
        {sql_quote(row.old_url)} AS old_url,
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
        logo_url = source.logo_url,
        the_memo = source.the_memo
WHEN NOT MATCHED THEN
    INSERT (name, the_class, old_url, logo_url, the_memo)
    VALUES (source.name, source.the_class, source.old_url, source.logo_url, source.the_memo);
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
        logo_url NVARCHAR(1000) NULL,
        the_memo NVARCHAR(MAX) NULL
    );
END
GO
"""
    body = "\n\n".join(build_merge_sql(row) for row in rows)
    return header + "\n" + body + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 ai-bot.cn 并生成可导入 SQL Server 的 .sql 文件")
    parser.add_argument("--sql-output", default="ai_url_import.sql", help="输出 SQL 文件路径，默认 ai_url_import.sql")
    parser.add_argument("--timeout", type=int, default=30, help="抓取超时秒数")
    args = parser.parse_args()

    rows = scrape_home_all(timeout=args.timeout)
    sql_text = generate_sql_script(rows)

    output_path = Path(args.sql_output)
    output_path.write_text(sql_text, encoding="utf-8")

    print(f"抓取完成：共 {len(rows)} 条")
    print(f"SQL 文件已生成：{output_path.resolve()}")
    print("可在 SQL Server Management Studio 中直接执行该 .sql 文件。")


if __name__ == "__main__":
    main()
