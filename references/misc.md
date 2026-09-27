# 杂项规范

## 1. 穷尽性检查：自己的枚举不用 `_` 兜底

### 为什么重要

Rust `match` 的穷尽性检查是**免费的静态分析**。新增枚举变体时，编译器会在所有 `match` 处报错，强制你处理新情况。用 `_ => {}` 兜底，等于主动关掉这个保护。

### 反模式

```rust
// ❌ 用通配符兜底，新增 HardDeprecated 变体时没有任何警告
match status {
    Status::Active => do_thing(),
    Status::Deprecated => warn(),
    _ => {}  // 静默吞掉了所有未来的新变体
}

// ❌ unreachable! 也不行，它只是运行时 panic，不是编译时检查
match status {
    Status::Active => do_thing(),
    Status::Deprecated => warn(),
    _ => unreachable!(),  // 新增变体后：运行时 panic，不是编译报错
}
```

### 正确做法

```rust
// ✅ 穷尽所有变体，新增变体时编译器强制提醒
match status {
    Status::Active => do_thing(),
    Status::Deprecated => warn(),
    Status::HardDeprecated => error_and_refuse(),
    // 忘记加新变体？编译报错，不会悄悄出 bug
}
```

### 例外：这些情况用 `_` 是对的

- 外部 crate 标了 `#[non_exhaustive]` 的枚举（如 `std::io::ErrorKind`）：跨 crate 匹配时编译器强制要求 `_` 分支
- 匹配整数、字符串、元组组合等无法一一列举的值
- 只关心一个变体：用 `if let` / `let ... else` / `matches!`，不要写一串空分支
- 自己的枚举确实是"其余一律不处理"，并且能接受未来新增的变体也不处理：可以用 `_`，加一行注释说明原因

```rust
// ✅ 只关心一种事件
if let Event::Key(key) = event {
    handle_key(key);
}

// ✅ io::ErrorKind 是 #[non_exhaustive]，必须有兜底分支
let content = match fs::read_to_string(path) {
    Ok(s) => s,
    Err(e) => match e.kind() {
        io::ErrorKind::NotFound => String::new(),
        _ => return Err(e.into()),
    },
};
```

---

## 2. `_` 前缀与 `let _ =`：先查漏写，再注意 drop 时机

### 先查是不是漏写了逻辑

编译器报 `unused_variables`（这是 rustc 的 lint，不是 clippy 的）时，第一反应是**检查后续逻辑是否被漏写**，而不是加 `_` 前缀消警告。

```rust
// ❌ 编译器提示 user_status 未使用，于是改名为 _user_status，校验逻辑被悄悄吞掉
let _user_status = db.check_status(user_id).await?;

// ✅ 补全被遗漏的业务逻辑
let user_status = db.check_status(user_id).await?;
if user_status == UserStatus::Banned {
    return Err(Error::UserBanned);
}
```

**规则：** 只有当你能明确说出"这个值确实不需要被使用"时，才用 `_` 前缀。如果说不出来，那就是逻辑漏洞。

### `_name` 和 `let _ =` 的 drop 时机不同

- `let _name = expr;`：值绑定到变量，活到作用域结束才 drop
- `let _ = expr;`：不绑定，值在这条语句结束时立刻 drop

对 RAII 守卫（锁、tracing span、临时目录、计时器等），这个区别就是 bug：

```rust
// ✅ 锁只用来互斥，守卫本身不被读取，但必须活到临界区结束
let _guard = self.write_lock.lock().await;   // tokio::sync::Mutex
write_part_a().await?;
write_part_b().await?;

// ❌ 看起来像"未使用的变量"，改成 let _ = 之后锁立刻释放，两次写入不再互斥
let _ = self.write_lock.lock().await;

// ✅ span 在作用域内一直生效
let _enter = span.enter();

// ❌ span 立刻退出，后面的日志不在 span 里
let _ = span.enter();
```

