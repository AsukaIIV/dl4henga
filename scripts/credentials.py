#!/usr/bin/env python3
"""
统一凭证管理
============
为 ExHentai 和 PicAcg 提供凭证的存储、读取和交互式配置。

存储位置 (按优先级):
  1. 环境变量
  2. ~/.config/nhentai-dl/credentials.json
  3. 交互式输入

用法:
  from credentials import get_credentials, setup_credentials
  creds = get_credentials()
  setup_credentials()  # 交互式配置
"""

import os, json, sys


CONFIG_DIR = os.path.expanduser("~/.config/dl4henga")
CONFIG_FILE = os.path.join(CONFIG_DIR, "credentials.json")


def _load_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_config(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG_FILE, 0o600)  # 仅所有者可读写


def get_credentials():
    """获取 ExHentai 凭证，按 env > file 优先级"""
    config = _load_config()
    creds = {}

    eh_cookie = (os.environ.get("EXHENTAI_COOKIES") or
                 os.environ.get("NH_EH_COOKIE") or
                 config.get("exhentai", {}).get("cookies"))
    if eh_cookie:
        creds["exhentai_cookies"] = eh_cookie

    return creds


def set_exhentai_cookies(cookies):
    config = _load_config()
    config.setdefault("exhentai", {})["cookies"] = cookies
    _save_config(config)
    print(f"✅ ExHentai cookies 已保存到 {CONFIG_FILE}")


def setup_credentials():
    """交互式凭证配置向导"""
    print("\n🔐 凭证配置向导")
    print("=" * 50)
    print()

    print("📌 ExHentai (Sad Panda)")
    print("   需要三个 cookie: ipb_member_id, ipb_pass_hash, igneous")
    print("   获取: 浏览器登录 e-hentai → 访问 exhentai → F12 → Application → Cookies")
    choice = input("\n   输入 cookie 字符串 [回车跳过]: ").strip()
    if choice:
        set_exhentai_cookies(choice)
        print("   也可设置环境变量: export EXHENTAI_COOKIES='...'")

    print(f"\n✅ 凭证已保存到 {CONFIG_FILE}")


def check_credentials(verbose=True):
    """检查凭证配置状态"""
    creds = get_credentials()
    has_eh = bool(creds.get("exhentai_cookies"))

    if verbose:
        print(f"🔐 凭证状态:")
        print(f"   ExHentai: {'✅ 已配置' if has_eh else '⚠️  未配置'}")
        if not has_eh:
            print(f"   💡 配置: python3 scripts/dl.py --setup")

    return has_eh


if __name__ == "__main__":
    if "--setup" in sys.argv:
        setup_credentials()
    else:
        creds = get_credentials()
        print(f"已加载凭证: {list(creds.keys())}")
        check_credentials()
