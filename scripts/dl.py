#!/usr/bin/env python3
"""
四站下载工具统一入口  v1
========================
自动识别 URL 并路由到正确脚本:

  nhentai.net / ID     → nhentai_dl.py
  e-hentai/exhentai    → ehentai_dl.py
  18comic/jmcomic/JM   → jmcomic_dl.py
  picacg/picacomic     → picacg_dl.py

用法:
  python3 dl.py <url|id>
  python3 dl.py --search "关键词"       # nhentai搜索
  python3 dl.py --jm-search "关键词"    # 禁漫搜索
  python3 dl.py --random --tag "标签"   # nhentai随机
  python3 dl.py --check                 # 全站检测
"""

import re, sys, os, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

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


def main():
    args = sys.argv[1:]

    # --check: run all checks
    if '--check' in args:
        print("🔬 四站全检")
        print("=" * 50)
        for script in ['nhentai_dl.py', 'ehentai_dl.py', 'jmcomic_dl.py']:
            path = os.path.join(SCRIPT_DIR, script)
            if os.path.exists(path):
                print(f"\n━━━ {script} ━━━")
                subprocess.run([sys.executable, path, '--check'], timeout=30)
        print(f"\n{'=' * 50}")
        print("✅ 四站全检完成")
        return

    # --setup
    if '--setup' in args:
        from credentials import setup_credentials, check_credentials
        check_credentials()
        setup_credentials()
        return

    # --help / -h
    if '--help' in args or '-h' in args:
        print("🔀 四站下载工具统一入口")
        print()
        print("  自动识别 URL 并路由到正确脚本:")
        print("    nhentai / 纯数字 ID       → nhentai_dl.py")
        print("    e-hentai / exhentai       → ehentai_dl.py")
        print("    18comic / JM / jmcomic    → jmcomic_dl.py")
        print()
        print("用法:")
        print("   python3 dl.py <url|id>     # 自动路由下载")
        print("   python3 dl.py --check      # 四站全检")
        print("   python3 dl.py --help       # 帮助")
        return

    # Auto-route based on first non-flag argument
    target = None
    for a in args:
        if not a.startswith('-'):
            target = a
            break

    if target:
        script = route(target)
        if script:
            path = os.path.join(SCRIPT_DIR, script)
            print(f"🔀 路由到 {script}")
            subprocess.run([sys.executable, path] + args)
            return

    # Fallback to nhentai_dl.py
    path = os.path.join(SCRIPT_DIR, 'nhentai_dl.py')
    subprocess.run([sys.executable, path] + args)


if __name__ == "__main__":
    main()
