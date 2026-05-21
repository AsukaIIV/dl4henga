#!/usr/bin/env python3
"""
nhentai / nxhentai 最佳下载方式提取器  v3
============================================
从 nhentai 生态所有镜像站点自动抓取最佳下载方式
(BT 磁力/种子、HTTP 直链、FTP)，按 种子数>体积>速度 排序输出。
无种子时回退到逐页图片下载 (--dl)。

v3 新增:
  - 搜索镜像去状态化 (实时探测代替存储状态)
  - nhentai.to 优先搜索 (nhentai.xxx 搜索有缺陷)
  - 搜索结果验证 (检测假结果自动回退)
  - --dl 逐页图片下载回退
  - 修复 HTML 搜索 ID/标题配对

用法:
  python3 nhentai_dl.py <url|id>
  python3 nhentai_dl.py --search "query"
  python3 nhentai_dl.py --random --tag "artist"
  python3 nhentai_dl.py --dl <url|id>
  python3 nhentai_dl.py --check
"""

import re
import sys
import os
import json
import time
import random
import socket
import subprocess
import argparse
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote_plus, urljoin

# ── 常量 ──────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7,ja;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1", "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

STAGE_NAMES = {1: "cloudscraper", 2: "curl_cffi", 3: "requests", 4: "curl"}
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIRRORS_PATH = os.path.join(SCRIPT_DIR, "mirrors.json")

PROXY_PORTS = [7890, 7897, 1087, 8118, 10808, 10809, 8080, 3128, 8888, 7891]
PROXY_SCAN_TIMEOUT = 1.5

# ── 正则 ─────────────────────────────────────────────────
GALLERY_URL_RE = re.compile(r"""(?:n(?:x)?hentai|hentai)[\w.-]*/g/(\d{1,6})""", re.IGNORECASE)
GALLERY_ID_RE = re.compile(r"""^(\d{1,6})$""")
MAGNET_RE = re.compile(r"""magnet:\?xt=urn:btih:[a-fA-F0-9]{32,60}[^\s"'<>]*""", re.IGNORECASE)
TORRENT_FILE_RE = re.compile(r"""https?://[^\s"'<>]+\.torrent[^\s"'<>]*""", re.IGNORECASE)
DIRECT_HTTP_RE = re.compile(
    r"""(?:href|data-url|data-link|src)=["']"""
    r"""(https?://[^\s"'<>]*(?:download|dl|get|file)[^\s"'<>]*\.(?:zip|rar|7z|cbz|cbr|pdf))""",
    re.IGNORECASE)
FTP_RE = re.compile(r"""ftp://[^\s"'<>]+""", re.IGNORECASE)
SEEDS_RE = re.compile(r"""(?:seeds?|seeders?|peers?|做种|シード)[:\s]*(\d[\d,]*)""", re.IGNORECASE)
SIZE_RE = re.compile(
    r"""(?:^|\s|>|Size|File\s*size|文件大小)[:\s]*(\d+[.,]?\d*)\s*(GB|MB|KB|B|GiB|MiB|KiB)\b""",
    re.IGNORECASE)
KEEPSHARE_RE = re.compile(r"""https?://keepshare\.org/[^\s"'<>]*magnet[^\s"'<>]*""", re.IGNORECASE)
TITLE_RE = re.compile(r"""<title>(.*?)</title>""", re.IGNORECASE)
OG_TITLE_RE = re.compile(r"""<meta\s+property=["']og:title["']\s+content=["']([^"']+)""", re.IGNORECASE)
H1_RE = re.compile(r"""<h1[^>]*>(.*?)</h1>""", re.IGNORECASE)

SEARCH_ID_RE = re.compile(r'/g/(\d{1,6})/')
SEARCH_TITLE_RE = re.compile(r'class="caption"[^>]*>([^<]+)')
# nhentai 图片 URL 模式: i.nhentai.xxx/galleries/{media_id}/{page}.{ext}
IMG_URL_RE = re.compile(r"""(?:src|data-src)=["'](https?://[^"']*/galleries/\d+/\d+\.[^"']+)""", re.IGNORECASE)
NUMPAGES_RE = re.compile(r'(\d+)\s*pages?', re.IGNORECASE)
THUMB_RE = re.compile(r'data-src="(https?://t\d?\.?nhentai[^"]*galleries/\d+/\d+t?\.[^"]*)"', re.IGNORECASE)

# ── 搜索镜像优先级 (nhentai.to 搜索比 xxx 可靠) ──────────
SEARCH_MIRROR_PRIORITY = ["nhentai.to", "nhentai.net", "nhentai.xxx"]


# ═══════════════════════════════════════════════════════════
# 代理自发现
# ═══════════════════════════════════════════════════════════

def discover_proxy():
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.environ.get(var)
        if val and (val.startswith("http://") or val.startswith("socks5://")):
            return val, f"环境变量 ${var}"
    for port in PROXY_PORTS:
        for host in ("127.0.0.1", "localhost"):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(PROXY_SCAN_TIMEOUT)
                if s.connect_ex((host, port)) == 0:
                    s.close()
                    proxy = f"http://127.0.0.1:{port}"
                    if _test_proxy(proxy):
                        return proxy, f"端口扫描 {host}:{port}"
                s.close()
            except Exception:
                pass
    for cfg_path in [
        os.path.expanduser("~/.config/clash/config.yaml"),
        os.path.expanduser("~/.config/mihomo/config.yaml"),
        os.path.expanduser("~/.config/clash-verge/config.yaml"),
    ]:
        proxy = _parse_clash_config(cfg_path)
        if proxy and _test_proxy(proxy):
            return proxy, f"Clash 配置 {cfg_path}"
    if sys.platform == "darwin":
        proxy = _macos_system_proxy()
        if proxy and _test_proxy(proxy):
            return proxy, "macOS 系统代理"
    return None, None


def _test_proxy(proxy_url, timeout=3):
    try:
        result = subprocess.run(
            ["curl", "-sI", "--max-time", str(timeout), "--proxy", proxy_url,
             "https://httpbin.org/ip"],
            capture_output=True, text=False, timeout=timeout + 3)
        return result.returncode == 0 and b"origin" in result.stdout
    except Exception:
        return False


def _parse_clash_config(cfg_path):
    try:
        with open(cfg_path, "r") as f:
            content = f.read()
        m = re.search(r"(?:mixed-?port|port|socks-?port):\s*(\d+)", content)
        if m:
            return f"http://127.0.0.1:{m.group(1)}"
    except Exception:
        pass
    return None


