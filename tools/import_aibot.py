#!/usr/bin/env python3
"""Import ai-bot.cn links into index.html and generate local AI detail/article pages.

Usage:
  pip install beautifulsoup4 lxml
  python3 tools/import_aibot.py --output index.html --pages-dir sites --icons-dir assets/icons
"""
from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
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


def ascii_slug(text: str, fallback_prefix: str = "ai") -> str:
    ascii_only = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    digest = hashlib.md5((text or "").encode("utf-8")).hexdigest()[:6]
    core = ascii_only[:40] if ascii_only else fallback_prefix
    return f"{core}-{digest}"


def slug_from_item(item: dict) -> str:
    if re.search(r"[a-zA-Z]", item.get("title", "")):
        return ascii_slug(item["title"], "ai")
    m = re.search(r"/sites/(\d+)\.html", item.get("profile_url", ""))
    if m:
        return f"ai-{m.group(1)}"
    return ascii_slug(item.get("title", ""), "ai")


def fetch_html(url: str, timeout: int = 30) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def scrape(timeout: int = 30):
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency: beautifulsoup4. Install with: pip install beautifulsoup4 lxml") from exc

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
            icon = icon_el.get("data-src") or icon_el.get("src") if icon_el else ""
            if title and external_url:
                links.append({
                    "category": category_name,
                    "title": title,
                    "url": external_url,
                    "desc": desc,
                    "icon": icon,
                    "profile_url": profile_url,
                })
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


