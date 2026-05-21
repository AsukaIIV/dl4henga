#!/usr/bin/env python3
"""
E-Hentai / ExHentai 画廊下载器  v1
===================================
从 e-hentai.org / exhentai.org 下载画廊图片。

特性:
  - 支持 e-hentai.org 和 exhentai.org
  - 逐页图片下载 (自动最高清)
  - Cookie 认证支持 (exhentai 需要)
  - 原生 Archive 下载优先
  - 代理支持

用法:
  python3 ehentai_dl.py <url>
  python3 ehentai_dl.py -c "cookie_string" <url>
  python3 ehentai_dl.py -p <proxy> <url>
  python3 ehentai_dl.py --check
"""

import re
import sys
import os
import time
import json
import random
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote_plus
from html.parser import HTMLParser

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY_PORTS = [7890, 7897, 1087, 8118, 10808, 10809, 8080]

# 凭证管理
sys.path.insert(0, SCRIPT_DIR)
try:
    from credentials import get_credentials
    _CREDS = get_credentials()
except ImportError:
    _CREDS = {}

# ── URL 解析 ──────────────────────────────────────────────
GALLERY_URL_RE = re.compile(
    r"""(?:exhentai|e-hentai)\.org/g/(\d+)/([a-f0-9]{10})/?""", re.IGNORECASE)

TAG_URL_RE = re.compile(
    r"""(?:exhentai|e-hentai)\.org/tag/([^/?]+)""", re.IGNORECASE)

# 从搜索结果/标签页提取画廊链接
SEARCH_LINK_RE = re.compile(r'/g/(\d+)/([a-f0-9]{10})/?', re.IGNORECASE)

IMAGE_PAGE_RE = re.compile(
    r"""href="(https?://(?:exhentai|e-hentai)\.org/s/[^"]+/(\d+)-(\d+))""", re.IGNORECASE)

FULL_IMG_RE = re.compile(
    r"""<img\s+id="img"[^>]*src="([^"]+)"[^>]*>""", re.IGNORECASE)

ORIGINAL_IMG_RE = re.compile(
    r"""href="([^"]+)"[^>]*>\s*Download\s+original""", re.IGNORECASE)

TITLE_RE = re.compile(r"""<h1[^>]*id="g[jn]"[^>]*>(.*?)</h1>""", re.IGNORECASE)
PAGES_RE = re.compile(r"""(\d+)\s*pages""", re.IGNORECASE)
ARCHIVE_RE = re.compile(
    r"""href="(https?://(?:exhentai|e-hentai)\.org/archiver\.php[^"]+)"[^>]*>""", re.IGNORECASE)


def extract_gallery_info(url):
    """提取画廊 ID 和 token"""
    m = GALLERY_URL_RE.search(url)
    if m:
        return m.group(1), m.group(2), m.group(0)
    return None, None, None


# ── 通用 curl GET ─────────────────────────────────────────

def _curl_get(url, proxy=None, cookies=None, timeout=15, referer=None):
    cmd = ["curl", "-sL", "--compressed", "--max-time", str(timeout),
           "--connect-timeout", "10",
           "-H", f"User-Agent: {USER_AGENT}",
           "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"]
    if proxy:
        cmd.extend(["--proxy", proxy])
    if cookies:
        if isinstance(cookies, dict):
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        else:
            cookie_str = cookies
        cmd.extend(["-H", f"Cookie: {cookie_str}"])
    if referer:
        cmd.extend(["-H", f"Referer: {referer}"])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=False, timeout=timeout + 5)
        if result.returncode == 0 and len(result.stdout) > 200:
            return result.stdout.decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


# ── 代理自发现 ────────────────────────────────────────────

def discover_proxy():
    import socket
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.environ.get(var)
        if val and val.startswith("http"):
            return val
    for port in PROXY_PORTS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                s.close()
                return f"http://127.0.0.1:{port}"
            s.close()
        except Exception:
            pass
    return None


# ── 画廊信息抓取 ──────────────────────────────────────────

