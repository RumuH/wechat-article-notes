# 配置与 JSON 接口

要求 Python 3.11+，先在 skill 目录执行 `python -m pip install -e .`。这会安装依赖，不安装模型服务；skill 本身应放到宿主的 skill 搜索目录。Python 安装包不是完整 skill 分发包，分发采用 Git 仓库或 release ZIP。

所有请求为一个 UTF-8 JSON 对象，通过 stdin 传入；响应为 stdout 的一个 JSON 对象。成功/重复退出码 0，失败/冲突/需要补充退出码 1。不打印原始异常或请求日志。stdin 和单文件最大 8 MiB，网络超时 20 秒。响应中的正文和保存路径供智能体使用，属于私人信息，不存入公共日志。

## 提取：`python scripts/extract.py`

输入选一种：

```json
{"kind":"url","url":"https://mp.weixin.qq.com/s/SYNTHETIC_EXAMPLE"}
```

```json
{"kind":"file","path":"/absolute/private/article.html"}
```

```json
{"kind":"text","text":"用户提供的完整正文","title":"可选标题"}
```

`kind: html` 使用 `text` 字段传入 HTML。文件支持 UTF-8 的 HTML/HTM/MD/TXT，不猜测其他编码。输入可附加 `title`、`author`、`account`、`published_at`、`source`；仅填写用户提供或页面中实际看到的信息。`source` 只接受公众号文章 URL，未知来源留空。不会从本地文件名生成元数据。

`kind: browser` 接收 `scripts/browser_capture.js` 在宿主浏览器中返回的完整 JSON 对象，不需要用户额外操作。详见 [浏览器流程](browser.md)。采集器返回 `capture.schema_version: 1`；成功时包括 `state: ready`、来源、可见元数据、正文、标题列表、图片状态和 `evidence`。脚本校验正文传输长度和章节内容，统一输出同样的 article；额外保留 `read_method: browser`、`headings`、`images`、`browser_evidence`。这些证据用于发现缺失，不是对浏览器或智能体的真实性认证。

URL 请求失败或未找到正文时，`next_action: read_browser` 指示智能体自动使用浏览器。只有浏览器实际返回 `verification_required` 才请用户完成页面验证；`not_ready` 指示智能体检查同一标签页，不能直接要求用户复制正文。浏览器能力由宿主提供，Python 脚本本身不启动浏览器。

返回 `status`、`warnings`、`article`。article 包含标题等元数据及 `body`、`body_hash`、`article_id`、`warnings`；直接用于保存请求。哈希基于规范化正文计算，无随机盐，属于私人阅读标识，不公开。

警告含义：

| 标识 | 处理 |
| --- | --- |
| `article_body_missing` | 缺少正文容器，不能总结 |
| `insufficient_text` | 少于 80 字符，需要更多正文 |
| `image_dominant` | 图片多、文字少，需要图中文字或完整材料 |
| `possibly_truncated` | 存在截断标记；先请求完整内容 |
| `images_not_read` | 图片未读取；总结仅涵盖文字 |
| `table_layout_requires_review` | 表格转为纯文本，回看原始材料确认对应关系 |
| `images_not_loaded` | 图片仍是占位图或未载入，先尝试浏览器加载，不能宣称已看图 |
| `browser_end_unconfirmed` | 没找到正文结束节点，回到页面核对末尾 |

完整性检测是启发式，不能证明网页完整。链接仅允许 HTTPS 公众号文章路径，逐次验证重定向；禁止登录端点及跨域跳转，不使用系统代理和持久 Cookie。微信可能拒绝自动读取，`fetch_failed_provide_content` 或 `redirect_blocked_provide_content` 时按 SKILL.md 走已有浏览器或正文输入路径。普通 HTML 必须有 `article` 或 `#js_content`，不把整个页面当作正文。

## 保存：`python scripts/save.py`

配置使用用户确认的绝对目录：

```json
{"action":"configure","vault":"/absolute/private/knowledge"}
```

Windows 路径在 JSON 中使用 `/` 或转义反斜杠。配置位于 Windows `%APPDATA%/wechat-article-notes/config.json`，其他平台 `$XDG_CONFIG_HOME/wechat-article-notes/config.json` 或 `~/.config/wechat-article-notes/config.json`。设置环境变量只应用于自己的隔离环境，不把私人配置放进仓库。

`{"action":"show-config"}` 返回配置目录；未配置返回 `vault_not_configured`。configure 可重新选择目录，但不会迁移已有笔记。

保存结构（article 必须使用真实提取返回值，此处仅示意）：

```json
{
  "action": "save",
  "article": {},
  "summary": {
    "abstract": "简短摘要",
    "claims": "作者的核心观点，标明原文段落",
    "evidence": "原文案例、数据及段落依据",
    "limitations": "局限与待核实内容",
    "analysis": "明确标注的智能体分析",
    "tags": ["阅读笔记"]
  },
  "force_new": false,
  "allow_partial": false
}
```

五个总结字段是非空 Markdown 字符串，标签最多 20 项，只含文字、数字、下划线、连字符和 `/`。不需要推断的部分写“原文未说明”或“暂无额外分析”，不要编造。布尔字段必须是 JSON 布尔值。`allow_partial` 只能在用户接受不完整原文时启用，不能绕过无正文或图片主导检查。

笔记直接保存在所配置目录，文件名为 `整理日期--安全标题--文章标识前16位.md`，同名依次加 `--v2` 等。正文变化或 `force_new` 会产生新文件；跨日期可能使用新日期文件名。`version` 表示该文件名的版本后缀序号，不是文章的全局版本。稳定公众号身份 `__biz/mid/idx` 优先；短链按稳定 URL；无链接按正文指纹。短链与长链无法在未解析身份时自动合并。

扫描配置目录顶层 Markdown 元数据实现去重；保留正文中的私人修改。元数据被手工改写且无法解析时，匹配原文件名的笔记返回 `conflict`，避免猜测。用户移动到子目录或移除身份信息后不保证去重。没有数据库或原文索引。

返回 `success`（含 `path` 和 `version`）、`duplicate`（含已有 `path`）、`conflict` 或 `failed`。保存时校验原文指纹、目录边界和必填部分，不校验总结是否真实；真实性由智能体核对。

同一知识库使用排他锁，忙时返回 `vault_busy`，不无限重试。崩溃可能留下 `.wechat-article-notes.lock` 或 `.wan-*.tmp`；确认没有写入进程后方可清理。采用原子硬链接发布，目标文件系统必须支持硬链接（如 NTFS/ext4）；不支持时安全失败，不退化成覆盖写入。不要将知识库放在来源不可信且正在更改的符号链接目录。
