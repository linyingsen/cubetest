#!/usr/bin/env python3
"""Fetch ai-bot.cn homepage categories/links, inject cards into index.html,
and generate local rewritten intro pages for every imported site.

Usage:
  pip install beautifulsoup4 lxml
  python3 tools/import_aibot.py --output index.html --pages-dir sites
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

URL = "https://ai-bot.cn/"
START = "<!-- AI_BOT_IMPORT_START -->"
END = "<!-- AI_BOT_IMPORT_END -->"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def slugify(text: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fa5]+", "-", (text or "").strip().lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:64] or "category"


def fetch_html(url: str, timeout: int = 30) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def rewrite_intro(raw: str, title: str, category: str) -> str:
    source = clean(raw)
    if not source:
        source = f"{title} 是一个与 {category} 相关的在线工具，覆盖常见创作与效率场景。"

    # Light rewrite rules to avoid direct copy and keep meaning.
    replacements = {
        "提供": "支持",
        "帮助": "用于帮助",
        "快速": "高效",
        "用户": "使用者",
        "平台": "服务",
        "一键": "便捷",
        "功能": "能力",
        "工具": "方案",
    }
    rewritten = source
    for old, new in replacements.items():
        rewritten = rewritten.replace(old, new)

    if not rewritten.endswith("。"):
        rewritten += "。"

    return (
        f"{title}（分类：{category}）可用于对应业务场景，以下为整理后的简介："
        f"{rewritten}"
        " 结合目录体验来看，它更适合希望缩短操作路径、快速完成任务的用户。"
    )


def scrape(timeout: int = 30):
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency: beautifulsoup4. Install with: pip install beautifulsoup4 lxml"
        ) from exc

    try:
        home_html = fetch_html(URL, timeout=timeout)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to download {URL}: {exc}") from exc

    soup = BeautifulSoup(home_html, "lxml")
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
            external_url = card.get("data-url") or card.get("href")
            profile_url = urljoin(URL, card.get("href") or "")

            icon_el = card.select_one(".url-img img")
            icon = ""
            if icon_el:
                icon = icon_el.get("data-src") or icon_el.get("src") or ""

            if title and external_url:
                links.append(
                    {
                        "category": category_name,
                        "title": title,
                        "url": external_url,
                        "desc": desc,
                        "icon": icon,
                        "profile_url": profile_url,
                    }
                )
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
                    if (
                        tab_wrap
                        and tab_content
                        and tab_content.name == "div"
                        and {"tab-content", "mt-4"}.issubset(set(tab_content.get("class", [])))
                    ):
                        for tab in tab_wrap.select(".slider_menu a[href^='#']"):
                            sub = clean(tab.get_text(" "))
                            pane = tab_content.select_one(tab.get("href"))
                            if pane:
                                data.extend(extract_links(pane, f"{main_cat} / {sub}"))
                i += 1
            continue
        i += 1

    return data


def extract_profile_summary(profile_html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(profile_html, "lxml")
    meta_desc = soup.select_one('meta[name="description"]')
    if meta_desc and meta_desc.get("content"):
        return clean(meta_desc.get("content"))

    og_desc = soup.select_one('meta[property="og:description"]')
    if og_desc and og_desc.get("content"):
        return clean(og_desc.get("content"))

    candidate = soup.select_one(".site-content p, .panel-body p, article p")
    return clean(candidate.get_text(" ")) if candidate else ""


def generate_detail_pages(imported, pages_dir: Path, timeout: int = 30):
    pages_dir.mkdir(parents=True, exist_ok=True)
    profile_cache = {}

    for idx, item in enumerate(imported, start=1):
        slug = slugify(item["title"]) or f"site-{idx}"
        filename = f"{idx:04d}-{slug}.html"
        item["local_page"] = f"{pages_dir.name}/{filename}"

        profile_url = item.get("profile_url", "")
        profile_summary = ""
        if profile_url:
            if profile_url not in profile_cache:
                try:
                    profile_cache[profile_url] = fetch_html(profile_url, timeout=timeout)
                except Exception:
                    profile_cache[profile_url] = ""
            if profile_cache[profile_url]:
                profile_summary = extract_profile_summary(profile_cache[profile_url])

        rewritten = rewrite_intro(profile_summary or item.get("desc", ""), item["title"], item["category"])

        page = f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{html.escape(item['title'])} - 站点介绍</title>
  <meta name=\"description\" content={html.escape(rewritten)!r} />
  <style>
    body {{ margin: 0; font-family: 'PingFang SC','Microsoft YaHei',sans-serif; background:#f4f8fb; color:#163a56; }}
    .wrap {{ width:min(860px, calc(100% - 32px)); margin:32px auto; }}
    .card {{ background:#fff; border:1px solid #d8e4ef; border-radius:14px; padding:22px; box-shadow:0 10px 24px rgba(20,57,87,.08); }}
    .head {{ display:flex; align-items:center; gap:10px; margin-bottom:10px; }}
    .head img {{ width:30px; height:30px; border-radius:8px; border:1px solid #d8e4ef; }}
    .meta {{ font-size:13px; color:#5e7b94; margin:6px 0 18px; }}
    .btns a {{ text-decoration:none; display:inline-block; margin-right:10px; padding:8px 12px; border-radius:10px; }}
    .btn-primary {{ background:#0f9d90; color:#fff; }}
    .btn-ghost {{ background:#ecf7f5; color:#0a7f74; }}
    .desc {{ line-height:1.8; }}
  </style>
</head>
<body>
  <main class=\"wrap\">
    <article class=\"card\">
      <div class=\"head\">{f'<img src="{html.escape(item.get("icon", ""))}" alt="图标" />' if item.get('icon') else ''}<h1>{html.escape(item['title'])}</h1></div>
      <p class=\"meta\">分类：{html.escape(item['category'])}</p>
      <p class=\"desc\">{html.escape(rewritten)}</p>
      <div class=\"btns\">
        <a class=\"btn-primary\" href={html.escape(item['url'])!r} target=\"_blank\" rel=\"noopener noreferrer\">访问官网</a>
        <a class=\"btn-ghost\" href=\"../index.html\">返回导航</a>
      </div>
    </article>
  </main>
</body>
</html>
"""
        (pages_dir / filename).write_text(page, encoding="utf-8")


