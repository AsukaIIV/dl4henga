#!/usr/bin/env python3
"""
三站统一搜索引擎  v1
====================
并行搜索 nhentai / E-Hentai / JMComic，自动处理站点不可用降级，
去重合并结果，输出统一格式。

用法 (模块导入):
  from search_engine import multi_search, random_gallery
  results = multi_search("毛玉牛乳", proxy="http://127.0.0.1:7890")
  gid = random_gallery("chinese", proxy="http://127.0.0.1:7890")

独立使用:
  python3 search_engine.py --search "query" [--site nhentai,jmcomic] [--json]
  python3 search_engine.py --random [--tag "tag"] [--json]
"""

import re
import sys
import os
import json
import time
import random
import difflib
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEARCH_TIMEOUT = 30  # 单站搜索超时 (秒)

# ── 站点搜索函数懒加载 ────────────────────────────────────
# 每个站点独立 try/except，一个失败不影响其他

_nh_search = None
_jm_search = None
_eh_search = None

_NH_LOADED = False
_JM_LOADED = False
_EH_LOADED = False


def _load_nhentai():
    global _nh_search, _NH_LOADED
    if _NH_LOADED:
        return _nh_search
    _NH_LOADED = True
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from nhentai_dl import search_galleries as fn
        _nh_search = fn
        return fn
    except Exception:
        return None


def _load_jmcomic():
    global _jm_search, _JM_LOADED
    if _JM_LOADED:
        return _jm_search
    _JM_LOADED = True
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from jmcomic_dl import search_albums as fn
        _jm_search = fn
        return fn
    except Exception:
        return None


def _load_ehentai():
    global _eh_search, _EH_LOADED
    if _EH_LOADED:
        return _eh_search
    _EH_LOADED = True
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from ehentai_dl import search_galleries as fn
        _eh_search = fn
        return fn
    except Exception:
        return None


# ── 站点元信息 ────────────────────────────────────────────

SITE_META = {
    "nhentai": {
        "name": "nhentai",
        "label": "NH",
        "icon": "🔶",
        "loader": _load_nhentai,
        "needs_proxy": True,
        "result_id_field": "id",
        "url_template": "https://nhentai.to/g/{id}/",
    },
    "jmcomic": {
        "name": "jmcomic",
        "label": "JM",
        "icon": "🟢",
        "loader": _load_jmcomic,
        "needs_proxy": False,
        "result_id_field": "id",
        "url_template": "https://18comic.vip/album/{id}/",
    },
    "ehentai": {
        "name": "ehentai",
        "label": "EH",
        "icon": "🔵",
        "loader": _load_ehentai,
        "needs_proxy": True,
        "result_id_field": "id",
        "url_template": "https://e-hentai.org/g/{id}/{token}/",
    },
}

ALL_SITES = ["nhentai", "jmcomic", "ehentai"]


# ═══════════════════════════════════════════════════════════
# 单站搜索 (包装器)
# ═══════════════════════════════════════════════════════════

def _search_one(site_name, query, proxy=None, count=20, cookies=None, verbose=False):
    """在单个站点搜索，返回 (site_name, results_list, error_str)"""
    meta = SITE_META[site_name]
    fn = meta["loader"]()
    if fn is None:
        return site_name, [], f"模块加载失败"

    site_proxy = proxy if meta["needs_proxy"] else None
    start = time.time()
    try:
        results = fn(query, proxy=site_proxy, count=count, verbose=verbose)
        elapsed = time.time() - start
        if verbose:
            print(f"  {meta['icon']} {site_name}: {len(results)} 结果 ({elapsed:.1f}s)")
        return site_name, results, None
    except Exception as e:
        elapsed = time.time() - start
        err = f"{type(e).__name__}: {str(e)[:100]}"
        if verbose:
            print(f"  {meta['icon']} {site_name}: ❌ {err} ({elapsed:.1f}s)")
        return site_name, [], err


# ═══════════════════════════════════════════════════════════
# 结果标准化
# ═══════════════════════════════════════════════════════════

def _normalize_result(item, source):
    """将各站点不同格式统一为: {source, site_id, title, pages, artists, url, ...}"""
    meta = SITE_META[source]
    site_id = str(item.get("id", item.get("site_id", "?")))
    url = item.get("url", "")
    if not url:
        token = item.get("token", "")
        url = meta["url_template"].format(id=site_id, token=token)

    return {
        "source": source,
        "site_id": site_id,
        "title": str(item.get("title", "N/A")),
        "pages": str(item.get("pages", "?")),
        "artists": item.get("artists", []),
        "url": url,
        # 保留原始数据用于调试
        "_raw": item,
    }


# ═══════════════════════════════════════════════════════════
# 去重合并
# ═══════════════════════════════════════════════════════════

def _title_similarity(a, b):
    """标题相似度 (0-1)，使用 SequenceMatcher"""
    # 预处理: 去除标点、转小写
    def _clean(t):
        t = re.sub(r'[^\w\s]', '', t.lower())
        return re.sub(r'\s+', ' ', t).strip()

    ca, cb = _clean(a), _clean(b)
    if not ca or not cb:
        return 0
    if ca == cb:
        return 1.0
    return difflib.SequenceMatcher(None, ca, cb).ratio()