def _macos_system_proxy():
    try:
        result = subprocess.run(["networksetup", "-getwebproxy", "Wi-Fi"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            enabled = re.search(r"Enabled:\s*(Yes|No)", result.stdout)
            server = re.search(r"Server:\s*(\S+)", result.stdout)
            port = re.search(r"Port:\s*(\d+)", result.stdout)
            if enabled and enabled.group(1) == "Yes" and server and port:
                return f"http://{server.group(1)}:{port.group(1)}"
    except Exception:
        pass
    return None


def get_proxy(proxy_arg=None):
    if proxy_arg:
        return proxy_arg
    url, _ = discover_proxy()
    return url


# ═══════════════════════════════════════════════════════════
# 镜像管理 (去状态化)
# ═══════════════════════════════════════════════════════════

def load_mirrors():
    try:
        with open(MIRRORS_PATH, "r") as f:
            return json.load(f).get("mirrors", [])
    except Exception:
        return _default_mirrors()


def _default_mirrors():
    return [
        {"domain": "nhentai.net", "aliases": ["nhentai.net", "www.nhentai.net"],
         "type": "primary", "url_pattern": "/g/{id}/", "download_pattern": "/g/{id}/download"},
        {"domain": "nhentai.to", "aliases": ["nhentai.to"],
         "type": "mirror", "url_pattern": "/g/{id}/", "download_pattern": "/g/{id}/download"},
        {"domain": "nhentai.xxx", "aliases": ["nhentai.xxx"],
         "type": "mirror", "url_pattern": "/g/{id}/", "download_pattern": "/g/{id}/download"},
    ]


# 非 nhentai 站点检测 (防止误解析)
NON_NHENTAI_DOMAINS = re.compile(
    r'(?:e-hentai|exhentai|18comic|jmcomic)', re.IGNORECASE)


def extract_gallery_id(raw):
    # 检测非 nhentai URL
    if NON_NHENTAI_DOMAINS.search(raw):
        domain = NON_NHENTAI_DOMAINS.search(raw).group(0)
        return None  # 让调用方提示使用对应脚本
    m = GALLERY_URL_RE.search(raw)
    if m:
        return m.group(1)
    m = GALLERY_ID_RE.match(raw.strip())
    if m:
        return m.group(1)
    return None


def build_urls(gallery_id, mirror=None):
    """构建下载 URL — 不再过滤 status，全部尝试"""
    urls = []
    mirrors = [mirror] if mirror else load_mirrors()
    for m in mirrors:
        domain = m.get("aliases", [m["domain"]])[0]
        scheme = "https"
        gallery_url = f"{scheme}://{domain}{m['url_pattern'].replace('{id}', gallery_id)}"
        download_url = f"{scheme}://{domain}{m['download_pattern'].replace('{id}', gallery_id)}"
        urls.append({"mirror": domain, "gallery_url": gallery_url, "download_url": download_url})
    return urls


# ═══════════════════════════════════════════════════════════
# 搜索 (修复版)
# ═══════════════════════════════════════════════════════════

def _is_cloudflare_page(html):
    """检测 Cloudflare challenge 页面 (多种变体)"""
    if not html:
        return False
    cf_indicators = [
        "Attention Required",
        "Just a moment...",
        "Checking your browser",
        "cf-browser-verification",
        "challenges.cloudflare.com",
    ]
    return any(ind in html for ind in cf_indicators)


def _curl_get(url, proxy=None, timeout=12, accept="text/html"):
    """通用 curl GET (跳过 Cloudflare 页面)"""
    cmd = ["curl", "-sL", "--compressed", "--max-time", str(timeout),
           "--connect-timeout", "8",
           "-H", f"User-Agent: {USER_AGENT}",
           "-H", f"Accept: {accept}"]
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=False, timeout=timeout + 5)
        if result.returncode == 0 and len(result.stdout) > 200:
            text = result.stdout.decode("utf-8", errors="replace")
            if _is_cloudflare_page(text):
                return None  # Cloudflare 拦截页面，丢弃
            return text
    except Exception:
        pass
    return None


def _quick_search_ids(domain, query, proxy, timeout=10):
    """快速搜索并返回 ID 集合 (用于验证搜索结果是否有效)"""
    url = f"https://{domain}/search/?q={quote_plus(query)}&sort=popular"
    html = _curl_get(url, proxy=proxy, timeout=timeout)
    if not html:
        return set()
    return set(SEARCH_ID_RE.findall(html))


def find_working_search_mirror(proxy=None):
    """实时探测可用搜索镜像 — 不依赖存储状态，nhentai.to 优先

    额外验证: 用两个不同搜索词确认搜索结果不同 (排除返回固定热门页面的假搜索)
    """
    mirrors = load_mirrors()

    # 按优先级排序
    def _priority(m):
        domain = m.get("aliases", [m["domain"]])[0]
        try:
            return SEARCH_MIRROR_PRIORITY.index(domain)
        except ValueError:
            return 99

    sorted_mirrors = sorted(mirrors, key=_priority)

    for m in sorted_mirrors:
        domain = m.get("aliases", [m["domain"]])[0]

        # 1. 尝试 API
        api_url = f"https://{domain}/api/galleries/search?query=test"
        resp = _curl_get(api_url, proxy=proxy, timeout=8, accept="application/json")
        if resp:
            try:
                json.loads(resp)
                return f"https://{domain}/api/galleries", True
            except json.JSONDecodeError:
                pass

        # 2. HTML 搜索 + 验证
        ids_a = _quick_search_ids(domain, "chinese", proxy, timeout=10)
        if not ids_a:
            continue
        ids_b = _quick_search_ids(domain, "english", proxy, timeout=10)
        if not ids_b:
            continue
        # 验证: 两个不同搜索词的结果应当有差异 (排除返回固定热门页的假搜索)
        overlap = len(ids_a & ids_b)
        total = min(len(ids_a), len(ids_b))
        if total > 0 and overlap / total < 0.9:
            return f"https://{domain}", False

    return None, None


def search_galleries(query, proxy=None, count=20, sort="popular", page=1, verbose=True):
    base_url, is_api = find_working_search_mirror(proxy)
    if not base_url:
        print("❌ 未找到可用的搜索镜像端点")
        return []
    if is_api:
        return _search_via_api(base_url, query, proxy, count, sort, page, verbose)
    else:
        return _search_via_html(base_url, query, proxy, count, sort, page, verbose)


def _search_via_api(api_base, query, proxy, count, sort, page, verbose):
    url = f"{api_base}/search?query={quote_plus(query)}&sort={sort}&page={page}"
    if verbose:
        p = f" (第{page}页)" if page > 1 else ""
        print(f"🔍 搜索: {query} (API) → {api_base}{p}")
    resp = _curl_get(url, proxy=proxy, timeout=20, accept="application/json")
    if not resp:
        return []
    try:
        data = json.loads(resp)
    except json.JSONDecodeError:
        return []
    results = data.get("result", [])[:count]
    if verbose:
        print(f"   找到 {data.get('num_results', len(results))} 个结果, 显示前 {len(results)} 个")
    galleries = []
    for r in results:
        gid = r.get("id")
        title = r.get("title", {}).get("pretty") or r.get("title", {}).get("english") or "N/A"
        pages = r.get("num_pages", "?")
        artists = [t["name"] for t in r.get("tags", []) if t.get("type") == "artist"]
        language_tags = [t["name"] for t in r.get("tags", []) if t.get("type") == "language"]
        language = language_tags[0] if language_tags else ""
        galleries.append({"id": gid, "title": title, "pages": pages, "artists": artists, "language": language})
        if verbose:
            art_str = f" [{', '.join(artists)}]" if artists else ""
            lang_str = f" ({language})" if language else ""
            print(f"   {gid:>6} | {title[:60]} | {pages}p{art_str}{lang_str}")
    return galleries


def _search_via_html(base_url, query, proxy, count, sort, page, verbose):
    url = f"{base_url}/search/?q={quote_plus(query)}&sort={sort}&page={page}"
    if verbose:
        p = f" (第{page}页)" if page > 1 else ""
        print(f"🔍 搜索: {query} (HTML) → {base_url}{p}")
    html = _curl_get(url, proxy=proxy, timeout=20)
    if not html:
        return []

    # 提取画像卡片区块，确保 ID 和标题配对
    # nhentai 搜索结果每个画廊是一个 <div class="gallery"> 包含 /g/ID/ 链接和 caption
    gallery_blocks = re.split(r'<div[^>]*class="[^"]*gallery[^"]*"', html)[1:]
    galleries = []
    seen_ids = set()

    for block in gallery_blocks:
        if len(galleries) >= count:
            break
        id_m = SEARCH_ID_RE.search(block)
        title_m = SEARCH_TITLE_RE.search(block)
        if id_m:
            gid = id_m.group(1)
            if gid in seen_ids:
                continue
            seen_ids.add(gid)
            title = title_m.group(1) if title_m else "N/A"
            galleries.append({"id": gid, "title": title, "pages": "?", "artists": []})

    # 如果 block 分割失败，回退到旧方法
    if not galleries:
        ids = SEARCH_ID_RE.findall(html)
        titles = SEARCH_TITLE_RE.findall(html)
        for i, gid in enumerate(ids):
            if gid in seen_ids:
                continue
            seen_ids.add(gid)
            if len(galleries) >= count:
                break
            title = titles[i] if i < len(titles) else "N/A"
            galleries.append({"id": gid, "title": title, "pages": "?", "artists": []})

    if verbose:
        print(f"   找到 {len(galleries)} 个结果")
        for g in galleries:
            print(f"   {g['id']:>6} | {g['title'][:60]}")

    return galleries


# ── 中文过滤 ──────────────────────────────────────────────
CHINESE_LANG_TAGS = {"chinese", "translated", "chinese-translated"}
CHINESE_TITLE_PATTERNS = [
    "chinese", "中文", "漢化", "汉化", "中翻", "中国翻訳",
    "中文本", "中国語", "chinese translated",
]


def _is_chinese_gallery(g):
    """判断画廊是否为中文 (优先用 API 返回的 language 字段，回退到标题匹配)"""
    lang = g.get("language", "").lower().replace(" ", "-")
    if lang in CHINESE_LANG_TAGS or "chinese" in lang:
        return True
    if lang == "translated":
        return True
    title = g.get("title", "").lower()
    return any(p in title for p in CHINESE_TITLE_PATTERNS)


def random_gallery(query=None, proxy=None, verbose=True):
    if query:
        galleries = search_galleries(query, proxy=proxy, count=50, sort="popular", verbose=verbose)
    else:
        galleries = search_galleries("chinese", proxy=proxy, count=25, sort="popular", verbose=verbose)
    if not galleries:
        print("❌ 没有找到任何画廊")
        return None
    chosen = random.choice(galleries)
    if verbose:
        print(f"\n🎲 随机选中: [{chosen['id']}] {chosen['title'][:60]} ({chosen['pages']}p)")
    return str(chosen["id"])


# ═══════════════════════════════════════════════════════════
# 图片直接下载 (--dl)
# ═══════════════════════════════════════════════════════════

def download_images(gallery_id, output_dir=None, proxy=None, max_workers=8, verbose=True):
    """逐页下载画廊图片"""
    # 1. 获取画廊页面，提取图片 URL 和页数
    urls_config = build_urls(gallery_id)
    html = None
    used_mirror = None
    for cfg in urls_config:
        html = _curl_get(cfg["gallery_url"], proxy=proxy, timeout=15)
        if html:
            used_mirror = cfg["mirror"]
            break
    if not html:
        print("❌ 无法访问画廊页面")
        return False

    title = extract_title(html) or gallery_id
    # 提取页数
    pages_m = NUMPAGES_RE.search(html)
    total_pages = int(pages_m.group(1)) if pages_m else 0

    # 提取 CDN 图片 URL 模式 — 支持多种 CDN (zrocdn.xyz, i.nhentai.xxx, etc.)
    img_urls = []
    media_id = None

    # 通用缩略图 URL 提取
    THUMB_GENERIC_RE = re.compile(
        r'(?:data-src|src)=["\'](https?://[^"\']*/galleries/(\d+)/(\d+)t\.[^"\']+)["\']',
        re.IGNORECASE)

    for m in THUMB_GENERIC_RE.finditer(html):
        src = m.group(1)
        mid = m.group(2)
        pagenum = int(m.group(3))
        if not media_id:
            media_id = mid
        img_urls.append((pagenum, src))

    if not media_id:
        print("❌ 无法解析图片 CDN 地址")
        return False

    # 从缩略图数量推断总页数
    if img_urls:
        max_thumb_page = max(p for p, _ in img_urls)
        if not total_pages:
            total_pages = max_thumb_page

    # 2. 确定输出目录
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:80]
    if not output_dir:
        output_dir = os.path.join(os.getcwd(), f"nhentai_{gallery_id}_{safe_title}")
    os.makedirs(output_dir, exist_ok=True)

    # 3. 构建图片 URL 列表 — 从缩略图推断完整图片 URL
    if not img_urls:
        print("❌ 未找到缩略图")
        return False

    # 从第一个缩略图推断 CDN 前缀和扩展名
    _, first_thumb = img_urls[0]
    parsed = urlparse(first_thumb)
    cdn_prefix = f"{parsed.scheme}://{parsed.netloc}"

    # 提取扩展名和路径前缀
    ext_m = re.search(r'(\d+)t\.(jpg|png|webp|gif)', first_thumb, re.IGNORECASE)
    if not ext_m:
        print("❌ 无法解析图片扩展名")
        return False
    ext = ext_m.group(2)
    # 构建 URL 模板: /galleries/{media_id}/{page}.{ext}
    path_prefix = re.sub(r'\d+t\.\w+$', '', parsed.path)  # 去掉 1t.jpg 部分

    # 尝试的格式列表 — 按质量优先级排序，自动选体积最大的
    QUALITY_FORMATS = ["jpg", "png", "webp", "gif"]

    if verbose:
        print(f"\n📥 图片下载: {title}")
        print(f"   镜像: {used_mirror}  页数: {total_pages or '?'}")
        print(f"   输出: {output_dir}")
        print(f"   质量: 自动优选 (jpg > png > webp > gif)")

    # 4. 并发下载 — 每页尝试多种格式，选体积最大的
    download_items = []
    for page in range(1, total_pages + 1):
        download_items.append(page)

    success = 0
    first_resolution = None

    # 图片魔数用于验证真实图片
    IMAGE_MAGIC = (b'\xff\xd8', b'\x89PNG', b'RIFF', b'GIF8')

    def _dl_one(page):
        best_path = None
        best_size = 0
        best_ext = None

        # 找到第一个成功格式后缓存其余尝试（大部分同一CDN只用一种格式）
        tried_formats = set()

        for fmt in QUALITY_FORMATS:
            url = f"{cdn_prefix}{path_prefix}{page}.{fmt}"
            out_path = os.path.join(output_dir, f"{page:04d}.{fmt}")
            # 检查缓存 — 必须是真实图片
            if os.path.exists(out_path) and os.path.getsize(out_path) > 2000:
                try:
                    with open(out_path, 'rb') as fh:
                        if fh.read(4).startswith(IMAGE_MAGIC):
                            if os.path.getsize(out_path) > best_size:
                                best_path = out_path
                                best_size = os.path.getsize(out_path)
                                best_ext = fmt
                            continue
                except:
                    pass
                os.remove(out_path)  # 缓存无效

            cmd = ["curl", "-sL", "-f", "--max-time", "30", "--connect-timeout", "10",
                   "-o", out_path,
                   "-H", f"User-Agent: {USER_AGENT}",
                   "-H", "Referer: https://nhentai.to/"]
            if proxy:
                cmd.extend(["--proxy", proxy])
            cmd.append(url)
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=35)
                if os.path.exists(out_path) and os.path.getsize(out_path) > 2000:
                    # 验证是真实图片
                    try:
                        with open(out_path, 'rb') as fh:
                            magic = fh.read(4)
                        if magic.startswith(IMAGE_MAGIC):
                            sz = os.path.getsize(out_path)
                            if sz > best_size:
                                if best_path:
                                    os.remove(best_path)
                                best_path = out_path
                                best_size = sz
                                best_ext = fmt
                        else:
                            os.remove(out_path)  # HTML或无效数据
                    except:
                        os.remove(out_path)
                elif os.path.exists(out_path):
                    os.remove(out_path)  # 空/太小
            except Exception:
                if os.path.exists(out_path):
                    os.remove(out_path)

        if best_path and best_ext != best_path.split('.')[-1]:
            # 统一扩展名
            final_path = os.path.join(output_dir, f"{page:04d}.{best_ext}")
            if best_path != final_path:
                os.rename(best_path, final_path)
                best_path = final_path

        return page, bool(best_path), best_ext or "?", best_size

    if verbose:
        print(f"   下载中... ({max_workers} 线程)")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_dl_one, item): item for item in download_items}
        for f in as_completed(futures):
            page, ok, chosen_fmt, size = f.result()
            if ok:
                success += 1
                if first_resolution is None:
                    # 检测首张图片分辨率
                    out_path = os.path.join(output_dir, f"{page:04d}.{chosen_fmt}")
                    first_resolution = _get_image_resolution(out_path)
                if verbose:
                    res_str = f" {first_resolution}" if first_resolution and page == 1 else ""
                    size_str = pretty_size(size) if size else ""
                    print(f"   ✓ 第{page}页 [{chosen_fmt}] {size_str}{res_str}")
            else:
                if verbose:
                    print(f"   ✗ 第{page}页")

    if verbose:
        # 下载后自动验证清理
        removed = _cleanup_invalid_files(output_dir, verbose)
        total_size = sum(
            os.path.getsize(os.path.join(output_dir, f))
            for f in os.listdir(output_dir)
            if os.path.isfile(os.path.join(output_dir, f))
        )
        res_info = f"  {first_resolution}" if first_resolution else ""
        clean_info = f"  (清理{removed}无效)" if removed else ""
        print(f"\n✅ 下载完成: {success}/{len(download_items)} 页{res_info}  ({pretty_size(total_size)}){clean_info} → {output_dir}")

    return success > 0


