# 专家市场标签

## 为什么标签归属于专家

“热门”描述的是某个专家卡片的展示状态，而不是分类本身。把标签存到专家上，管理后台可以按专家 ID 独立配置，也允许同一专家后续同时拥有多个市场标签，避免分类下所有专家共享同一个标签。

## `marketLabels` 字段

- 类型：枚举数组。
- 当前支持：`hot`。
- `[]` 表示没有市场标签。
- 创建时未传默认为 `[]`。
- PATCH 未传时保留原值，传 `[]` 时清除全部标签。
- Service 会去重并保留首次出现的顺序。
- 不支持的值返回 `422`。

创建热门专家：

```json
{
  "name": "广告专家",
  "categoryId": "expert_cat_ads",
  "abilityIntro": "负责广告投放和 ACOS 分析",
  "marketLabels": ["hot"]
}
```

设置热门：

```json
{
  "marketLabels": ["hot"]
}
```

取消热门：

```json
{
  "marketLabels": []
}
```

## 受影响接口

管理接口返回完整专家对象，并在创建和编辑时接受 `marketLabels`：

- `GET /api/v1/experts`
- `GET /api/v1/experts/{expert_id}`
- `POST /api/v1/experts`
- `PATCH /api/v1/experts/{expert_id}`

市场接口返回的专家对象包含 `marketLabels`：

- `GET /api/v1/expert-market/experts`
- `GET /api/v1/expert-market/experts/{expert_id}`

`GET /api/v1/expert-market/categories` 继续只提供分类筛选信息，不负责专家卡片标签。标签不改变 published 过滤和现有排序规则。

## 前端后续调整

- 创建和编辑专家时增加“热门”选项。
- 专家卡片根据 `marketLabels` 展示标签。
