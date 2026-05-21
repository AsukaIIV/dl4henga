#!/usr/bin/env python3
"""
四站下载工具统一入口  v2
========================
自动识别 URL 并路由到正确脚本:

  nhentai.net / 纯数字 ID   → nhentai_dl.py
  e-hentai/exhentai         → ehentai_dl.py
  18comic/jmcomic/JM        → jmcomic_dl.py

v2 新增: --search 默认三站并行搜索 (nhentai + JMComic + E-Hentai)
         --site 限制站点, 某站不可用时自动降级

用法:
  python3 dl.py <url|id>                # 自动路由下载
  python3 dl.py --search "关键词"        # 三站搜索
  python3 dl.py --search "xx" --site jm # 单站搜索
  python3 dl.py --random                # 三站随机推荐
  python3 dl.py --random --tag "标签"    # 按标签随机
  python3 dl.py --check                 # 全站检测
"""

import re, sys, os, subprocess, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── URL 路由 (下载模式) ───────────────────────────────────
ROUTES = [
    (re.compile(r'(?:exhentai|e-hentai)\.org', re.I), 'ehentai_dl.py'),
    (re.compile(r'(?:18comic|jmcomic)', re.I), 'jmcomic_dl.py'),
    (re.compile(r'(?:n(?:x)?hentai|hentai)[\w.-]*/g/\d', re.I), 'nhentai_dl.py'),
    (re.compile(r'^\d{1,6}$'), 'nhentai_dl.py'),
    (re.compile(r'^JM\d', re.I), 'jmcomic_dl.py'),
]


def route(raw):
    for pattern, script in ROUTES:
        if pattern.search(raw):
            return script
    return None


# ── 帮助 ──────────────────────────────────────────────────

def print_help():
    print("🔀 dl4henga 四站下载工具 统一入口 v2")
    print()
    print("━━━ 搜索 ━━━")
    print("  --search QUERY            三站并行搜索 (nhentai + JMComic + E-Hentai)")
    print("  --site SITES              限制搜索站点: nhentai, jmcomic, ehentai")
    print("                             逗号分隔, 支持简写: nh, jm, eh")
    print("  --count N                 每站结果数 (默认 20)")
    print("  --page N                  搜索页码 (默认 1)")
    print("  --sort SORT               排序: popular / recent")
    print("  --json                    JSON 输出")
    print("  --no-web-verify           关闭 web 搜索双向验证 (默认开启)")
    print("  --web-threshold FLOAT     web 验证触发的最小相似度 (默认 0.5)")
    print()
    print("━━━ 随机推荐 ━━━")
    print("  --random                  三站随机推荐")
    print("  --random --tag TAG        按标签随机推荐")
    print("  --random --site jm         限定站点随机")
    print()
    print("━━━ 下载 ━━━")
    print("  python3 dl.py <url|id>    自动识别 URL 路由下载")
    print("    nhentai / 纯数字 ID       → nhentai_dl.py")
    print("    e-hentai / exhentai       → ehentai_dl.py")
    print("    18comic / JM / jmcomic    → jmcomic_dl.py")
    print()
    print("━━━ 工具 ━━━")
    print("  --check                    四站全检")
    print("  --setup                    凭证配置")
    print("  --help, -h                 帮助")
    print()
    print("━━━ 示例 ━━━")
    print("  python3 dl.py --search \"毛玉牛乳\"")
    print("  python3 dl.py --search \"fate\" --site nhentai,eh --json")
    print("  python3 dl.py --random --tag \"chinese\"")
    print("  python3 dl.py 604256")
    print("  python3 dl.py --check")


