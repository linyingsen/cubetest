#!/usr/bin/env python3
"""从 SQL Server 的 ai_url.logo_url 下载图片，并回填 ai_url.the_img。

功能：
1) 读取 dbo.ai_url.logo_url
2) 下载图片到本地目录
3) 文件名默认取 logo_url 路径里的文件名；若重名自动追加后缀
4) 将最终文件名写回 dbo.ai_url.the_img

依赖：pyodbc
安装：pip install pyodbc
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
import urllib.error
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip())
    cleaned = cleaned.strip(".-_")
    return cleaned[:180] or "logo"


def infer_ext(content_type: str, data: bytes, default: str = ".png") -> str:
    ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp"}:
        return ext
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return ".webp"
    if b"<svg" in data[:512].lower():
        return ".svg"
    if data[:4] == b"\x00\x00\x01\x00":
        return ".ico"
    return default


def looks_like_image(content_type: str, data: bytes) -> bool:
    ctype = (content_type or "").lower()
    if ctype.startswith("image/"):
        return True
    return infer_ext(content_type, data, default="") != ""


def unique_path(base_name: str, target_dir: Path, used: set[str]) -> Path:
    candidate = base_name
    stem, ext = os.path.splitext(base_name)
    index = 1
    while candidate.lower() in used or (target_dir / candidate).exists():
        candidate = f"{stem}-{index}{ext}"
        index += 1
    used.add(candidate.lower())
    return target_dir / candidate


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


def ensure_column(conn) -> None:
    conn.cursor().execute(
        """
        IF COL_LENGTH('dbo.ai_url', 'the_img') IS NULL
        BEGIN
            ALTER TABLE dbo.ai_url ADD the_img NVARCHAR(500) NULL;
        END
        """
    )
    conn.commit()


def download_binary(url: str, timeout: int = 30):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://ai-bot.cn/",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def pick_filename(logo_url: str, content_type: str, data: bytes) -> str:
    parsed = urlparse(logo_url)
    url_name = os.path.basename(parsed.path)
    url_name = safe_name(url_name)

    if not url_name or "." not in url_name:
        ext = infer_ext(content_type, data, default=".png")
        return f"logo{ext}"

    stem, ext = os.path.splitext(url_name)
    if ext.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp"}:
        ext = infer_ext(content_type, data, default=".png")
    return f"{safe_name(stem)}{ext.lower()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="读取 ai_url.logo_url 下载图片并回填 ai_url.the_img")
    parser.add_argument("--server", default="localhost", help="SQL Server 地址，默认 localhost")
    parser.add_argument("--database", default="ai", help="数据库名，默认 ai")
    parser.add_argument("--user", default="sa", help="登录用户，默认 sa")
    parser.add_argument("--password", default="saa1b2C3sa", help="登录密码")
    parser.add_argument("--driver", default="ODBC Driver 18 for SQL Server", help="ODBC 驱动名")
    parser.add_argument("--out-dir", default="assets/db_logos", help="图片下载目录")
    parser.add_argument("--timeout", type=int, default=30, help="下载超时秒数")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_sqlserver(args.server, args.database, args.user, args.password, args.driver)
    ensure_column(conn)

    cur = conn.cursor()
    rows = cur.execute("SELECT old_url, logo_url FROM dbo.ai_url WHERE logo_url IS NOT NULL AND LTRIM(RTRIM(logo_url)) <> ''").fetchall()

    used_names: set[str] = set()
    ok = 0
    fail = 0
    for row in rows:
        old_url = str(row[0] or "").strip()
        logo_url = str(row[1] or "").strip()
        if not old_url or not logo_url:
            continue
        try:
            data, content_type = download_binary(logo_url, timeout=args.timeout)
            if not looks_like_image(content_type, data):
                raise ValueError("响应内容不是图片")

            base_name = pick_filename(logo_url, content_type, data)
            file_path = unique_path(base_name, out_dir, used_names)
            file_path.write_bytes(data)

            file_name = file_path.name
            cur.execute("UPDATE dbo.ai_url SET the_img = ? WHERE old_url = ?", (file_name, old_url))
            ok += 1
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError):
            fail += 1

    conn.commit()
    conn.close()

    print(f"处理完成：成功 {ok}，失败 {fail}")
    print(f"图片目录：{out_dir.resolve()}")


if __name__ == "__main__":
    main()
