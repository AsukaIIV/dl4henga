#!/usr/bin/env python3
"""
nhentai 镜像站点自动发现/更新器  v2
===================================
- 从多个更新源抓取最新镜像列表
- 并行连通性测试 (支持代理)
- DNS 探测发现新镜像 (扩展 TLD/前缀)
- 更新 mirrors.json

用法:
  python3 update_mirrors.py                 # 交互式更新
  python3 update_mirrors.py --auto          # 自动更新
  python3 update_mirrors.py --test-only     # 仅测试现有镜像
  python3 update_mirrors.py --scan          # DNS 扫描新镜像
  python3 update_mirrors.py -p <proxy>      # 指定代理
"""

import json
import os
import sys
import time
import socket
import subprocess
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MIRRORS_PATH = os.path.join(SCRIPT_DIR, "mirrors.json")

# ── 更新源 ────────────────────────────────────────────────
KNOWN_UPDATE_URLS = [
    "https://raw.githubusercontent.com/nickdeny/nhentai-mirror-list/main/mirrors.json",
    "https://nhentai-mirror.pages.dev/mirrors.json",
]

# ── DNS 探测候选 ──────────────────────────────────────────
DNS_CANDIDATE_TLDS = [
    "net", "to", "xxx", "com", "org", "io", "co", "me", "xyz",
    "cc", "tv", "info", "pw", "ws", "su", "nu", "se", "dk",
    "asia", "site", "online", "live", "blog", "fun", "world",
]

DNS_PREFIXES = [
    "nhentai", "nxhentai", "n-hentai", "www.nhentai", "hentai",
    "hentai.mama", "hentai.cafe", "nhentai.moe",
    "nhentai.space", "nhentaix",
]

# ── 工具函数 ──────────────────────────────────────────────

def discover_proxy():
    """代理自发现 (与 nhentai_dl.py 相同逻辑)"""
    # 1. 环境变量
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                "ALL_PROXY", "all_proxy"):
        val = os.environ.get(var)
        if val and (val.startswith("http://") or val.startswith("socks5://")):
            return val

    # 2. 端口扫描
    for port in [7890, 7897, 1087, 8118, 10808, 10809, 8080, 3128, 8888]:
        for host in ("127.0.0.1", "localhost"):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                if s.connect_ex((host, port)) == 0:
                    s.close()
                    proxy = f"http://127.0.0.1:{port}"
                    if _test_proxy(proxy):
                        return proxy
                s.close()
            except Exception:
                pass

    # 3. Clash 配置
    for cfg_path in [
        os.path.expanduser("~/.config/clash/config.yaml"),
        os.path.expanduser("~/.config/mihomo/config.yaml"),
        os.path.expanduser("~/.config/clash-verge/config.yaml"),
    ]:
        try:
            with open(cfg_path, "r") as f:
                content = f.read()
            m = re.search(r"(?:mixed-?port|port|socks-?port):\s*(\d+)", content)
            if m:
                proxy = f"http://127.0.0.1:{m.group(1)}"
                if _test_proxy(proxy):
                    return proxy
        except Exception:
            continue

    return None


def _test_proxy(proxy_url, timeout=3):
    try:
        result = subprocess.run(
            ["curl", "-sI", "--max-time", str(timeout),
             "--proxy", proxy_url, "https://httpbin.org/ip"],
            capture_output=True, text=False, timeout=timeout + 3,
        )
        return result.returncode == 0 and b"origin" in result.stdout
    except Exception:
        return False


def load_mirrors():
    try:
        with open(MIRRORS_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"mirrors": [], "last_updated": "never"}


def save_mirrors(data):
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(MIRRORS_PATH, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  💾 已保存到 {MIRRORS_PATH}")


def curl_fetch(url, proxy=None, timeout=12):
    """用 curl 获取 URL 内容"""
    cmd = ["curl", "-sL", "--max-time", str(timeout), "--connect-timeout", "8",
           "-H", "User-Agent: dl4henga-mirror-updater/2.0"]
    if proxy:
        cmd.extend(["--proxy", proxy])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        if result.returncode == 0 and len(result.stdout) > 100:
            return result.stdout
    except Exception:
        pass
    return None


def test_mirror(domain, proxy=None, timeout=8):
    """测试镜像连通性: DNS + HTTPS"""
    try:
        socket.gethostbyname(domain)
    except socket.gaierror:
        return False, "DNS 解析失败"

    try:
        cmd = ["curl", "-sI", "--max-time", str(timeout),
               "-H", "User-Agent: Mozilla/5.0"]
        if proxy:
            cmd.extend(["--proxy", proxy])
        cmd.append(f"https://{domain}/")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 3)
        if result.returncode == 0:
            status_match = re.search(r"HTTP/\d\.\d\s+(\d+)", result.stdout)
            if status_match and int(status_match.group(1)) < 500:
                return True, f"HTTP {status_match.group(1)}"
            return True, f"HTTP {status_match.group(1) if status_match else '?'}"
        return False, f"curl 返回码 {result.returncode}"
    except Exception as e:
        return False, str(e)[:60]


