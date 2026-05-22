#!/usr/bin/env python3
"""
picacg (哔咔漫画) 下载器  v1
============================
搜索: 直接调用 picacg REST API
下载: 委托 pica-cli (justorez/pica-cli ⭐220), 无 pica-cli 时回退直接下载

底层:
  - 搜索: picacg API (https://picaapi.picacomic.com)
  - 下载: pica-cli (npm i -g pica-cli) > 直接 API 回退

用法:
  python3 pica_dl.py --search "关键词" [--count N]
  python3 pica_dl.py <comic_id>
  python3 pica_dl.py --favorites
  python3 pica_dl.py --leaderboard
  python3 pica_dl.py --check
  python3 pica_dl.py --setup
"""

import re
import sys
import os
import json
import time
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"

# picacg API
PICA_API_BASE = "https://picaapi.picacomic.com"
PICA_API_KEY = "C69BAF41DA5ABD1FFEDC6D2FEA56B"
PICA_SECRET_KEY = "~d}$Q7$eIni=V)9\\RK/P.RM4;9[7|@/CA}b~OW!3?EV`:<>M7pddUBL5n|0/*Cn"
PICA_APP_VERSION = "2.2.1.2.3.4"
PICA_APP_CHANNEL = "1"
PICA_APP_PLATFORM = "ios"

# 凭证管理
sys.path.insert(0, SCRIPT_DIR)
try:
    from credentials import get_credentials, save_credentials, CREDENTIALS_PATH as _CP
    _CREDS = get_credentials()
except ImportError:
    _CREDS = {}
    _CP = os.path.expanduser("~/.config/dl4henga/credentials.json")


# ═══════════════════════════════════════════════════════════
# 认证
# ═══════════════════════════════════════════════════════════

def _build_auth_headers(token=None):
    """构建 picacg API 请求头"""
    import uuid
    import hashlib
    nonce = uuid.uuid4().hex
    ts = str(int(time.time()))
    raw = f"{PICA_API_KEY}{nonce}{ts}{PICA_SECRET_KEY}"
    signature = hashlib.sha256(raw.encode()).hexdigest()
    headers = {
        "api-key": PICA_API_KEY,
        "nonce": nonce,
        "time": ts,
        "signature": signature,
        "app-version": PICA_APP_VERSION,
        "app-channel": PICA_APP_CHANNEL,
        "app-platform": PICA_APP_PLATFORM,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if token:
        headers["authorization"] = token
    return headers


def _picacg_login(email, password, proxy=None):
    """登录 picacg，返回 token"""
    url = f"{PICA_API_BASE}/auth/sign-in"
    headers = _build_auth_headers()
    headers["Content-Type"] = "application/json;charset=UTF-8"
    body = json.dumps({"email": email, "password": password})

    cmd = ["curl", "-s", "--max-time", "15", "-X", "POST",
           "-H", f"Content-Type: application/json;charset=UTF-8"]
    for k, v in headers.items():
        if k != "Content-Type":
            cmd.extend(["-H", f"{k}: {v}"])
    cmd.extend(["-d", body])
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            data = json.loads(r.stdout)
            if data.get("code") == 200:
                return data["data"]["token"]
            else:
                print(f"  ❌ 登录失败: {data.get('message', '未知错误')}")
    except Exception as e:
        print(f"  ❌ 登录异常: {e}")
    return None


def _get_token(proxy=None):
    """获取有效 token (缓存或重新登录)"""
    picacg = _CREDS.get("picacg", {})
    token = picacg.get("token")
    # TODO: token 过期检测 (简单起见每次重新登录)
    email = picacg.get("email") or os.environ.get("PICA_ACCOUNT")
    password = picacg.get("password") or os.environ.get("PICA_PASSWORD")
    if not email or not password:
        return None
    token = _picacg_login(email, password, proxy)
    if token:
        picacg["token"] = token
        _CREDS["picacg"] = picacg
        try:
            import credentials
            credentials.save_credentials(_CREDS)
        except Exception:
            pass
    return token


# ═══════════════════════════════════════════════════════════
# 搜索
# ═══════════════════════════════════════════════════════════

def search_comics(query, proxy=None, count=20, verbose=True):
    """搜索 picacg 漫画，返回标准化结果 [{id, title, author, pages, ...}]"""
    token = _get_token(proxy)
    if not token:
        print("❌ 未配置 picacg 账号\n   设置: python3 pica_dl.py --setup")
        return []

    url = f"{PICA_API_BASE}/comics?keyword={quote_plus(query)}&page=1&s=dd"
    headers = _build_auth_headers(token)
    cmd = ["curl", "-s", "--max-time", "15", "--compressed"]
    for k, v in headers.items():
        cmd.extend(["-H", f"{k}: {v}"])
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)

    if verbose:
        print(f"🔍 picacg 搜索: {query}")

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            print(f"  ❌ 请求失败")
            return []
        data = json.loads(r.stdout)
        if data.get("code") != 200:
            print(f"  ❌ API 错误: {data.get('message', '')}")
            return []

        comics = data["data"]["comics"]["docs"][:count]
        if verbose:
            print(f"   找到 {data['data']['comics']['total']} 个结果, 显示前 {len(comics)} 个")

        results = []
        for c in comics:
            cid = c.get("_id", "?")
            title = c.get("title", "N/A")
            author = c.get("author", "?")
            pages = c.get("pagesCount", "?")
            categories = c.get("categories", [])
            cats = ", ".join(categories) if categories else ""
            results.append({
                "id": cid,
                "title": title,
                "author": author,
                "pages": pages,
                "categories": cats,
                "epsCount": c.get("epsCount", "?"),
                "finished": c.get("finished", False),
                "url": f"https://pica.picacomic.com/comics/{cid}",
            })
            if verbose:
                fin = " [完结]" if c.get("finished") else ""
                print(f"   {cid:>24} | {title[:45]:<45} | {author}{fin}")

        return results
    except json.JSONDecodeError:
        print("  ❌ JSON 解析失败")
    except Exception as e:
        print(f"  ❌ 搜索异常: {e}")
    return []