def extract_profile_full(profile_html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(profile_html, "lxml")
    chunks = []
    for selector in ['meta[name="description"]', 'meta[property="og:description"]']:
        node = soup.select_one(selector)
        if node and node.get("content"):
            chunks.append(clean(node.get("content")))
    for p in soup.select(".site-content p, .entry-content p, .panel-body p, article p"):
        t = clean(p.get_text(" "))
        if len(t) > 16:
            chunks.append(t)
    for li in soup.select(".site-content li, .entry-content li, article li"):
        t = clean(li.get_text(" "))
        if len(t) > 10:
            chunks.append(t)

    unique, seen = [], set()
    for c in chunks:
        k = c[:120]
        if k not in seen:
            seen.add(k)
            unique.append(c)
    return " ".join(unique[:40])


def infer_icon_ext(icon_url: str) -> str:
    ext = os.path.splitext(urlparse(icon_url).path.lower())[1]
    return ext if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico"} else ".png"


def download_icons(imported, project_root: Path, icons_dir: Path, timeout: int = 30):
    icons_dir.mkdir(parents=True, exist_ok=True)
    cache = {}
    for idx, item in enumerate(imported, 1):
        icon_url = item.get("icon") or ""
        if not icon_url:
            continue
        if icon_url in cache:
            item["local_icon"] = cache[icon_url]
            continue
        try:
            content = fetch_bytes(icon_url, timeout=timeout)
        except Exception:
            continue
        fname = f"{idx:04d}-{slug_from_item(item)}{infer_icon_ext(icon_url)}"
        path = icons_dir / fname
        path.write_bytes(content)
        rel = path.relative_to(project_root).as_posix()
        item["local_icon"] = rel
        cache[icon_url] = rel


def build_article_items(title: str, category: str, long_intro: str, kind: str):
    kind_cn = {"news": "新闻资讯", "tips": "使用技巧", "prompts": "提示词"}[kind]
    seeds = [s for s in re.split(r"[。！？!?]", long_intro) if clean(s)]
    if not seeds:
        seeds = [f"{title} 在 {category} 方向持续更新能力。"]

    items = []
    for i in range(1, 7):
        base = clean(seeds[(i - 1) % len(seeds)])
        if kind == "news":
            head = f"{title}{kind_cn}速递 {i}"
        elif kind == "tips":
            head = f"{title}实战技巧 {i}"
        else:
            head = f"{title}高效提示词 {i}"
        excerpt = f"围绕“{base[:36]}”整理的 {kind_cn} 要点，适合快速了解与落地。"
        body = (
            f"{head}\n\n"
            f"本文基于 {title} 的公开资料进行整理。{base}"
            f" 在实际应用中，可结合具体任务拆解目标、输入约束与输出格式，"
            f"并通过多轮迭代提升结果稳定性。"
        )
        items.append({"title": head, "excerpt": excerpt, "body": body})
    return items


def generate_detail_and_articles(imported, project_root: Path, pages_dir: Path, timeout: int = 30):
    pages_dir.mkdir(parents=True, exist_ok=True)
    article_root = project_root / "articles"
    article_root.mkdir(parents=True, exist_ok=True)
    profile_cache = {}

    for item in imported:
        slug = slug_from_item(item)
        detail_name = f"{slug}.html"
        item["local_page"] = f"{pages_dir.name}/{detail_name}"

        profile_url = item.get("profile_url", "")
        profile_full = ""
        if profile_url:
            if profile_url not in profile_cache:
                try:
                    profile_cache[profile_url] = fetch_html(profile_url, timeout=timeout)
                except Exception:
                    profile_cache[profile_url] = ""
            if profile_cache[profile_url]:
                # User explicitly requested full copy style.
                profile_full = extract_profile_full(profile_cache[profile_url])

        intro = profile_full or item.get("desc") or f"{item['title']} 是一个面向 {item['category']} 的 AI 服务。"

        icon_rel = item.get("local_icon", "")
        icon_on_detail = (Path("..") / icon_rel).as_posix() if icon_rel else ""

        sections_html = []
        for kind, cn in [("news", "新闻资讯"), ("tips", "使用技巧"), ("prompts", "提示词")]:
            list_name = f"{slug}-{kind}.html"
            list_rel = f"../articles/{list_name}"
            articles = build_article_items(item["title"], item["category"], intro, kind)

            # list page
            list_cards = []
            for idx, art in enumerate(articles, 1):
                detail_file = f"{slug}-{kind}-{idx}.html"
                list_cards.append(
                    f'<li><a href="{html.escape(detail_file)}">{html.escape(art["title"])}</a><p>{html.escape(art["excerpt"])}</p></li>'
                )
                detail_html = f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{html.escape(art['title'])}</title><style>body{{font-family:PingFang SC,Microsoft YaHei,sans-serif;background:#f5f8fb;margin:0}}main{{max-width:860px;margin:28px auto;padding:0 16px}}article{{background:#fff;border:1px solid #d8e4ef;border-radius:12px;padding:22px}}a{{color:#0a7f74;text-decoration:none}}</style></head><body><main><article><h1>{html.escape(art['title'])}</h1><p>{html.escape(art['body'])}</p><p><a href=\"{html.escape(list_name)}\">返回列表</a></p></article></main></body></html>"""
                (article_root / detail_file).write_text(detail_html, encoding="utf-8")

            list_html = f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{html.escape(item['title'])} - {cn}</title><style>body{{font-family:PingFang SC,Microsoft YaHei,sans-serif;background:#f5f8fb;margin:0}}main{{max-width:920px;margin:28px auto;padding:0 16px}}section{{background:#fff;border:1px solid #d8e4ef;border-radius:12px;padding:22px}}li{{margin:0 0 14px}}a{{color:#0a7f74;text-decoration:none}}p{{color:#5e7b94}}</style></head><body><main><section><h1>{html.escape(item['title'])} · {cn}</h1><ul>{''.join(list_cards)}</ul><p><a href=\"../{html.escape(item['local_page'])}\">返回介绍页</a></p></section></main></body></html>"""
            (article_root / list_name).write_text(list_html, encoding="utf-8")

            preview = "".join(
                f'<li><a href="../articles/{slug}-{kind}-{i}.html">{html.escape(articles[i-1]["title"])}</a></li>'
                for i in range(1, 4)
            )
            sections_html.append(
                f'<section class="panel"><div class="panel-h"><h2>{cn}</h2><a href="{list_rel}">更多</a></div><ul>{preview}</ul></section>'
            )

        detail_html = f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>{html.escape(item['title'])} - 介绍页</title>
<style>
body{{margin:0;font-family:PingFang SC,Microsoft YaHei,sans-serif;background:#f4f8fb;color:#163a56}}
.wrap{{max-width:980px;margin:28px auto;padding:0 16px}}
.card{{background:#fff;border:1px solid #d8e4ef;border-radius:14px;padding:22px;box-shadow:0 10px 24px rgba(20,57,87,.08)}}
.head{{display:flex;align-items:center;gap:10px}} .head img{{width:34px;height:34px;border-radius:8px;border:1px solid #d8e4ef}}
.meta{{color:#5e7b94;font-size:13px;margin:8px 0 16px}} .desc{{line-height:1.85}}
.btns a{{display:inline-block;padding:8px 12px;border-radius:10px;text-decoration:none;margin-right:8px}}
.p{{background:#0f9d90;color:#fff}} .g{{background:#ecf7f5;color:#0a7f74}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:18px}}
.panel{{border:1px solid #d8e4ef;border-radius:10px;padding:12px}} .panel-h{{display:flex;justify-content:space-between;align-items:center}}
.panel a{{color:#0a7f74;text-decoration:none}}
</style></head><body><main class=\"wrap\"><article class=\"card\">
<div class=\"head\">{f'<img src="{html.escape(icon_on_detail)}" alt="logo" />' if icon_on_detail else ''}<h1>{html.escape(item['title'])}</h1></div>
<p class=\"meta\">分类：{html.escape(item['category'])}</p>
<p class=\"desc\">{html.escape(intro)}</p>
<div class=\"btns\"><a class=\"p\" href=\"{html.escape(item['url'])}\" target=\"_blank\" rel=\"noopener noreferrer\">官网链接</a><a class=\"g\" href=\"../index.html\">返回导航</a></div>
<div class=\"grid\">{''.join(sections_html)}</div>
</article></main></body></html>"""
        (pages_dir / detail_name).write_text(detail_html, encoding="utf-8")


def render(imported):
    grouped, order = {}, []
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
        out.append(f'    <a href="#aibot-{slugify(cat)}">{html.escape(cat)}</a>')
    out.extend(["  </div>", "</section>"])

    for cat in order:
        items = grouped[cat]
        out.extend([
            f'<section class="category-block" id="aibot-{slugify(cat)}" data-category="{html.escape(cat)}">',
            f'  <div class="category-head"><h2>{html.escape(cat)}</h2><span class="category-tag">{len(items)} 个</span></div>',
            '  <div class="card-grid">',
        ])
        for item in items:
            icon_rel = html.escape(item.get("local_icon", ""))
            icon_html = f'<img class="site-icon" src="{icon_rel}" alt="{html.escape(item["title"])} 图标" loading="lazy" />' if icon_rel else '<span class="site-icon site-icon--placeholder" aria-hidden="true"></span>'
            out.append(
                "    <article class=\"site-card site-card--rich\""
                f" data-keywords=\"{html.escape(item['category'])}\">"
                f"<div class=\"site-card__top\">{icon_html}<h3 class=\"site-title\">{html.escape(item['title'])}</h3></div>"
                f"<p class=\"site-desc\">{html.escape(item['desc'])}</p>"
                f"<span class=\"site-meta\">{html.escape(item['category'])}</span>"
                f"<div class=\"site-actions\"><a href=\"{html.escape(item.get('local_page','#'))}\" class=\"site-link\">查看本地介绍</a>"
                f"<a href=\"{html.escape(item['url'])}\" class=\"site-link site-link--ghost\" target=\"_blank\" rel=\"noopener noreferrer\">访问官网</a></div></article>"
            )
        out.extend(["  </div>", "</section>"])

    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="index.html")
    parser.add_argument("--pages-dir", default="sites")
    parser.add_argument("--icons-dir", default="assets/icons")
    parser.add_argument("--timeout", default=30, type=int)
    args = parser.parse_args()

    html_path = Path(args.output)
    project_root = html_path.parent
    text = html_path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise RuntimeError(f"index.html must include markers: {START} ... {END}")

    imported = scrape(timeout=args.timeout)
    download_icons(imported, project_root=project_root, icons_dir=project_root / args.icons_dir, timeout=args.timeout)
    generate_detail_and_articles(imported, project_root=project_root, pages_dir=project_root / args.pages_dir, timeout=args.timeout)

    block = render(imported)
    html_path.write_text(re.sub(f"{re.escape(START)}[\\s\\S]*?{re.escape(END)}", f"{START}\n{block}\n{END}", text), encoding="utf-8")

    print(f"Imported {len(imported)} links into {html_path}")
    print(f"Generated site pages under: {project_root / args.pages_dir}")
    print(f"Generated article pages under: {project_root / 'articles'}")
    print(f"Downloaded local icons under: {project_root / args.icons_dir}")


if __name__ == "__main__":
    main()