def fetch_gallery_info(gid, token, proxy=None, cookies=None, verbose=True):
    """获取画廊元信息"""
    for domain in ["e-hentai.org", "exhentai.org"]:
        url = f"https://{domain}/g/{gid}/{token}/"
        if verbose:
            print(f"  🌐 尝试: {domain}")
        html = _curl_get(url, proxy=proxy, cookies=cookies, timeout=20)
        if not html:
            continue
        if "This IP address has been temporarily banned" in html:
            ban_m = re.search(r'(\d+)\s*minutes?', html)
            if ban_m:
                mins = int(ban_m.group(1))
                if verbose:
                    print(f"  ⏳ IP 被 {domain} 封禁 {mins} 分钟，等待中...")
                time.sleep(min(mins * 60, 300))
                html = _curl_get(url, proxy=proxy, cookies=cookies, timeout=20)
                if html and "banned" not in html:
                    continue
            print(f"  ❌ IP 被 {domain} 暂时封禁")
            continue
        if "Content Warning" in html or "exhentai.org" in html.lower() and "Gallery Not Available" in html:
            continue

        # 提取标题
        title_m = TITLE_RE.search(html)
        title = title_m.group(1).strip() if title_m else "Unknown"

        # 提取页数
        pages_m = PAGES_RE.search(html)
        total_pages = int(pages_m.group(1)) if pages_m else 0

        # 提取图片页面 URL 列表
        img_pages = []
        for m in IMAGE_PAGE_RE.finditer(html):
            img_pages.append({
                "url": m.group(1),
                "gid": m.group(2),
                "page": int(m.group(3)),
            })

        # 检查 Archive 下载
        archive_url = None
        arch_m = ARCHIVE_RE.search(html)
        if arch_m:
            archive_url = arch_m.group(1)

        info = {
            "gid": gid, "token": token, "title": title,
            "total_pages": total_pages or len(img_pages),
            "image_pages": img_pages,
            "archive_url": archive_url,
            "domain": domain,
        }

        if verbose:
            print(f"  ✅ 成功 ({domain})")
            print(f"  📖 {title}")
            print(f"  📄 {info['total_pages']} 页")

        return info

    return None


# ── 单张图片 URL 提取 ─────────────────────────────────────

def fetch_image_url(img_page_url, proxy=None, cookies=None, timeout=15):
    """从图片页面提取全尺寸图片 URL"""
    referer = re.sub(r'/s/[^/]+/', '/g/', img_page_url.rsplit('-', 1)[0] + '/')
    html = _curl_get(img_page_url, proxy=proxy, cookies=cookies, timeout=timeout, referer=referer)
    if not html:
        return None

    # 1. 尝试找 Download original 链接 (最高清)
    orig_m = ORIGINAL_IMG_RE.search(html)
    if orig_m:
        return orig_m.group(1)

    # 2. 找 img#img
    img_m = FULL_IMG_RE.search(html)
    if img_m:
        return img_m.group(1)

    # 3. 通用 img src 提取
    m = re.search(r'<img[^>]+src="(https?://[^"]+)"[^>]*>', html)
    if m and '/fullimg/' not in m.group(1):
        return m.group(1)

    return None


# ── 图片下载 ──────────────────────────────────────────────

def search_tag(tag, page=1, proxy=None, cookies=None, verbose=True):
    """搜索标签，返回画廊列表 [(gid, token, domain), ...]"""
    domain = "e-hentai.org"
    url = f"https://{domain}/tag/{quote_plus(tag)}?page={page}"
    if verbose:
        print(f"🔍 E-Hentai 标签: {tag} (第{page}页)")
    html = _curl_get(url, proxy=proxy, cookies=cookies, timeout=20)
    if not html:
        return []

    seen = set()
    galleries = []
    for m in SEARCH_LINK_RE.finditer(html):
        gid = m.group(1)
        if gid in seen:
            continue
        seen.add(gid)
        token = m.group(2)
        galleries.append((gid, token, domain))

    if verbose:
        print(f"   找到 {len(galleries)} 个画廊")
        for gid, token, _ in galleries[:10]:
            print(f"   /g/{gid}/{token}/")

    return galleries


# ── 新增: 标题搜索正则 ────────────────────────────────────
SEARCH_TITLE_RE = re.compile(r'<div class="it5"[^>]*>\s*<a[^>]*>([^<]+)</a>', re.IGNORECASE)
SEARCH_CATEGORY_RE = re.compile(r'<div class="cs"[^>]*>\s*<div[^>]*>([^<]+)</div>', re.IGNORECASE)