def _cleanup_invalid_files(directory, verbose=False):
    """清理目录中的无效图片文件，返回删除数量"""
    IMG_MAGIC = (b'\xff\xd8', b'\x89PNG', b'RIFF', b'GIF8')
    removed = 0
    for f in os.listdir(directory):
        fp = os.path.join(directory, f)
        if not os.path.isfile(fp): continue
        sz = os.path.getsize(fp)
        if sz < 2000:
            os.remove(fp); removed += 1; continue
        try:
            with open(fp, 'rb') as fh:
                if not fh.read(4).startswith(IMG_MAGIC):
                    os.remove(fp); removed += 1
        except: pass
    return removed


def _get_image_resolution(path):
    """获取图片分辨率"""
    try:
        # 用 Python 标准库检测
        with open(path, 'rb') as f:
            header = f.read(32)
        # WebP
        if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
            # VP8/VP8L/VP8X
            if header[12:16] in (b'VP8 ', b'VP8L'):
                w = int.from_bytes(header[26:28], 'little') if header[12:16] == b'VP8 ' else 0
                h = int.from_bytes(header[28:30], 'little') if header[12:16] == b'VP8 ' else 0
                if header[12:16] == b'VP8L':
                    bits = int.from_bytes(header[21:25], 'little')
                    w = (bits & 0x3FFF) + 1
                    h = ((bits >> 14) & 0x3FFF) + 1
                return f"{w}x{h}"
            elif header[12:16] == b'VP8X':
                w = int.from_bytes(header[24:27], 'little') + 1
                h = int.from_bytes(header[27:30], 'little') + 1
                return f"{w}x{h}"
        # JPEG
        if header[:2] == b'\xff\xd8':
            return _jpeg_resolution(path)
        # PNG
        if header[:8] == b'\x89PNG\r\n\x1a\n':
            w = int.from_bytes(header[16:20], 'big')
            h = int.from_bytes(header[20:24], 'big')
            return f"{w}x{h}"
    except Exception:
        pass
    return None


