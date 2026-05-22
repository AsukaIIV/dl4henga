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

## 凭证配置

ExHentai 和 picacg 需要凭证。存储在:

```
~/.config/dl4henga/credentials.json
```

### 文件格式

```json
{
  "exhentai_cookies": "ipb_member_id=xxx; ipb_pass_hash=xxx; igneous=xxx",
  "picacg": {
    "email": "user@example.com",
    "password": "secret"
  }
}
```

### 自动配置 (推荐)

交给 AI 助手配置:
```
# 在 AI 对话中直接说
"帮我配置 dl4henga 凭证"
"配置 picacg 账号"
"配置 ExHentai cookie"
```

AI 助手会引导你提供信息并自动写入 credentials.json。

### 手动配置

```bash
# ExHentai cookie
# 1. 浏览器登录 e-hentai.org
# 2. F12 → Application → Cookies → 复制三个值
# 3. 写入文件
python3 -c "
import json, os
p = os.path.expanduser('~/.config/dl4henga/credentials.json')
os.makedirs(os.path.dirname(p), exist_ok=True)
data = {}
if os.path.exists(p):
    with open(p) as f: data = json.load(f)
data['exhentai_cookies'] = 'ipb_member_id=你的值; ipb_pass_hash=你的值; igneous=你的值'
with open(p, 'w') as f:
    json.dump(data, f)
os.chmod(p, 0o600)
"

# picacg 账号
python3 -c "
import json, os
p = os.path.expanduser('~/.config/dl4henga/credentials.json')
os.makedirs(os.path.dirname(p), exist_ok=True)
data = {}
if os.path.exists(p):
    with open(p) as f: data = json.load(f)
data['picacg'] = {'email': '你的哔咔邮箱', 'password': '你的密码'}
with open(p, 'w') as f:
    json.dump(data, f)
os.chmod(p, 0o600)
"
```

### 环境变量 (备选)

```bash
export EXHENTAI_COOKIES='ipb_member_id=xxx; ipb_pass_hash=xxx; igneous=xxx'
export PICA_ACCOUNT='user@example.com'
export PICA_PASSWORD='secret'
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
```

## 站点支持

| 站点 | 搜索 | 下载 | 需代理 | 需登录 |
|------|------|------|--------|--------|
| nhentai | ✅ | ✅ 磁力/直链/逐页 | ✅ | ❌ |
| E-Hentai | ✅ | ✅ Archive/逐页 | ✅ | exhentai需cookie |
| JMComic | ✅ | ✅ 自动解密 | ❌ | ❌ |
| picacg | ✅ | ✅ pica-cli/API | ❌ | ✅ 账号 |

详细文档: [SKILL.md](./SKILL.md)
