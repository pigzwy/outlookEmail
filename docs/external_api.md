# 📡 对外 API 对接文档

## 概述

Outlook 邮件管理系统提供一组 RESTful API，支持外部系统通过 API Key 进行邮箱账号管理和邮件读取，无需登录 Web 界面。

**Base URL**: `http://your-host:5000`

---

## 🔑 认证方式

所有接口均需 API Key 认证，支持两种传递方式：

```
# 方式一：Header（推荐）
X-API-Key: your-api-key

# 方式二：查询参数
?api_key=your-api-key
```

### 获取 API Key

登录 Web 界面 → 点击「⚙️ 设置」→ 「对外 API Key」→ 点击「🔑 随机生成」→ 保存

### 认证错误响应

```json
// 401 - 未提供 API Key
{"success": false, "error": "缺少 API Key，请通过 Header X-API-Key 或查询参数 api_key 提供"}

// 401 - Key 无效
{"success": false, "error": "API Key 无效"}

// 403 - 未配置
{"success": false, "error": "未配置对外 API Key，请在系统设置中配置"}
```

---

## 📋 接口列表

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/external/accounts` | GET | 获取所有邮箱账号（含标签） |
| `/api/external/accounts/tags` | POST | 批量打标签 / 去标签 |
| `/api/external/emails` | GET | 获取指定邮箱的邮件列表 |

---

## 1. 获取邮箱账号列表

### `GET /api/external/accounts`

获取所有邮箱账号信息，包含分组、标签、状态等。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `group_id` | int | ❌ | 按分组筛选，不传则返回所有 |

**请求示例：**

```bash
# 获取所有邮箱
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/accounts"

# 按分组筛选
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/accounts?group_id=2"
```

**成功响应：**

```json
{
  "success": true,
  "accounts": [
    {
      "id": 1,
      "email": "user@outlook.com",
      "group_id": 2,
      "group_name": "100个",
      "remark": "备注信息",
      "status": "active",
      "last_refresh_at": "2026-03-25 10:00:00",
      "last_refresh_status": "success",
      "tags": [
        {
          "id": 1,
          "name": "已处理",
          "color": "#107c10"
        },
        {
          "id": 3,
          "name": "VIP",
          "color": "#0078d4"
        }
      ]
    },
    {
      "id": 2,
      "email": "test@outlook.com",
      "group_id": 1,
      "group_name": "默认分组",
      "remark": "",
      "status": "active",
      "last_refresh_at": "",
      "last_refresh_status": null,
      "tags": []
    }
  ]
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 账号 ID（打标签时需要） |
| `email` | string | 邮箱地址（获取邮件时需要） |
| `group_id` | int | 所属分组 ID |
| `group_name` | string | 分组名称 |
| `remark` | string | 备注 |
| `status` | string | 状态：`active` / `inactive` |
| `last_refresh_at` | string | 最后刷新时间 |
| `last_refresh_status` | string/null | 最后刷新结果：`success` / `failed` / `null` |
| `tags` | array | 标签列表，每个包含 `id`、`name`、`color` |

---

## 2. 获取邮件列表

### `GET /api/external/emails`

获取指定邮箱的邮件列表。系统会依次尝试 Graph API → IMAP(新) → IMAP(旧)，自动回退。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 | 默认值 |
|------|------|------|------|--------|
| `email` | string | ✅ | 邮箱地址 | - |
| `folder` | string | ❌ | `inbox`（收件箱）或 `junkemail`（垃圾邮件） | `inbox` |
| `skip` | int | ❌ | 跳过邮件数（分页） | `0` |
| `top` | int | ❌ | 返回数量（最大 50） | `20` |

**请求示例：**

```bash
# 获取收件箱前 20 封邮件
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com"

# 获取垃圾邮件
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com&folder=junkemail"

# 分页：跳过前 20 封，取 10 封
curl -H "X-API-Key: your-api-key" \
  "http://localhost:5000/api/external/emails?email=user@outlook.com&skip=20&top=10"
```

**成功响应：**

```json
{
  "success": true,
  "method": "Graph API",
  "has_more": true,
  "emails": [
    {
      "id": "AAMkAGQ2...",
      "subject": "Welcome to Outlook",
      "from": "noreply@microsoft.com",
      "date": "2026-03-25T02:30:00Z",
      "is_read": false,
      "has_attachments": false,
      "body_preview": "Thank you for creating your account..."
    }
  ]
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 邮件唯一 ID |
| `subject` | string | 邮件主题 |
| `from` | string | 发件人邮箱 |
| `date` | string | 接收时间（ISO 8601） |
| `is_read` | bool | 是否已读 |
| `has_attachments` | bool | 是否有附件 |
| `body_preview` | string | 正文预览（纯文本摘要） |
| `has_more` | bool | 是否还有更多邮件（用于分页） |

**错误响应：**

```json
// 400 - 参数错误
{"success": false, "error": "缺少 email 参数"}
{"success": false, "error": "folder 参数无效，支持: inbox, junkemail"}

// 404 - 邮箱不存在
{"success": false, "error": "邮箱账号不存在"}

// 获取失败（含各方法的详细错误）
{"success": false, "error": "无法获取邮件，所有方式均失败", "details": {...}}
```

---

## 3. 批量管理标签

### `POST /api/external/accounts/tags`

给邮箱账号批量添加或移除标签。

**请求 Body（JSON）：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `account_ids` | array\<int\> | ✅ | 账号 ID 列表（从 accounts 接口获取） |
| `tag_id` | int | ✅ | 标签 ID（Web 界面创建标签后获取） |
| `action` | string | ✅ | `add`（添加）或 `remove`（移除） |

**请求示例：**

```bash
# 给 3 个邮箱打上 tag_id=1 的标签
curl -X POST -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"account_ids":[1,2,3], "tag_id":1, "action":"add"}' \
  "http://localhost:5000/api/external/accounts/tags"

