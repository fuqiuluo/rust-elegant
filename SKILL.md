---
name: rust-elegant
description: >
  Rust 优雅开发规范，必须在以下场景触发：为 Rust 项目写代码、review Rust 代码、设计 Rust 项目结构、处理 Rust 错误类型时。覆盖注释规范、枚举设计、trait 抽象、项目结构、错误处理、所有权、迭代器、宏、内存分配、match 穷尽性等所有 Rust惯用法。只要任务涉及写或修改 Rust 代码，必须读取此 skill。
---

# Rust 优雅开发规范

**核心原则：写出来的代码要让有经验的 Rust 工程师看了不难受。能跑不是标准，惯用、可维护、高性能才是标准。**

---

## 适用范围

- 这些规则作用于**本次新写或改动的代码**。已有代码优先遵循项目现有约定（错误类型、模块布局、命名、注释风格），不要在修 bug 或加功能时顺手重构周边代码。
- 在已有代码里发现下表的问题：在回复里指出，是否重构由用户决定。
- 规则是默认做法，不是教条。常见例外写在对应的 reference 里；偏离默认做法时，在注释或回复里说明理由。
- review 代码时，区分"会导致 bug"的问题和"风格建议"，不要把风格建议说成必须修改。

---

## 快速诊断：看到这些先停一下

| 看到这个 | 可能的问题 | 去读 |
|---|---|---|
| 主语是自定义类型的自由函数，如 `fn parse_version(s)`、`fn version_to_string(v)` | 行为没有归位到类型上 | [type-design.md](references/type-design.md) |
| `utils.rs` / `helpers.rs` 里堆着某个类型专属的函数 | 同上 | [project-structure.md](references/project-structure.md) |
| 调用处像 `f(url, 8, 30_000, 3, true)`，看不出每个值是什么 | C 式传参 | [type-design.md](references/type-design.md) |
| `fn foo(x: &String)` / `fn foo(x: &Vec<T>)` | 过度具体化 | [type-design.md](references/type-design.md) |
| 数值收窄用 `as`（如 `n as u16`） | 越界时静默截断 | [type-design.md](references/type-design.md) |
| 生产路径上的 `.unwrap()`；库的公共 API 返回 `Box<dyn Error>` | 错误处理走极端 | [error-handling.md](references/error-handling.md) |
| `Arc<Mutex<T>>` 满天飞，或借用报错就 `.clone()` | 所有权逃避 | [ownership.md](references/ownership.md) |
| 只为收集结果的 `for` + `push`（循环体里没有 `.await`、提前返回等） | 可以用迭代器表达 | [iterators.md](references/iterators.md) |
| `match opt { Some(x) => ..., None => ... }` 多层嵌套 | Option/Result 组合子盲区 | [iterators.md](references/iterators.md) |
| 对**本 crate 定义的**枚举用 `_ => {}` / `_ => unreachable!()` 兜底 | 放弃穷尽性检查 | [misc.md](references/misc.md) |
| 为了消 unused 警告给变量加 `_` 前缀 | 可能掩盖漏写的逻辑 | [misc.md](references/misc.md) |
| 锁、span 等守卫写成 `let _ = ...` | 守卫被立刻 drop | [misc.md](references/misc.md) |
| 不必要的 `.to_string()` / `.clone()` 在函数签名或热路径 | 无效分配 | [misc.md](references/misc.md) |
| 同一份映射（如枚举 ↔ 字符串）在多处手写 | 缺少单一数据源 | [misc.md](references/misc.md) |
| 单个 `main.rs` / `lib.rs` 上千行、没有模块划分 | 缺少模块拆分 | [project-structure.md](references/project-structure.md) |
| `///` 写废话，或 `// ====` 横幅注释 | 违反注释规范 | [comments.md](references/comments.md) |
| 凭记忆写 crate 版本号或 API | 依赖幻觉 | [misc.md](references/misc.md) |

---

## 写代码前的检查清单

在落笔前，依次问自己：

**1. 这个函数是某个类型的行为吗？**
- 是 → 写进 `impl T`，不要写成自由函数
- 不属于任何自定义类型的操作（如 `fs::read_to_string`）本来就该是自由函数

**2. 涉及转换？**
- `&str/String → T` → `impl FromStr for T`（支持 `.parse()`）
- `T → 显示字符串` → `impl Display for T`
- 无损转换 → `impl From<A> for B`
- 可能失败的转换 → `impl TryFrom<A> for B`；数值收窄用 `u16::try_from(x)`，不用 `as`

**3. 函数参数只需要某种"能力"，不需要具体类型？**
- → 定义 trait；参数用 `impl Trait` / 泛型（静态分发），需要存放不同实现时用 `&dyn Trait` / `Box<dyn Trait>`
- 只有一个实现、也不需要测试替身时，直接用具体类型

**4. 参数多到调用处看不懂（通常 5 个以上），或有多个 `bool` 参数？**
- → 必填参数保留为位置参数，可选项放进配置结构体 + 手写 `impl Default`；需要校验或保持 API 兼容时用 Builder
- 单个 `bool` 让调用处看不懂 → 换成两值枚举
- 一两个 `Option` 参数本身不是问题