def _jpeg_resolution(path):
    """从 JPEG 文件读取分辨率"""
    try:
        with open(path, 'rb') as f:
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2:
                    break
                if marker[0] != 0xFF:
                    break
                if marker[1] in (0xC0, 0xC1, 0xC2):
                    f.read(3)
                    h = int.from_bytes(f.read(2), 'big')
                    w = int.from_bytes(f.read(2), 'big')
                    return f"{w}x{h}"
                length = int.from_bytes(f.read(2), 'big')
                f.seek(length - 2, 1)
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════

def run_check():
    print("🔬 dl4henga nhentai v3 健康自检")
    print("=" * 50)
    print("\n📦 依赖检查:")
    deps_ok = True
    for dep, pkg in [("requests", "requests"), ("cloudscraper", "cloudscraper"),
                      ("curl_cffi", "curl_cffi")]:
        try:
            __import__(dep)
            print(f"   ✅ {pkg}")
        except ImportError:
            print(f"   ⚠️  {pkg} — 未安装 (pip install {pkg})")
            deps_ok = False
    print("\n🔧 工具检查:")
    try:
        subprocess.run(["curl", "--version"], capture_output=True, timeout=3)
        print("   ✅ curl")
    except Exception:
        print("   ❌ curl 不可用")
    print("\n🔗 代理检测:")
    proxy_url, source = discover_proxy()
    if proxy_url:
        print(f"   ✅ {proxy_url} (来源: {source})")
    else:
        print("   ⚠️  未检测到代理")
    print("\n🌐 镜像连通性:")
    mirrors = load_mirrors()
    active_count = 0
    for m in mirrors:
        domain = m.get("aliases", [m["domain"]])[0]
        ok = _test_mirror_quick(domain, proxy_url)
        icon = "✅" if ok else "❌"
        print(f"   {icon} {domain}")
        if ok:
            active_count += 1
    print(f"\n   {active_count}/{len(mirrors)} 个镜像可达")
    print("\n🔍 搜索镜像验证:")
    search_base, is_api = find_working_search_mirror(proxy_url)
    if search_base:
        mode = "API" if is_api else "HTML"
        print(f"   ✅ {search_base} ({mode})")
    else:
        print("   ❌ 无可用搜索镜像")
    print(f"\n🖥  平台: {sys.platform}  Python: {sys.version.split()[0]}")
    print("\n💡 建议:")
    if not deps_ok:
        print("   - pip install requests cloudscraper curl_cffi")
    if not proxy_url:
        print("   - 设置代理: export https_proxy=http://127.0.0.1:7890")
    if active_count == 0:
        print("   - 需要代理访问 nhentai")
    print("\n✅ 自检完成")


