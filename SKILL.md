---
name: dl4henga
description: >
  四站同人志下载工具集 (nhentai / E-Hentai / JMComic / picacg)。
  支持四站并行搜索、随机推荐、BT种子提取、逐页高清下载、跨站全集下载、代理自发现。

触发规则 (任一满足即激活):
  1. URL 含 nhentai.net / nhentai.to / nhentai.xxx / e-hentai.org / exhentai.org /
     18comic.vip / jmcomic / picacg / picacomic 等域名
  2. 纯数字 ID (1-6位) 或 JM+数字 ID 或 24位 hex ID
  3. 用户要求搜索/下载 nhentai/禁漫/E站/哔咔 的本子
  4. 用户要求随机推荐/下载本子
  5. 用户提及 "nhentai" "禁漫" "ehentai" "exhentai" "picacg" 等画师名
  6. 用户要求更新镜像或配置凭证
  7. 用户询问如何部署/安装/发布 dl4henga
---

# dl4henga — 四站下载工具集 v2

## 核心脚本

| 脚本 | 站点 | 用途 |
|------|------|------|
| **`scripts/dl.py`** | **统一入口** | 自动识别 URL 路由 + 三站并行搜索 |
| **`scripts/search_engine.py`** | **三站** | 并行搜索引擎 (去重/降级/合并) |
| `scripts/nhentai_dl.py` | nhentai | 种子/直链 + 搜索/随机 + 逐页下载 |
| `scripts/ehentai_dl.py` | E-Hentai/ExHentai | 逐页下载 + Archive + Cookie + 关键词搜索 |
| `scripts/jmcomic_dl.py` | JMComic (禁漫天堂) | 自动解密 + 搜索/随机 |
| `scripts/pica_dl.py` | picacg (哔咔漫画) | 搜索 + pica-cli/API 下载 |
| `scripts/update_mirrors.py` | nhentai | 镜像维护 |

## 依赖安装

```bash
# Python 依赖 (必须)
pip3 install jmcomic cloudscraper curl_cffi

# 可选: picacg 下载加速
npm install -g pica-cli
```

## 安装与部署

### 方式一: Git 克隆 (推荐)

```bash
git clone https://github.com/AsukaIIV/dl4henga.git
cd dl4henga/scripts

# Python 依赖
pip3 install jmcomic cloudscraper curl_cffi

# 直接使用
python3 dl.py --help
python3 dl.py --search "毛玉牛乳"
```

### 方式二: 作为 AI Skill 部署

将此目录放到 AI 工具的 skills 路径下:

```bash
# DeepSeek TUI
cp -r dl4henga ~/.deepseek/skills/dl4henga

# Claude Code / Claude Desktop
cp -r dl4henga ~/.claude/skills/dl4henga
```

### 环境要求

| 组件 | 版本 | 用途 |
|------|------|------|
| Python | ≥ 3.8 | 核心脚本 |
| curl | 系统自带 | HTTP 请求 |
| pip 包 | jmcomic, cloudscraper, curl_cffi | 站点访问 |
| pica-cli (可选) | latest | picacg 下载加速 |

### 项目结构

```
dl4henga/
├── README.md           ← 项目说明
├── SKILL.md            ← AI Skill 定义 (本文档)
└── scripts/            ← Python 核心
    ├── dl.py           ← 统一路由 + 凭证横幅
    ├── search_engine.py ← 并行搜索 + 去重 + web 验证
    ├── nhentai_dl.py   ← nhentai 种子/直链/逐页
    ├── ehentai_dl.py   ← E-Hentai Archive/逐页
    ├── jmcomic_dl.py   ← JMComic 自动解密
    ├── pica_dl.py      ← picacg API/pica-cli
    ├── credentials.py  ← 凭证读写
    ├── update_mirrors.py ← nhentai 镜像维护
    └── mirrors.json    ← 镜像列表
```

## Agent 凭证自配置

**在执行任何需要凭证的操作前，先检查并主动配置。**

### 检查时机
- 用户首次使用任何功能时
- 搜索/下载涉及 picacg 或 ExHentai 时
- 用户说"配置"、"setup"、"登录"时

### 配置流程

**ExHentai cookie**:
1. 运行 `python3 scripts/dl.py --check` 检测
2. 未配置时，引导用户:
   - 浏览器登录 e-hentai.org → F12 → Application → Cookies
   - 复制 `ipb_member_id`, `ipb_pass_hash`, `igneous` 三个值
   - 格式: `ipb_member_id=xxx; ipb_pass_hash=xxx; igneous=xxx`
