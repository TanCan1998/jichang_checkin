# 通用机场签到

通过 GitHub Actions 定时为兼容 SSPANEL 的站点签到。请先确认目标站点允许自动签到，并妥善保管 Cookie。

## 配置

在仓库的 **Settings → Secrets and variables → Actions** 添加以下 Actions secrets：

| 名称 | 必需 | 说明 |
| --- | --- | --- |
| `URL` | 是 | 站点地址，例如 `https://example.com`。填写站点根地址，不要在末尾加 `/`。 |
| `COOKIE` | 是 | 已登录账号的完整请求头 Cookie，每个账号一行。Cookie 过期后需要更新。 |
| `SCKEY` | 否 | Server 酱 SendKey。未设置时不发送通知。 |

在浏览器中登录站点后，可从开发者工具的 Network 请求头中复制 Cookie。不要把 Cookie 写入代码、提交记录或公开日志。工作流只读取 `URL`、`COOKIE` 和可选的 `SCKEY`。

## 运行

1. 在仓库 **Actions** 页面启用工作流。
2. 选择 **Common airport Checkin**，点击 **Run workflow** 手动运行。
3. 在工作流运行记录中查看 `Run sign` 步骤的签到结果。

工作流每天北京时间 **00:10** 自动运行（GitHub 调度可能延迟）。定时和手动运行会先执行测试，再进行签到；对 `main.py`、依赖、测试或工作流文件的推送只运行测试，不会签到。

程序按 Cookie 逐个签到。接口报告“今日已签到”视为成功；Cookie 过期、网络或签到失败会使工作流失败。`SCKEY` 推送失败只记录错误，不会改变签到结果。

## 本地测试

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

依赖及 GitHub Actions 运行环境由 `requirements.txt` 和 `.github/workflows/main.yml` 管理。

## 独立仓库

如果 GitHub 仓库仍显示为 fork，可在仓库 **Settings → General → Danger Zone → Leave fork network** 中解除 fork 关系。此操作不可撤销；解除后仓库将成为独立仓库，不再与上游同步。
