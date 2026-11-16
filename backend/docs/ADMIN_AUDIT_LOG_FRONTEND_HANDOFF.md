# 管理端操作审计 Backend 交接说明

## 1. 实现状态

Backend 已完成管理端操作审计的事件持久化和查询接口。当前记录：

- 具有平台角色用户的成功登录。
- 由平台权限保护并成功改变业务数据的管理操作。

审计事件存在即表示操作成功，因此：

- 没有 `result`、`outcome`、`success`、HTTP 状态、错误码或失败原因字段。
- 不记录 401、403、404、409、参数校验失败、500 或被回滚操作。
- 批量操作只记录成功子项，失败子项不记录，也没有“部分成功”汇总事件。
- 不包含 Backend stdout/stderr、HTTP access log、Gateway usage event、AI 对话、用户提问、AI 回答或 reasoning。
- 不回填上线前历史数据。
- `clientIp` 当前固定为 `null`。

Backend 只保存稳定的英文 action code 和结构化字段，不保存中文或英文展示文案。

审计事件与对应业务变更在同一数据库事务中提交。审计事件写入失败时，业务变更也会回滚。

## 2. 查询 API

### 2.1 Endpoint 与权限

```http
GET /api/v1/audit-events
Authorization: Bearer <access-token>
```

所需平台权限：`system:audit_read`。

- `admin`：拥有 `system:audit_read`，允许查询。
- `operator`：默认不拥有，返回 `403 AUTH_FORBIDDEN`。
- `expert`：默认不拥有，返回 `403 AUTH_FORBIDDEN`。
- 普通租户用户：返回 `403 AUTH_FORBIDDEN`。
- 缺少或无效 Token：返回 `401 AUTH_UNAUTHORIZED`。

### 2.2 查询参数

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `category` | enum | 无 | 见下方 category 列表 |
| `operationType` | enum | 无 | `create`、`update`、`delete`、`login`、`grant`、`revoke`、`upload` |
| `actorId` | string | 无 | 精确匹配操作人 user ID |
| `resourceType` | string | 无 | 精确匹配资源类型 |
| `resourceId` | string | 无 | 精确匹配资源 ID |
| `search` | string | 无 | 模糊搜索操作人姓名、邮箱、资源名称、资源 ID、action code |
| `from` | ISO 8601 datetime | 无 | 包含起点，按 UTC 规范化 |
| `to` | ISO 8601 datetime | 无 | 包含终点，按 UTC 规范化 |
| `page` | integer | `1` | 最小为 1 |
| `pageSize` | integer | `50` | 1 到 100 |

`category` 可选值：

```text
auth
platform_user
user
platform_role
tenant
tenant_member
knowledge_base
document
skill
expert_category
expert
plan
```

当 `from > to` 时返回：

```json
{
  "code": "AUDIT_TIME_RANGE_INVALID",
  "message": "from must not be later than to"
}
```

### 2.3 排序与分页

固定排序：

```text
occurredAt DESC, id DESC
```

响应结构使用现有管理列表的 `page/pageSize/total` 风格：

```json
{
  "items": [
    {
      "id": "audit_4f6070763c34469ba0e10db954cd3862",
      "requestId": "req_04622f02be8349cba09960f6a3356663",
      "occurredAt": "2026-07-21T10:30:12.345678+00:00",
      "category": "plan",
      "action": "plan.delete",
      "operationType": "delete",
      "actor": {
        "userId": "user_admin",
        "name": "Platform Admin",
        "email": "admin@example.com",
        "platformRoles": ["admin"]
      },
      "tenant": null,
      "resource": {
        "type": "plan",
        "id": "plan_pro",
        "name": "专业版"
      },
      "changes": {},
      "metadata": {
        "code": "pro",
        "level": 20,
        "status": "active"
      },
      "clientIp": null
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 50
}
```

`actor`、`resource.name` 和可选的 `tenant` 都是操作发生时的快照。资源删除或以后改名不会影响历史展示。

### 2.4 Request ID

Backend 对每个 HTTP 请求生成或规范化 Request ID：

- 可接受的 `X-Request-ID` 最长 128 字符，仅允许字母、数字、`.`、`_`、`:`、`-`。
- 缺少、超长或非法值会被替换成 `req_<uuid>`。
- 响应头会返回 `X-Request-ID`。
- 同一次批量请求成功的多个子项共享同一个 `requestId`。

当前 Request ID 尚未与 Gateway trace 打通。

## 3. 响应字段语义

