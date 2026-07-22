# apollo-config-client

一个**轻量、同步、贴近 Apollo 官方 HTTP API** 的 Python 配置中心客户端。

> 直接基于 Apollo 开放的 HTTP 接口实现，不依赖任何第三方 Apollo 专用客户端，版本兼容性最好，且对热更新逻辑完全可控。官方 Java / .NET 客户端底层使用的也是同一套接口，可稳定对接 Apollo 1.6 – 2.4.1。

## 特性

| 能力 | 说明 |
|------|------|
| 长轮询热更新 | 后台守护线程长轮询 `notifications/v2`，配置发布后**秒级生效**，并给出 key 级 diff |
| 本地容灾缓存 | 每次成功拉取都落盘；Apollo 全部不可用时，应用仍可用上一次的配置启动 |
| 访问密钥签名 | 兼容 Apollo 1.6+ 的 `Access Key` HMAC-SHA1 签名（匿名访问同样支持） |
| 类型化读取 | `get_typed(namespace, Model)` 用任意模型类（如 pydantic）解析配置 |
| 极简依赖 | **核心仅依赖 `requests`**；pydantic 模型与 Oracle 助手都是可选 extra |

## 安装

```bash
pip install apollo-config-client            # 核心（仅 requests）
pip install apollo-config-client[models]    # + pydantic 领域模型 DatabaseConfig / LdapConfig
pip install apollo-config-client[oracle]    # + init_oracle_thick_mode 助手
pip install apollo-config-client[all]       # 以上全部
```

> 发布前请先在 https://pypi.org 确认包名 `apollo-config-client` 可用；若被占用，备选 `apolloc` / `apollo-config`。

## 快速开始

```python
from apollo_config import create_config_manager_from_env

# 读环境变量 APOLLO_APP_ID / APOLLO_CONFIG_URL / APOLLO_NAMESPACES ...
cm = create_config_manager_from_env()

# 普通读取
cm.get_configs("application")
cm.get_value("feature_flag", "off")

# 订阅 namespace 变更，配置一发布即刻拿到 key 级 diff
@cm.on_namespace_change("database")
def _on_db_change(namespace, changes):
    # 这里只做「置空 / 标记失效」等轻量操作，
    # 真正的资源重建放到请求路径上惰性执行（避免回调里做重 IO）
    rebuild_connection_pool_lazily()
```

显式参数创建（不走环境变量）：

```python
from apollo_config import create_config_manager

cm = create_config_manager(
    app_id="my-app",
    config_url="http://apollo-config-service:8080",
    namespaces=["application", "database"],
    access_key_secret="38fdae497a324263a5ad81aa387deee3",  # 可选
)
```

### 用 pydantic 模型读取（可选 extra `[models]`）

```python
from apollo_config.contrib import DatabaseConfig

cfg = cm.get_typed("database", DatabaseConfig)
engine = create_engine(cfg.connection_url(), pool_size=cfg.pool_size)
```

## 设计要点

1. **直接调用 Apollo 开放 HTTP API**（官方客户端同款接口）：
   - 配置拉取：`GET {config_url}/configs/{appId}/{cluster}/{namespace}`
   - 变更通知：`GET {config_url}/notifications/v2`（HTTP 长轮询，秒级生效）
2. **热更新机制**：后台守护线程长轮询 `notifications/v2`，一旦 Apollo 发布新配置，
   客户端拉取最新值并计算 key 级 diff，触发业务注册的回调。
3. **本地容灾缓存**：每次成功拉取都会落盘到缓存目录；即使 Apollo 全部不可用，
   应用也能用上一次的配置正常启动。
4. **访问密钥签名**：配置 `access_key_secret` 后，对 `configs` 与 `notifications/v2`
   两类请求统一做 HMAC-SHA1 加签；留空则走匿名访问，行为完全一致。

## 环境变量（用于 `create_config_manager_from_env`）

| 变量 | 说明 | 默认 |
|------|------|------|
| `APOLLO_APP_ID` | 应用 AppId | `apollo-app` |
| `APOLLO_CONFIG_URL` | Config Service 地址（非 Portal 的 8070） | `http://localhost:8080` |
| `APOLLO_CLUSTER` | 集群 | `default` |
| `APOLLO_NAMESPACES` | 逗号分隔的 namespace | `application` |
| `APOLLO_ENV` | 环境名 | 空 |
| `APOLLO_ACCESS_KEY_SECRET` | 访问密钥（可选） | 空 |
| `APOLLO_CACHE_DIR` | 本地缓存目录 | `.apollo_cache` |
| `ORACLE_INSTANT_CLIENT` | Oracle Instant Client 路径（仅 11g 需要） | 空 |

## 示例应用

`examples/` 下提供 Flask / FastAPI 两个完整示例（DB 连接池热重建）：

```bash
cd examples
pip install -r requirements.txt        # 会以 editable 方式安装本库
cp ../.env.example .env                # 按需修改 Apollo 地址 / AppId
python flask_app.py                    # http://localhost:5000/config/database
# 或 python fastapi_app.py
```

## 生产建议

- **脱敏**：`password` / `bind_password` 等建议标记为 Apollo「私密配置」，对外接口务必脱敏（见 `public_dict()`）。
- **优雅关闭**：进程退出前调用 `config_manager.stop()` 停止长轮询线程（示例在 `settings.py` 用 `atexit` 注册）。
- **回调要快**：变更回调里只做「置空 / 标记失效」这类轻量操作，真正的重建放到请求路径上惰性执行。
- **本地缓存目录** `.apollo_cache/` 应加入 `.gitignore`，不要提交到代码库。

## Roadmap

- [ ] 多 Config Service 端点 / HA 故障转移（当前为单 `config_url`）
- [ ] 可选的 async wrapper（基于 `httpx` 或线程池），不进核心
- [ ] 配置变更事件的同步原语（如 `watch()` 返回最新值的上下文管理器）

## License

[MIT](LICENSE)
