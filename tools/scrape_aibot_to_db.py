#!/usr/bin/env python3
"""抓取 ai-bot.cn 首页导航数据并写入 SQL Server 数据库 ai.ai_url。

目标表结构：
- name
- the_class
- old_url
- logo_url
- the_memo

默认连接参数：
- server: localhost
- database: ai
- user: sa
- password: saa1b2C3sa

依赖：beautifulsoup4, lxml, pyodbc
安装：pip install beautifulsoup4 lxml pyodbc
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Iterable
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


def connect_sqlserver(server: str, database: str, user: str, password: str, driver: str):
    try:
        import pyodbc
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少依赖 pyodbc，请先安装：pip install pyodbc") from exc

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def init_table(conn) -> None:
    conn.cursor().execute(
        """
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
        """
    )
    conn.commit()


def save_rows(conn, rows: Iterable[AiUrl]) -> int:
    cur = conn.cursor()
    count = 0
    for row in rows:
        cur.execute(
            """
            MERGE dbo.ai_url AS target
            USING (SELECT ? AS old_url, ? AS name, ? AS the_class, ? AS logo_url, ? AS the_memo) AS source
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
            """,
            (row.old_url, row.name, row.the_class, row.logo_url, row.the_memo),
        )
        count += 1
    conn.commit()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 ai-bot.cn 并写入 SQL Server 数据库 ai 的 ai_url 表")
    parser.add_argument("--server", default="localhost", help="SQL Server 地址，默认 localhost")
    parser.add_argument("--database", default="ai", help="数据库名，默认 ai")
    parser.add_argument("--user", default="sa", help="登录用户，默认 sa")
    parser.add_argument("--password", default="saa1b2C3sa", help="登录密码")
    parser.add_argument("--driver", default="ODBC Driver 18 for SQL Server", help="ODBC 驱动名")
    parser.add_argument("--timeout", type=int, default=30, help="抓取超时秒数")
    args = parser.parse_args()

    rows = scrape_home_all(timeout=args.timeout)
    conn = connect_sqlserver(args.server, args.database, args.user, args.password, args.driver)
    try:
        init_table(conn)
        total = save_rows(conn, rows)
    finally:
        conn.close()

    print(f"抓取完成：共 {len(rows)} 条，写入/更新 {total} 条")
    print(f"目标库：{args.server}/{args.database}，目标表：dbo.ai_url")


if __name__ == "__main__":
    main()