- `actor`：操作发生时的用户姓名、邮箱和平台角色快照。
- `tenant`：相关租户快照；与租户无关的事件为 `null`。
- `resource`：操作目标的类型、ID 和名称快照。
- `changes`：允许记录字段的修改前后值；无字段变化时为空对象。
- `metadata`：与事件相关的安全摘要；无摘要时为空对象。
- `requestId`：产生该事件的 HTTP 请求标识。
- `clientIp`：当前固定为 `null`。

`actor`、`tenant` 和 `resource.name` 均为事件发生时的快照，后续改名或删除不会改变历史事件。

`changes` 示例：

```json
{
  "status": {
    "before": "draft",
    "after": "published"
  }
}
```

以下字段是脱敏后的变化摘要：

- `metadataKeys`：业务 metadata 的 key，不包含 value。
- `metadataChanged`：metadata value 是否发生变化。
- `upgradeRuleKeys` / `upgradeRulesChanged`：套餐升级规则的 key 与是否发生变化。
- 套餐 entitlement 中的 `featureKeys` / `featuresChanged`：feature key 与是否发生变化。

Backend 对各 action 可写入的 `changes` 和 `metadata` 字段执行白名单校验，不记录密码、Token、激活码、签名 URL 或 Skill 文件内容。

## 4. 中英文语义设计

Backend 返回稳定的英文字段名和枚举 code。下列中英文名称用于说明字段和事件的业务语义，不作为审计数据保存。

### 4.1 响应字段

| 字段 | 中文语义 | English meaning |
| --- | --- | --- |
| `items` | 审计事件列表 | Audit events |
| `total` | 总记录数 | Total records |
| `page` | 页码 | Page |
| `pageSize` | 每页条数 | Page size |
| `id` | 审计事件 ID | Audit event ID |
| `requestId` | 请求 ID | Request ID |
| `occurredAt` | 操作时间 | Occurred at |
| `category` | 业务分类 | Category |
| `action` | 操作标识 | Action |
| `operationType` | 操作类型 | Operation type |
| `actor` | 操作人 | Actor |
| `tenant` | 关联租户 | Tenant |
| `resource` | 操作对象 | Resource |
| `changes` | 变更内容 | Changes |
| `metadata` | 事件摘要 | Metadata |
| `clientIp` | 客户端 IP | Client IP |

### 4.2 Category

| Code | 中文语义 | English meaning |
| --- | --- | --- |
| `auth` | 登录认证 | Authentication |
| `platform_user` | 平台用户 | Platform user |
| `user` | 用户 | User |
| `platform_role` | 平台角色 | Platform role |
| `tenant` | 租户 | Tenant |
| `tenant_member` | 租户成员 | Tenant member |
| `knowledge_base` | 知识库 | Knowledge base |
| `document` | 文档 | Document |
| `skill` | Skill | Skill |
| `expert_category` | 专家分类 | Expert category |
| `expert` | 专家 | Expert |
| `plan` | 套餐 | Plan |

### 4.3 Operation Type

| Code | 中文语义 | English meaning |
| --- | --- | --- |
| `create` | 创建 | Create |
| `update` | 修改 | Update |
| `delete` | 删除 | Delete |
| `login` | 登录 | Login |
| `grant` | 授予 | Grant |
| `revoke` | 撤销 | Revoke |
| `upload` | 上传 | Upload |

### 4.4 Action

`action` 是具体操作的稳定标识，当前中英文语义如下：

