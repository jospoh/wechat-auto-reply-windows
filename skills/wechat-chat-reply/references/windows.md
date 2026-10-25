# Windows 安装与使用

## 带到另一台机器

解压分发 ZIP，保留 wechat-chat-reply 整个文件夹。对另一台机器上的 Codex 说：

“请安装这个目录中的 wechat-chat-reply skill，运行 scripts/install.py，然后按 SKILL.md 初始化依赖并检查微信。”

install.py 只用 Python 标准库，默认复制到当前用户 ~/.agents/skills/wechat-chat-reply；这是当前 Codex 官方文档列出的用户技能发现位置。支持 --skills-dir 指定本机已使用的技能根目录。拒绝覆盖已有安装。未发现技能时重启或新开聊天。

原始源码：https://github.com/fanyuantaier/wechatauto-replica
Codex 本地技能位置：https://learn.chatgpt.com/docs/build-skills

## 首次准备

需要 Windows 10/11、同机已登录的微信 4.x、64 位 Python 3.10+。系统 Python 不存在时由用户正常安装，skill 不自动安装系统软件或修改系统安全设置。包内不带 Python、虚拟环境、语音模型、账号配置、私聊消息或密钥。

下文路径都是示例占位；换成本机实际路径。后续 Python 路径使用 bootstrap 返回的独立环境解释器，不写死开发机盘符。

    # 可选：先把环境与模型放到空间充足的盘，本次 shell 及其子进程生效。
    $env:WECHAT_REPLY_HOME = 'D:\CodexWechatReply'
    & 'C:\Path\To\python.exe' 'D:\Skills\wechat-chat-reply\scripts\bootstrap.py'
    # 需要语音：再次运行 bootstrap.py --with-asr

首次初始化需要下载依赖，语音模型也另需空间和网络。bootstrap 支持 --offline --wheelhouse ABS_PATH，但 ZIP 不附离线 wheels。语音默认 small 模型首次运行联网下载，后续使用同机缓存。私聊音频不会随模型下载上传。

## 命令

先将 $python 和 $helper 设为 bootstrap 返回的路径。

    & $python $helper 'doctor'
    & $python $helper 'activate'
    & $python $helper 'restore'
    & $python $helper 'read' '--contact' '完整备注' '--limit' '20'
    & $python $helper 'open' '--contact' '完整备注'
    & $python $helper 'ui'
    & $python $helper 'image' '--contact' '完整备注' '--message-id' '123' '--shard' 'message__message_0.db' '--tier' 'best'
    & $python $helper 'transcribe' '--contact' '完整备注' '--message-id' '123' '--shard' 'message__message_0.db' '--model' 'small'
    & $python $helper 'prepare' '--contact' '完整备注' '--content-file' 'D:\Temp\reply.txt'
    # 仅在用户确认 prepare 展示的收件人与全文之后运行：
    & $python $helper 'send' '--ticket' 'PREPARE返回的ticket' '--approved-digest' 'PREPARE返回的digest'
    # 全局参数放在子命令之前：
    & $python $helper '--db-dir' 'D:\xwechat_files' '--account' '具体账号目录名' 'read' '--contact' '完整备注'

命令失败时保留 error 原文并说明边界。activate 失败只表明该版本/进程热激活没有通过验证；read 的身份字段来自消息所在分片的 Name2Id，不能拿 UI 名称代替。微信进程和窗口状态分开检测：托盘隐藏仍报告 running=true、window.state=hidden。数据库读取保持托盘状态。需要界面时，restore 通过唯一的微信托盘图标打开原客户端；找不到可见图标会先展开隐藏图标并重新枚举。无需 OCR，不重新执行客户端。普通最小化仍走原生窗口恢复。

restore 只有在原进程的真实主窗口可见、子控件树非空且取得前台焦点后才成功；输出 method（tray_double_click、native_minimized 或 already_visible）、uia_tree_available=true 和 new_process_started=false。灰色空白窗口不会通过验证。ui、open、send 自动复用此流程；聊天会话和输入框在后续导航中单独核实。托盘图标或展开按钮不唯一、控件树超时为空时停止，不猜坐标、不操作登录确认。当前托盘展开入口已在本机 Windows 通知区域验证，其他 Windows 托盘布局需另行验证。

## 权限与清理

脚本与微信应同一 Windows 用户、同等权限。不要为了绕过失败自动提权、关闭安全软件或修改隐私设置。用户本人扫码或确认登录。

运行目录保存当前机器的 venv、模型缓存、无障碍扫描缓存、解码后的私聊图片和发送单。图片依赖已包含在核心初始化中；旧版本安装需要重新运行 bootstrap.py。发送单含待发送正文，保留本地以防不确定结果被重复发送，不复制到另一台机器。清理时由用户明确指定目录和范围；发布包只包含清单内源码，不包含运行目录。