# ═══════════════════════════════════════════════════════════
# 下载
# ═══════════════════════════════════════════════════════════

def _check_pica_cli():
    """检查 pica-cli 是否可用"""
    try:
        r = subprocess.run(["pica-cli", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def download_comic(comic_id, proxy=None, output_dir=None, verbose=True):
    """
    下载 picacg 漫画
    策略: pica-cli 优先 → 直接 API 回退
    """
    picacg = _CREDS.get("picacg", {})
    email = picacg.get("email") or os.environ.get("PICA_ACCOUNT")
    password = picacg.get("password") or os.environ.get("PICA_PASSWORD")

    if not email or not password:
        print("❌ 未配置 picacg 账号\n   设置: python3 pica_dl.py --setup")
        return False

    has_cli = _check_pica_cli()

    if has_cli:
        # 策略1: pica-cli 子进程
        if verbose:
            print(f"📥 picacg 下载: {comic_id} (via pica-cli)")

        env = os.environ.copy()
        env["PICA_ACCOUNT"] = email
        env["PICA_PASSWORD"] = password
        env["PICA_DL_CONTENT"] = "search"
        env["PICA_DL_SEARCH_KEYWORDS"] = comic_id
        if proxy:
            env["PICA_PROXY"] = proxy
        env["PICA_DL_CONCURRENCY"] = "8"

        try:
            r = subprocess.run(["pica-cli"], env=env, timeout=600)
            if r.returncode == 0:
                if verbose:
                    print("✅ 下载完成 (pica-cli)")
                return True
            else:
                if verbose:
                    print(f"⚠️  pica-cli 返回码 {r.returncode}, 回退到直接下载")
        except subprocess.TimeoutExpired:
            if verbose:
                print("⚠️  pica-cli 超时, 回退到直接下载")
        except FileNotFoundError:
            pass

    # 策略2: 直接 API 下载 (简化版)
    if verbose:
        print(f"📥 picacg 下载: {comic_id} (via API)")

    token = _get_token(proxy)
    if not token:
        return False

    if not output_dir:
        output_dir = os.path.join(os.getcwd(), "picacg", comic_id)

    try:
        # 1. 获取漫画信息
        headers = _build_auth_headers(token)
        info_url = f"{PICA_API_BASE}/comics/{comic_id}"
        cmd = ["curl", "-s", "--max-time", "15", "--compressed"]
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.append(info_url)

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
        if data.get("code") != 200:
            print(f"  ❌ 获取漫画信息失败")
            return False

        comic = data["data"]["comic"]
        title = comic.get("title", comic_id)

        # 2. 获取章节列表
        eps_url = f"{PICA_API_BASE}/comics/{comic_id}/eps?page=1"
        cmd[-1] = eps_url
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        eps_data = json.loads(r.stdout)
        episodes = eps_data["data"]["eps"]["docs"]

        if verbose:
            print(f"  📖 {title} — {len(episodes)} 章节")

        # 3. 逐章节下载
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:60]
        base_dir = os.path.join(output_dir, safe_title)
        os.makedirs(base_dir, exist_ok=True)

        success_eps = 0
        for ep in episodes:
            ep_id = ep.get("_id")
            ep_title = ep.get("title", f"第{ep.get('order','?')}话")
            ep_order = ep.get("order", 0)

            safe_ep = re.sub(r'[<>:"/\\|?*]', '_', f"{ep_order:03d}_{ep_title}")[:60]
            ep_dir = os.path.join(base_dir, safe_ep)
            os.makedirs(ep_dir, exist_ok=True)

            # 获取图片列表
            pages_url = f"{PICA_API_BASE}/comics/{comic_id}/order/{ep_order}/pages?page=1"
            cmd[-1] = pages_url
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            pages_data = json.loads(r.stdout)
            pages = pages_data["data"]["pages"]["docs"]

            if verbose:
                print(f"    📄 {safe_ep} — {len(pages)} 页")

            # 下载图片
            for p in pages:
                media = p["media"]
                img_url = media.get("path", "")
                if not img_url.startswith("http"):
                    img_url = f"https://{media.get('fileServer','storage1.picacomic.com')}/static/{img_url}"

                fname = f"{p.get('_id','')}.{media.get('path','').split('.')[-1] or 'jpg'}"
                out_path = os.path.join(ep_dir, fname)

                if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                    continue

                dl_cmd = ["curl", "-sL", "--max-time", "30", "-o", out_path]
                if proxy:
                    dl_cmd.extend(["--proxy", proxy])
                # picacg 图片需要 token
                for k, v in headers.items():
                    if k in ("authorization", "api-key"):
                        dl_cmd.extend(["-H", f"{k}: {v}"])
                dl_cmd.append(img_url)

                try:
                    subprocess.run(dl_cmd, capture_output=True, timeout=35)
                except Exception:
                    pass

            success_eps += 1

        if verbose:
            total_size = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, files in os.walk(base_dir)
                for f in files
            )
            mb = total_size / 1024 / 1024
            print(f"\n✅ 下载完成: {success_eps} 章 ({mb:.1f} MB) → {base_dir}")

        return success_eps > 0

    except Exception as e:
        print(f"  ❌ 下载异常: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# 连通性检查
# ═══════════════════════════════════════════════════════════

def run_check():
    print("🔬 picacg 连通性检测")
    has_cli = _check_pica_cli()
    print(f"   {'✅' if has_cli else '⚠️'} pica-cli {'已安装' if has_cli else '未安装 (npm i -g pica-cli)'}")

    picacg = _CREDS.get("picacg", {})
    has_creds = bool(picacg.get("email") or os.environ.get("PICA_ACCOUNT"))
    print(f"   {'✅' if has_creds else '⚠️'} picacg 账号 {'已配置' if has_creds else '未配置 (--setup)'}")

    # 测试 API 可达性
    try:
        r = subprocess.run(
            ["curl", "-sI", "--max-time", "8", f"{PICA_API_BASE}/"],
            capture_output=True, timeout=10)
        print(f"   {'✅' if r.returncode == 0 else '❌'} API {PICA_API_BASE}")
    except Exception:
        print(f"   ❌ API 不可达")


# ═══════════════════════════════════════════════════════════
# 凭证配置
# ═══════════════════════════════════════════════════════════

def setup_credentials():
    print("🔐 picacg 凭证配置")
    print("=" * 40)
    email = input("  邮箱: ").strip()
    password = input("  密码: ").strip()
    if not email or not password:
        print("❌ 邮箱和密码不能为空")
        return

    picacg = {"email": email, "password": password}
    _CREDS["picacg"] = picacg

    try:
        from credentials import save_credentials
        save_credentials(_CREDS)
        print("✅ 已保存到 credentials.json")
    except Exception as e:
        print(f"⚠️  保存失败: {e}")
        print(f"💡 可手动设置环境变量:")
        print(f"   export PICA_ACCOUNT={email}")
        print(f"   export PICA_PASSWORD={password}")


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="picacg (哔咔漫画) 下载器",
        epilog="示例:\n"
               "  python3 pica_dl.py --search \"关键词\"\n"
               "  python3 pica_dl.py 5f8c8c3c8b5e3c0b1c8b4567\n"
               "  python3 pica_dl.py --favorites\n"
               "  python3 pica_dl.py --setup\n"
               "  python3 pica_dl.py --check",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?", help="漫画 ID")
    parser.add_argument("--search", metavar="QUERY", help="搜索漫画")
    parser.add_argument("--count", type=int, default=20, help="搜索结果数")
    parser.add_argument("--favorites", action="store_true", help="下载收藏夹")
    parser.add_argument("--leaderboard", action="store_true", help="下载排行榜")
    parser.add_argument("-p", "--proxy", metavar="PROXY", help="代理地址")
    parser.add_argument("-o", "--output", metavar="DIR", help="输出目录")
    parser.add_argument("-q", "--quiet", action="store_true", help="安静模式")
    parser.add_argument("--setup", action="store_true", help="配置凭证")
    parser.add_argument("--check", action="store_true", help="连通性检测")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    if args.setup:
        setup_credentials()
        return

    if args.check:
        run_check()
        return

    if args.search:
        results = search_comics(args.search, proxy=args.proxy,
                                count=args.count, verbose=not args.quiet)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif results:
            print(f"\n💡 下载: python3 pica_dl.py {results[0]['id']}")
        return

    if args.favorites:
        print("📥 下载 picacg 收藏夹 (via pica-cli)")
        picacg = _CREDS.get("picacg", {})
        email = picacg.get("email") or os.environ.get("PICA_ACCOUNT")
        password = picacg.get("password") or os.environ.get("PICA_PASSWORD")
        if not email:
            print("❌ 未配置账号, 运行: python3 pica_dl.py --setup")
            sys.exit(1)
        env = os.environ.copy()
        env["PICA_ACCOUNT"] = email
        env["PICA_PASSWORD"] = password
        env["PICA_DL_CONTENT"] = "favorites"
        if args.proxy:
            env["PICA_PROXY"] = args.proxy
        subprocess.run(["pica-cli"], env=env)
        return

    if args.leaderboard:
        print("📥 下载 picacg 排行榜 (via pica-cli)")
        picacg = _CREDS.get("picacg", {})
        email = picacg.get("email") or os.environ.get("PICA_ACCOUNT")
        password = picacg.get("password") or os.environ.get("PICA_PASSWORD")
        if not email:
            print("❌ 未配置账号, 运行: python3 pica_dl.py --setup")
            sys.exit(1)
        env = os.environ.copy()
        env["PICA_ACCOUNT"] = email
        env["PICA_PASSWORD"] = password
        env["PICA_DL_CONTENT"] = "leaderboard"
        if args.proxy:
            env["PICA_PROXY"] = args.proxy
        subprocess.run(["pica-cli"], env=env)
        return

    if args.input:
        ok = download_comic(args.input, proxy=args.proxy,
                           output_dir=args.output, verbose=not args.quiet)
        if not ok:
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