def _test_mirror_quick(domain, proxy=None, timeout=5):
    try:
        cmd = ["curl", "-sI", "--max-time", str(timeout), "-H", f"User-Agent: {USER_AGENT}"]
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.append(f"https://{domain}/")
        result = subprocess.run(cmd, capture_output=True, text=False, timeout=timeout + 3)
        if result.returncode == 0:
            stdout = result.stdout.decode("utf-8", errors="replace")
            if re.search(r"HTTP/\d\.\d\s+[23]\d\d", stdout):
                return True
        return False
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def parse_size(s):
    m = SIZE_RE.search(s)
    if not m:
        return 0
    value = float(m.group(1).replace(",", ""))
    unit = m.group(2).upper()
    mult = {"B": 1, "KB": 1024, "KIB": 1024, "MB": 1024 ** 2, "MIB": 1024 ** 2,
            "GB": 1024 ** 3, "GIB": 1024 ** 3}
    return int(value * mult.get(unit, 1))


def parse_seeds(text):
    m = SEEDS_RE.search(text)
    return int(m.group(1).replace(",", "")) if m else 0


def pretty_size(n_bytes):
    if n_bytes >= 1024 ** 3:
        return f"{n_bytes / (1024 ** 3):.2f} GB"
    if n_bytes >= 1024 ** 2:
        return f"{n_bytes / (1024 ** 2):.1f} MB"
    if n_bytes >= 1024:
        return f"{n_bytes / 1024:.1f} KB"
    return f"{n_bytes} B"


def extract_title(html):
    for regex in [OG_TITLE_RE, TITLE_RE, H1_RE]:
        m = regex.search(html)
        if m:
            title = m.group(1).strip()
            title = re.sub(r"\s*[-–|»]\s*nhentai.*$", "", title, flags=re.IGNORECASE)
            return title
    return None


def normalize_magnet(url):
    m = re.match(r"https?://keepshare\.org/(?:p/)?[^/]+/(magnet:\?.*)", url, re.IGNORECASE)
    if m:
        url = m.group(1)
    url = url.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return url if url.startswith("magnet:?") else url


# ═══════════════════════════════════════════════════════════
# 抓取层
# ═══════════════════════════════════════════════════════════

def _fetch_cloudscraper(url, proxy=None):
    try:
        import cloudscraper
        kw = {"browser": "chrome", "platform": "darwin", "mobile": False}
        scraper = cloudscraper.create_scraper(browser=kw)
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = scraper.get(url, headers=BROWSER_HEADERS, timeout=25, proxies=proxies)
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text, None
        if resp.status_code == 503:
            return None, "Cloudflare 503"
        return None, f"状态 {resp.status_code}"
    except ImportError:
        return None, "未安装: pip install cloudscraper"
    except Exception as e:
        return None, str(e)