# ── 主入口 ────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    # --help / -h
    if '--help' in args or '-h' in args:
        print_help()
        return

    # --check: run all checks
    if '--check' in args:
        print("🔬 四站全检")
        print("=" * 50)
        for script in ['nhentai_dl.py', 'ehentai_dl.py', 'jmcomic_dl.py']:
            path = os.path.join(SCRIPT_DIR, script)
            if os.path.exists(path):
                print(f"\n━━━ {script} ━━━")
                try:
                    subprocess.run([sys.executable, path, '--check'], timeout=30)
                except subprocess.TimeoutExpired:
                    print(f"   ⏱️  超时")
        print(f"\n{'=' * 50}")
        print("✅ 四站全检完成")
        return

    # --setup
    if '--setup' in args:
        from credentials import setup_credentials, check_credentials
        check_credentials()
        setup_credentials()
        return

    # ── 搜索 / 随机模式 ────────────────────────────────────
    has_search = '--search' in args
    has_random = '--random' in args

    # 解析参数
    try:
        search_idx = args.index('--search') if has_search else -1
    except ValueError:
        search_idx = -1

    if has_search or has_random:
        # 提取参数
        query = None
        if search_idx >= 0 and search_idx + 1 < len(args):
            query = args[search_idx + 1]

        # --site
        sites = None
        if '--site' in args:
            try:
                site_idx = args.index('--site')
                if site_idx + 1 < len(args):
                    site_val = args[site_idx + 1]
                    site_map = {
                        "nh": "nhentai", "nhentai": "nhentai",
                        "jm": "jmcomic", "jmcomic": "jmcomic",
                        "eh": "ehentai", "ehentai": "ehentai", "e-hentai": "ehentai",
                    }
                    sites = []
                    for s in site_val.lower().replace(" ", "").split(","):
                        mapped = site_map.get(s)
                        if mapped:
                            sites.append(mapped)
            except (ValueError, IndexError):
                pass

        # --jm-search 兼容 (等同于 --site jmcomic)
        if '--jm-search' in args:
            sites = ["jmcomic"]

        # --tag
        tag = None
        if '--tag' in args:
            try:
                tag_idx = args.index('--tag')
                if tag_idx + 1 < len(args):
                    tag = args[tag_idx + 1]
            except (ValueError, IndexError):
                pass

        # 合并 query
        if has_random and not query:
            query = tag or "chinese"

        # --count
        count = 20
        if '--count' in args:
            try:
                cnt_idx = args.index('--count')
                if cnt_idx + 1 < len(args):
                    count = int(args[cnt_idx + 1])
            except (ValueError, IndexError, TypeError):
                pass

        # --page
        page = 1
        if '--page' in args:
            try:
                p_idx = args.index('--page')
                if p_idx + 1 < len(args):
                    page = int(args[p_idx + 1])
            except (ValueError, IndexError, TypeError):
                pass

        # --sort
        sort = "popular"
        if '--sort' in args:
            try:
                s_idx = args.index('--sort')
                if s_idx + 1 < len(args):
                    sort = args[s_idx + 1]
                    if sort not in ("popular", "recent"):
                        sort = "popular"
            except (ValueError, IndexError):
                pass

        # --proxy
        proxy = None
        if '-p' in args:
            try:
                p_idx = args.index('-p')
                if p_idx + 1 < len(args):
                    proxy = args[p_idx + 1]
            except (ValueError, IndexError):
                pass
        if '--proxy' in args:
            try:
                p_idx = args.index('--proxy')
                if p_idx + 1 < len(args):
                    proxy = args[p_idx + 1]
            except (ValueError, IndexError):
                pass

        # --json
        json_out = '--json' in args
        # --quiet
        quiet = '-q' in args or '--quiet' in args
        # --web-verify (默认开启)
        web_verify = '--no-web-verify' not in args
        web_threshold = 0.5
        if '--web-threshold' in args:
            try:
                wt_idx = args.index('--web-threshold')
                if wt_idx + 1 < len(args):
                    web_threshold = float(args[wt_idx + 1])
            except (ValueError, IndexError, TypeError):
                pass

        # 导入搜索引擎
        sys.path.insert(0, SCRIPT_DIR)
        try:
            from search_engine import multi_search, random_gallery, print_results, SITE_META
        except ImportError as e:
            print(f"❌ 无法加载搜索引擎: {e}")
            sys.exit(1)

        if has_random:
            if not quiet:
                q = query or "chinese (热门)"
                site_info = f" (站点: {','.join(sites)})" if sites else ""
                print(f"🎲 随机推荐模式, 候选: {q}{site_info}")
            chosen = random_gallery(query or "chinese", proxy=proxy,
                                    count=count, sites=sites,
                                    verbose=not quiet)
            if chosen:
                if json_out:
                    print(json.dumps(chosen, ensure_ascii=False, indent=2))
                else:
                    icon = SITE_META.get(chosen["source"], {}).get("icon", "🎯")
                    print(f"\n🎯 推荐结果:")
                    print(f"   {icon} [{chosen['source']}] {chosen['title'][:70]}")
                    print(f"   📄 {chosen['pages']}p" if chosen.get("pages", "?") != "?" else "")
                    print(f"   🔗 {chosen['url']}")
                    src = chosen["source"]
                    sid = chosen["site_id"]
                    print(f"\n💡 下载: python3 dl.py {chosen['url']}")
            else:
                if json_out:
                    print(json.dumps({"error": "无结果"}, ensure_ascii=False))
                sys.exit(1)
            return

        if has_search:
            if not query:
                print("❌ 请提供搜索词: --search \"关键词\"")
                sys.exit(1)

            result = multi_search(query, proxy=proxy, count=count,
                                  page=page, sort=sort,
                                  sites=sites, verbose=not quiet,
                                  merge=True,
                                  web_verify=web_verify,
                                  web_threshold=web_threshold)

            if json_out:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"\n📋 搜索结果 ({result['total']} 个):")
                print_results(result)

                if result["sites_failed"]:
                    print(f"\n⚠️  部分站点不可用:")
                    for sf in result["sites_failed"]:
                        print(f"   - {sf['site']}: {sf['error']}")

                if result["results"]:
                    first = result["results"][0]
                    print(f"\n💡 下载: python3 dl.py {first['url']}")
                    if first.get("cross_site"):
                        labels = ", ".join(first["cross_site"])
                        print(f"💡 跨站可用: {labels}")
            return

    # ── 下载模式: 自动路由 ─────────────────────────────────
    # 查找第一个非 flag 参数
    target = None
    extra_args = []
    skip_next = False
    for i, a in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if a in ('--search', '--site', '--tag', '--count', '--page', '--sort',
                 '--proxy', '-p', '--jm-search', '--random', '--json', '--quiet', '-q',
                 '--no-web-verify', '--web-threshold'):
            if a in ('--search', '--site', '--tag', '--count', '--page', '--sort',
                     '--proxy', '-p', '--web-threshold'):
                skip_next = True
            continue
        if a.startswith('-'):
            continue
        target = a
        extra_args = args[i + 1:]
        break

    if target:
        script = route(target)
        if script:
            path = os.path.join(SCRIPT_DIR, script)
            script_name = script.replace('_dl.py', '')
            print(f"🔀 路由到 {script_name}")
            # 构建子命令: 只传递 target 和剩余非 flag 参数
            subprocess.run([sys.executable, path, target] + extra_args)
            return

    # 无法路由，fallback 到 nhentai
    if target:
        path = os.path.join(SCRIPT_DIR, 'nhentai_dl.py')
        subprocess.run([sys.executable, path] + [target] + extra_args)
    else:
        print("❌ 无法识别输入")
        print("   用法: python3 dl.py <url|id>  或  python3 dl.py --search \"关键词\"")
        print("   帮助: python3 dl.py --help")
        sys.exit(1)


if __name__ == "__main__":
    main()
