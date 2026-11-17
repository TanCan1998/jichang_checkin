# 通用机场签到😍<br/>
>只要机场网站''' Powered by SSPANEL ''',就可以进行签到。要确认是否是''' Powered by SSPANEL '''，在机场首页滑倒最底端就可以看到。例如：
![Y0}SY$J`8837H8T5GXM1DZY](https://user-images.githubusercontent.com/21276183/214764546-4f66333a-cb9b-420e-8260-697d26fb4547.png)
## 作用
>每天进行签到，获取额外的流量奖励

## 推送方式
  🚀🚀该脚本采用的是<a href = 'https://sct.ftqq.com/r/5126'>Server酱</a>的推送方式，如果不需要推送，就下面的SCKEY参数的值设置为<b>空</b>就行

# 部署过程
 
1. 右上角Fork此仓库
2. 然后到`Settings`→`Secrets and variables`→`Actions` 新建以下机密：

| 参数   | 是否必须  | 内容  | 
| ------------ | ------------ | ------------ |
| URL | 是 | 网站地址，如 `https://example.com` |
| CONFIG| 账号密码登录时必填 | 账号密码，每行一个，交替填写 |
| COOKIE | Cookie 登录时必填 | 浏览器手动登录后，请求头中的完整 Cookie；每个账号一行。设置后优先使用，CONFIG 可不填 |
| SCKEY  | 否  | Sever酱秘钥  |
<br/>
<b>其中URL的值必须是机场网站的地址，例如：https://example.com</b>,尾部不要加''' / '''号 config写法：一行账号一行密码

3. 到 `Actions` 启用工作流，选择 `Common airport Checkin` → `Run workflow`，手动运行一次。之后每天北京时间 **00:10** 自动签到（GitHub 调度可能延迟）。<br/>
4. 最后，可以到Run sign查看签到情况，同时也会也会将签到详情推送到Sever酱。

## 运行与版本

- 运行环境固定为 Ubuntu 26.04、Python 3.15.2、pip 26.3。
- Actions 固定到完整提交 SHA：checkout v7.0.1、setup-python v7.1.0。
- GeekedTest 固定到 `d4e8e7562cfeab8319154a6af6538443cc47bfd9`，仅加载原有 AI 验证模式。
- `requirements.txt` 固定直接及间接依赖到 2026-11-17 核实的最新稳定版本；以后升级需显式修改版本并验证。
- 推送代码时运行测试；定时或手动触发时运行测试并签到。登录、验证码、网络或签到失败会使工作流失败；“今日已签到”视为成功。推送通知失败单独记录，不覆盖签到结果。
- 公共日志不输出账号、密码、验证码令牌或原始响应。
- GitHub 可能在公开仓库连续 60 天没有活动后停用定时工作流；届时需到 Actions 重新启用。

本地验证：`python -m unittest discover -s tests -v`。

### 当前验证码兼容性

2026-11-17 实跑确认：当前网站密码登录需要验证码，GeekedTest 当前提交返回 `KeyError`，尚不能完成该站点的密码自动登录。可使用已登录的 Cookie 执行每日签到：浏览器手动登录网站，在开发者工具 Network 中选择网站请求，将 Request Headers 的 Cookie 值保存到本仓库 Actions Secret `COOKIE`，再手动运行工作流验证。不要将 Cookie 写入代码或公开日志。会话过期后需更新 Secret。

脚本支持解码网站 Base64 登录页、初始化 Cookie 和隐藏字段，以及新版 `phase=password` 登录流程。自动签到是否成功，以 `Run sign` 中的结果为准。