def _merge_results(all_results, verbose=False):
    """
    合并去重三站搜索结果。
    策略:
      1. 按标题相似度 > 0.85 判定为同一本子
      2. 同一本子出现多站，保留信息最全的那个 (有页数 > 无页数 > 标题更长)
      3. 标注 cross_site 属性
    """
    if not all_results:
        return []

    merged = []
    seen_groups = []  # [[result1, result2], ...] 同一本子的所有版本

    for item in all_results:
        title = item.get("title", "")
        # 找到最相似的已有组
        best_group = None
        best_score = 0
        for group in seen_groups:
            for existing in group:
                score = _title_similarity(title, existing.get("title", ""))
                if score > best_score:
                    best_score = score
                    best_group = group

        if best_score > 0.85 and best_group is not None:
            best_group.append(item)
        else:
            new_group = [item]
            seen_groups.append(new_group)
            merged.append(item)

    # 为每个组选择代表
    final = []
    for i, group in enumerate(seen_groups):
        if len(group) == 1:
            final.append(group[0])
        else:
            # 选择最优代表
            best = group[0]
            for item in group[1:]:
                # 有页数的优先
                if item.get("pages", "?") != "?" and best.get("pages", "?") == "?":
                    best = item
                # 标题更长的优先
                elif len(item.get("title", "")) > len(best.get("title", "")):
                    best = item
            # 记录跨站信息
            sources = list(set(g.get("source") for g in group))
            best["cross_site"] = sources if len(sources) > 1 else None
            best["_alternates"] = [{s: g.get("url") for s, g in zip(
                [x["source"] for x in group], group)} if len(group) > 1 else None]
            final.append(best)

    if verbose:
        dupes = len(all_results) - len(final)
        if dupes > 0:
            print(f"  📎 去重: {dupes} 个重复结果已合并")

    return final


# ═══════════════════════════════════════════════════════════
# 主入口: 多站并行搜索
# ═══════════════════════════════════════════════════════════

def _discover_proxy():
    """快速代理发现 (仅检测环境变量和常用端口)"""
    import socket
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        val = os.environ.get(var)
        if val and val.startswith("http"):
            return val
    for port in [7890, 7897, 1087, 8118, 10808, 10809, 8080]:
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


def _load_cookies():
    """加载 E-Hentai cookies"""
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from credentials import get_credentials
        creds = get_credentials()
        return creds.get("exhentai_cookies")
    except Exception:
        return None


def multi_search(query, *, proxy=None, count=20, sites=None,
                 verbose=True, merge=True):
    """
    三站并行搜索 (主入口)

    参数:
      query:   搜索关键词
      proxy:   代理地址 (None=自动发现)
      count:   每站结果数上限
      sites:   站点列表 (None=全部三站), 如 ["nhentai", "jmcomic"]
      verbose: 是否输出进度
      merge:   是否去重合并

    返回:
      {
        "results": [标准化结果, ...],
        "sites_searched": ["nhentai", ...],
        "sites_failed": [{"site": "jmcomic", "error": "..."}, ...],
        "total_raw": 去重前总数,
        "total": 去重后总数,
      }
    """
    if proxy is None:
        proxy = _discover_proxy()

    if sites is None:
        sites = list(ALL_SITES)

    cookies = _load_cookies()

    if verbose:
        icons = " ".join(SITE_META[s]["icon"] for s in sites)
        print(f"\n🔍 三站搜索: {query}  ({icons})")
        if proxy:
            print(f"🔗 代理: {proxy}")
        elif any(SITE_META[s]["needs_proxy"] for s in sites):
            print(f"⚠️  未检测到代理，部分站点可能不可达")

    # 并行搜索
    all_results = []
    sites_searched = []
    sites_failed = []

    with ThreadPoolExecutor(max_workers=len(sites)) as pool:
        futures = {
            pool.submit(_search_one, site, query, proxy, count, cookies, verbose=False): site
            for site in sites
        }
        for f in as_completed(futures):
            site = futures[f]
            try:
                site_name, results, error = f.result(timeout=SEARCH_TIMEOUT + 5)
            except Exception as e:
                site_name = site
                results = []
                error = f"超时: {str(e)[:80]}"

            sites_searched.append(site_name)

            if error:
                sites_failed.append({"site": site_name, "error": error})
            elif results:
                normalized = [_normalize_result(r, site_name) for r in results]
                all_results.extend(normalized)

    # 去重
    if merge:
        final = _merge_results(all_results, verbose=verbose)
    else:
        final = all_results

    if verbose:
        print(f"\n📊 搜索统计:")
        print(f"   站点: {', '.join(sites_searched)}")
        for sf in sites_failed:
            print(f"   ⚠️  {sf['site']} 失败: {sf['error']}")
        print(f"   去重前: {len(all_results)}  去重后: {len(final)}")

    return {
        "results": final,
        "sites_searched": sites_searched,
        "sites_failed": sites_failed,
        "total_raw": len(all_results),
        "total": len(final),
    }