def search_galleries(query, proxy=None, cookies=None, count=20, verbose=True):
    """E-Hentai 关键词搜索 (?f_search=), 返回标准化结果列表 [{id, title, pages, url}, ...]"""
    domain = "e-hentai.org"
    url = f"https://{domain}/?f_search={quote_plus(query)}"
    if verbose:
        print(f"🔍 E-Hentai 搜索: {query}")
    html = _curl_get(url, proxy=proxy, cookies=cookies, timeout=20)
    if not html:
        return []

    # 增加页数匹配
    # E-Hentai 搜索结果中，每个画廊通常在 <div class="it5"> 中有标题链接
    results = []
    seen = set()

    # 分割每个画廊条目
    # E-Hentai 搜索结果中，每个画廊以 <div class="gtr0"> 或 <div class="gtr1"> 开始
    blocks = re.split(r'<div class="gtr[01]"[^>]*>', html)
    if len(blocks) <= 1:
        # 备用: 直接扫描 SEARCH_LINK_RE
        pass

    for block in blocks[1:]:
        if len(results) >= count:
            break
        link_m = SEARCH_LINK_RE.search(block)
        if not link_m:
            continue
        gid = link_m.group(1)
        token = link_m.group(2)
        if gid in seen:
            continue
        seen.add(gid)

        # 提取标题 (it5 中的链接文本)
        title_m = re.search(r'<div class="it5"[^>]*>\s*<a[^>]*>([^<]+)</a>', block, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else "N/A"

        # 提取分类/标签信息
        category = ""
        cat_m = re.search(r'<div class="cs"[^>]*>\s*<div[^>]*>([^<]+)</div>', block, re.IGNORECASE)
        if cat_m:
            category = cat_m.group(1).strip()

        results.append({
            "id": gid,
            "title": title,
            "pages": "?",
            "category": category,
            "url": f"https://{domain}/g/{gid}/{token}/",
            "token": token,
        })

    # 如果 block 分割失败，回退到简单扫描
    if not results:
        for m in SEARCH_LINK_RE.finditer(html):
            if len(results) >= count:
                break
            gid = m.group(1)
            if gid in seen:
                continue
            seen.add(gid)
            token = m.group(2)
            # 尝试在附近找标题
            start = max(0, m.start() - 500)
            end = min(len(html), m.end() + 500)
            context = html[start:end]
            title_m = re.search(r'<a[^>]*>([^<]{3,120})</a>', context, re.IGNORECASE)
            title = title_m.group(1).strip() if title_m else "N/A"
            results.append({
                "id": gid,
                "title": title,
                "pages": "?",
                "category": "",
                "url": f"https://{domain}/g/{gid}/{token}/",
                "token": token,
            })

    if verbose:
        print(f"   找到 {len(results)} 个结果")
        for r in results[:10]:
            print(f"   {r['id']:>8} | {r['title'][:60]}")

    return results


def download_gallery(gid, token, output_dir=None, proxy=None, cookies=None,
                     max_workers=6, verbose=True):
    """下载完整画廊"""
    info = fetch_gallery_info(gid, token, proxy=proxy, cookies=cookies, verbose=verbose)
    if not info:
        print("❌ 无法获取画廊信息")
        return False

    # Archive 优先
    if info["archive_url"]:
        if verbose:
            print(f"\n📦 尝试 Archive 下载: {info['archive_url']}")
        # 尝试下载 archive
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', info['title'])[:80]
        if not output_dir:
            output_dir = os.path.join(os.getcwd(), f"eh_{gid}_{safe_title}")
        os.makedirs(output_dir, exist_ok=True)
        archive_path = os.path.join(output_dir, f"{gid}.zip")
        cmd = ["curl", "-sL", "--max-time", "300", "-o", archive_path]
        if proxy:
            cmd.extend(["--proxy", proxy])
        if cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items()) if isinstance(cookies, dict) else cookies
            cmd.extend(["-H", f"Cookie: {cookie_str}"])
        cmd.append(info["archive_url"])
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=360)
            if r.returncode == 0 and os.path.exists(archive_path) and os.path.getsize(archive_path) > 1024:
                size = os.path.getsize(archive_path)
                if verbose:
                    print(f"  ✅ Archive 下载成功 ({size / 1024 / 1024:.1f} MB)")
                return True
            else:
                if verbose:
                    print("  ⚠️  Archive 下载失败，回退到逐页下载")
                os.remove(archive_path) if os.path.exists(archive_path) else None
        except Exception:
            pass

    # 逐页下载
    if not output_dir:
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', info['title'])[:80]
        output_dir = os.path.join(os.getcwd(), f"eh_{gid}_{safe_title}")
    os.makedirs(output_dir, exist_ok=True)

    if not info["image_pages"]:
        print("❌ 未找到图片页面链接")
        return False

    # 先获取所有图片 URL（串行以避免封禁）
    if verbose:
        print(f"\n🔍 解析 {len(info['image_pages'])} 张图片 URL...")

    img_tasks = []
    for imp in info["image_pages"]:
        img_tasks.append((imp["page"], imp["url"]))

    def _resolve_img(item):
        page, url = item
        img_url = fetch_image_url(url, proxy=proxy, cookies=cookies)
        return page, img_url

    image_urls = {}
    delay = 1.0 / max_workers  # 控制请求速率
    with ThreadPoolExecutor(max_workers=min(max_workers, len(img_tasks))) as pool:
        futures = {pool.submit(_resolve_img, t): t for t in img_tasks}
        for f in as_completed(futures):
            page, img_url = f.result()
            if img_url:
                image_urls[page] = img_url
                if verbose:
                    print(f"  ✓ 解析第{page}页 → {img_url[:70]}...")
            else:
                if verbose:
                    print(f"  ✗ 第{page}页解析失败")
            time.sleep(delay)

    if not image_urls:
        print("❌ 未能解析任何图片 URL")
        return False

    # 下载图片
    QUALITY_FORMATS = ["jpg", "png", "webp", "gif"]
    success = 0

    def _dl_one(item):
        page, url = item
        # 尝试多种格式
        best_path = None
        best_size = 0
        best_ext = None

        for fmt in QUALITY_FORMATS:
            test_url = re.sub(r'\.\w+$', f'.{fmt}', url, count=1)
            out_path = os.path.join(output_dir, f"{page:04d}.{fmt}")
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                if os.path.getsize(out_path) > best_size:
                    best_path, best_size, best_ext = out_path, os.path.getsize(out_path), fmt
                continue
            cmd = ["curl", "-sL", "--max-time", "60", "--connect-timeout", "10",
                   "-o", out_path, "-H", f"User-Agent: {USER_AGENT}"]
            if proxy:
                cmd.extend(["--proxy", proxy])
            cmd.append(test_url)
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=65)
                if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 500:
                    sz = os.path.getsize(out_path)
                    if sz > best_size:
                        best_path, best_size, best_ext = out_path, sz, fmt
                elif os.path.exists(out_path) and os.path.getsize(out_path) <= 500:
                    os.remove(out_path)
            except Exception:
                if os.path.exists(out_path):
                    os.remove(out_path)

        if best_path and best_ext != best_path.split('.')[-1]:
            final_path = os.path.join(output_dir, f"{page:04d}.{best_ext}")
            if best_path != final_path:
                os.rename(best_path, final_path)

        return page, bool(best_path), best_ext or "?", best_size

    if verbose:
        print(f"\n📥 下载 {len(image_urls)} 张图片... ({max_workers} 线程)")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_dl_one, (p, u)): p for p, u in image_urls.items()}
        for f in as_completed(futures):
            page, ok, fmt, size = f.result()
            if ok:
                success += 1
                if verbose:
                    size_kb = size / 1024 if size else 0
                    print(f"   ✓ 第{page}页 [{fmt}] {size_kb:.0f} KB")
            else:
                if verbose:
                    print(f"   ✗ 第{page}页")

    if verbose:
        total = sum(os.path.getsize(os.path.join(output_dir, f)) for f in os.listdir(output_dir)
                    if os.path.isfile(os.path.join(output_dir, f)))
        print(f"\n✅ 下载完成: {success}/{len(image_urls)} 页 ({total / 1024 / 1024:.1f} MB) → {output_dir}")

    return success > 0