def fetch_remote_mirrors(proxy=None):
    """从远程更新源获取最新镜像列表"""
    new_mirrors = []
    for url in KNOWN_UPDATE_URLS:
        print(f"  📡 获取远程列表: {url}")
        text = curl_fetch(url, proxy=proxy, timeout=15)
        if not text:
            print(f"     ⚠️  获取失败")
            continue
        try:
            remote = json.loads(text)
            mirrors = remote.get("mirrors", [])
            print(f"     ✅ 获取到 {len(mirrors)} 个镜像")
            for m in mirrors:
                new_mirrors.append({
                    "domain": m.get("domain", m.get("alias", [m.get("domain", "")])[0] if m.get("alias") else m.get("domain", "")),
                    "aliases": m.get("aliases", [m.get("domain", "")]),
                    "status": "active",
                    "type": m.get("type", "mirror"),
                    "url_pattern": m.get("url_pattern", "/g/{id}/"),
                    "download_pattern": m.get("download_pattern", "/g/{id}/download"),
                    "tested_at": datetime.now().strftime("%Y-%m-%d"),
                })
        except json.JSONDecodeError:
            print(f"     ⚠️  JSON 解析失败")
    return new_mirrors


def dns_scan_candidates(proxy=None):
    """DNS 扫描: 探测常见前缀+TLD 组合"""
    found = []

    def probe(domain):
        try:
            socket.gethostbyname(domain)
            return domain
        except socket.gaierror:
            return None

    candidates = []
    # 完整域名
    for prefix in DNS_PREFIXES:
        if "." in prefix:
            candidates.append(prefix)
        else:
            for tld in DNS_CANDIDATE_TLDS:
                candidates.append(f"{prefix}.{tld}")

    # 额外模式: nhentai-{tld}
    for tld in DNS_CANDIDATE_TLDS[:12]:
        candidates.append(f"nhentai-{tld}.{tld}")

    # 去重
    candidates = list(set(candidates))

    print(f"  🔍 DNS 扫描 {len(candidates)} 个候选域名...")
    with ThreadPoolExecutor(max_workers=30) as pool:
        futures = {pool.submit(probe, c): c for c in candidates}
        for f in as_completed(futures):
            result = f.result()
            if result:
                found.append(result)

    # 对发现的域名做连通性测试
    if found:
        print(f"  🆕 DNS 解析成功 {len(found)} 个域名，正在测试连通性...")
        tested_found = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {}
            for domain in found:
                futures[pool.submit(test_mirror, domain, proxy, 10)] = domain
            for f in as_completed(futures):
                domain = futures[f]
                ok, msg = f.result()
                icon = "✅" if ok else "❌"
                print(f"     {icon} {domain:35s} — {msg}")
                if ok:
                    tested_found.append(domain)
        return tested_found

    return found


def merge_mirrors(existing, new_list, tested_results):
    existing_domains = {m["domain"] for m in existing}
    merged = list(existing)
    for m in new_list:
        domain = m["domain"]
        if domain not in existing_domains:
            existing_domains.add(domain)
            merged.append(m)
    for m in merged:
        domain = m["domain"]
        if domain in tested_results:
            ok, msg = tested_results[domain]
            m["status"] = "active" if ok else "down"
            m["tested_at"] = datetime.now().strftime("%Y-%m-%d")
            m["test_result"] = msg
    return merged


def main():
    import argparse
    parser = argparse.ArgumentParser(description="nhentai 镜像站点更新器 v2")
    parser.add_argument("--auto", action="store_true", help="自动更新，不询问")
    parser.add_argument("--test-only", action="store_true", help="仅测试现有镜像连通性")
    parser.add_argument("--scan", action="store_true", help="DNS 扫描新镜像")
    parser.add_argument("-p", "--proxy", metavar="PROXY", help="指定代理")
    args = parser.parse_args()

    # ── 代理 ──
    proxy = args.proxy or discover_proxy()
    if proxy:
        print(f"🔗 使用代理: {proxy}")

    print("nhentai 镜像站点更新器 v2")
    print("=" * 50)

    data = load_mirrors()
    existing = data.get("mirrors", [])
    print(f"📦 当前镜像数: {len(existing)}")

    # ── 测试现有镜像 (并行) ──
    print("\n🔬 连通性测试 (并行)...")
    tested = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for m in existing:
            domain = m["domain"]
            futures[pool.submit(test_mirror, domain, proxy, 10)] = domain
        for f in as_completed(futures):
            domain = futures[f]
            ok, msg = f.result()
            icon = "✅" if ok else "❌"
            print(f"  {icon} {domain:30s} — {msg}")
            tested[domain] = (ok, msg)

    if args.test_only:
        data["mirrors"] = merge_mirrors(existing, [], tested)
        save_mirrors(data)
        return

    # ── 获取远程列表 ──
    print("\n🌍 获取远程镜像列表...")
    remote_mirrors = fetch_remote_mirrors(proxy)

    # ── DNS 扫描 ──
    dns_found = []
    if args.scan:
        print("\n🔎 DNS 扫描...")
        dns_found = dns_scan_candidates(proxy)
        for domain in dns_found:
            ok, msg = test_mirror(domain, proxy, 10)
            icon = "✅" if ok else "❌"
            print(f"     {icon} 连通性 — {msg}")
            tested[domain] = (ok, msg)

    # ── 合并 ──
    all_new = remote_mirrors + [
        {
            "domain": d,
            "aliases": [d],
            "status": "active",
            "type": "mirror",
            "url_pattern": "/g/{id}/",
            "download_pattern": "/g/{id}/download",
            "tested_at": datetime.now().strftime("%Y-%m-%d"),
        }
        for d in dns_found
    ]

    data["mirrors"] = merge_mirrors(existing, all_new, tested)

    # ── 统计 ──
    active = sum(1 for m in data["mirrors"] if m.get("status") == "active")
    down = sum(1 for m in data["mirrors"] if m.get("status") == "down")
    print(f"\n📊 最终统计:")
    print(f"  总计: {len(data['mirrors'])} 个镜像")
    print(f"  正常: {active} 个")
    print(f"  离线: {down} 个")

    save_mirrors(data)
    print("\n✅ 更新完成")


if __name__ == "__main__":
    main()
