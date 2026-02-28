#!/usr/bin/env python3
"""Fetch ai-bot.cn homepage categories/links and inject static cards into index.html.

Usage:
  pip install requests beautifulsoup4 lxml
  python3 tools/import_aibot.py --output index.html
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


URL = "https://ai-bot.cn/"
START = "<!-- AI_BOT_IMPORT_START -->"
END = "<!-- AI_BOT_IMPORT_END -->"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def scrape(timeout: int = 30):
    import requests
    from bs4 import BeautifulSoup

    resp = requests.get(URL, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    content_layout = soup.select_one(".content-layout")
    if not content_layout:
        raise RuntimeError("Unable to find .content-layout on ai-bot homepage")

    children = [c for c in content_layout.children if getattr(c, "name", None)]
    data = []

    def extract_links(container, category_name):
        links = []
        for card in container.select("div.url-card a.card[href]"):
            title = clean(card.select_one("strong").get_text(" ")) if card.select_one("strong") else ""
            desc = clean(card.select_one("p").get_text(" ")) if card.select_one("p") else ""
            url = card.get("data-url") or card.get("href")
            if title and url:
                links.append({"category": category_name, "title": title, "url": url, "desc": desc})
        return links

    i = 0
    while i < len(children):
        node = children[i]
        classes = set(node.get("class", []))
        if node.name == "div" and {"d-flex", "flex-fill", "align-items-center", "mb-4"}.issubset(classes):
            h4 = node.select_one("h4")
            main_cat = clean(h4.get_text(" ")) if h4 else "未命名分类"
            i += 1
            while i < len(children):
                cur = children[i]
                cur_cls = set(cur.get("class", []))
                if cur.name == "div" and {"d-flex", "flex-fill", "align-items-center", "mb-4"}.issubset(cur_cls):
                    break

                if cur.name == "div" and {"row", "io-mx-n2"}.issubset(cur_cls):
                    data.extend(extract_links(cur, main_cat))

                if cur.name == "h4" and {"text-gray", "text-lg"}.issubset(cur_cls):
                    tab_wrap = children[i + 1] if i + 1 < len(children) else None
                    tab_content = children[i + 2] if i + 2 < len(children) else None
                    if tab_wrap and tab_content and tab_content.name == "div" and {"tab-content", "mt-4"}.issubset(set(tab_content.get("class", []))):
                        for tab in tab_wrap.select(".slider_menu a[href^='#']"):
                            sub = clean(tab.get_text(" "))
                            pane = tab_content.select_one(tab.get("href"))
                            if pane:
                                data.extend(extract_links(pane, f"{main_cat} / {sub}"))
                i += 1
            continue
        i += 1

    return data


def render(imported):
    out = ["<section class=\"category-block\" id=\"aibot-full\" data-category=\"AI-BOT首页全量导入\">",
           "  <div class=\"category-head\"><h2>AI-BOT 首页链接导入</h2><span class=\"category-tag\">自动同步</span></div>",
           "  <div class=\"card-grid\">"]

    for item in imported:
        kws = html.escape(item["category"])
        out.append(
            "    <a class=\"site-card\" target=\"_blank\" rel=\"noopener noreferrer\""
            f" href=\"{html.escape(item['url'])}\" data-keywords=\"{kws}\">"
            f"<h3 class=\"site-title\">{html.escape(item['title'])}</h3>"
            f"<p class=\"site-desc\">{html.escape(item['desc'])}</p>"
            f"<span class=\"site-meta\">{html.escape(item['category'])}</span></a>"
        )

    out.append("  </div>")
    out.append("</section>")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="index.html")
    args = parser.parse_args()

    html_path = Path(args.output)
    text = html_path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise RuntimeError(f"index.html must include markers: {START} ... {END}")

    imported = scrape()
    block = render(imported)
    new_text = re.sub(f"{re.escape(START)}[\\s\\S]*?{re.escape(END)}", f"{START}\n{block}\n{END}", text)
    html_path.write_text(new_text, encoding="utf-8")
    print(f"Imported {len(imported)} links into {html_path}")


if __name__ == "__main__":
    main()