def render(imported):
    grouped = {}
    order = []
    for item in imported:
        cat = item["category"]
        if cat not in grouped:
            grouped[cat] = []
            order.append(cat)
        grouped[cat].append(item)

    out = [
        '<section class="category-block" id="aibot-overview" data-category="AI-BOT 抓取分类">',
        '  <div class="category-head"><h2>AI-BOT 抓取分类总览</h2><span class="category-tag">自动同步</span></div>',
        '  <div class="quick-links">',
    ]

    for cat in order:
        cid = f"aibot-{slugify(cat)}"
        out.append(f'    <a href="#{cid}">{html.escape(cat)}</a>')

    out.extend(["  </div>", "</section>"])

    for cat in order:
        cid = f"aibot-{slugify(cat)}"
        items = grouped[cat]
        out.extend(
            [
                f'<section class="category-block" id="{cid}" data-category="{html.escape(cat)}">',
                f'  <div class="category-head"><h2>{html.escape(cat)}</h2><span class="category-tag">{len(items)} 个</span></div>',
                '  <div class="card-grid">',
            ]
        )

        for item in items:
            kws = html.escape(item["category"])
            icon = html.escape(item.get("icon", ""))
            icon_html = (
                f'<img class="site-icon" src="{icon}" alt="{html.escape(item["title"])} 图标" loading="lazy" />'
                if icon
                else '<span class="site-icon site-icon--placeholder" aria-hidden="true"></span>'
            )
            local_page = html.escape(item.get("local_page", "#"))
            out.append(
                "    <article class=\"site-card site-card--rich\""
                f" data-keywords=\"{kws}\">"
                f"<div class=\"site-card__top\">{icon_html}<h3 class=\"site-title\">{html.escape(item['title'])}</h3></div>"
                f"<p class=\"site-desc\">{html.escape(item['desc'])}</p>"
                f"<span class=\"site-meta\">{html.escape(item['category'])}</span>"
                f"<div class=\"site-actions\"><a href=\"{local_page}\" class=\"site-link\">查看本地介绍</a>"
                f"<a href=\"{html.escape(item['url'])}\" class=\"site-link site-link--ghost\" target=\"_blank\" rel=\"noopener noreferrer\">访问官网</a></div></article>"
            )

        out.extend(["  </div>", "</section>"])

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="index.html")
    parser.add_argument("--pages-dir", default="sites")
    parser.add_argument("--timeout", default=30, type=int)
    args = parser.parse_args()

    html_path = Path(args.output)
    text = html_path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise RuntimeError(f"index.html must include markers: {START} ... {END}")

    imported = scrape(timeout=args.timeout)
    pages_dir = html_path.parent / args.pages_dir
    generate_detail_pages(imported, pages_dir=pages_dir, timeout=args.timeout)

    block = render(imported)
    new_text = re.sub(f"{re.escape(START)}[\\s\\S]*?{re.escape(END)}", f"{START}\n{block}\n{END}", text)
    html_path.write_text(new_text, encoding="utf-8")
    print(f"Imported {len(imported)} links into {html_path}")
    print(f"Generated local intro pages under: {pages_dir}")


if __name__ == "__main__":
    main()
