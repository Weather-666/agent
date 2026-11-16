# 当前用户个人资料 Backend 交接说明

## 1. 实现范围

Backend 已实现当前登录用户的个人资料读取、部分更新，以及头像的上传、替换和删除。

| 接口 | 中文语义 | English meaning |
| --- | --- | --- |
| `GET /api/v1/auth/me` | 获取当前用户资料 | Get current user profile |
| `PATCH /api/v1/auth/me` | 更新当前用户资料 | Update current user profile |
| `PUT /api/v1/auth/me/avatar` | 上传或替换当前用户头像 | Upload or replace current user avatar |
| `DELETE /api/v1/auth/me/avatar` | 删除当前用户头像 | Delete current user avatar |

四个接口均要求有效的 Bearer access token，只操作 token 对应的当前用户，不接收
`userId`，也不需要 `x-tenant-id` 或租户权限。

登录、注册和刷新接口中的基础 `user` 对象仍为 `id`、`email`、`name`。完整个人资料由
`GET /api/v1/auth/me` 返回。

## 2. 完整资料响应

四个接口成功时返回相同的个人资料结构：

```json
{
  "id": "user_example",
  "email": "user@example.com",
  "name": "张三",
  "preferredLocale": "zh-CN",
  "avatarUrl": "https://files.example.com/signed-avatar?signature=REDACTED",
  "avatarUrlExpiresAt": "2026-07-21T12:00:00Z",
  "updatedAt": "2026-07-21T10:00:00Z"
}
```

字段名和错误码使用稳定的英文标识；下表中的中英文名称用于说明 Backend 的字段设计语义。

| 字段 | 类型 | 中文语义 | English meaning |
| --- | --- | --- | --- |
| `id` | `string` | 当前用户 ID | Current user ID |
| `email` | `string` | 登录邮箱，只读 | Sign-in email, read-only |
| `name` | `string` | 显示名称 | Display name |
| `preferredLocale` | `"zh-CN" \| "en-US" \| null` | 账号语言偏好；`null` 表示未设置 | Preferred locale; `null` means unset |
| `avatarUrl` | `string \| null` | 头像临时读取地址 | Temporary avatar read URL |
| `avatarUrlExpiresAt` | `string \| null` | 头像地址的 UTC 过期时间 | Avatar URL expiration time in UTC |
| `updatedAt` | `string` | 资料最后更新时间 | Profile last-updated time |

语言值的设计语义：

| 值 | 中文语义 | English meaning |
| --- | --- | --- |
| `zh-CN` | 简体中文 | Simplified Chinese |
| `en-US` | 英文（美国） | English (United States) |
| `null` | 未设置账号语言偏好 | No account locale preference |

时间字段以 UTC ISO 8601 字符串返回。用户没有自定义头像时，`avatarUrl` 和
`avatarUrlExpiresAt` 均为 `null`。Backend 不返回头像的对象存储 Key。

## 3. 读取当前用户资料

```http
GET /api/v1/auth/me
Authorization: Bearer <access-token>
```

成功返回 `200 OK` 和完整资料响应。

该接口已从原来的基础 `id/email/name` 响应扩展为完整资料响应；登录、注册和刷新接口的基础
`user` 响应未随之扩展。

## 4. 修改当前用户资料

```http
PATCH /api/v1/auth/me
Authorization: Bearer <access-token>
Content-Type: application/json
```

请求字段均为可选：

| 字段 | 类型 | 中文语义 | English meaning | 约束 |
| --- | --- | --- | --- | --- |
| `name` | `string` | 显示名称 | Display name | 去除首尾空白后 1～80 个字符；不能为 `null` 或包含控制字符 |
| `preferredLocale` | `"zh-CN" \| "en-US" \| null` | 账号语言偏好 | Preferred locale | 显式传 `null` 表示清除偏好 |

示例：

```json
{
  "name": "新的显示名称",
  "preferredLocale": "en-US"
}
```

PATCH 使用部分更新语义：未提交的字段保持原值，空对象 `{}` 不覆盖现有资料。成功返回
`200 OK` 和更新后的完整资料响应。

`name` 的设计含义是显示名称，继续保存到现有的 `users.name`；它不是唯一用户名，也不改变
邮箱登录标识。`email`、`status`、角色、租户、权限和 `userId` 均不是该接口的可写字段，
提交未定义字段返回 `422`。现有管理员资料接口及其权限语义不受影响。

## 5. 上传或替换头像

```http
PUT /api/v1/auth/me/avatar
Authorization: Bearer <access-token>
Content-Type: multipart/form-data
```

multipart 表单字段：

| 字段 | 类型 | 必填 | 中文语义 | English meaning | 约束 |
| --- | --- | --- | --- | --- | --- |
| `file` | 文件 | 是 | 头像图片 | Avatar image | JPEG、PNG 或 WebP；最大 2 MiB |