| Action | 中文语义 | English meaning |
| --- | --- | --- |
| `auth.platform_login` | 登录管理平台 | Sign in to admin platform |
| `platform_user.invite` | 邀请平台用户 | Invite platform user |
| `user.update` | 修改用户信息 | Update user |
| `user.status_change` | 修改用户状态 | Change user status |
| `platform_role.grant` | 授予平台角色 | Grant platform role |
| `platform_role.revoke` | 撤销平台角色 | Revoke platform role |
| `tenant.create` | 创建租户 | Create tenant |
| `tenant.update` | 修改租户 | Update tenant |
| `tenant.status_change` | 修改租户状态 | Change tenant status |
| `tenant.subscription_change` | 修改租户套餐 | Change tenant subscription |
| `tenant_member.add` | 添加租户成员 | Add tenant member |
| `tenant_member.role_change` | 修改租户成员角色 | Change tenant member role |
| `tenant_member.remove` | 移除租户成员 | Remove tenant member |
| `knowledge_base.create` | 创建知识库 | Create knowledge base |
| `knowledge_base.update` | 修改知识库 | Update knowledge base |
| `knowledge_base.archive` | 归档知识库 | Archive knowledge base |
| `knowledge_base.activate` | 激活知识库 | Activate knowledge base |
| `knowledge_base.delete` | 删除知识库 | Delete knowledge base |
| `document.upload_completed` | 上传知识库文档 | Upload knowledge-base document |
| `document.source_replaced` | 替换知识库文档原件 | Replace knowledge-base document source |
| `document.update` | 修改知识库文档 | Update knowledge-base document |
| `document.delete` | 删除知识库文档 | Delete knowledge-base document |
| `skill.create` | 创建 Skill | Create skill |
| `skill.update` | 修改 Skill | Update skill |
| `skill.delete` | 删除 Skill | Delete skill |
| `expert_category.create` | 创建专家分类 | Create expert category |
| `expert_category.update` | 修改专家分类 | Update expert category |
| `expert_category.delete` | 删除专家分类 | Delete expert category |
| `expert.create` | 创建专家 | Create expert |
| `expert.update` | 修改专家 | Update expert |
| `expert.status_change` | 修改专家状态 | Change expert status |
| `expert.delete` | 删除专家 | Delete expert |
| `plan.create` | 创建套餐 | Create plan |
| `plan.update` | 修改套餐 | Update plan |
| `plan.prices_replace` | 替换套餐价格 | Replace plan prices |
| `plan.entitlements_replace` | 替换套餐权益 | Replace plan entitlements |
| `plan.experts_replace` | 替换套餐专家 | Replace plan experts |
| `plan.delete` | 删除套餐 | Delete plan |

设计上，`action` 表示操作语义，`resource.name` 表示操作对象在事件发生时的名称。例如 `plan.delete` 表示“删除套餐 / Delete plan”，具体套餐名称来自 `resource.name`，属于业务数据快照。

## 5. 登录审计

- 用户具有至少一个 platform role 时，成功登录会记录 `auth.platform_login`。
- 普通租户用户成功登录不会生成该事件。
- 登录审计依据 Backend 校验后的 platform role，不使用客户端 surface 字段判断。

## 6. Backend 契约边界

- Backend 只提供审计事件查询接口，不提供客户端写入审计事件的接口。
- 审计事件由 Backend 在业务事务内生成并持久化。
- 查询接口支持第 2.2 节列出的筛选和分页参数。
- Backend 返回稳定的 `action`、结构化字段、HTTP 状态和业务错误码，不返回本地化展示文案。
- 批量操作中的每个成功子项分别生成事件，失败子项不生成事件；同一批量请求的成功事件共享 `requestId`。

## 7. 当前未实现项与原因

| 未实现项 | 原因 |
| --- | --- |
| 失败请求和回滚操作审计 | 当前审计事件与业务变更在同一事务中提交；记录失败事件需要独立、可靠的持久化通道。 |
| 退出事件 | 退出可能表现为调用 Backend、仅清理浏览器状态、关闭页面或 Token 自然过期，Backend 无法统一可靠感知。 |
| 真实客户端 IP | 可信代理链、请求头清洗和隐私策略尚未统一，`clientIp` 当前返回 `null`。 |
| 上线前历史事件 | 现有业务数据无法可靠还原操作人、时间和修改前后值，因此未做历史回填。 |
| 普通用户注册、平台激活、Token 刷新、密码重置及用户侧日常操作 | 本次仅完成平台管理链路的审计接入，这些链路尚未接入。 |
| 租户用户侧 `/rbac/tenant/**` 成员操作 | 该链路尚未接入；平台控制台使用的 `/tenants/{tenantId}/members/**` 已记录。 |
| AI 模型、通知、安全和外观设置 | 当前 Backend 没有对应的真实持久化变更。 |
| `storage.gc` | 当前流程同时涉及外部对象删除和多次数据库提交，尚不能与单条摘要事件形成可靠的原子边界。 |

## 8. Backend 实现位置

| 内容 | 文件 |
| --- | --- |
| 查询路由和参数定义 | `app/api/v1/routers/audit.py` |
| 响应模型和枚举 | `app/domain/audit.py` |
| 事件构造、字段白名单和时间范围校验 | `app/services/audit_service.py` |
| 查询与持久化 | `app/services/audit_repository.py` |
| Request ID 生成和响应头 | `app/core/request_id.py`、`app/main.py` |
| 数据库表和索引 | `infra/sql/010_audit_events.sql` |
| 自动化测试 | `tests/test_audit.py` |
