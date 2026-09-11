# 公众号阅读笔记 · wechat-article-notes

让智能体阅读公众号文章，生成有依据的中文结构化笔记，自动保存到你的本地 Markdown 知识库。兼容 Obsidian，无须额外模型 API。

**English:** An agent skill that reads user-supplied WeChat articles or local HTML/Markdown/text, produces source-grounded Chinese notes, and saves them to a private Markdown vault. The host agent performs summarization; Python handles extraction and safe file persistence. No separate LLM API, telemetry, cookies, or account integration is required.

## 安装

需要 Python 3.11+、Git 和能够读取 skill、执行 Python 的智能体宿主。完整 skill 以 Git 仓库或 ZIP 分发，不能只安装 Python wheel。

1. 克隆本仓库或下载 release ZIP，保留完整目录，命名为 `wechat-article-notes`。
2. 将目录放进宿主的 skills 目录；对于使用 `$CODEX_HOME/skills` 的安装，放在该目录下，未设置时使用 `~/.codex/skills`。开发仓库可以单独保存，复制已验证版本到安装目录；不要复制 `.git`、缓存或私人配置。
3. 在该 skill 目录安装依赖：

```sh
python -m pip install -e .
```

也可以创建虚拟环境，之后让智能体使用该虚拟环境的 Python 执行辅助脚本。确认运行脚本的解释器与安装依赖的解释器相同。

## 使用

向智能体发送：

> 使用 $wechat-article-notes 整理这篇公众号文章，存入我的知识库：[文章链接]

或提供 HTML、Markdown、TXT 文件、粘贴完整正文。首次使用会询问知识库绝对目录；之后默认入库。需要只看不存时明确说“这次只展示”，需要另存新总结时说“重新整理并保存新版本”。

脚本输入使用 stdin JSON；日常由智能体组织请求，你不需要手工构造总结 JSON。详见 [接口与配置](references/interface.md)。

每篇笔记包括摘要、作者观点、原文依据、局限、智能体分析、标签及来源。总结质量由智能体承担，脚本只检查结构与保存完整性。默认不外部核实原文，不把推测作为事实。阅读标准见 [总结规范](references/summary.md)。

## 保存与隐私

- 知识库必须位于 skill 开源仓库之外，原文不会作为独立文件长期保存。
- 配置存于用户配置目录，不使用仓库配置保存你的绝对路径。
- 相同文章与正文返回已有笔记；正文变化或明确重做时另存，保留私人修改。
- 不向 GitHub 上传阅读记录、文章或总结。没有同步服务，也不自动提交知识库。
- stdout 中的提取正文和成功路径属于私人结果，别收集为公开 CI 日志。
- 开源样例完全虚构；作者、源码贡献者与知识库内容相互独立。代码采用 MIT，来源文章的权利不随代码许可证转移。

## 读取限制

支持公开公众号文章链接和本地 UTF-8 文件。微信可能要求验证或限制自动读取；此时由已有浏览器工具读取公开正文，或请你提供正文/HTML。skill 不保证所有链接可抓取，不绕过验证，不获取付费文章，不追踪公众号更新。

HTML 脚本不执行，图片和视频不识别；图片主导或正文过短时拒绝完整总结。表格转换成文本时需检查行列关系。缺失元数据留空；不能保证识别所有截断情况。

原子保存要求支持硬链接的文件系统（NTFS、常见 Linux 文件系统）；不支持时返回失败。崩溃锁的恢复和去重边界见接口文档。此工具不防御在本机以同一身份并发篡改目录的恶意进程。

## 开发与检查

```sh
python -m pip install -e '.[test]'
python -m unittest discover -s tests -v
git add SKILL.md README.md LICENSE pyproject.toml .gitignore .gitattributes agents references scripts tests .github
python scripts/audit_release.py --staged
git diff --cached --check
git diff --cached
```

测试使用隔离临时目录与合成文章，不连接真实知识库。CI 矩阵覆盖 Windows/Linux、Python 3.11/3.14。测试中的符号链接案例在系统无权限时跳过。

发布前运行 `python scripts/audit_release.py` 检查全部 Git 历史。审查工具只输出对象标识和规则名，覆盖常见凭据、用户路径及意外文件，不是通用个人信息识别器；仍需人工检查文章、截图、日志、提交身份和发布附件。CI 的提交邮箱规则要求项目示例邮箱或 GitHub noreply 邮箱。

## GitHub 发布

在通过本地测试、人工阅读验收、完整历史审查与跨平台 CI 后发布 `v0.1.0`。先绑定你拥有的 GitHub 远程仓库，推送 `main`，在仓库设置检查 secret scanning / push protection，然后创建标签和 release。安全能力与覆盖范围以 [GitHub 官方说明](https://docs.github.com/en/code-security/concepts/secret-security/push-protection) 为准；自动扫描不能代替人工脱敏。

发布包使用 `git archive` 从已审核提交导出，不能压缩整个工作目录。建议命令：

```sh
git tag -a v0.1.0 -m 'Release v0.1.0'
git archive --format=zip --prefix=wechat-article-notes/ --output=../wechat-article-notes-v0.1.0.zip v0.1.0
```

ZIP 应只含公开源码、skill 指令、文档、CI 和合成测试材料。初次发布不应包含私人配置、文章、知识库或 `.git`。