std 的 `Mutex` / `RwLock` 写成 `let _ = m.lock();` 时 rustc 会直接报错（`let_underscore_lock`），parking_lot 的锁 clippy 会报（`clippy::let_underscore_lock`）；但 tokio 的锁、tracing span 和自定义守卫不会有任何提示。

所以：
- `_guard`、`_enter` 这类带 `_` 前缀的守卫是正确写法，**不要**为了"去掉未使用变量"把它改成 `let _ =`
- 用 `let _ = fallible();` 故意忽略一个 `Result` 时，加注释说明为什么可以忽略

---

## 3. 无效分配：能零拷贝就不分配

### 反模式

```rust
// ❌ 函数只读字符串，却要求传入已分配的 String
fn log_event(name: String) {  // 调用方被迫分配
    println!("[EVENT] {name}");
}

// ❌ 热路径里每次循环都为 key 分配一个新 String
let mut counts: HashMap<String, usize> = HashMap::new();
for item in &items {
    *counts.entry(item.category.to_string()).or_default() += 1;
}

// ❌ 函数只读 config，却要求拿走所有权
fn process(config: Config) {
    use_config(&config);
}
// 调用方：process(self.config.clone()); // 为了保留 config 而 clone
```

### 正确做法

```rust
// ✅ 借用切片，零分配
fn log_event(name: &str) { ... }
// 调用方可以传字面量、String 引用、任何字符串类型

// ✅ key 直接借用 item 里的字符串，零分配（只要 items 活得比 counts 久）
let mut counts: HashMap<&str, usize> = HashMap::new();
for item in &items {
    *counts.entry(item.category.as_str()).or_default() += 1;
}

// ✅ 只读就借用，不消耗
fn process(config: &Config) {
    use_config(config);
}

// ✅ Cow：能借用就借用，必须拥有时才分配
use std::borrow::Cow;
fn normalize(s: &str) -> Cow<'_, str> {
    if s.contains(' ') {
        Cow::Owned(s.replace(' ', "_"))  // 需要修改时才分配
    } else {
        Cow::Borrowed(s)                 // 不需要修改时零拷贝
    }
}
```

### 分配决策速查

| 场景 | 用什么 |
|---|---|
| 函数参数，只读字符串 | `&str` |
| 函数参数，只读切片 | `&[T]` |
| 函数参数，只读路径 | `&Path` 或 `impl AsRef<Path>` |
| 返回值可能需要也可能不需要分配 | `Cow<'_, str>` |
| 需要存储且生命周期不确定 | `String` / `Vec<T>`（拥有所有权） |
| 跨线程共享只读数据 | `Arc<str>` / `Arc<[T]>` |

---

## 4. 宏：最后的手段

消除重复的顺序：**函数 → 泛型 / trait → 现成的 derive 宏 → 自己写 `macro_rules!`**。宏会让报错信息晦涩、IDE 补全失效、调试变难，前面几种办不到时才用。

该用宏的信号：
- 重复的是**结构**而不是逻辑：要为一组类型/变体生成 impl、match 分支、常量表，函数和泛型表达不了
- 需要变参，或需要 `stringify!` / `concat!` 这类编译期能力
- 同一份映射（比如枚举 ↔ 字符串）要在多处保持同步，希望只有一个数据源

```rust
// ❌ 同一份映射散在三处，每加一个版本都要同时改三个地方
impl Display for Version { /* V1 => "1.0", V2 => "2.0", V3 => "3.0" */ }
impl FromStr for Version { /* "1.0" => V1, "2.0" => V2, "3.0" => V3 */ }
impl Version { fn cli_arg(self) -> &'static str { /* V1 => "v1", V2 => "v2", V3 => "v3" */ } }
```

先看现成的 derive 能不能覆盖，比如 `strum` 提供 Display / FromStr 等 derive（属性写法查 docs.rs 上对应版本，不要凭记忆写）。现成的不合适时，用 `macro_rules!` 把映射收拢到一处：