def random_gallery(query=None, *, proxy=None, count=50, sites=None, verbose=True):
    """
    从三站中随机推荐一个画廊

    参数:
      query:   搜索词 (None=随机热榜)
      count:   候选池大小
      sites:   站点列表 (None=全部)

    返回:
      标准化结果 dict 或 None
    """
    search_query = query or "chinese"
    result = multi_search(search_query, proxy=proxy, count=count,
                          sites=sites, verbose=verbose, merge=True)
    if not result["results"]:
        if verbose:
            print("❌ 没有找到任何画廊")
        return None

    chosen = random.choice(result["results"])
    if verbose:
        icon = SITE_META.get(chosen["source"], {}).get("icon", "🎲")
        print(f"\n🎲 随机选中: {icon} [{chosen['source']}] {chosen['title'][:60]}")
        print(f"   {chosen['url']}")
    return chosen


# ═══════════════════════════════════════════════════════════
# 格式化输出
# ═══════════════════════════════════════════════════════════

def print_results(result_data, max_lines=50):
    """格式化打印搜索结果"""
    results = result_data["results"]
    if not results:
        print("(无结果)")
        return

    for i, r in enumerate(results[:max_lines]):
        icon = SITE_META.get(r["source"], {}).get("icon", "  ")
        pages = f" {r['pages']}p" if r.get("pages", "?") != "?" else ""
        cross = ""
        if r.get("cross_site"):
            labels = "|".join(SITE_META.get(s, {}).get("label", s) for s in r["cross_site"])
            cross = f" 🌐{labels}"
        artists = ""
        if r.get("artists"):
            artists = f" [{', '.join(r['artists'])}]"
        print(f"  {icon} {r['site_id']:>7} | {r['title'][:55]:<55}{pages}{artists}{cross}")

    if len(results) > max_lines:
        print(f"  ... 还有 {len(results) - max_lines} 个结果")


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="三站统一搜索引擎",
        epilog="示例:\n"
               "  python3 search_engine.py --search \"毛玉牛乳\"\n"
               "  python3 search_engine.py --search \"fate\" --site nhentai,eh\n"
               "  python3 search_engine.py --random --tag \"chinese\"\n"
               "  python3 search_engine.py --search \"全彩\" --json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--search", metavar="QUERY", help="搜索关键词")
    parser.add_argument("--random", action="store_true", help="随机推荐")
    parser.add_argument("--tag", metavar="TAG", help="搜索配合 --random/--search")
    parser.add_argument("--site", metavar="SITES",
                        help="限制站点, 逗号分隔: nhentai,jmcomic,ehentai (默认全站)")
    parser.add_argument("--count", type=int, default=20, help="每站结果数")
    parser.add_argument("-p", "--proxy", metavar="PROXY", help="代理地址")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--no-merge", action="store_true", help="不去重")
    args = parser.parse_args()

    # 解析站点
    sites = None
    if args.site:
        site_map = {
            "nh": "nhentai", "nhentai": "nhentai",
            "jm": "jmcomic", "jmcomic": "jmcomic",
            "eh": "ehentai", "ehentai": "ehentai", "e-hentai": "ehentai",
        }
        sites = []
        for s in args.site.lower().replace(" ", "").split(","):
            mapped = site_map.get(s)
            if mapped:
                sites.append(mapped)
        if not sites:
            print(f"❌ 无效站点: {args.site}")
            print(f"   可用: nhentai, jmcomic, ehentai (或简写 nh, jm, eh)")
            sys.exit(1)

    query = args.search or args.tag or ("" if args.random else None)

    if args.random:
        if not args.quiet:
            q = query or "chinese (热门)"
            print(f"🎲 随机推荐模式, 候选: {q}")
        chosen = random_gallery(query or "chinese", proxy=args.proxy,
                                count=args.count, sites=sites,
                                verbose=not args.quiet)
        if chosen:
            if args.json:
                print(json.dumps(chosen, ensure_ascii=False, indent=2))
            else:
                print(f"\n🎯 推荐结果:")
                print(f"   标题: {chosen['title']}")
                print(f"   站点: {chosen['source']}")
                print(f"   链接: {chosen['url']}")
        else:
            if args.json:
                print(json.dumps({"error": "无结果"}, ensure_ascii=False))
            sys.exit(1)
        return

    if not query:
        parser.print_help()
        sys.exit(1)

    result = multi_search(query, proxy=args.proxy, count=args.count,
                          sites=sites, verbose=not args.quiet,
                          merge=not args.no_merge)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n📋 搜索结果 ({result['total']} 个):")
        print_results(result)

        # 使用提示
        if result["results"]:
            first = result["results"][0]
            src = first["source"]
            sid = first["site_id"]
            print(f"\n💡 下载: python3 {src}_dl.py {sid}")
            if first.get("cross_site"):
                print(f"💡 跨站可用: {', '.join(first['cross_site'])}")


if __name__ == "__main__":
    main()
