# dl4henga

四站同人志下载工具 — nhentai / E-Hentai / JMComic / picacg 统一搜索与下载

## 安装

```bash
# npx 即时运行 (无需安装)
npx dl4henga --help

# 全局安装
npm install -g dl4henga
dl4henga --help
```

## Python 依赖

```bash
pip3 install jmcomic cloudscraper curl_cffi
```

可选 (picacg 下载加速):
```bash
npm install -g pica-cli
```

## 快速开始

```bash
# 四站并行搜索
dl4henga search "毛玉牛乳"

# 限定站点
dl4henga search "fate" --site nh,eh

# 随机推荐
dl4henga random --tag "chinese"

# 直接下载
dl4henga 604256
dl4henga https://e-hentai.org/g/123456/abcdef0123/

# 配置凭证
dl4henga --setup
dl4henga pica-setup
```

## 站点支持

| 站点 | 搜索 | 下载 | 需代理 | 需登录 |
|------|------|------|--------|--------|
| nhentai | ✅ | ✅ 磁力/直链/逐页 | ✅ | ❌ |
| E-Hentai | ✅ | ✅ Archive/逐页 | ✅ | exhentai需cookie |
| JMComic | ✅ | ✅ 自动解密 | ❌ | ❌ |
| picacg | ✅ | ✅ pica-cli/API | ❌ | ✅ 账号 |

详细文档: [SKILL.md](./SKILL.md)