3. 用户提供后，直接写入 credentials.json:
   ```bash
   python3 -c "
   import json, os
   p = os.path.expanduser('~/.config/dl4henga/credentials.json')
   os.makedirs(os.path.dirname(p), exist_ok=True)
   data = {}
   if os.path.exists(p):
       with open(p) as f: data = json.load(f)
   data['exhentai_cookies'] = '用户提供的cookie字符串'
   with open(p, 'w') as f:
       json.dump(data, f)
   os.chmod(p, 0o600)
   "
   ```

**picacg 账号**:
1. 引导用户提供哔咔注册邮箱和密码
2. 直接写入 credentials.json:
   ```bash
   python3 -c "
   import json, os
   p = os.path.expanduser('~/.config/dl4henga/credentials.json')
   os.makedirs(os.path.dirname(p), exist_ok=True)
   data = {}
   if os.path.exists(p):
       with open(p) as f: data = json.load(f)
   data['picacg'] = {'email': '用户邮箱', 'password': '用户密码'}
   with open(p, 'w') as f:
       json.dump(data, f)
   os.chmod(p, 0o600)
   "
   ```
3. 自动验证: `python3 scripts/pica_dl.py --check`

### 存储位置
`~/.config/dl4henga/credentials.json` (权限 600)

```json
{
  "exhentai_cookies": "ipb_member_id=xxx; ipb_pass_hash=xxx; igneous=xxx",
  "picacg": {"email": "user@example.com", "password": "secret"}
}
```

---

## 一、nhentai

```bash
python3 scripts/nhentai_dl.py --check
python3 scripts/nhentai_dl.py --search "关键词" [--count 20] [--chinese]
python3 scripts/nhentai_dl.py --random --tag "艺术家" --dl
python3 scripts/nhentai_dl.py --dl <id|url>
python3 scripts/nhentai_dl.py --artist-dl "艺术家" --chinese -o ./全集
```

策略: 磁力 > BT种子 > HTTP直链 > FTP → 无种子 `--dl` 逐页

---

## 二、E-Hentai / ExHentai

```bash
python3 scripts/ehentai_dl.py --check
python3 scripts/ehentai_dl.py --search "关键词" [--count 20] [--json]
python3 scripts/ehentai_dl.py https://e-hentai.org/g/{id}/{token}/
python3 scripts/ehentai_dl.py -c "cookie_str" <url>
```

策略: Archive(zip) 优先 → 逐页回退

---

## 三、JMComic (禁漫天堂)

```bash
python3 scripts/jmcomic_dl.py --check
python3 scripts/jmcomic_dl.py --search "关键词" [--count 20] [--json]
python3 scripts/jmcomic_dl.py --random --tag "标签"
python3 scripts/jmcomic_dl.py 123456
python3 scripts/jmcomic_dl.py 350234 -o ~/Desktop
```

底层: `hect0x7/JMComic-Crawler-Python` (⭐5.8k)，自动镜像 + 解密

> **输出目录**: `-o` 指定基础目录，jmcomic 会在其下自动创建 `作者/本子名` 子目录。

---

## 四、picacg (哔咔漫画) v1 新增

```bash
python3 scripts/pica_dl.py --check
python3 scripts/pica_dl.py --search "关键词" [--count 20] [--json]
python3 scripts/pica_dl.py <24位hex_comic_id>
python3 scripts/pica_dl.py --favorites
python3 scripts/pica_dl.py --leaderboard
python3 scripts/pica_dl.py --setup
```

底层: `justorez/pica-cli` (⭐220) + 直接 API 回退。需配置 picacg 账号密码。

> **搜索**: 通过 picacg REST API 搜索，返回标题/作者/章节数。**下载**: pica-cli 优先（需要 `npm i -g pica-cli`），无 pica-cli 时回退到直接 API 逐章下载。

---

## 五、四站统一搜索 (v2)

`--search` 默认并行搜索 nhentai + JMComic + E-Hentai，自动去重合并。
某站不可用时**静默降级**，不影响其他站点。

```bash
# 三站搜索 (默认)
python3 scripts/dl.py --search "毛玉牛乳"

# 单站搜索
python3 scripts/dl.py --search "fate" --site jmcomic
python3 scripts/dl.py --search "原神" --site nhentai,eh

# 站点简写: nh / jm / eh
python3 scripts/dl.py --search "全彩" --site nh,jm

# JSON 输出 (供脚本消费)
python3 scripts/dl.py --search "test" --json

# 三站随机推荐
python3 scripts/dl.py --random
python3 scripts/dl.py --random --tag "chinese"
python3 scripts/dl.py --random --site jm
```

### 搜索降级行为

```
三站搜索: nhentai + JMComic + E-Hentai
    │
    ├─ nhentai 可用    → ✅ 正常搜索
    ├─ JMComic 可用    → ✅ 正常搜索
    └─ E-Hentai 不可达 → ⚠️ 跳过，显示在 sites_failed

结果: 前两站结果合并去重，E-Hentai 静默跳过
```

