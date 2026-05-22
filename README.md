# dl4henga

四站同人志下载工具 — nhentai / E-Hentai / JMComic / picacg 统一搜索与下载

> 仓库: https://github.com/AsukaIIV/dl4henga

## 安装

```bash
git clone https://github.com/AsukaIIV/dl4henga.git
cd dl4henga

# Python 依赖
pip3 install jmcomic cloudscraper curl_cffi

# 可选: picacg 下载加速
npm install -g pica-cli
```

## 凭证配置

存储在 `~/.config/dl4henga/credentials.json`:

```json
{
  "exhentai_cookies": "ipb_member_id=xxx; ipb_pass_hash=xxx; igneous=xxx",
  "picacg": {"email": "user@example.com", "password": "secret"}
}
```

交给 AI 助手自动配置，或手动创建上述文件。

## 快速开始

```bash
cd dl4henga/scripts

# 四站并行搜索
python3 dl.py --search "毛玉牛乳"

# 限定站点
python3 dl.py --search "fate" --site nh,eh

# 随机推荐
python3 dl.py --random --tag "chinese"

# 直接下载
python3 dl.py 604256
python3 dl.py https://e-hentai.org/g/123456/abcdef0123/
```

## 自更新

```bash
python3 dl.py --update
```

## 站点支持

| 站点 | 搜索 | 下载 | 需代理 | 需登录 |
|------|------|------|--------|--------|
| nhentai | ✅ | ✅ 磁力/直链/逐页 | ✅ | ❌ |
| E-Hentai | ✅ | ✅ Archive/逐页 | ✅ | exhentai需cookie |
| JMComic | ✅ | ✅ 自动解密 | ❌ | ❌ |
| picacg | ✅ | ✅ pica-cli/API | ❌ | ✅ 账号 |

详细文档: [SKILL.md](./SKILL.md)
