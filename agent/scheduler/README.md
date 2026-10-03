# 定时任务工具 (Scheduler Tool)

## 功能简介

定时任务工具允许 Agent 创建、管理和执行定时任务，支持：

- ⏰ **定时提醒**: 在指定时间发送消息
- 🔄 **周期性任务**: 按固定间隔或 cron 表达式重复执行
- 🔧 **动态工具调用**: 定时执行其他工具并发送结果（如搜索新闻、查询天气等）
- 📋 **任务管理**: 查询、启用、禁用、删除任务

## 安装依赖

```bash
pip install croniter>=2.0.0
```

## 使用方法

### 1. 创建定时任务

Agent 可以通过自然语言创建定时任务，支持两种类型：

#### 1.1 静态消息任务

发送预定义的消息：

**示例对话：**
```
用户: 每天早上9点提醒我开会
Agent: [调用 scheduler 工具]
      action: create
      name: 每日开会提醒
      message: 该开会了！
      schedule_type: cron
      schedule_value: 0 9 * * *
```

#### 1.2 动态工具调用任务

定时执行工具并发送结果：

**示例对话：**
```
用户: 每天早上8点帮我读取一下今日日程
Agent: [调用 scheduler 工具]
      action: create
      name: 每日日程
      tool_call:
        tool_name: read
        tool_params:
          file_path: ~/stella/schedule.txt
        result_prefix: 📅 今日日程
      schedule_type: cron
      schedule_value: 0 8 * * *
```

**工具调用参数说明：**
- `tool_name`: 要调用的工具名称（如 `bash`、`read`、`write` 等内置工具）
- `tool_params`: 工具的参数（字典格式）
- `result_prefix`: 可选，在结果前添加的前缀文本

**注意：** 如果要使用 skills（如 bocha-search），需要通过 `bash` 工具调用 skill 脚本

### 2. 支持的调度类型

#### Cron 表达式 (`cron`)
5 位 Linux crontab，或 6 位 Quartz（秒在最前）：

```
0 9 * * *        # 每天 9:00（分 时 日 月 周）
0 0 9 * * *      # 每天 9:00:00（秒 分 时 日 月 周）
0 */2 * * *      # 每 2 小时
30 8 * * 1-5     # 工作日 8:30
0 0 1 * *        # 每月 1 号 0:00
0 9 L * *        # 每月最后一天 9:00
```

#### 固定间隔 (`interval`)
以秒为单位的间隔：

```
3600           # 每小时
86400          # 每天
1800           # 每 30 分钟
```

#### 一次性任务 (`once`)
指定具体时间（ISO 格式）：

```
2024-12-25T09:00:00
2024-12-31T23:59:59
```

### 3. 查询任务列表

```
用户: 查看我的定时任务
Agent: [调用 scheduler 工具]
      action: list
```

### 4. 查看任务详情

```
用户: 查看任务 abc123 的详情
Agent: [调用 scheduler 工具]
      action: get
      task_id: abc123
```

### 5. 删除任务

```
用户: 删除任务 abc123
Agent: [调用 scheduler 工具]
      action: delete
      task_id: abc123
```

### 6. 启用/禁用任务

```
用户: 暂停任务 abc123
Agent: [调用 scheduler 工具]
      action: disable
      task_id: abc123

用户: 恢复任务 abc123
Agent: [调用 scheduler 工具]
      action: enable
      task_id: abc123
```

## 任务存储

桌面版任务保存在 SQLite 中；其他渠道仍使用 JSON：
```
~/stella/scheduler/automation.db
~/stella/scheduler/tasks.json
```

任务数据结构：

首次启动不会自动创建定时任务。需要每日简报时，可手动创建调用 `briefing` 工具的任务。

桌面任务必须明确选择 `source`（绑定现有对话）、`reuse`（同一个任务对话）或 `new`（每次新对话）；`reuse` 和 `new` 还需选择普通或项目空间。其他消息渠道继续使用各自的接收人。

任务可选 `catch_up: "same_day"` 以补执行当天最近一次 Cron，避免重放离线期间的每日任务；未设置时仍使用原十分钟宽限。`retry_interval_seconds` 指定失败重试间隔，`retry_at` 保存重试时间。静默 `tool_call` 设置 `action.silent: true`，无需接收人或就绪的消息通道；工具报错不会被当作成功，保留计划并重试。

