# 密码重置 Backend 交接说明

## 1. 实现状态

Backend 已完成登录页“忘记密码”所需的完整服务端流程：

1. 根据注册邮箱申请密码重置验证码。
2. 通过阿里云 DirectMail SMTP 发送 6 位数字验证码。
3. 校验邮箱、验证码和新密码。
4. 更新密码并吊销该用户全部未吊销的 refresh token。
5. 用户使用新密码重新登录。

该流程无需登录，不会签发新 token，也不会自动登录。

Backend 已提供以下接口：

- `POST /api/v1/auth/password-reset/request`
- `POST /api/v1/auth/password-reset/confirm`

## 2. 申请密码重置验证码

```http
POST /api/v1/auth/password-reset/request
Content-Type: application/json
```

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `email` | `string` | 是 | 合法邮箱；Backend 会执行 trim 和 lower |
| `locale` | `"zh-CN" \| "en-US"` | 否 | 决定邮件语言；缺省为 `zh-CN` |

请求示例：

```json
{
  "email": "user@example.com",
  "locale": "en-US"
}
```

### 成功响应

`202 Accepted`

```json
{
  "message": "如果该邮箱已注册，密码重置验证码将发送到该邮箱"
}
```

以下情况均返回相同的 `202` 响应：

- 邮箱存在且用户状态为 active，邮件已提交发送。
- 邮箱不存在。
- 用户状态为 disabled 或 pending_activation。
- 同一用户仍处于 60 秒发送冷却期。

统一响应用于避免泄露邮箱是否已注册。邮箱不存在或用户状态不可用时不会发送邮件。

### 邮件服务异常

`503 Service Unavailable`

```json
{
  "code": "EMAIL_SEND_FAILED",
  "message": "密码重置邮件发送失败，请稍后重试"
}
```

SMTP 发送失败后，本次生成的验证码会立即失效。

### 请求校验失败

邮箱格式错误或 `locale` 不是 `zh-CN`、`en-US` 时返回 FastAPI 标准 `422` 响应。

## 3. 确认密码重置

```http
POST /api/v1/auth/password-reset/confirm
Content-Type: application/json
```

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `email` | `string` | 是 | 合法邮箱；Backend 会执行 trim 和 lower |
| `code` | `string` | 是 | 6 位 ASCII 数字 |
| `newPassword` | `string` | 是 | 至少 8 位 |

请求示例（验证码仅为格式示例）：

```json
{
  "email": "user@example.com",
  "code": "123456",
  "newPassword": "new-password"
}
```

### 成功响应

`200 OK`

```json
{
  "message": "密码重置成功，请重新登录"
}
```

成功响应只包含消息，不包含 access token、refresh token 或用户信息。

### 验证码无效

`400 Bad Request`

```json
{
  "code": "AUTH_PASSWORD_RESET_CODE_INVALID",
  "message": "验证码无效或已过期"
}
```

以下情况统一使用该错误：

- 邮箱不存在或用户状态不是 active。
- 验证码错误。
- 验证码过期。
- 验证码已使用或已被新验证码替代。
- 验证失败次数达到上限。

### 请求校验失败

以下情况返回 FastAPI 标准 `422` 响应：

- 邮箱格式错误。
- 验证码不是 6 位 ASCII 数字。
- `newPassword` 少于 8 位。

## 4. 验证码生命周期

- 使用 Python `secrets` 生成 6 位数字验证码。
- 有效期为 10 分钟。
- 同一用户 60 秒内不重复生成或发送。
- 新验证码生成后，该用户之前未失效的验证码立即失效。
- 错误验证码会增加失败次数。
- 最多允许失败 5 次，第 5 次失败后验证码失效。
- 成功使用后验证码立即失效，不能重复消费。
- SMTP 发送失败时本次验证码失效。
- 数据库只保存 PBKDF2 慢速散列，不保存验证码明文。
- 并发确认请求只能有一个成功消费验证码。

## 5. 密码和 token 行为

- 密码重置的新密码至少 8 位。
- Backend 使用现有 `hash_password` 机制保存新密码。
- 密码更新、验证码消费和 refresh token 吊销在同一数据库事务内完成。
- 重置成功后，旧密码无法登录，新密码可以登录。
- 重置成功后，该用户全部未吊销的 refresh token 都会被吊销。
- 重置接口不会签发新 token。
- 已签发的 access token 最长仍可能继续使用 15 分钟。本次未实现 `auth_version` 或 access token 即时吊销。

## 6. 多语言契约

Backend 接收申请接口中的 `locale`，并据此选择邮件模板：

| locale | 邮件语言 |
| --- | --- |
| `zh-CN` | 中文标题、纯文本正文和 HTML 正文 |
| `en-US` | 英文标题、纯文本正文和 HTML 正文 |
| 未传 | 默认中文 |

API 的业务错误码保持稳定且与语言无关：

- `EMAIL_SEND_FAILED`
- `AUTH_PASSWORD_RESET_CODE_INVALID`

响应中的中文 `message` 是 Backend 默认说明。调用方可依据 HTTP 状态和业务错误码展示自己的本地化文案。

`locale` 仅影响验证码邮件，不影响验证码规则、密码规则或错误码。

## 7. Backend 实现位置

| 内容 | 文件 |
| --- | --- |
| 请求/响应模型和字段校验 | `app/domain/auth.py` |
| HTTP 路由 | `app/api/v1/routers/auth.py` |
| 密码重置业务和事务 | `app/services/password_reset_service.py` |
| 验证码 SQL 和并发控制 | `app/services/password_reset_repository.py` |
| SMTP 和中英文邮件模板 | `app/services/email_service.py` |
| 配置 | `app/core/config.py`、`.env.example` |
| 数据库表和索引 | `infra/sql/001_auth.sql` |
| 自动化测试 | `tests/test_app.py` |

## 8. BFF 交接边界

两个 Backend 接口均为匿名 JSON POST 接口，不需要 access token、Cookie 或 tenant header。

BFF 需要透传：

- 请求 JSON，包括申请接口的 `locale`。
- Backend HTTP 状态码。
- Backend JSON 响应和业务错误码。

BFF 使用现有 Backend 服务地址，不应由浏览器直接访问或硬编码 Backend 地址。

## 9. Backend 验证结果

- 密码重置相关定向测试：`11 passed`。
- Backend 完整测试：`110 passed`。
- Ruff：通过。
- `git diff --check`：通过。
- OpenAPI 已包含两个密码重置接口。
- OpenAPI 中 `locale` 为 `zh-CN`、`en-US`，缺省为 `zh-CN`。
- OpenAPI 中 `newPassword.minLength` 为 `8`。
- 中英文邮件的标题、纯文本正文和 HTML 正文已使用 SMTP mock 验证。
- 真实中文邮件发送、密码重置、旧密码失效、新密码登录和旧 refresh token 吊销已完成闭环验证。