### 去重规则

- 标题相似度 > 85% 视为同一本子
- 跨站重复时保留信息最全的那个 (有页数 > 标题更长)
- 跨站命中的本子标注 `🌐NH|JM|EH`

---

## 六、四站对比

| | nhentai | E-Hentai | JMComic | picacg |
|---|---|---|---|---|
| 需要登录 | ❌ | exhentai 需 cookie | ❌ | ✅ 账号密码 |
| 需要代理 | 需要 | 需要 | 不需要 | 不需要 |
| 搜索 | ✅ | ✅ | ✅ | ✅ |
| 随机推荐 | ✅ | ✅ | ✅ | - |
| 全集下载 | ✅ `--artist-dl` | tag `--download-all` | - | ✅ `--favorites` |
| 逐页下载 | ✅ `--dl` | ✅ 自动 | ✅ 自动 | ✅ API |
| Archive (zip) | - | ✅ 优先 | - | ✅ via pica-cli |
| 种子/BT 提取 | ✅ 磁力+种子 | - | - | - |
| JSON 输出 | ✅ | ✅ | ✅ | ✅ |
| 代理自发现 | ✅ | ✅ | ✅ | - |
| 排行榜 | - | - | - | ✅ `--leaderboard` |

---

## 七、统一命令速查

| 参数 | 说明 |
|------|------|
| `--search QUERY` | **三站并行搜索** (v2: 默认全站) |
| `--site SITES` | 限制搜索站点: nhentai, jmcomic, ehentai (逗号分隔) |
| `--random` | **三站随机推荐** (v2: 跨站) |
| `--tag TAG` | 配合 --search/--random 使用 |
| `--count N` | 每站搜索结果数 (默认 20) |
| `--page N` | 搜索页码 (默认 1) |
| `--sort SORT` | 排序: popular (最热) / recent (最新) |
| `--chinese` | 过滤只显示中文结果 (nhentai 支持) |
| `--no-web-verify` | 关闭 web 搜索双向验证 (默认开启) |
| `--web-threshold F` | web 验证触发的相似度下限 (默认 0.5) |
| `--json` | JSON 格式输出 |
| `-p, --proxy` | 代理地址 |
| `-o, --output` | 输出目录 |
| `-q, --quiet` | 安静模式 |
| `-t, --threads` | 下载线程数 |
| `--check` | 连通性检测 |
| `--update, --upgrade` | 自更新 (git pull) |

```bash
# 搜索
python3 scripts/dl.py --search "毛玉牛乳"              # 三站搜索
python3 scripts/dl.py --search "fate" --site nh,eh     # 限定站点
python3 scripts/dl.py --search "全彩" --json           # JSON 输出

# 随机推荐
python3 scripts/dl.py --random                         # 三站随机
python3 scripts/dl.py --random --tag "chinese"         # 中文随机

# 下载
python3 scripts/dl.py 604256                           # 自动路由
python3 scripts/dl.py https://e-hentai.org/g/{id}/{token}/

# 工具
python3 scripts/dl.py --check                          # 四站全检
python3 scripts/dl.py --setup                          # 凭证配置
python3 scripts/dl.py --update                         # 自更新

# 仓库
https://github.com/AsukaIIV/dl4henga
```

## 常见问题

| 问题 | 解决 |
|------|------|
| 三站搜索某站无结果 | 正常降级，查看输出中的 ⚠️ 提示 |
| 搜索结果很多重复 | 标题相似度 > 85% 自动去重，跨站本子合并为一条 |
| 想只看某个站 | `--site jmcomic` 或 `--site nhentai` |
| jmcomic 下载到错误目录 | 更新到 v2+，`-o` 改用 `dir_rule` 设置 |
| `pip: command not found` | 用 `pip3` 或 `python3 -m pip` |

| TLS connect error (curl 35) | jmcomic 的 curl_cffi 与系统 OpenSSL 不兼容，等待镜像切换重试即可 |
| nhentai 搜索无结果 | 先 `--check` 确认代理和镜像状态 |
| E-Hentai 搜索不可达 | 需要代理，或用 ExHentai cookie |

## 注意事项

- 首次使用: `pip3 install jmcomic cloudscraper curl_cffi`
- ExHentai 需凭证: `python3 scripts/dl.py --setup`
- 脚本目录: `.claude/skills/dl4henga/scripts/`
- jmcomic `-o` 指定基础目录，实际文件在 `基础目录/作者/本子名/` 下
- `--search` 默认搜索三站，`--site` 可限制到单站或多站
- JSON 模式下所有输出为机器可读格式，适合脚本/管道消费
