#!/usr/bin/env python3
"""
JMComic (禁漫天堂) 下载器  v2
===============================
从 18comic / jmcomic 等禁漫天堂镜像站点下载本子。
底层: hect0x7/JMComic-Crawler-Python (⭐5.8k)

用法:
  python3 jmcomic_dl.py <id>                        # 下载
  python3 jmcomic_dl.py --search "关键词" [--count N] # 搜索
  python3 jmcomic_dl.py --random --tag "标签"         # 随机下载
  python3 jmcomic_dl.py --check                      # 检测
"""

import re, sys, os, logging, random, argparse

# 抑制 jmcomic 库调试输出 (设置为 ERROR 级别)
import logging as _logging
for _name in ['', 'jmcomic', 'api', 'album', 'photo', 'image']:
    _logging.getLogger(_name).setLevel(_logging.ERROR)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ALBUM_ID_RE = re.compile(r'(?:album|photo)/(\d+)', re.IGNORECASE)
ALBUM_URL_RE = re.compile(r'(\d{4,10})')


def extract_album_id(raw):
    m = ALBUM_ID_RE.search(raw)
    if m: return m.group(1)
    m = ALBUM_URL_RE.search(raw)
    if m and len(m.group(1)) >= 4: return m.group(1)
    return None


def _check_jmcomic():
    try:
        import jmcomic
        return True, jmcomic.__version__
    except ImportError:
        return False, None


def download_album(album_id, proxy=None, output_dir=None, image_format="png", verbose=True):
    ok, ver = _check_jmcomic()
    if not ok:
        print("❌ 未安装 jmcomic 库\n   安装: pip install jmcomic")
        return False
    import jmcomic, contextlib, io
    try:
        if not output_dir:
            output_dir = os.path.join(os.getcwd(), "JMComic")
        opt = {
            "download": {
                "image": {"suffix": f".{image_format}"},
                "dir_rule": {"rule": "Bd_Aid", "base_dir": output_dir},
            }
        }
        if proxy:
            opt["client"] = {"proxy": proxy}
        option = jmcomic.JmOption.construct(opt)
        if verbose: print(f"📥 禁漫下载: {album_id} → {output_dir}")
        # 重定向 stderr 抑制 jmcomic 内部日志
        with contextlib.redirect_stderr(io.StringIO()):
            jmcomic.download_album(album_id, option)
        if verbose: print("✅ 下载完成")
        return True
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return False


def search_albums(query, proxy=None, count=20, verbose=True):
    ok, ver = _check_jmcomic()
    if not ok:
        print("❌ 未安装 jmcomic 库, 安装: pip install jmcomic")
        return []
    import jmcomic
    try:
        client = jmcomic.JmOption.default().new_jm_client()
        if proxy:
            client = jmcomic.JmOption.construct({"client": {"proxy": proxy}}).new_jm_client()
        if verbose: print(f"🔍 禁漫搜索: {query}")
        page = client.search_site(query, page=1)
        results = list(page)[:count]
        if verbose: print(f"   找到 {len(results)} 个结果")
        galleries = []
        for r in results:
            if isinstance(r, tuple):
                aid, title = r[0], r[1] if len(r) > 1 else str(r)
            else:
                aid = getattr(r, 'aid', getattr(r, 'id', '?'))
                title = getattr(r, 'title', str(r))
            galleries.append({"id": str(aid), "title": str(title)})
            if verbose: print(f"   JM{aid} | {str(title)[:70]}")
        return galleries
    except Exception as e:
        print(f"❌ 搜索失败: {e}")
        return []


def run_check():
    print("🔬 JMComic 连通性检测")
    ok, ver = _check_jmcomic()
    print(f"   {'✅' if ok else '❌'} jmcomic {'v'+ver if ok else '未安装 (pip install jmcomic)'}")
    import socket
    for domain in ["18comic.vip", "jmcomic.me"]:
        try:
            socket.gethostbyname(domain)
            print(f"   ✅ {domain}")
        except:
            print(f"   ❌ {domain}")


def main():
    parser = argparse.ArgumentParser(description="JMComic (禁漫天堂) 下载器 v2",
        epilog="示例: python3 jmcomic_dl.py 123456\n       python3 jmcomic_dl.py --search \"女骑士\"",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?", help="本子 ID 或 URL")
    parser.add_argument("-p", "--proxy", metavar="PROXY", help="代理")
    parser.add_argument("-o", "--output", metavar="DIR", help="输出目录")
    parser.add_argument("-f", "--format", choices=["png","jpg","webp"], default="png", help="格式")
    parser.add_argument("--search", metavar="QUERY", help="搜索")
    parser.add_argument("--count", type=int, default=20, help="搜索结果数")
    parser.add_argument("--random", action="store_true", help="随机下载")
    parser.add_argument("--tag", metavar="TAG", help="配合 --random 使用")
    parser.add_argument("--check", action="store_true", help="检测")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    if args.check:
        run_check()
        return

    if args.search or (args.random and args.tag):
        query = args.search or args.tag
        galleries = search_albums(query, proxy=args.proxy, count=args.count, verbose=not args.quiet and not args.json)
        if args.json:
            import json as _json
            print(_json.dumps(galleries, ensure_ascii=False, indent=2))
            return
        if args.random and galleries:
            chosen = random.choice(galleries)
            print(f"\n🎲 随机选中: JM{chosen['id']} | {chosen['title'][:60]}")
            download_album(chosen['id'], proxy=args.proxy, output_dir=args.output,
                          image_format=args.format, verbose=not args.quiet)
        return

    if args.random and not args.tag:
        galleries = search_albums("chinese", proxy=args.proxy, count=50, verbose=not args.quiet)
        if galleries:
            chosen = random.choice(galleries)
            print(f"\n🎲 随机选中: JM{chosen['id']} | {chosen['title'][:60]}")
            download_album(chosen['id'], proxy=args.proxy, output_dir=args.output,
                          image_format=args.format, verbose=not args.quiet)
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    aid = extract_album_id(args.input)
    if not aid:
        print("❌ 无法识别的禁漫本子 ID\n   格式: JM123456 或 URL")
        sys.exit(1)

    ok = download_album(aid, proxy=args.proxy, output_dir=args.output,
                        image_format=args.format, verbose=not args.quiet)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