**5. 参数是 `&String` 或 `&Vec<T>`？**
- → 改成 `&str` 或 `&[T]`
- 函数要**存储**参数时反过来，直接接收 `String` / `Vec<T>`

**6. 遇到借用检查器报错？**
- 先想：能不能调整语句顺序、改数据流或所有权结构？
- 不能再考虑：`Rc` / `Arc`（共享所有权）、`RefCell` / `Mutex`（内部可变性）
- 不要：还没想清楚数据流就 `.clone()` 或套 `Arc<Mutex<T>>`

**7. 错误处理：**
- 调用方需要按错误种类分别处理（典型是 library）→ `thiserror` 错误枚举
- 只需要上报/记录（典型是 bin）→ `anyhow` + `.context()`
- 生产路径不用裸 `.unwrap()`：能失败就 `?`，逻辑上不可能失败用 `.expect("为什么不可能")`；测试、example、doctest 里可以 unwrap
- 库的公共 API 不返回 `Box<dyn Error>`；`main`、example、doctest 里用它没问题

**8. match 一个枚举时：**
- 本 crate 定义的枚举：列出所有变体，不用 `_` 兜底，新增变体时编译器会指出所有要改的地方
- 外部 `#[non_exhaustive]` 枚举（如 `io::ErrorKind`）、整数、字符串：必须写 `_`
- 只关心一个变体 → `if let` / `let ... else` / `matches!`

**9. 有 unused variable 警告？**
- 先问：后续处理逻辑是不是漏写了？
- 确认不需要，再加 `_` 前缀
- `let _name = x` 活到作用域结束，`let _ = x` 立刻 drop。锁守卫、tracing span 等必须用 `_name`，不要改成 `let _ =`

**10. 要用外部 crate？**
- 新增依赖用 `cargo add <crate>`，不要凭记忆写版本号
- 已有项目按 `Cargo.toml` / `Cargo.lock` 里的版本写代码
- 不确定某个方法/宏是否存在 → 查 docs.rs 上对应版本的文档，不要猜

---

## 写完之后：用 cargo 验证

项目有自己的检查命令（CI 配置、Makefile、justfile、`cargo xtask`）时优先用项目的。否则依次跑：

```
cargo clippy --all-targets   # 包含 cargo check
cargo test
```

- 编译错误、测试失败必须修到通过
- 本次改动不能引入新的 clippy 警告；和本次改动无关的已有警告不去动
- 不要用 `#[allow(...)]` 压警告，除非能说出理由，并在旁边写注释
- 项目已经在用 rustfmt（CI 里有 `cargo fmt --check`，或者跑 `cargo fmt --check` 没有 diff）时，改完跑 `cargo fmt`；否则不要格式化整个项目，免得产生大量无关 diff
- 跑不了（没有工具链、依赖下载失败等）时，在回复里明确说明代码没有经过编译验证

很多规则 clippy 可以自动检查。`ptr_arg`（`&String` / `&Vec<T>` 参数）和 `too_many_arguments` 默认就开着。**新项目**可以在 `Cargo.toml` 里再开启下面这些（workspace 写在 `[workspace.lints.clippy]`，成员里写 `lints.workspace = true`）。已有项目不要擅自改 lint 配置。

```toml
[lints.clippy]
unwrap_used = "warn"                 # 生产路径的 unwrap；测试里放行见下方 clippy.toml
cast_possible_truncation = "warn"    # as 收窄可能截断
needless_pass_by_value = "warn"      # 只读参数却拿走所有权
fn_params_excessive_bools = "warn"   # 多个 bool 参数
undocumented_unsafe_blocks = "warn"  # unsafe 块缺 // SAFETY: 注释
missing_errors_doc = "warn"          # pub fn 返回 Result 却没写 # Errors
missing_panics_doc = "warn"          # pub fn 可能 panic 却没写 # Panics
```

```toml
# clippy.toml：测试里允许 unwrap
allow-unwrap-in-tests = true
```

---

## 详细规范

各专题详细说明和 before/after 示例在 `references/` 目录：

- **[comments.md](references/comments.md)** — 注释规范（Why/Safety/Contract，禁止废话和横幅）
- **[type-design.md](references/type-design.md)** — 枚举设计、trait 抽象、配置结构体与 Builder、Newtype、`&str` vs `&String`
- **[error-handling.md](references/error-handling.md)** — thiserror/anyhow 使用决策，`.unwrap()` / `.expect()` / `Box<dyn Error>` 的适用场景
- **[ownership.md](references/ownership.md)** — 所有权设计，避免无脑 clone/锁，常见借用冲突解法
- **[iterators.md](references/iterators.md)** — Iterator 链式调用、何时用 for 循环、Option/Result 组合子
- **[project-structure.md](references/project-structure.md)** — 模块与 Workspace 拆分，crate 边界设计
- **[misc.md](references/misc.md)** — 穷尽性检查、`_` 与 drop 时机、无效分配、宏、依赖管理
