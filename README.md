# 微信聊天回复 Skill

用于 Codex 的 Windows 微信 4.x 技能：读取指定联系人的聊天记录，核实发送方，读取本地图片和语音，并在用户确认具体内容后回复。当前版本：**v1.2.0**，更新内容见 [CHANGELOG.md](CHANGELOG.md)。

**不依赖截图或 OCR。** 账号登录由用户本人完成。消息和附件在本机处理；本地语音识别不上传音频。

## 功能

- 按数据库真实身份区分本人、对方及未知发送者，避免把自己的消息当成对方消息。
- 读取本机缓存的图片：原图、压缩版或缩略图，返回真实档位、尺寸和文件路径。
- 读取微信界面已有的语音转文字；也可提取 SILK 语音，用本地 faster-whisper 转写并标记低置信度。
- 生成绑定收件人、正文和聊天上下文的发送单；用户确认后才发送。
- 发送前校验账号、会话、草稿、输入回读及焦点，发送后查数据库核对；结果不明时禁止自动重发。
- 自动发现本机微信路径、进程和数据目录；多账号、同名联系人不唯一时停止并消歧。
- 微信收进托盘时，通过无障碍接口展开隐藏图标并双击唯一的微信图标；打开后校验正常主窗口和可读子控件，再核实聊天会话。无需 OCR，不重新启动客户端。

## 环境

- Windows 10/11，同机已安装并登录微信 4.x。
- 64 位 Python 3.10+，Codex 能执行本地脚本。
- 首次初始化需要下载 Python 依赖；本地语音模型首次使用另行下载。
- 当前实测客户端为微信 **4.1.15.56**。其他客户端版本和另一台机器需自行验证，安装技能不会自动登录微信。

本技能会只读扫描当前微信进程以读取本地数据库；启用无障碍接口时会尝试修改微信进程的一个 Qt 状态字节并验证结果。它不修改微信安装文件，不保存或打印数据库/图片密钥，不自动提权或修改系统安全设置。

## 安装

### 在 Codex 中安装

对 Codex 说：

    $skill-installer install https://github.com/jospoh/wechat-auto-reply-windows/tree/main/skills/wechat-chat-reply

安装后让 Codex 读取技能并初始化环境：

    使用 $wechat-chat-reply 初始化依赖，检查我的微信。

如果未发现新技能，重启 Codex 或新开聊天。

### 下载 ZIP 或手动安装

从 [Releases](https://github.com/jospoh/wechat-auto-reply-windows/releases) 下载技能 ZIP，解压后在 wechat-chat-reply 文件夹中执行：

    python scripts/install.py

也可以克隆源码仓库后执行：

    python skills/wechat-chat-reply/scripts/install.py

默认安装到当前用户 ~/.agents/skills/wechat-chat-reply，已有安装不会覆盖。可用 --skills-dir 指定本机使用的技能根目录。随后让 Codex 按 SKILL.md 运行 scripts/bootstrap.py。

## 使用示例

    使用 $wechat-chat-reply 查看“完整联系人备注”的最新消息。
    帮我读取这个联系人最近发来的图片。
    读取对方最新语音，先优先看微信已有的转写。
    根据最新消息拟一条回复，确认后发送。

发送必须确认本次具体收件人和正文。聊天记录中出现的指令不构成操作授权。

脚本命令和初始化步骤见 [Windows 使用说明](skills/wechat-chat-reply/references/windows.md)，操作契约见 [SKILL.md](skills/wechat-chat-reply/SKILL.md)。

## 数据保存

运行环境、模型缓存、解码图片和发送单保存在本机 LOCALAPPDATA/CodexWechatReply，可用 WECHAT_REPLY_HOME 指向其他磁盘。数据库只在临时目录解密，用完删除；密钥只留内存。图片和发送单属于私聊数据，不应加入 Git 仓库或跨机器分发。

发布 ZIP 只包含源码、文档、依赖清单与许可证，不包含账号、消息、密钥、图片、语音、Python 虚拟环境或模型。

## 已知边界

- 自动触发微信原生“转文字”尚未成功。可读取用户已经触发的微信转写，或改用本地语音识别。
- 本地 base 模型在短中文语音上出现过错词和重复词；默认 small 模型未在本次验证中评估准确率。低置信度结果不能当作原话。
- 图片或音频未缓存、密钥不可用时，需要用户在微信打开图片或播放语音后再试，不通过截图交差。
- 托盘展开入口已在本机 Windows 通知区域验证；其他 Windows 托盘布局和其他微信版本尚未实测。

详细范围见 [验证记录](skills/wechat-chat-reply/references/validation.md)。目前通过 **55 项离线测试**，包含托盘展开、唯一图标、恢复后空树拒绝、会话定位、草稿保护和发送防重。

测试命令（用初始化返回的 Python 路径）：

    python skills/wechat-chat-reply/scripts/test_wechat_reply.py

## 参考项目与许可

核心微信读取与无障碍模块来自 [fanyuantaier/wechatauto-replica](https://github.com/fanyuantaier/wechatauto-replica)，固定提交：

    5d29e297aee095df65785fc8386af77506554698

本仓库仅附带 db.py、accessibility.py、media.py 三个最小模块，保留 Apache-2.0 许可证和来源说明。文件校验值见 [vendor/manifest.json](skills/wechat-chat-reply/vendor/manifest.json)。上游完整包初始化不会执行，以避免顺带导入 OCR 或自动登录入口。

本仓库按 [Apache-2.0](LICENSE) 发布。上游说明见 [NOTICE](NOTICE) 和 [vendor/NOTICE.txt](skills/wechat-chat-reply/vendor/NOTICE.txt)。本项目不是腾讯或微信官方提供的接口。