# 移除标签
curl -X POST -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"account_ids":[1,2,3], "tag_id":1, "action":"remove"}' \
  "http://localhost:5000/api/external/accounts/tags"
```

**成功响应：**

```json
{"success": true, "message": "成功处理 3 个账号"}
```

**错误响应：**

```json
// 400 - 参数不完整
{"success": false, "error": "参数不完整，需要 account_ids, tag_id, action(add/remove)"}
```

> **注意**：标签（tag）需要先在 Web 界面「标签管理」中创建，记下 `tag_id` 后在 API 中使用。

---

## 🔗 业务对接示例

### 典型流程：筛选未处理邮箱 → 获取邮件 → 标记已处理

```python
import requests

BASE_URL = "http://localhost:5000"
API_KEY = "your-api-key"
HEADERS = {"X-API-Key": API_KEY}
TAG_ID = 1  # "已处理" 标签的 ID，在 Web 界面创建后获取

def main():
    # ① 获取所有邮箱（含标签信息）
    resp = requests.get(f"{BASE_URL}/api/external/accounts", headers=HEADERS)
    accounts = resp.json()["accounts"]
    print(f"共 {len(accounts)} 个邮箱")

    # ② 业务侧筛选：排除已打过"已处理"标签的邮箱
    todo = [
        acc for acc in accounts
        if acc["status"] == "active"
        and TAG_ID not in [t["id"] for t in acc["tags"]]
    ]
    print(f"待处理 {len(todo)} 个邮箱")

    # ③ 逐个获取邮件并处理
    processed_ids = []
    for acc in todo:
        resp = requests.get(
            f"{BASE_URL}/api/external/emails",
            params={"email": acc["email"], "folder": "inbox", "top": 10},
            headers=HEADERS
        )
        data = resp.json()

        if data["success"] and data["emails"]:
            for email in data["emails"]:
                print(f"  [{acc['email']}] {email['subject']}")
                # ... 你的业务逻辑 ...

            processed_ids.append(acc["id"])

    # ④ 批量打标签，标记为已处理
    if processed_ids:
        resp = requests.post(
            f"{BASE_URL}/api/external/accounts/tags",
            headers={**HEADERS, "Content-Type": "application/json"},
            json={
                "account_ids": processed_ids,
                "tag_id": TAG_ID,
                "action": "add"
            }
        )
        print(resp.json()["message"])

if __name__ == "__main__":
    main()
```

### Java / HTTP 通用调用

```
GET  http://localhost:5000/api/external/accounts
     Header: X-API-Key: your-api-key

GET  http://localhost:5000/api/external/emails?email=user@outlook.com&folder=inbox
     Header: X-API-Key: your-api-key

POST http://localhost:5000/api/external/accounts/tags
     Header: X-API-Key: your-api-key
     Header: Content-Type: application/json
     Body: {"account_ids":[1,2,3], "tag_id":1, "action":"add"}
```

---

## ⚠️ 注意事项

1. **API Key 安全**：请妥善保管 API Key，不要暴露在前端代码或公开仓库中
2. **邮件获取频率**：Graph API 有微软的速率限制，建议每个邮箱之间间隔 1-2 秒
3. **标签预先创建**：`tag_id` 需要先在 Web 界面创建对应标签后获取
4. **邮箱状态**：`status=inactive` 的邮箱已被停用，建议跳过
5. **分页**：邮件列表每次最多返回 50 封，通过 `skip` 参数实现分页