def _fetch_curl_cffi(url, proxy=None):
    try:
        from curl_cffi import requests as curl_requests
        resp = curl_requests.get(url, headers=BROWSER_HEADERS, impersonate="chrome131",
                                 timeout=25, proxy=proxy)
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text, None
        return None, f"状态 {resp.status_code}"
    except ImportError:
        return None, "未安装: pip install curl_cffi"
    except Exception as e:
        return None, str(e)


def _fetch_requests(url, proxy=None):
    try:
        import requests
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        proxies = {"http": proxy, "https": proxy} if proxy else None
        base = re.match(r"(https?://[^/]+)", url)
        if base:
            try:
                session.get(base.group(1), timeout=8, proxies=proxies)
            except Exception:
                pass
        resp = session.get(url, timeout=25, proxies=proxies)
        if resp.status_code == 200 and len(resp.text) > 500:
            return resp.text, None
        return None, f"状态 {resp.status_code}"
    except ImportError:
        return None, "未安装: pip install requests"
    except Exception as e:
        return None, str(e)


def _fetch_curl(url, proxy=None):
    return _curl_get(url, proxy=proxy, timeout=28), None


FETCH_STRATEGIES = [
    (1, _fetch_cloudscraper), (2, _fetch_curl_cffi),
    (3, _fetch_requests), (4, _fetch_curl),
]
MAX_RETRIES = 3
RETRY_BACKOFF = [0, 2, 5]


def fetch_page(url, proxy=None, verbose=True):
    for stage, func in FETCH_STRATEGIES:
        for attempt in range(MAX_RETRIES):
            html, err = func(url, proxy=proxy)
            # 连接错误/拒绝 — 快速失败不重试
            if err and any(kw in str(err).lower() for kw in ('connection refused', 'refused', 'timed out')):
                if verbose and stage < 3:
                    print(f"  ⚠️  第{stage}层 {STAGE_NAMES[stage]} 连接失败，跳过")
                break
            if html and len(html) > 500 and not _is_cloudflare_page(html):
                if verbose:
                    tag = f"(重试{attempt}次)" if attempt > 0 else ""
                    print(f"  ✅ 第{stage}层 {STAGE_NAMES[stage]} {tag} — {len(html)} 字节")
                return html
            if err and ("503" in err or "cloudflare" in err.lower()):
                break
            if attempt < MAX_RETRIES - 1 and "超时" not in str(err):
                if verbose:
                    print(f"  ⏳ {STAGE_NAMES[stage]} 失败, {RETRY_BACKOFF[attempt]}s 后重试...")
                time.sleep(RETRY_BACKOFF[attempt])
        if verbose:
            print(f"  ⚠️  第{stage}层 {STAGE_NAMES[stage]} 不可用 ({err})")
    if verbose:
        print("  ❌ 所有策略均失败")
    return None


# ═══════════════════════════════════════════════════════════
# 解析层
# ═══════════════════════════════════════════════════════════

class DownloadLinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.candidates = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for attr in ("href", "data-link", "data-magnet", "data-href", "data-url", "src"):
            val = attrs.get(attr, "")
            if not val:
                continue
            if val.startswith("magnet:?"):
                self.candidates.append(
                    {"url": val, "type": "magnet", "size_bytes": 0, "seeds": 0,
                     "source": f"html_{attr}"})
                return
            if "keepshare.org" in val and "magnet" in val:
                self.candidates.append(
                    {"url": val, "type": "magnet", "size_bytes": 0, "seeds": 0,
                     "source": "keepshare"})
                return
            if val.lower().endswith(".torrent"):
                self.candidates.append(
                    {"url": val, "type": "torrent", "size_bytes": 0, "seeds": 0,
                     "source": f"html_{attr}"})
                return
            if val.lower().startswith("ftp://"):
                self.candidates.append(
                    {"url": val, "type": "ftp", "size_bytes": 0, "seeds": 0,
                     "source": f"html_{attr}"})
                return
            if re.search(r"""\.(?:zip|rar|7z|cbz|cbr|pdf)(?:\?|$|&)""", val, re.IGNORECASE):
                self.candidates.append(
                    {"url": val, "type": "http", "size_bytes": 0, "seeds": 0,
                     "source": f"html_{attr}"})


def extract_candidates(html):
    seen = set()
    cands = []
    parser = DownloadLinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    for c in parser.candidates:
        url = normalize_magnet(c["url"])
        if url not in seen:
            seen.add(url)
            cands.append(c)
    for pat, ctype, src in [
        (MAGNET_RE, "magnet", "magnet_re"), (KEEPSHARE_RE, "magnet", "keepshare_re"),
        (TORRENT_FILE_RE, "torrent", "torrent_re"), (DIRECT_HTTP_RE, "http", "http_re"),
        (FTP_RE, "ftp", "ftp_re"),
    ]:
        for m in pat.finditer(html):
            url = normalize_magnet(m.group(1) if ctype == "http" else m.group(0))
            if url not in seen:
                seen.add(url)
                cands.append({"url": url, "type": ctype, "size_bytes": 0, "seeds": 0,
                              "source": src})
    for c in cands:
        sm = re.search(r"""[&?]size=(\d+)""", c["url"], re.IGNORECASE)
        if sm:
            c["size_bytes"] = int(sm.group(1))
        if c["size_bytes"] == 0 or c["seeds"] == 0:
            identifier = ""
            if c["type"] == "magnet":
                btih_m = re.search(r"btih:([a-fA-F0-9]{32,60})", c["url"])
                if btih_m:
                    identifier = btih_m.group(1)
            elif c["url"].endswith(".torrent"):
                identifier = c["url"].rsplit("/", 1)[-1][:30]
            else:
                identifier = re.escape(c["url"][-60:])
            if identifier:
                idx = html.find(identifier)
                if idx >= 0:
                    context = html[max(0, idx - 500): idx + 500]
                    if c["size_bytes"] == 0:
                        sm = SIZE_RE.search(context)
                        if sm:
                            c["size_bytes"] = parse_size(sm.group(0))
                    if c["seeds"] == 0:
                        c["seeds"] = parse_seeds(context)
    return cands


def sort_candidates(cands):
    def type_rank(t):
        return {"magnet": 0, "torrent": 1, "http": 2, "ftp": 3}.get(t, 9)

    return sorted(cands, key=lambda c: (
        type_rank(c.get("type", "http")), -c.get("seeds", 0),
        -c.get("size_bytes", 0), len(c.get("url", "")), c.get("url", "")))


# ═══════════════════════════════════════════════════════════
# 镜像选择 (尝试所有，不依赖状态)
# ═══════════════════════════════════════════════════════════