Backend 会同时核对文件名扩展名、请求 MIME 和实际解码格式。SVG、GIF、动画图片、损坏图片、
声明类型与内容不一致的图片、超过 2 MiB 或超过像素总数上限的图片会被拒绝。

合法图片会应用 EXIF 方向，居中裁剪为正方形，最长边限制为 512 像素且不放大小图，然后重新
编码为静态 WebP。原始 EXIF、ICC 等客户端元数据不会复制到结果文件。

成功返回 `200 OK` 和完整资料响应。

## 6. 头像地址与对象生命周期

`avatarUrl` 是 ObjectStore 生成的短期签名 GET URL，默认有效期为 15 分钟，精确过期时间由
`avatarUrlExpiresAt` 返回。数据库只保存长期对象引用，不保存签名 URL。

URL 过期后，再次调用 `GET /api/v1/auth/me` 会生成新的地址。本地 ObjectStore 配置公共
Backend origin 时返回绝对 URL；未配置时可能返回 Backend 相对路径。

上传或替换头像的处理顺序：

1. 校验、裁剪并重新编码图片。
2. 使用新的不可预测对象名称写入 ObjectStore。
3. 在数据库事务中切换当前头像引用并提交。
4. 数据库提交成功后尽力删除旧头像对象。

数据库更新失败时会补偿删除刚写入的新对象。旧对象删除失败不会回滚已经提交的新头像资料，
也不会把成功的资料更新改为错误响应。

删除头像时先提交数据库清空操作，再尽力删除旧对象。头像不写入 `library_files`，不参与用户
资料库或聊天附件的生命周期。

## 7. 删除头像

```http
DELETE /api/v1/auth/me/avatar
Authorization: Bearer <access-token>
```

成功返回 `200 OK` 和完整资料响应，其中 `avatarUrl`、`avatarUrlExpiresAt` 均为 `null`。

在对象存储依赖可正常初始化时，删除接口具有幂等语义：用户没有头像或重复删除时仍返回
`200 OK`。

## 8. HTTP 状态与错误码

| HTTP 状态 | 错误码 | 场景 |
| --- | --- | --- |
| `400` | `AVATAR_INVALID_IMAGE` | 文件为空、损坏、无法真实解码或超过像素总数上限 |
| `401` | `AUTH_UNAUTHORIZED` | 缺少、无效或过期的 access token |
| `404` | `USER_NOT_FOUND` | 操作期间当前用户记录不存在 |
| `413` | `AVATAR_TOO_LARGE` | 输入文件超过 2 MiB |
| `415` | `AVATAR_UNSUPPORTED_TYPE` | 非 JPEG/PNG/WebP、动画图片或声明类型与真实内容不一致 |
| `503` | `OBJECT_STORE_UNAVAILABLE` | 头像操作所需的对象存储不可用 |
| `422` | FastAPI validation detail | JSON 字段、名称约束、locale、额外字段或 multipart 结构无效 |

业务错误沿用 Backend 的 `ApiError` 格式：

```json
{
  "code": "AVATAR_UNSUPPORTED_TYPE",
  "message": "Avatar must be a JPEG, PNG, or WebP image"
}
```

错误响应不包含对象 Key、本地文件路径、签名 URL 或底层存储配置。

## 9. 当前未实现项与原因

| 未实现项 | 原因 |
| --- | --- |
| 通过个人资料接口修改登录邮箱 | 邮箱属于登录身份，需要独立的身份校验和安全确认流程 |
| 通过个人资料接口修改密码 | 密码重置已有独立认证流程，不并入普通资料 PATCH |
| 唯一 username | 当前 `name` 的产品语义是显示名称，不承担唯一登录标识 |
| 保存头像原图或头像历史 | 当前设计只保留规范化后的单个当前头像对象 |
| 永久公开头像 URL | 当前设计使用有过期时间的签名读取地址，避免公开长期对象地址 |


## 10. 已知限制

- `DELETE /api/v1/auth/me/avatar` 会预先初始化 ObjectStore。当用户没有头像但对象存储不可用
  时，当前实现返回 `503 OBJECT_STORE_UNAVAILABLE`，尚未达到完全不依赖存储状态的幂等删除。
- `updatedAt` 和 `avatarUrlExpiresAt` 实际按 UTC ISO 8601 字符串返回，但当前 OpenAPI schema
  仅标记为 `string`，尚未附加 `date-time` format。

## 11. Backend 实现位置

| 文件 | 职责 |
| --- | --- |
| `app/api/v1/routers/auth.py` | 路由、认证依赖和请求接收 |
| `app/domain/profile.py` | 请求与响应模型、字段校验 |
| `app/services/profile_service.py` | 资料更新、图片处理和对象生命周期 |
| `app/services/profile_repository.py` | 用户资料持久化和事务更新 |
| `app/core/config.py` | 头像大小、像素、尺寸和 URL 有效期配置 |
| `infra/sql/001_auth.sql` | `preferred_locale`、`avatar_object_key` 数据库字段 |
| `tests/test_app.py` | 个人资料和头像接口测试 |