# ── 主函数 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="E-Hentai / ExHentai 画廊下载器",
        epilog="示例:\n"
               "  python3 ehentai_dl.py https://e-hentai.org/g/123456/abcdef0123/\n"
               "  python3 ehentai_dl.py -c 'ipb_member_id=xxx; ipb_pass_hash=xxx' <url>\n"
               "  python3 ehentai_dl.py -p http://127.0.0.1:7890 <url>",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", nargs="?", help="E-Hentai/ExHentai 画廊 URL")
    parser.add_argument("-p", "--proxy", metavar="PROXY", help="代理地址")
    parser.add_argument("-c", "--cookie", metavar="COOKIE", help="Cookie 字符串 (用于 exhentai 认证)")
    parser.add_argument("-o", "--output", metavar="DIR", help="输出目录")
    parser.add_argument("-t", "--threads", type=int, default=6, help="下载线程数")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式")
    parser.add_argument("--search", metavar="QUERY", help="关键词搜索")
    parser.add_argument("--count", type=int, default=20, help="搜索结果数")
    parser.add_argument("--check", action="store_true", help="连通性检测")
    parser.add_argument("--download-all", action="store_true", help="下载标签搜索的全部结果")
    parser.add_argument("--cookie-file", metavar="FILE", help="从文件读取 cookie")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    if args.check:
        print("🔬 E-Hentai 连通性检测")
        proxy = args.proxy or discover_proxy()
        if proxy:
            print(f"   代理: {proxy}")
        for domain in ["e-hentai.org", "exhentai.org"]:
            html = _curl_get(f"https://{domain}/", proxy=proxy, timeout=10)
            if html:
                print(f"   ✅ {domain} 可达")
            else:
                print(f"   ❌ {domain} 不可达")
        return

    proxy = args.proxy or discover_proxy()
    if proxy and not args.quiet:
        print(f"🔗 代理: {proxy}")

    cookies = None
    if args.cookie:
        cookies = args.cookie
    elif args.cookie_file:
        try:
            with open(args.cookie_file) as f:
                cookies = f.read().strip()
        except Exception:
            print(f"⚠️  无法读取 cookie 文件: {args.cookie_file}")
    elif _CREDS.get("exhentai_cookies"):
        cookies = _CREDS["exhentai_cookies"]
        if not args.quiet:
            print("🔐 已加载 ExHentai 凭证")

    # ── 关键词搜索模式 ──
    if args.search:
        galleries = search_galleries(
            args.search, proxy=proxy, cookies=cookies,
            count=args.count, verbose=not args.quiet and not args.json)
        if args.json:
            print(json.dumps(galleries, ensure_ascii=False, indent=2))
            return
        if not galleries:
            print("❌ 未找到结果")
            sys.exit(1)
        print(f"\n💡 下载单个: python3 ehentai_dl.py {galleries[0]['url']}")
        return

    if not args.url:
        parser.print_help()
        sys.exit(1)

    # 标签搜索模式
    tag_m = TAG_URL_RE.search(args.url) if args.url else None
    if tag_m:
        tag = tag_m.group(1)
        galleries = search_tag(tag, proxy=proxy, cookies=cookies, verbose=not args.quiet)
        if not galleries:
            print("❌ 未找到画廊或页面不可达")
            sys.exit(1)
        if args.download_all:
            print(f"\n📥 下载全部 {len(galleries)} 个画廊...")
            for gid, token, _ in galleries:
                download_gallery(gid, token, output_dir=args.output,
                               proxy=proxy, cookies=cookies,
                               max_workers=args.threads, verbose=not args.quiet)
        else:
            print(f"\n💡 下载全部: python3 ehentai_dl.py --download-all {args.url}")
            print(f"💡 下载单个: python3 ehentai_dl.py https://e-hentai.org/g/{galleries[0][0]}/{galleries[0][1]}/")
        return

    gid, token, _ = extract_gallery_info(args.url)
    if not gid:
        print("❌ 无效的 E-Hentai/ExHentai URL")
        print("   支持格式: https://e-hentai.org/g/{id}/{token}/")
        print("   或标签: https://e-hentai.org/tag/{tag}")
        sys.exit(1)

    ok = download_gallery(gid, token, output_dir=args.output,
                          proxy=proxy, cookies=cookies,
                          max_workers=args.threads, verbose=not args.quiet)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