def try_mirrors(gallery_id, proxy=None, verbose=True, max_mirrors=6):
    urls_config = build_urls(gallery_id)
    # nhentai.to 优先 (比 net 更可靠，Cloudflare少)
    priority = {"nhentai.to": 0, "nhentai.xxx": 1, "nhentai.net": 2}
    urls_config.sort(key=lambda x: priority.get(x["mirror"], 9))
    for i, cfg in enumerate(urls_config[:max_mirrors]):
        if verbose and i > 0:
            print(f"  🔄 尝试镜像: {cfg['mirror']}")
        if verbose:
            print(f"  🌐 {cfg['download_url']}")
        html = fetch_page(cfg["download_url"], proxy=proxy, verbose=verbose)
        if html:
            return html, cfg["mirror"]
    for i, cfg in enumerate(urls_config[:max_mirrors]):
        if verbose:
            print(f"  🔄 尝试 gallery 页面: {cfg['mirror']}")
        html = fetch_page(cfg["gallery_url"], proxy=proxy, verbose=verbose)
        if html:
            return html, cfg["mirror"]
    return None, None


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def process_input(raw, proxy=None, verbose=True, batch=False, dl_fallback=False, dl_output_dir=None):
    # 检测非 nhentai 站点
    if NON_NHENTAI_DOMAINS.search(raw):
        domain = NON_NHENTAI_DOMAINS.search(raw).group(0)
        site_map = {
            'e-hentai': 'ehentai_dl.py', 'exhentai': 'ehentai_dl.py',
            '18comic': 'jmcomic_dl.py', 'jmcomic': 'jmcomic_dl.py',
        }
        script = site_map.get(domain.lower(), '???')
        msg = f"⚠️  这是 {domain} 的链接，请用 scripts/{script} 下载"
        if batch:
            print(f"  {msg}")
        elif verbose:
            print(msg)
        return None

    gallery_id = extract_gallery_id(raw)
    if not gallery_id:
        msg = f"❌ 无法识别为 nhentai 画廊 ID 或 URL: {raw[:60]}"
        if batch:
            print(f"  {msg}")
        elif verbose:
            print(msg)
        return None

    if verbose and not batch:
        print(f"\n{'─' * 60}")
        print(f"▸ 画廊 ID: {gallery_id}  (来源: {raw[:80]})")

    html, used_mirror = try_mirrors(gallery_id, proxy=proxy, verbose=(verbose and not batch))
    if not html:
        if batch:
            print(f"  ❌ {gallery_id} — 所有镜像均无法访问")
        return None

    title = extract_title(html)
    if title and verbose and not batch:
        print(f"  📖 {title}")

    cands = extract_candidates(html)
    if not cands:
        # 无下载链接 — 提供回退
        gurl = f"https://{used_mirror}/g/{gallery_id}/" if used_mirror else f"https://nhentai.to/g/{gallery_id}/"
        if dl_fallback:
            if verbose:
                print("  ⚠️  无种子/直链，切换到逐页图片下载...")
            ok = download_images(gallery_id, proxy=proxy, verbose=verbose, output_dir=dl_output_dir)
            if ok:
                return {"gallery_id": gallery_id, "title": title, "best_link": "图片下载",
                        "link_type": "dl", "best_size": "N/A", "best_seeds": 0,
                        "total_candidates": 0, "mirror_used": used_mirror}
            return None
        else:
            if batch:
                print(f"  ⚠️  {gallery_id} — 无下载链接 (可用 --dl 逐页下载)")
            elif verbose:
                print(f"  ⚠️  未找到下载链接")
                print(f"  💡 画廊链接: {gurl}")
                print(f"  💡 逐页下载: python3 nhentai_dl.py --dl {gallery_id}")
            else:
                print(gurl)
            return None

    cands = sort_candidates(cands)
    best = cands[0]

    if batch:
        size = pretty_size(best.get("size_bytes", 0)) if best.get("size_bytes") else "?"
        seeds = f"{best.get('seeds', 0)}S" if best.get("seeds") else ""
        tag = title or gallery_id
        extra = f"{size} {seeds}".strip()
        print(f"  ✓ {tag[:40]:<40} {extra:>15}  {best['url'][:80]}")
    elif verbose:
        type_icons = {"magnet": "🧲", "torrent": "📥", "http": "🌐", "ftp": "📁"}
        print(f"\n  📋 {len(cands)} 个候选 (镜像: {used_mirror}):")
        for i, c in enumerate(cands):
            icon = type_icons.get(c.get("type", "http"), "❓")
            size = pretty_size(c.get("size_bytes", 0)) if c.get("size_bytes") else "?"
            seeds = f" 种子:{c.get('seeds', '-')}" if c.get("seeds") else ""
            star = " ★" if i == 0 else "  "
            short = c["url"]
            if len(short) > 90:
                short = short[:87] + "..."
            print(f"   {star} [{i + 1}] {icon} {size:>8}{seeds}  {short}")
        link_type = {"magnet": "磁力链接", "torrent": "BT 种子", "http": "HTTP 直链", "ftp": "FTP"}.get(
            best.get("type", "http"), "下载链接")
        print(f"\n  ✅ 最佳{link_type}:")
        print(f"  {best['url']}")

    return {
        "gallery_id": gallery_id, "title": title,
        "best_link": best["url"], "link_type": best.get("type", "http"),
        "best_size": pretty_size(best.get("size_bytes", 0)) if best.get("size_bytes") else "未知",
        "best_seeds": best.get("seeds", 0),
        "total_candidates": len(cands), "mirror_used": used_mirror,
    }


