# 错误处理规范

## 核心决策树

```
调用方需要根据不同错误做不同处理吗？（判断标准来自 Luca Palmieri）
  ├─ 是 → thiserror 定义具体错误枚举，让调用方可以 match 变体
  └─ 否（只是上报/打日志）→ anyhow::Error 足够

对应到常见情况：
  library crate（被别人依赖）→ 通常是"是"，用 thiserror
  bin / application 内部   → 通常是"否"，用 anyhow + .context()
```

---

## 反模式

```rust
// ❌ 1. 生产路径上的 unwrap 定时炸弹
let config = std::fs::read_to_string("config.toml").unwrap();
let port: u16 = env::var("PORT").unwrap().parse().unwrap();

// ❌ 2. 库的公共 API 返回 Box<dyn Error>，调用方无法区分错误类型
pub fn load_config(path: &Path) -> Result<Config, Box<dyn std::error::Error>> {
    let text = std::fs::read_to_string(path)?;
    let cfg: Config = toml::from_str(&text)?;
    Ok(cfg)
}

// ❌ 3. 手写 Display / Error / From 样板（有 thiserror 之后没必要）
impl std::fmt::Display for MyError { ... }
impl std::error::Error for MyError { ... }
impl From<std::io::Error> for MyError { ... }
```

---

## 正确做法

### Library crate：thiserror

```rust
// ✅ 具体枚举，调用方能 match
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("config file not found at {path}")]
    NotFound { path: PathBuf },

    #[error("invalid TOML: {0}")]
    ParseFailed(#[from] toml::de::Error),  // #[from] 自动生成 From impl

    #[error("missing required field: {field}")]
    MissingField { field: &'static str },
}

pub fn load_config(path: &Path) -> Result<Config, ConfigError> { ... }

// 调用方可以精确处理：配置文件不存在 → 用默认值，其他错误照常上报
fn load_or_default(path: &Path) -> Result<Config, ConfigError> {
    match load_config(path) {
        Ok(cfg) => Ok(cfg),
        Err(ConfigError::NotFound { .. }) => Ok(Config::default()),
        Err(e) => Err(e),
    }
}
```

### Application / bin：anyhow

```rust
// ✅ 快速传播，专注业务；设置 RUST_BACKTRACE=1 或 RUST_LIB_BACKTRACE=1 时会捕获 backtrace
use anyhow::{Context, Result};

fn main() -> Result<()> {
    let config = load_config(Path::new("config.toml"))
        .context("failed to load configuration")?;

    let port: u16 = std::env::var("PORT")
        .context("PORT env var not set")?
        .parse()
        .context("PORT must be a valid u16")?;

    run(config, port)
}
```

### 混用：thiserror 定义 + anyhow 传播

```rust
// ✅ 库暴露具体类型，应用层用 anyhow 包装
// 在 lib crate：
#[derive(Debug, thiserror::Error)]
pub enum ApiError {
    #[error("rate limit exceeded")]
    RateLimit,
    #[error("upstream error: {0}")]
    Upstream(#[from] reqwest::Error),
}

impl ApiClient {
    pub async fn fetch_data(&self) -> Result<Data, ApiError> { ... }
}

// 在 bin crate：
use anyhow::{Context, Result};

async fn refresh(client: &ApiClient) -> Result<Data> {
    let data = client.fetch_data().await.context("refreshing data")?; // ApiError 自动转成 anyhow::Error
    Ok(data)
}
```

---

## `.unwrap()` 和 `.expect()` 使用准则

| 场景 | 怎么做 |
|---|---|
| 生产代码，可能失败 | `?` 传播错误，或 `.context("...")?` |
| 值逻辑上不可能是 None/Err | `.expect("为什么不可能")`，把理由写进 expect 信息 |
| 单元测试、`examples/`、doctest | `.unwrap()` 可以，测试里 panic 就是 test fail |
| 用字面量初始化的静态值（如固定正则） | `LazyLock` + `.expect(...)`，见下 |
| 生产路径上的裸 `.unwrap()` | 不要写 |

```rust
use std::sync::LazyLock;

// 正则是字面量：写错了会在第一次使用时 panic，测试能覆盖到
static VERSION_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\d+\.\d+$").expect("VERSION_RE is a valid regex"));
```

`std::sync::LazyLock` 从 Rust 1.80 起稳定，不需要再引入 `once_cell` / `lazy_static`。

---

## `Box<dyn Error>` 什么时候可以用

| 场景 | 结论 |
|---|---|
| 库的公共 API 返回值 | 不要用。调用方无法 match，用 thiserror 枚举 |
| `main`、`examples/`、doctest、一次性小工具 | 可以。`fn main() -> Result<(), Box<dyn Error>>` 是标准写法，不必为此引入 anyhow |
| 错误枚举里包一个来源不确定的错误（插件、用户回调） | 可以。变体里放 `#[source] Box<dyn Error + Send + Sync>` |

`anyhow::Error` 本质上也是类型擦除的错误，所以同样不要出现在库的公共 API 里。

---

## `?` 操作符是标准，不是可选的

```rust
// ❌ 手写 match 传播错误，没有任何好处
let file = match File::open(path) {
    Ok(f) => f,
    Err(e) => return Err(e),
};

// ✅ ? 操作符，简洁，配合 From trait 自动类型转换
let file = File::open(path)?;
```