**静态消息任务：**
```json
{
  "id": "abc123",
  "name": "每日提醒",
  "enabled": true,
  "created_at": "2024-01-01T10:00:00",
  "updated_at": "2024-01-01T10:00:00",
  "schedule": {
    "type": "cron",
    "expression": "0 9 * * *"
  },
  "action": {
    "type": "send_message",
    "content": "该开会了！",
    "receiver": "wxid_xxx",
    "receiver_name": "张三",
    "is_group": false,
    "channel_type": "wechat"
  },
  "next_run_at": "2024-01-02T09:00:00",
  "last_run_at": "2024-01-01T09:00:00"
}
```

**动态工具调用任务：**
```json
{
  "id": "def456",
  "name": "每日日程",
  "enabled": true,
  "created_at": "2024-01-01T10:00:00",
  "updated_at": "2024-01-01T10:00:00",
  "schedule": {
    "type": "cron",
    "expression": "0 8 * * *"
  },
  "action": {
    "type": "tool_call",
    "tool_name": "read",
    "tool_params": {
      "file_path": "~/stella/schedule.txt"
    },
    "result_prefix": "📅 今日日程",
    "receiver": "wxid_xxx",
    "receiver_name": "张三",
    "is_group": false,
    "channel_type": "wechat"
  },
  "next_run_at": "2024-01-02T08:00:00"
}
```

## 后台服务

定时任务由后台服务 `SchedulerService` 管理：

- 每 30 秒检查一次到期任务
- 自动执行到期任务
- 计算下次执行时间
- 记录执行历史和错误

服务在 Agent 初始化时自动启动，无需手动配置。

## 接收者确定

其他消息渠道的定时任务会发送给**创建任务时的对话对象**：

- 如果在私聊中创建，发送给该用户
- 如果在群聊中创建，发送到该群
- 接收者信息在创建时自动保存

## 常见用例

### 1. 每日提醒（静态消息）
```
用户: 每天早上8点提醒我吃药
Agent: ✅ 定时任务创建成功
       任务ID: a1b2c3d4
       调度: 每天 8:00
       消息: 该吃药了！
```

### 2. 工作日提醒（静态消息）
```
用户: 工作日下午6点提醒我下班
Agent: [创建 cron: 0 18 * * 1-5]
       消息: 该下班了！
```

### 3. 倒计时提醒（静态消息）
```
用户: 1小时后提醒我
Agent: [创建 interval: 3600]
```

### 4. 每日日程推送（动态工具调用）
```
用户: 每天早上8点帮我读取今日日程
Agent: ✅ 定时任务创建成功
       任务ID: schedule001
       调度: 每天 8:00
       工具: read(file_path='~/stella/schedule.txt')
       前缀: 📅 今日日程
```

### 5. 定时文件备份（动态工具调用）
```
用户: 每天晚上11点备份工作文件
Agent: [创建 cron: 0 23 * * *]
       工具: bash(command='cp ~/stella/work.txt ~/stella/backup/work_$(date +%Y%m%d).txt')
       前缀: ✅ 文件已备份
```

### 6. 周报提醒（静态消息）
```
用户: 每周五下午5点提醒我写周报
Agent: [创建 cron: 0 17 * * 5]
       消息: 📊 该写周报了！
```

### 4. 特定日期提醒
```
用户: 12月25日早上9点提醒我圣诞快乐
Agent: [创建 once: 2024-12-25T09:00:00]
```

## 注意事项

1. **时区**: 使用系统本地时区
2. **精度**: 检查间隔为 30 秒，实际执行可能有 ±30 秒误差
3. **持久化**: 任务保存在文件中，重启后自动恢复
4. **一次性任务**: 执行后自动禁用，不会删除（可手动删除）
5. **错误处理**: 执行失败会记录错误，不影响其他任务

## 技术实现

- **TaskStore** (`agent/scheduler/store.py`): 任务持久化存储
- **SchedulerService** (`agent/scheduler/service.py`): 后台调度服务
- **Integration** (`agent/scheduler/integration.py`): 与 AgentBridge 集成
- **SchedulerTool** (`agent/tools/scheduler/`): Agent 工具接口（薄适配器）

## 依赖

- `croniter`: Cron 表达式解析（轻量级，仅 ~50KB）
