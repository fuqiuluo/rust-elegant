# 项目结构规范

## 先用模块，再考虑 Workspace

一个 package 可以同时有 `src/lib.rs` 和 `src/main.rs`（多个 binary 放 `src/bin/`），这是 Cargo 的标准布局，不需要为此建 workspace。代码多了先拆模块（`mod`），模块足以表达大部分边界。`main.rs` 堆了上千行，要解决的是模块划分，不是 workspace。

出现下面情况时，再拆成 workspace 里的多个 crate：
- 多个 binary / 服务共享一部分代码，并且希望各自的依赖互相隔离
- 需要编译器强制依赖方向（比如 core 不许依赖 IO 层），模块的可见性管不住
- 增量编译太慢，拆 crate 能让并行编译和缓存生效
- 某部分有不同的编译要求：`no_std`、WASM 目标、proc-macro（必须是独立 crate）
- 某部分要单独发布到 crates.io

---

## 推荐结构：扁平 crates/ 布局

来自 rust-analyzer（20万行代码）的实战经验：**扁平优于树形**。

```
my-project/
├── Cargo.toml          # workspace 虚拟 manifest，不放代码
├── Cargo.lock
├── crates/
│   ├── my-project-core/        # 核心领域逻辑，零 IO 依赖
│   ├── my-project-protocol/    # 协议定义、序列化（serde）
│   ├── my-project-storage/     # 数据库、持久化
│   ├── my-project-api/         # HTTP/gRPC 接口层
│   └── my-project-common/      # 日志、错误、metrics 等基础设施
└── bins/
    └── my-project-server/      # 二进制入口，只负责启动和 wiring
```

**根 Cargo.toml（虚拟 manifest）：**
```toml
[workspace]
members = [
    "crates/*",
    "bins/*",
]
resolver = "3"   # edition 2024 的默认 resolver；虚拟 manifest 没有 edition，要显式写

[workspace.package]
edition = "2024"

# 统一管理所有依赖版本，避免版本冲突。
# 版本号仅作格式示意：实际用 `cargo add` 写入当前版本后再移到这里，不要凭记忆写
[workspace.dependencies]
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
thiserror = "2"
anyhow = "1"
tracing = "0.1"
```

**各 crate 的 Cargo.toml 引用 workspace 配置：**
```toml
[package]
name = "my-project-core"
edition.workspace = true

[dependencies]
tokio.workspace = true
serde.workspace = true
```

---

## 为什么扁平优于树形

```
# ❌ 树形（看起来有逻辑，实际维护噩梦）
src/
  core/
    Cargo.toml
    hir/
      Cargo.toml    ← Cargo 里没有命名空间，hir::def 在 Cargo.toml 里写不出来

# ✅ 扁平（rust-analyzer 的选择）
crates/
  project-core/
  project-hir/
  project-hir-def/
  project-hir-ty/
```

扁平的优点：
1. Cargo crate 命名空间本来就是扁平的，结构和命名保持一致
2. 增删 crate 不需要重新考虑放在哪棵树上
3. 长期维护中，树形结构会腐化（没有完美的层次），扁平不需要维护

---

## Crate 边界如何划分

**按"稳定性"和"依赖方向"划分，不按文件大小划分：**

```
依赖方向（下层不知道上层的存在）：

bins/server        ← 入口，依赖所有 crates
  ↓
crates/api         ← HTTP 层，依赖 core + protocol
  ↓
crates/core        ← 业务逻辑，只依赖 common + protocol
  ↓
crates/protocol    ← 数据结构定义，只依赖 serde
  ↓
crates/common      ← 基础设施，几乎零内部依赖
```

**何时拆出新 crate：**
- 一段逻辑已经稳定，不再频繁改动
- 有清晰的语义边界（协议 vs 业务 vs 存储）
- 不同 crate 有不同的编译特性需求（如 no_std）
- 需要被多个 binary 共享

**不要为了拆而拆：** 文件大不是拆 crate 的理由，文件里可以有多个 `mod`。

---

## Trait 驱动的适配层（以 AI Gateway 为例）

```rust
// ✅ 在 gateway-protocol crate 定义 trait
pub trait ModelAdapter: Send + Sync {
    fn to_canonical(&self, req: RawRequest) -> Result<CanonicalRequest, ProtocolError>;
    fn from_canonical(&self, resp: CanonicalResponse) -> Result<RawResponse, ProtocolError>;
    fn model_id(&self) -> &str;
}

// 每个 provider 实现 trait，互不依赖
pub struct OpenAiAdapter { ... }
impl ModelAdapter for OpenAiAdapter { ... }

pub struct AnthropicAdapter { ... }
impl ModelAdapter for AnthropicAdapter { ... }

// gateway-core 只依赖 trait，不依赖具体实现
pub struct Router {
    adapters: HashMap<String, Box<dyn ModelAdapter>>,
    engine: Engine,
}

impl Router {
    pub fn route(&self, model_id: &str, req: RawRequest) -> Result<RawResponse, Error> {
        let adapter = self.adapters.get(model_id)
            .ok_or_else(|| Error::UnknownModel(model_id.to_string()))?;
        let canonical = adapter.to_canonical(req)?;
        let resp = self.engine.process(canonical)?;
        adapter.from_canonical(resp)
    }
}
```

新增 provider 只需实现 `ModelAdapter` trait，核心代码零修改。这是 Workspace + Trait 联合使用的典型收益。

---

## 关于 `utils.rs` / `helpers.rs` / `common.rs`

这类文件是坏味道，通常意味着行为没有归位到正确的类型上。

- `version_utils.rs` 里有 `parse_version` → 应该是 `impl FromStr for Version`
- `string_helpers.rs` 里有 `truncate_string` → 只有一两个调用点时，放进调用它的模块做私有函数；很多地方都要用，再做成扩展 trait（`trait StrExt { fn truncate_chars(&self, n: usize) -> &str; }`）。不能给 `str` 这种外部类型加 inherent 方法，扩展 trait 是唯一办法，按惯例放在 `ext.rs`
- `common.rs` 里什么都有 → 按职责拆分成独立模块

唯一合理的 `common` / `shared` crate：放**基础设施**（日志初始化、metrics、错误基类），而不是放各个业务 crate 的溢出物。
