#!/usr/bin/env python3
"""Import ai-bot.cn homepage links into index.html and generate local detail pages.

Usage:
  pip install beautifulsoup4 lxml
  python3 tools/import_aibot.py --output index.html --pages-dir sites --icons-dir assets/icons
"""
from __future__ import annotations

import argparse
import hashlib
import html
import mimetypes
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

URL = "https://ai-bot.cn/"
START = "<!-- AI_BOT_IMPORT_START -->"
END = "<!-- AI_BOT_IMPORT_END -->"
TOP_NAV = [
    ("首页", "../index.html"),
    ("AI工具", "#"),
    ("AI教程", "#"),
    ("AI提示词", "#"),
    ("MCP", "#"),
    ("Skill", "#"),
    ("AI资讯", "#"),
]


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


def fetch_response(url: str, timeout: int = 30):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urlopen(req, timeout=timeout)


def fetch_binary(url: str, timeout: int = 30, referer: str = URL):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": referer,
        "Origin": "https://ai-bot.cn",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def scrape_homepage_only(timeout: int = 30):
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
    data, seen = [], set()

    def extract_links(container, category_name):
        links = []
        for card in container.select("div.url-card a.card[href]"):
            title = clean(card.select_one("strong").get_text(" ")) if card.select_one("strong") else ""
            desc = clean(card.select_one("p").get_text(" ")) if card.select_one("p") else ""
            external_url = card.get("data-url") or card.get("href")
            profile_url = urljoin(URL, card.get("href") or "")
            icon_el = card.select_one(".url-img img")
            icon = icon_el.get("data-src") or icon_el.get("src") if icon_el else ""
            key = profile_url or external_url
            if title and external_url and key not in seen:
                seen.add(key)
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


