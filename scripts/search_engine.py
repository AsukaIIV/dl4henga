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
_pc_search = None

_NH_LOADED = False
_JM_LOADED = False
_EH_LOADED = False
_PC_LOADED = False


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


def _load_picacg():
    global _pc_search, _PC_LOADED
    if _PC_LOADED:
        return _pc_search
    _PC_LOADED = True
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from pica_dl import search_comics as fn
        _pc_search = fn
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
    "picacg": {
        "name": "picacg",
        "label": "PC",
        "icon": "🟣",
        "loader": _load_picacg,
        "needs_proxy": False,
        "result_id_field": "id",
        "url_template": "https://pica.picacomic.com/comics/{id}",
    },
}

ALL_SITES = ["nhentai", "jmcomic", "ehentai", "picacg"]


# ═══════════════════════════════════════════════════════════
# 单站搜索 (包装器)
# ═══════════════════════════════════════════════════════════

def _search_one(site_name, query, proxy=None, count=20, page=1, sort="popular", cookies=None, verbose=False):
    """在单个站点搜索，返回 (site_name, results_list, error_str)"""
    meta = SITE_META[site_name]
    fn = meta["loader"]()
    if fn is None:
        return site_name, [], f"模块加载失败"

    site_proxy = proxy if meta["needs_proxy"] else None
    start = time.time()
    try:
        # 各站点搜索函数签名不同，按需传参
        if site_name == "nhentai":
            results = fn(query, proxy=site_proxy, count=count, sort=sort, page=page, verbose=verbose)
        elif site_name == "ehentai":
            results = fn(query, proxy=site_proxy, cookies=cookies, count=count, page=page, verbose=verbose)
        elif site_name == "picacg":
            results = fn(query, proxy=site_proxy, count=count, verbose=verbose)
        else:
            results = fn(query, proxy=site_proxy, count=count, page=page, verbose=verbose)
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

    # picacg 用 "author" 字段，转为 artists 列表
    artists = item.get("artists", [])
    if not artists and item.get("author") and item["author"] != "?":
        artists = [item["author"]]

    return {
        "source": source,
        "site_id": site_id,
        "title": str(item.get("title", "N/A")),
        "pages": str(item.get("pages", "?")),
        "artists": artists,
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


# ═══════════════════════════════════════════════════════════
# Web 搜索双向验证 (v2 新增)
# ═══════════════════════════════════════════════════════════

def _web_search(query, timeout=8):
    """DuckDuckGo HTML 搜索，返回结果摘要文本列表"""
    import subprocess
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    cmd = ["curl", "-sL", "--max-time", str(timeout), "--connect-timeout", "5",
           "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
           "-H", "Accept: text/html",
           url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
        if result.returncode != 0 or len(result.stdout) < 200:
            return []
        html = result.stdout

        # 提取搜索结果摘要 (class="result__snippet")
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        if not snippets:
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</', html, re.DOTALL)

        # 清理 HTML 标签
        clean = []
        for s in snippets[:10]:
            s = re.sub(r'<[^>]+>', ' ', s)
            s = re.sub(r'\s+', ' ', s).strip()
            if len(s) > 10:
                clean.append(s)
        return clean
    except Exception:
        return []


def _web_verify_match(item_a, item_b, score, verbose=False):
    """
    当标题相似度在不确定区间时，用 web 搜索验证是否为同一本子。

    参数:
      item_a, item_b: 标准化的结果 dict
      score:          当前标题相似度 (0-1)
      verbose:        是否输出调试信息

    返回:
      (is_match: bool, confidence: str)
    """
    # 快速拒绝: 来源相同且 ID 不同 → 肯定不是同一本
    if item_a["source"] == item_b["source"] and item_a["site_id"] != item_b["site_id"]:
        return False, "同站不同ID"

    # 提取共同的关键词
    def _keywords(title):
        words = re.findall(r'[\w\u4e00-\u9fff]{2,}', title.lower())
        # 过滤常见无意义词
        stop = {"the", "and", "of", "in", "to", "a", "is", "no", "de", "la",
                "digital", "dl", "版", "翻譯", "漢化", "修正", "無修正"}
        return {w for w in words if w not in stop}

    kw_a = _keywords(item_a.get("title", ""))
    kw_b = _keywords(item_b.get("title", ""))

    # 中文标题特殊处理: 提取日文原作名的罗马字部分
    romaji_a = re.findall(r'[a-zA-Z]{4,}', item_a.get("title", ""))
    romaji_b = re.findall(r'[a-zA-Z]{4,}', item_b.get("title", ""))

    common_kw = kw_a & kw_b
    common_romaji = set(romaji_a) & set(romaji_b)

    # 构造搜索查询
    queries = []

    # 策略1: 用 nhentai ID + 共同关键词搜索
    nh_item = item_a if item_a["source"] == "nhentai" else (item_b if item_b["source"] == "nhentai" else None)
    other_item = item_b if nh_item is item_a else item_a

    if nh_item and common_romaji:
        q = f'nhentai {nh_item["site_id"]} {" ".join(list(common_romaji)[:3])}'
        queries.append(("nhentai_id", q))
    elif nh_item and common_kw:
        q = f'nhentai {nh_item["site_id"]} {" ".join(list(common_kw)[:4])}'
        queries.append(("nhentai_id", q))

    # 策略2: 用作者名 + 共同罗马字
    artists_a = set(item_a.get("artists", []))
    artists_b = set(item_b.get("artists", []))
    common_artists = artists_a & artists_b
    if common_artists and common_romaji:
        # 用罗马字作者名
        artist_romaji = [a for a in common_artists if re.match(r'^[a-zA-Z]', a)]
        if artist_romaji:
            q = f'{" ".join(artist_romaji[:2])} {" ".join(list(common_romaji)[:3])}'
            queries.append(("artist_romaji", q))

    # 策略3: 用日文/中文关键标题词
    if common_kw and not queries:
        q = f'{" ".join(list(common_kw)[:5])}'
        queries.append(("keywords", q))

    if not queries:
        return False, "无可搜索关键词"

    # 执行搜索
    for strategy, query in queries:
        snippets = _web_search(query, timeout=8)
        if not snippets:
            continue

        # 检查搜索结果中是否同时提到两个站点的作品
        id_a = item_a["site_id"]
        id_b = item_b["site_id"]
        title_a_frag = item_a.get("title", "")[:30].lower()
        title_b_frag = item_b.get("title", "")[:30].lower()

        combined = " ".join(snippets).lower()

        hits_a = id_a in combined or title_a_frag in combined
        hits_b = id_b in combined or title_b_frag in combined

        if hits_a and hits_b:
            if verbose:
                print(f"  🌐 web验证 ✅ [{strategy}] {item_a['source']}:{id_a} ↔ {item_b['source']}:{id_b}")
            return True, f"web:{strategy}"

    if verbose:
        print(f"  🌐 web验证 ❌ {item_a['source']}:{id_a} ≉ {item_b['source']}:{id_b} (score={score:.2f})")
    return False, f"web:no_match"


def _merge_results(all_results, web_verify=False, web_threshold=0.5, verbose=False):
    """
    合并去重三站搜索结果。
    策略:
      1. 按标题相似度 > 0.85 判定为同一本子
      2. 同一本子出现多站，保留信息最全的那个 (有页数 > 无页数 > 标题更长)
      3. 标注 cross_site 属性
      4. 相似度在 [web_threshold, 0.85] 之间时，用 web 搜索双向验证
    """
    if not all_results:
        return []

    # 预检 web 搜索可用性 (只做一次)
    if web_verify:
        test_results = _web_search("test", timeout=4)
        if not test_results:
            if verbose:
                print("  🌐 web 搜索不可达，跳过双向验证")
            web_verify = False

    web_verified = 0
    web_confirmed = 0

    merged = []
    seen_groups = []  # [[result1, result2], ...] 同一本子的所有版本

    for item in all_results:
        title = item.get("title", "")
        # 找到最相似的已有组
        best_group = None
        best_score = 0
        best_existing = None
        for group in seen_groups:
            for existing in group:
                score = _title_similarity(title, existing.get("title", ""))
                if score > best_score:
                    best_score = score
                    best_group = group
                    best_existing = existing

        matched = False

        # 高置信度: 相似度 > 0.85，直接合并
        if best_score > 0.85 and best_group is not None:
            best_group.append(item)
            matched = True

        # 不确定区间: web_verify 启用时，尝试 web 搜索确认 (最多 30 次)
        elif web_verify and best_score >= web_threshold and best_group is not None and web_verified < 30:
            web_verified += 1
            is_match, reason = _web_verify_match(best_existing, item, best_score, verbose=verbose)
            if is_match:
                web_confirmed += 1
                best_group.append(item)
                matched = True
                item["_web_match"] = reason

        if not matched:
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
        parts = []
        if dupes > 0:
            parts.append(f"{dupes} 个重复结果已合并")
        if web_verified > 0:
            parts.append(f"web验证 {web_verified} 对, 确认 {web_confirmed} 对")
        if parts:
            print(f"  📎 去重: {', '.join(parts)}")

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


def multi_search(query, *, proxy=None, count=20, page=1, sort="popular", sites=None,
                 verbose=True, merge=True, web_verify=True, web_threshold=0.5):
    """
    三站并行搜索 (主入口)

    参数:
      query:   搜索关键词
      proxy:   代理地址 (None=自动发现)
      count:   每站结果数上限
      page:    搜索页码 (默认 1)
      sort:    排序方式 (popular/recent, 仅 nhentai 支持)
      sites:   站点列表 (None=全部三站), 如 ["nhentai", "jmcomic"]
      verbose: 是否输出进度
      merge:   是否去重合并
      web_verify: 是否启用 web 搜索双向验证
      web_threshold: web 验证触发的最小相似度 (默认 0.5)

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
            pool.submit(_search_one, site, query, proxy, count, page, sort, cookies, verbose=False): site
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
        final = _merge_results(all_results, web_verify=web_verify,
                               web_threshold=web_threshold, verbose=verbose)
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
                          sites=sites, verbose=verbose, merge=True, sort="popular")
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
    parser.add_argument("--page", type=int, default=1, help="搜索页码")
    parser.add_argument("--sort", choices=["popular", "recent"], default="popular", help="排序")
    parser.add_argument("-p", "--proxy", metavar="PROXY", help="代理地址")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--no-merge", action="store_true", help="不去重")
    parser.add_argument("--no-web-verify", action="store_true", help="关闭 web 搜索双向验证 (默认开启)")
    parser.add_argument("--web-threshold", type=float, default=0.5,
                        help="web 验证触发的最小相似度 (默认 0.5)")
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
                          page=args.page, sort=args.sort,
                          sites=sites, verbose=not args.quiet,
                          merge=not args.no_merge,
                          web_verify=not args.no_web_verify,
                          web_threshold=args.web_threshold)

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
