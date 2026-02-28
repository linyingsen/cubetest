#!/usr/bin/env python3
"""Fetch ai-bot.cn homepage categories/links, inject cards into index.html,
and generate local rewritten intro pages for every imported site.

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


def ascii_slug(text: str, fallback_prefix: str = "site") -> str:
    ascii_only = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    digest = hashlib.md5((text or "").encode("utf-8")).hexdigest()[:8]
    core = ascii_only[:40] if ascii_only else fallback_prefix
    return f"{core}-{digest}"


def fetch_html(url: str, timeout: int = 30) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_bytes(url: str, timeout: int = 30) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0"}
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def rewrite_intro(raw: str, title: str, category: str) -> str:
    source = clean(raw)
    if not source:
        source = f"{title} 是一个与 {category} 相关的在线工具，覆盖常见创作与效率场景。"

    replacements = {
        "提供": "支持",
        "帮助": "用于帮助",
        "快速": "高效",
        "用户": "使用者",
        "平台": "服务",
        "一键": "便捷",
        "功能": "能力",
        "工具": "方案",
        "适合": "更适用于",
    }

    normalized = re.sub(r"[\n\r]+", "。", source)
    normalized = re.sub(r"[；;]+", "。", normalized)
    sentences = [clean(x) for x in re.split(r"[。！？!?]", normalized) if clean(x)]

    rewritten_sentences = []
    for idx, sentence in enumerate(sentences):
        line = sentence
        for old, new in replacements.items():
            line = line.replace(old, new)

        prefix = ["在实际使用中，", "从能力结构看，", "结合应用场景来看，"][idx % 3]
        line = f"{prefix}{line}"
        if not line.endswith("。"):
            line += "。"
        rewritten_sentences.append(line)

    merged = "".join(rewritten_sentences)
    if len(merged) < max(160, int(len(source) * 0.9)):
        merged += (
            "此外，它通常覆盖从信息输入、内容处理到结果输出的完整链路，"
            "对需要持续产出、强调效率与质量并重的个人或团队更友好。"
        )

    return (
        f"{title}（分类：{category}）的能力说明（改写版）如下："
        f"{merged}"
        "以上内容基于原站点资料进行结构化改写与整理，尽量保留关键信息密度。"
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
    parts = []

    for selector in ['meta[name="description"]', 'meta[property="og:description"]']:
        node = soup.select_one(selector)
        if node and node.get("content"):
            parts.append(clean(node.get("content")))

    for p in soup.select(".site-content p, .panel-body p, article p, .entry-content p"):
        text = clean(p.get_text(" "))
        if text and len(text) >= 18:
            parts.append(text)

    for li in soup.select(".site-content li, .panel-body li, article li, .entry-content li"):
        text = clean(li.get_text(" "))
        if text and len(text) >= 12:
            parts.append(f"- {text}")

    unique = []
    seen = set()
    for part in parts:
        key = part[:120]
        if key not in seen:
            seen.add(key)
            unique.append(part)

    return " ".join(unique[:24])


def infer_icon_ext(icon_url: str) -> str:
    path = urlparse(icon_url).path.lower()
    ext = os.path.splitext(path)[1]
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico"}:
        return ext
    return ".png"


def download_icons(imported, project_root: Path, icons_dir: Path, timeout: int = 30):
    icons_dir.mkdir(parents=True, exist_ok=True)
    icon_cache = {}

    for idx, item in enumerate(imported, start=1):
        icon_url = item.get("icon", "")
        if not icon_url:
            continue

        if icon_url in icon_cache:
            item["local_icon"] = icon_cache[icon_url]
            continue

        try:
            content = fetch_bytes(icon_url, timeout=timeout)
        except Exception:
            continue

        filename = f"{idx:04d}-{ascii_slug(item['title'], 'icon')}{infer_icon_ext(icon_url)}"
        file_path = icons_dir / filename
        file_path.write_bytes(content)

        rel = file_path.relative_to(project_root).as_posix()
        item["local_icon"] = rel
        icon_cache[icon_url] = rel


def generate_detail_pages(imported, project_root: Path, pages_dir: Path, timeout: int = 30):
    pages_dir.mkdir(parents=True, exist_ok=True)
    profile_cache = {}

    for idx, item in enumerate(imported, start=1):
        filename = f"{idx:04d}-{ascii_slug(item['title'])}.html"
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

        icon_rel = item.get("local_icon", "")
        detail_icon = ""
        if icon_rel:
            detail_icon = Path("..") / Path(icon_rel)

        page = f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{html.escape(item['title'])} - 站点介绍</title>
  <meta name=\"description\" content={html.escape(rewritten)!r} />
  <style>
    body {{ margin: 0; font-family: 'PingFang SC','Microsoft YaHei',sans-serif; background:#f4f8fb; color:#163a56; }}
    .wrap {{ width:min(900px, calc(100% - 32px)); margin:32px auto; }}
    .card {{ background:#fff; border:1px solid #d8e4ef; border-radius:14px; padding:24px; box-shadow:0 10px 24px rgba(20,57,87,.08); }}
    .head {{ display:flex; align-items:center; gap:10px; margin-bottom:10px; }}
    .head img {{ width:30px; height:30px; border-radius:8px; border:1px solid #d8e4ef; }}
    .meta {{ font-size:13px; color:#5e7b94; margin:6px 0 18px; }}
    .btns a {{ text-decoration:none; display:inline-block; margin-right:10px; padding:8px 12px; border-radius:10px; }}
    .btn-primary {{ background:#0f9d90; color:#fff; }}
    .btn-ghost {{ background:#ecf7f5; color:#0a7f74; }}
    .desc {{ line-height:1.85; }}
  </style>
</head>
<body>
  <main class=\"wrap\">
    <article class=\"card\">
      <div class=\"head\">{f'<img src="{html.escape(detail_icon.as_posix())}" alt="图标" />' if detail_icon else ''}<h1>{html.escape(item['title'])}</h1></div>
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
            icon_rel = html.escape(item.get("local_icon", ""))
            icon_html = (
                f'<img class="site-icon" src="{icon_rel}" alt="{html.escape(item["title"])} 图标" loading="lazy" />'
                if icon_rel
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
    generate_detail_pages(imported, project_root=project_root, pages_dir=project_root / args.pages_dir, timeout=args.timeout)

    block = render(imported)
    new_text = re.sub(f"{re.escape(START)}[\\s\\S]*?{re.escape(END)}", f"{START}\n{block}\n{END}", text)
    html_path.write_text(new_text, encoding="utf-8")
    print(f"Imported {len(imported)} links into {html_path}")
    print(f"Generated local intro pages under: {project_root / args.pages_dir}")
    print(f"Downloaded local icons under: {project_root / args.icons_dir}")


if __name__ == "__main__":
    main()
