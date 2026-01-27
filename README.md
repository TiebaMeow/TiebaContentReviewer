# TiebaContentReviewer

与 TiebaMeow 工具集无缝集成的贴吧内容审查服务

## 简介

TiebaContentReviewer 是一个专为百度贴吧设计的内容审查服务。它能够自动根据预定义的规则高效地检测和处理违规内容，协助吧务团队维护社区环境。该服务可与 TiebaMeow 工具集无缝集成，提供强大的内容审查能力。

在开始使用前，请确保您已经安装并配置了 TiebaScraper（Redis object 推送模式） 和一个用来处理审查结果的消费者服务（如 TiebaManageBot）。

## 功能特性

- **高性能异步架构**：基于 Python `asyncio` 和 `uvloop`（如果安装），充分利用异步 I/O 优势，高效处理高并发数据流。
- **动态规则热加载**：支持通过 Redis Pub/Sub 实时同步规则变更，无需重启服务即可生效。
- **强大的规则引擎**：支持 `AND`、`OR`、`NOT`、`XOR` 等复杂逻辑组合，以及嵌套字段访问，满足多样化的审查需求。
- **多模式函数执行**：支持本地函数（Local）和远程 gRPC 调用（RPC），甚至混合模式（Hybrid），灵活扩展审查逻辑。
- **无缝集成**：专为 TiebaMeow 生态设计，通过 Redis Stream 与 Scraper 和 Bot 组件解耦协作。
- **持久化存储**：规则存储于 PostgreSQL，确保数据安全和持久性。
- **水平扩展**：基于 Manager + Worker 模式，动态管理多个 Worker 实例以提升吞吐量。

## 环境配置

- **Python**: >= 3.12
- **PostgreSQL**: >= 15
- **Redis**: >= 7.0
- **包管理器**: 推荐使用 [uv](https://docs.astral.sh/uv/) 进行依赖管理。

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/TiebaMeow/TiebaContentReviewer.git
cd TiebaContentReviewer
```

### 2. 安装依赖

本项目使用 `uv` 管理依赖：

```bash
# 安装 uv (如果尚未安装)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 同步依赖
uv sync
```

### 3. 配置环境变量

复制 `.env.example` (如果不存在则手动创建) 到 `.env` 并根据实际情况修改：

```ini
# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=tieba_reviewer

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Stream & Queue
REDIS_STREAM_KEY=scraper:tieba:events
REDIS_ACTION_STREAM_KEY=reviewer:actions:stream
REDIS_CONSUMER_GROUP=reviewer_group
REDIS_CONSUMER_NAME=worker_1
BATCH_SIZE=10

# RPC (Optional)
RPC_ENABLED=False
RPC_URL=http://localhost:8000
```

### 4. 运行服务

确保 PostgreSQL 和 Redis 服务已启动，然后运行：

```bash
uv run main.py
```

服务启动后会自动初始化数据库表结构，并开始监听 Redis Stream。

## 高级用法

### 规则定义示例

规则以 JSON 格式存储，支持复杂的逻辑嵌套。例如，定义一个规则：当帖子内容包含 "违规词" 且 (等级 < 3 或 user_id in [123456, 654321]) 时，执行 "删除" 和 "封禁" 操作。

```json
{
  "name": "低等级用户违规词过滤",
  "enabled": true,
  "priority": 10,
  "trigger": {
    "type": "group",
    "logic": "AND",
    "conditions": [
      {
        "type": "condition",
        "field": "content",
        "operator": "contains",
        "value": "违规词"
      },
      {
        "type": "group",
        "logic": "OR",
        "conditions": [
          {
            "type": "condition",
            "field": "author.level",
            "operator": "lt",
            "value": 3
          },
          {
            "type": "condition",
            "field": "author.user_id",
            "operator": "in",
            "value": [123456, 654321]
          }
        ]
      }
    ]
  },
  "actions": [
    { "type": "delete_post" },
    { "type": "ban_user", "params": { "duration": 1 } }
  ]
}
```

除了基本的字段比较，您还可以使用注册的函数（支持本地和 RPC）作为触发条件。例如，调用 `keyword_count` 函数统计违规词出现次数：

```json
{
  "name": "高频违规词检测",
  "enabled": true,
  "fid": 123456,
  "priority": 200,
  "trigger": {
    "type": "condition",
    "function": "keyword_count",
    "args": [["垃圾", "广告"]],
    "operator": "ge",
    "value": 3
  },
  "actions": [
    { "type": "delete_post" },
    { "type": "block_user", "params": { "duration": 10 } }
  ]
}
```

## Docker 部署

本项目提供了 `docker-compose.yml` 文件，可一键启动包含 PostgreSQL 和 Redis 的完整环境。

```bash
docker-compose up -d
```

这将启动三个容器：

- `tieba_reviewer`: 审查服务核心应用
- `tieba_reviewer_db`: PostgreSQL 数据库
- `tieba_reviewer_redis`: Redis 服务

## 项目结构

```text
TiebaContentReviewer/
├── src/
│   ├── core/             # 核心业务逻辑
│   │   ├── engine.py     # 规则匹配引擎
│   │   ├── provider.py   # 函数执行策略 (Local/RPC)
│   │   └── registry.py   # 本地函数注册表
│   ├── infra/            # 基础设施层
│   │   ├── db.py         # 数据库连接与模型
│   │   ├── repository.py # 规则仓储实现
│   │   └── dispatcher.py # 动作分发器
│   ├── rpc/              # gRPC 服务定义
│   │   └── review_service.proto
│   ├── worker/           # 工作进程
│   │   ├── manager.py    # Worker 管理器
│   │   └── consumer.py   # Redis Stream 消费者
│   ├── config.py         # 应用配置
│   └── functions.py      # 本地规则函数实现
├── tests/                # 测试用例
├── main.py               # 程序入口
├── pyproject.toml        # 项目依赖配置
├── docker-compose.yml    # Docker 编排文件
└── README.md             # 项目文档
```