def detect_ext(icon_url: str, content: bytes, content_type: str = "") -> str:
    # `imghdr` is removed in newer Python versions (e.g. 3.13), so rely on
    # content-type + url suffix fallback for cross-version compatibility.
    ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".bmp"}:
        return ext
    from_url = os.path.splitext(urlparse(icon_url).path.lower())[1]
    if from_url in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".bmp"}:
        return from_url
    # tiny signature-based fallback (no extra dependency)
    if content.startswith(b"\x89PNG"):
        return ".png"
    if content[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return ".gif"
    if content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        return ".webp"
    if b"<svg" in content[:512].lower():
        return ".svg"
    if content[:4] == b"\x00\x00\x01\x00":
        return ".ico"
    return ".png"


def looks_like_image(content: bytes, content_type: str = "") -> bool:
    ctype = (content_type or "").lower()
    if ctype.startswith("image/"):
        return True
    if b"<svg" in content[:512].lower():
        return True
    if content.startswith(b"\x89PNG"):
        return True
    if content[:3] == b"\xff\xd8\xff":
        return True
    if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
        return True
    if content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        return True
    if content[:4] == b"\x00\x00\x01\x00":
        return True
    return False


def icon_candidates(item: dict) -> list[str]:
    candidates = []
    raw_icon = (item.get("icon") or "").strip()
    if raw_icon:
        candidates.append(urljoin(URL, raw_icon))

    profile_url = (item.get("profile_url") or "").strip()
    if profile_url:
        p = urlparse(profile_url)
        if p.scheme and p.netloc:
            candidates.append(f"{p.scheme}://{p.netloc}/favicon.ico")

    site_url = (item.get("url") or "").strip()
    if site_url:
        s = urlparse(site_url)
        if s.scheme and s.netloc:
            candidates.append(f"{s.scheme}://{s.netloc}/favicon.ico")

    # dedupe while preserving order
    uniq = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            uniq.append(candidate)
            seen.add(candidate)
    return uniq


def download_icons(imported, project_root: Path, icons_dir: Path, timeout: int = 30):
    icons_dir.mkdir(parents=True, exist_ok=True)
    cache = {}
    success_count = 0
    fail_count = 0
    for idx, item in enumerate(imported, 1):
        candidates = icon_candidates(item)
        if not candidates:
            fail_count += 1
            continue

        downloaded = False
        for candidate in candidates:
            if candidate in cache:
                item["local_icon"] = cache[candidate]
                downloaded = True
                break
            try:
                content, content_type = fetch_binary(candidate, timeout=timeout)
            except Exception:
                continue

            if not looks_like_image(content, content_type):
                continue

            ext = detect_ext(candidate, content, content_type)
            fname = f"{idx:04d}-{slug_from_item(item)}{ext}"
            path = icons_dir / fname
            path.write_bytes(content)
            rel = path.relative_to(project_root).as_posix()
            item["local_icon"] = rel
            cache[candidate] = rel
            downloaded = True
            break

        if downloaded:
            success_count += 1
        else:
            fail_count += 1

    print(f"Icon download summary: success={success_count}, failed={fail_count}")


def top_nav_html() -> str:
    return '<nav class="top-nav">' + ''.join(
        f'<a href="{html.escape(href)}">{html.escape(name)}</a>' for name, href in TOP_NAV
    ) + '</nav>'


def extract_detail_content(profile_html: str):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(profile_html, "lxml")

    # Try keep original layout: prefer detail container html.
    container = (
        soup.select_one(".entry-content")
        or soup.select_one(".site-content")
        or soup.select_one("article")
        or soup.select_one("main")
    )

    content_html = ""
    if container:
        # remove script/style to keep clean html
        for bad in container.select("script, style, noscript"):
            bad.decompose()
        # normalize relative image/src links
        for tag in container.select("img[src], a[href], source[src], video[src]"):
            attr = "href" if tag.has_attr("href") else "src"
            tag[attr] = urljoin(URL, tag.get(attr) or "")
        content_html = str(container)

    # fallback summary for cards/description
    meta = soup.select_one('meta[name="description"]')
    summary = clean(meta.get("content")) if meta and meta.get("content") else ""
    if not summary:
        p = soup.select_one(".entry-content p, .site-content p, article p, main p")
        summary = clean(p.get_text(" ")) if p else ""

    return summary, content_html


def generate_detail_pages(imported, project_root: Path, pages_dir: Path, timeout: int = 30):
    pages_dir.mkdir(parents=True, exist_ok=True)
    profile_cache = {}

    for item in imported:
        slug = slug_from_item(item)
        detail_name = f"{slug}.html"
        item["local_page"] = f"{pages_dir.name}/{detail_name}"

        profile_url = item.get("profile_url", "")
        detail_summary, detail_html = "", ""
        if profile_url:
            if profile_url not in profile_cache:
                try:
                    profile_cache[profile_url] = fetch_html(profile_url, timeout=timeout)
                except Exception:
                    profile_cache[profile_url] = ""
            if profile_cache[profile_url]:
                detail_summary, detail_html = extract_detail_content(profile_cache[profile_url])

        intro = detail_summary or item.get("desc") or f"{item['title']} 是一个面向 {item['category']} 的 AI 服务。"
        icon_rel = item.get("local_icon", "")
        icon_on_detail = (Path("..") / icon_rel).as_posix() if icon_rel else ""

        page = f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>{html.escape(item['title'])} - 介绍页</title>
<style>
:root{{--bg:#f2f5f9;--surface:#fff;--ink:#1b3550;--muted:#5d748a;--line:#d9e2ec;--accent:#c2181e}}
body{{margin:0;background:var(--bg);font-family:PingFang SC,Microsoft YaHei,sans-serif;color:var(--ink)}}
.top-nav{{display:flex;gap:14px;flex-wrap:wrap;max-width:1180px;margin:0 auto;padding:12px 16px;background:#fff;border-bottom:1px solid var(--line)}}
.top-nav a{{text-decoration:none;color:#1d4468;font-size:14px}}
.wrap{{max-width:1180px;margin:20px auto;padding:0 16px;display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px}}
.main{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:22px}}
.head{{display:flex;align-items:center;gap:10px}} .head img{{width:42px;height:42px;border-radius:10px;border:1px solid #d8e4ef}}
.main h1{{margin:0;font-size:30px}} .meta{{font-size:13px;color:var(--muted);margin:8px 0 12px}}
.desc{{line-height:1.95;font-size:17px;background:#f8fbff;border:1px solid #e2edf7;border-radius:10px;padding:14px}}
.btns a{{display:inline-block;padding:8px 12px;border-radius:10px;text-decoration:none;margin-right:8px}} .p{{background:#0f9d90;color:#fff}} .g{{background:#ecf7f5;color:#0a7f74}}
.raw{{margin-top:16px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px;overflow:auto}}
.raw img{{max-width:100%;height:auto}} .raw table{{max-width:100%;display:block;overflow:auto}}
.side{{display:grid;gap:14px}} .ad{{background:linear-gradient(120deg,#eef4fb,#f8fbff);border:1px dashed #b9ccde;border-radius:10px;padding:14px;text-align:center;color:#6b85a0;font-size:13px}}
@media(max-width:980px){{.wrap{{grid-template-columns:1fr}}}}
</style></head><body>
{top_nav_html()}
<main class=\"wrap\"><article class=\"main\"><div class=\"head\">{f'<img src="{html.escape(icon_on_detail)}" alt="logo" />' if icon_on_detail else ''}<h1>{html.escape(item['title'])}</h1></div><p class=\"meta\">分类：{html.escape(item['category'])}</p><p class=\"desc\">{html.escape(intro)}</p><div class=\"btns\"><a class=\"p\" href=\"{html.escape(item['url'])}\" target=\"_blank\" rel=\"noopener noreferrer\">官网链接</a><a class=\"g\" href=\"../index.html\">返回导航</a></div><section class=\"raw\">{detail_html if detail_html else '<p>未抓取到详情正文。</p>'}</section></article>
<aside class=\"side\"><div class=\"ad\">广告位 A</div><div class=\"ad\">广告位 B</div></aside></main></body></html>"""
        (pages_dir / detail_name).write_text(page, encoding="utf-8")


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
            local_page = html.escape(item.get("local_page", "#"))
            out.append(
                "    <article class=\"site-card site-card--rich\""
                f" data-keywords=\"{html.escape(item['category'])}\">"
                f"<div class=\"site-card__top\">{icon_html}<h3 class=\"site-title\"><a class=\"site-title-link\" href=\"{local_page}\">{html.escape(item['title'])}</a></h3></div>"
                f"<p class=\"site-desc\">{html.escape(item['desc'])}</p>"
                "</article>"
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

    imported = scrape_homepage_only(timeout=args.timeout)
    download_icons(imported, project_root=project_root, icons_dir=project_root / args.icons_dir, timeout=args.timeout)
    generate_detail_pages(imported, project_root=project_root, pages_dir=project_root / args.pages_dir, timeout=args.timeout)

    block = render(imported)
    html_path.write_text(re.sub(f"{re.escape(START)}[\\s\\S]*?{re.escape(END)}", f"{START}\n{block}\n{END}", text), encoding="utf-8")

    print(f"Imported {len(imported)} homepage links into {html_path}")
    print(f"Generated detail pages under: {project_root / args.pages_dir}")
    print(f"Downloaded local icons under: {project_root / args.icons_dir}")


if __name__ == "__main__":
    main()