def copy_to_clipboard(text):
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="nhentai/nxhentai 最佳下载方式提取器 v3",
        epilog="示例:\n"
               "  python3 nhentai_dl.py 177013\n"
               "  python3 nhentai_dl.py --search \"artist name\"\n"
               "  python3 nhentai_dl.py --random --tag \"artist name\"\n"
               "  python3 nhentai_dl.py --dl 604716\n"
               "  python3 nhentai_dl.py --check",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", help="nhentai URL 或画廊 ID")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式")
    parser.add_argument("-c", "--clipboard", action="store_true", help="复制到剪贴板 (macOS)")
    parser.add_argument("-j", "--json", action="store_true", help="JSON 输出")
    parser.add_argument("-o", "--output", metavar="DIR", help="输出目录")
    parser.add_argument("-p", "--proxy", metavar="PROXY", help="代理地址")
    parser.add_argument("-b", "--batch", action="store_true", help="批量模式")
    parser.add_argument("--all", action="store_true", help="显示所有候选")
    parser.add_argument("--update-mirrors", action="store_true", help="更新镜像列表")
    parser.add_argument("--check", action="store_true", help="健康自检")
    parser.add_argument("--search", metavar="QUERY", help="搜索画廊")
    parser.add_argument("--random", action="store_true", help="随机推荐")
    parser.add_argument("--tag", metavar="TAG", help="搜索过滤 (配合 --search/--random)")
    parser.add_argument("--count", type=int, default=20, help="搜索结果数量")
    parser.add_argument("--page", type=int, default=1, help="搜索页码")
    parser.add_argument("--sort", choices=["popular", "recent"], default="popular", help="排序")
    parser.add_argument("--chinese", action="store_true", help="搜索时过滤只显示中文结果")
    parser.add_argument("--artist-dl", metavar="ARTIST", help="搜索并下载某艺术家的全部作品")
    parser.add_argument("--dl", action="store_true", help="无种子时回退逐页下载")
    parser.add_argument("--dl-threads", type=int, default=8, help="下载线程数")
    parser.add_argument("--dl-dir", metavar="DIR", help="同 --output")
    args = parser.parse_args()

    if args.update_mirrors:
        updater = os.path.join(SCRIPT_DIR, "update_mirrors.py")
        if os.path.exists(updater):
            subprocess.run([sys.executable, updater])
        else:
            print("⚠️  update_mirrors.py 未找到")
        return

    if args.check:
        run_check()
        return

    proxy = get_proxy(args.proxy)
    if proxy and not args.quiet and not args.json:
        if args.proxy:
            print(f"🔗 使用代理: {proxy}")
            # 快速预检代理可用性
            if not _test_proxy(proxy, timeout=3):
                print(f"⚠️  代理 {proxy} 不可用，尝试直连...")
                proxy = None
        else:
            _, source = discover_proxy()
            print(f"🔗 自动检测代理: {proxy} (来源: {source})")

    if args.search or (args.random and args.tag):
        query = args.search or args.tag
        if args.random:
            gid = random_gallery(query, proxy=proxy, verbose=not args.quiet)
            if gid:
                args.inputs = [gid]
            else:
                sys.exit(1)
        else:
            galleries = search_galleries(query, proxy=proxy, count=args.count,
                                         sort=args.sort, page=args.page, verbose=not args.quiet)
            if args.chinese:
                galleries = [g for g in galleries if _is_chinese_gallery(g)]
            if args.json:
                print(json.dumps(galleries, ensure_ascii=False, indent=2))
            if not galleries:
                sys.exit(1)
            if not args.json:
                print(f"\n💡 提取下载链接: python3 nhentai_dl.py {' '.join(str(g['id']) for g in galleries[:5])} ...")
                print(f"💡 逐页下载: python3 nhentai_dl.py --dl {' '.join(str(g['id']) for g in galleries[:3])} ...")
            return

    if args.artist_dl:
        name = args.artist_dl
        print(f"🎨 搜索并下载 {name} 全部作品...")
        galleries = search_galleries(name, proxy=proxy, count=100, verbose=not args.quiet)
        if args.chinese:
            galleries = [g for g in galleries if _is_chinese_gallery(g)]
            print(f"   中文过滤后: {len(galleries)} 个")
        if not galleries:
            print("❌ 未找到作品")
            sys.exit(1)
        ids = [g['id'] for g in galleries]
        if not args.quiet:
            print(f"\n📥 开始下载 {len(ids)} 个作品...")
            for g in galleries:
                print(f"   {g['id']} | {g['title'][:60]}")
        args.inputs = ids
        args.dl = True  # 强制启用逐页下载

    if args.random and not args.tag and not args.search:
        gid = random_gallery(proxy=proxy, verbose=not args.quiet)
        if gid:
            args.inputs = [gid]
        else:
            sys.exit(1)

    inputs = list(args.inputs)
    if not inputs and not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        inputs = re.findall(r"(?:https?://[^\s]+|\d{1,6})", data)

    if not inputs:
        parser.print_help()
        print("\n💡 用法示例:")
        print("  python3 nhentai_dl.py 177013")
        print("  python3 nhentai_dl.py --search \"artist\"")
        print("  python3 nhentai_dl.py --dl 604716")
        print("  python3 nhentai_dl.py --check")
        sys.exit(1)

    verbose = not args.quiet and not args.json
    batch = args.batch or (len(inputs) >= 10 and not args.quiet and not args.json)
    max_workers = min(3, len(inputs)) if batch else min(5, len(inputs))
    if batch:
        verbose = False

    results = []
    dl_dir = getattr(args, 'dl_dir', None) or getattr(args, 'output', None)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(process_input, inp, proxy, verbose, batch, args.dl, dl_dir): inp
                   for inp in inputs}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)

    if not results:
        if not args.quiet:
            print("\n❌ 所有输入均未能提取到下载链接")
        sys.exit(1)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.quiet:
        for r in results:
            print(r["best_link"])
    elif batch:
        print(f"\n{'=' * 60}")
        print(f"✅ 完成 — {len(results)}/{len(inputs)} 成功")
        for r in results:
            print(f"  {r['best_link']}")
    else:
        print(f"\n{'=' * 60}")
        print(f"✅ 完成 — {len(results)}/{len(inputs)} 成功\n")
        for r in results:
            type_icons = {"magnet": "🧲", "torrent": "📥", "http": "🌐", "ftp": "📁", "dl": "🖼️"}
            icon = type_icons.get(r.get("link_type", "http"), "❓")
            seeds = f" [种子:{r.get('best_seeds', 0)}]" if r.get("best_seeds") else ""
            print(f"  {icon} [{r.get('gallery_id', '?')}] {r['best_link']}{seeds}")

    if args.clipboard and results:
        text = "\n".join(r["best_link"] for r in results)
        if copy_to_clipboard(text):
            print("📋 已复制到剪贴板")

    if args.output:
        with open(args.output, "w") as f:
            for r in results:
                f.write(r["best_link"] + "\n")
        if not args.quiet:
            print(f"💾 已保存到 {args.output}")

    if args.all and not args.quiet and not args.json:
        for r in results:
            print(f"\n  [全部候选] {r.get('title') or r['gallery_id']}:")
            print(f"  最佳: {r['best_link']}  ({r['best_size']}, 种子:{r.get('best_seeds', '-')})")


if __name__ == "__main__":
    main()