```rust
// ✅ 宏：在一个地方定义所有版本的全部映射
macro_rules! define_versions {
    ($($variant:ident => $str:literal, $cli:literal);* $(;)?) => {
        #[derive(Debug, Clone, Copy, PartialEq, Eq)]
        pub enum Version { $($variant),* }

        impl std::fmt::Display for Version {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str(match self { $(Self::$variant => $str),* })
            }
        }

        impl std::str::FromStr for Version {
            type Err = crate::Error;
            fn from_str(s: &str) -> Result<Self, Self::Err> {
                match s {
                    $($str => Ok(Self::$variant),)*
                    _ => Err(crate::Error::UnknownVersion(s.to_string())),
                }
            }
        }

        impl Version {
            pub fn cli_arg(self) -> &'static str {
                match self { $(Self::$variant => $cli),* }
            }
        }
    };
}

define_versions! {
    V1 => "1.0", "v1";
    V2 => "2.0", "v2";
    V3 => "3.0", "v3";
}
// 新增版本：只改这一处
```

### 过程宏 vs 声明宏

- **声明宏** (`macro_rules!`)：用于重复模式、语法扩展，在当前 crate 定义即可
- **过程宏** (`#[derive(...)]`, `#[proc_macro]`)：用于复杂的代码生成，需要独立 crate，优先用已有的（`serde`, `thiserror`, `derive_more`, `strum`）

### 不该用宏的场景

- 只是想少写几个参数 → 用配置结构体或默认值
- 只是想重用逻辑 → 用函数或 trait
- 重复只有两三处、以后也不太会变 → 保留重复，比引入宏更好读

---

## 5. 依赖管理：避免版本幻觉

### 反模式

```toml
# ❌ 凭记忆写版本
[dependencies]
tokio = "0.2"   # 早已是 1.x，API 完全不同
rand = "0.8"    # 记忆里的版本，而当前版本的 API 已经改了好几轮
```

```rust
// ❌ 按记忆写的 rand 0.8 API：在 rand 0.10 上编译不过
use rand::Rng;
let n = rand::thread_rng().gen_range(1..=6);

// ✅ rand 0.10 的写法：0.9 把函数改名为 rand::rng() / random_range()，
//    0.10 又删掉了 thread_rng，并把 random_range 移到了 RngExt trait
use rand::RngExt;
let n = rand::rng().random_range(1..=6);
```

同一个 crate 几个版本之间的 API 差异，只能靠查当前版本的文档和编译验证，不能靠记忆。

### 版本号怎么写

Cargo 的版本号默认是 caret 需求：`"1"`、`"1.0"`、`"1.0.100"` 都表示 `>= 该版本, < 2.0.0`，区别只在最低版本。`"1.0.100"` 不是精确锁定，精确锁定要写 `"=1.0.100"`，一般不需要。实际编译用的版本由 `Cargo.lock` 固定。

### 正确做法

- 新增依赖：用 `cargo add` 写入当前最新版本，不要手写版本号
  ```
  $ cargo add tokio --features full
  $ cargo add serde --features derive
  ```
- 已有项目：先看 `Cargo.toml` / `Cargo.lock` 里实际用的版本，按**那个**版本写代码，不要按记忆里的最新版写
- Workspace 里用 `[workspace.dependencies]` 统一管理版本，见 [project-structure.md](project-structure.md)
- 不确定 API → 查 `docs.rs/<crate>/<version>`，不要猜

### 对 AI 生成代码的警告

AI 的训练数据有时间截止，可能混用不同年份的 API：
- `tokio 0.x` 和 `tokio 1.x` 的 API 不兼容
- `actix-web 3.x` 和 `4.x` 有重大变化
- `hyper 1.x` 移除了 `hyper::Server` 等高层 API（挪到了 `hyper-util`）
- `rand 0.8` / `0.9` / `0.10` 的随机数 API 各不相同（见上）

**原则：写完代码后用 `cargo check` 验证所有外部 crate 的调用在当前使用的版本里确实存在。**
