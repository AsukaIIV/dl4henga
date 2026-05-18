# dl4henga

> 三站同人志下载 Skill — 对 AI 说句话，本子到手

一个跨平台的 Agent Skill，支持 Claude、Cursor、DeepSeek 等任何能调用脚本的 AI 助手。

## 安装

```
https://github.com/AsukaIIV/dl4henga,安装该仓库内的skill

dl4henga,初始化该skill
```

## 触发规则

Skill 在以下情况自动激活：

| 用户说 | 触发 |
|--------|------|
| `下个毛玉牛乳的本子` | 下载意图 |
| `https://nhentai.net/g/177013/` | nhentai URL |
| `629879` | 纯数字 ID |
| `随便来一个` | 随机推荐 |
| `https://e-hentai.org/g/...` | E-Hentai URL |
| `JM254939` | JMComic ID |
| `禁漫搜一下女骑士` | 站点关键词 |

## 对话示例

```
用户: 下个毛玉牛乳的本子
Agent: 搜索 "毛玉牛乳" → 24 结果 → 随机选 → 逐页下载 18 页 ✅

用户: https://nhentai.net/g/629879/
Agent: 解析 → 无种子 → --dl 逐页下载 52 页 20.5MB ✅

用户: 搜一下 e-hentai 的 artbook 标签
Agent: 标签搜索 → 25 个画廊 → 列出结果

用户: 随便来个禁漫
Agent: JMComic 随机 → 172 页自动解密下载 ✅
```

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/dl.py` | 统一入口，自动路由 |
| `scripts/nhentai_dl.py` | nhentai: 种子/直链 + 搜索/随机 + 逐页 |
| `scripts/ehentai_dl.py` | E-Hentai: 标签搜索 + 画廊 |
| `scripts/jmcomic_dl.py` | JMComic: 搜索/随机 + 解密 |
| `scripts/update_mirrors.py` | 镜像维护 |
| `scripts/credentials.py` | ExHentai 凭证 |

## 依赖

```bash
pip install jmcomic cloudscraper curl_cffi
```

## 代理

内置自发现（环境变量 → 端口扫描 → Clash/mihomo 配置）。JMComic 不需要代理。

## 特性

- 代理自发现 · Cloudflare 5 种变体检测绕过
- 高清自动优选 (jpg→png→webp→gif)
- 下载后魔数验证，自动删除无效文件
- 搜索双词交叉验证，过滤假结果
- 断点续传，已下载自动跳过
