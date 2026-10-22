# 类型设计规范

## 1. 枚举行为归位

### 反模式
```rust
// ❌ 行为流放到 utils.rs
pub fn parse_version(v: &str) -> Result<Version, Error> { ... }
pub fn version_to_string(v: Version) -> &'static str { ... }
pub fn require_selectable(v: Version) -> Result<(), Error> { ... }
```

### 正确做法：标准 trait + impl 块

```rust
// ✅ 行为全部归位到类型上
impl std::fmt::Display for Version {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::V1 => "1.0",
            Self::V2 => "2.0",
        })
    }
}

impl std::str::FromStr for Version {
    type Err = Error;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "1.0" => Ok(Self::V1),
            "2.0" => Ok(Self::V2),
            _ => Err(Error::UnknownVersion(s.to_string())),
        }
    }
}

impl Version {
    pub const LATEST: Self = Self::V2;

    pub fn require_selectable(self) -> Result<(), Error> {
        match self.status() {
            Status::Active => Ok(()),
            Status::Deprecated => Err(Error::Deprecated(self)),
        }
    }
}
```

**调用方对比：**
```rust
// ❌ 之前
let v = parse_version(s)?;
require_selectable(v)?;
let s = version_to_string(v);

// ✅ 之后
let v: Version = s.parse()?;   // FromStr，标准 .parse()
v.require_selectable()?;        // 方法在类型上
let s = v.to_string();          // Display，免费获得
```

不是所有自由函数都是坏味道。不属于任何一个类型的操作本来就该是自由函数，如 `std::fs::read_to_string`、`serde_json::from_str`。判断标准：这个函数的主语是不是某个你自己定义的类型。

### 转换类型选择速查

| 场景 | 用哪个 trait |
|---|---|
| `&str / String → T`，可失败 | `impl FromStr for T`（启用 `.parse()`） |
| `OtherType → T`，可失败 | `impl TryFrom<OtherType> for T` |
| `OtherType → T`，无损 | `impl From<OtherType> for T`（`Into` 自动获得） |
| 数值收窄（如 `i64 → u16`） | `u16::try_from(x)`；不要用 `as`，越界时会静默截断 |
| `T → 显示字符串` | `impl Display for T`（`.to_string()` 自动获得） |
| 判等 / 用作 HashMap key | `#[derive(PartialEq, Eq, Hash)]` |
| 排序 | `#[derive(PartialOrd, Ord)]`（或手动实现并注释排序语义） |
| 默认值 | 字段的零值就是合理默认时 `#[derive(Default)]`，否则手写 `impl Default` |

### 常用 trait 的实现建议

- 能 `#[derive]` 就不手写。必须手写时（比如 `PartialEq` 只比较 `id`），在 impl 上注释说明语义
- 库的公共类型主动实现常用 trait：至少 `Debug`，语义允许时再加 `Clone`、`PartialEq` / `Eq`、`Hash`、`Default`。下游 crate 没法给你的类型补这些 impl（孤儿规则）。应用内部的类型用到时再加
- 有无参的 `new()` 就同时实现 `Default`（clippy `new_without_default`），可以直接 `fn new() -> Self { Self::default() }`
- 有 `len()` 就提供 `is_empty()`（clippy `len_without_is_empty`）
- 运算符重载（`Add`、`Mul`、`Index`…）只用于数学或逻辑上说得通的语义，不要当语法糖：给路径拼接实现 `Add` 让人写 `base + "file.txt"` 是反例，用 `join` 方法

---

## 2. Trait 抽象替代 C 式传参

### 反模式
```rust
// ❌ 写死具体实现，无法测试，无法替换
pub fn send_alert(
    smtp_host: &str,
    smtp_port: u16,
    recipient: String,
    subject: String,
    body: String,
) -> Result<(), Error> { ... }
```

### 修法一：对"能力"抽象

```rust
// ✅ 抽象出能力，而不是具体实现
pub trait Notifier: Send + Sync {
    fn notify(&self, recipient: &str, subject: &str, body: &str) -> Result<(), Error>;
}

pub struct SmtpNotifier { host: String, port: u16 }
impl Notifier for SmtpNotifier { ... }

pub struct StubNotifier(std::sync::Mutex<Vec<String>>); // 测试用
impl Notifier for StubNotifier { ... }

// 调用方只依赖 trait，随时可换实现
pub fn alert(notifier: &dyn Notifier, recipient: &str) -> Result<(), Error> {
    notifier.notify(recipient, "Alert", "Something happened")
}
```

参数写法的选择：
- `impl Notifier` / 泛型 `<N: Notifier>`：静态分发，零开销，但每种实现单独生成一份代码
- `&dyn Notifier` / `Box<dyn Notifier>`：动态分发，能把不同实现放进同一个集合或结构体字段

只有一个实现、也不需要测试替身时，直接用具体类型。等第二个实现真的出现（测试替身也算）再抽 trait。

### 修法二：参数多或有 bool 参数 → 配置结构体

经验阈值：参数多到调用处看不出每个值是什么（通常 5 个以上；clippy 的 `too_many_arguments` 默认 7 个才报），或者有多个 `bool` 参数。一两个 `Option` 参数本身不是问题。

```rust
// ❌ 调用处全是裸值：create_pipeline(url, 8, 30_000, 3, true)
fn create_pipeline(url: &str, workers: usize, timeout_ms: u64, retry: u32, cache: bool) -> Pipeline

// ✅ 必填参数保留为位置参数，可选项放进带默认值的配置结构体
pub struct PipelineOptions {
    pub workers: usize,
    pub timeout: Duration,
    pub retry: u32,
    pub cache: bool,
}

// 默认值有业务含义，要手写；#[derive(Default)] 只会给 0 / Duration::ZERO / false
impl Default for PipelineOptions {
    fn default() -> Self {
        Self {
            workers: std::thread::available_parallelism().map_or(1, |n| n.get()),
            timeout: Duration::from_secs(30),
            retry: 3,
            cache: false,
        }
    }
}

impl Pipeline {
    pub fn connect(db_url: &str, opts: PipelineOptions) -> Result<Self, Error> { ... }
}

// 调用方只写和默认值不同的字段
let pipeline = Pipeline::connect(&db_url, PipelineOptions {
    workers: 8,
    ..Default::default()
})?;
```

上面是"配置结构体 + struct update 语法"，不是 Builder 模式。字段需要校验、或者库以后要加字段而不想破坏兼容性时，用真正的 Builder（`Pipeline::builder(url).workers(8).build()?`）。公共结构体加了 `#[non_exhaustive]` 后，外部 crate 不能再用结构体字面量构造，只能走 Builder 或构造函数。

单个 `bool` 参数让调用处成了谜语时，换成两值枚举：

```rust
// ❌ render(&doc, true)   —— true 是什么？
// ✅ render(&doc, Quality::Draft)
pub enum Quality { Draft, Final }
```

### 修法三：Newtype 携带语义

```rust
// ❌ 两个同类型参数，传反了编译器也发现不了
fn connect(host: &str, port: u16, timeout_ms: u16) -> ...

// ✅ 用类型区分：端口用 newtype，时长直接用 Duration（本身就带单位）
pub struct Port(u16);

impl Port {
    pub fn new(n: u16) -> Result<Self, Error> {
        (n != 0).then_some(Self(n)).ok_or(Error::InvalidPort)
    }
}

fn connect(host: &str, port: Port, timeout: Duration) -> ...
```

---

## 3. 参数与返回值类型：`&str` 和 `&[T]` 而不是 `&String` 和 `&Vec<T>`

### 反模式
```rust
// ❌ Rust 新手标志：&String 极大限制复用性
fn process(text: &String, items: &Vec<i32>) -> ...

// 调用方被迫：
process(&"hello".to_string(), &vec![1, 2, 3]); // 无意义的堆分配
```

### 正确做法
```rust
// ✅ 利用 Deref 强制转换，接受任何字符串/切片
fn process(text: &str, items: &[i32]) -> ...

// 调用方可以传：
process("hello", &[1, 2, 3]);           // 字面量，零分配
process(&owned_string, &owned_vec);      // String / Vec
process(&arc_str, &boxed_slice);         // Arc<str> / Box<[i32]> 也能通过 Deref 传入
```

### 函数参数类型速查

前提是函数**只读、不存储**这个参数：

| 场景 | 不要写 | 改写成 |
|---|---|---|
| 只读字符串 | `&String` | `&str` |
| 只读序列 | `&Vec<T>` | `&[T]` |
| 只读 Box 里的值 | `&Box<T>` | `&T` |
| 只读可能不存在的值 | `&Option<T>` | `Option<&T>`（调用方传 `opt.as_ref()`） |
| 只读字符串，调用方手里可能是 `String` 也可能是 `&str` | `String` | `&str` 或 `impl AsRef<str>` |
| 只遍历一次 | `Vec<T>` | 库的公共 API：`impl IntoIterator<Item = T>`；应用代码用 `&[T]` 更简单就直接用 |
| 只读路径 | `&PathBuf` / `PathBuf` | `&Path` 或 `impl AsRef<Path>` |
| 当场调用、不保存的回调 | `Box<dyn Fn(...)>` | `impl Fn(...)` |

函数要把参数**存起来**时反过来：直接接收拥有所有权的类型（`String`、`Vec<T>`、`PathBuf`、`Box<dyn Fn(...)>`）。接收 `&str` 再在函数里 `.to_string()` 只是把分配藏了起来。

`impl Into<String>` 能让调用方直接传字面量，但它是泛型：签名更复杂，每种实参类型各生成一份代码，有时还会让调用处的类型推断失败。只在库的公共 API、且调用方便利性很重要时用（比如 builder 的 setter）；应用代码直接接收 `String`，让调用方自己写 `.to_string()`。

### 返回值：迭代器还是 `Vec`

库的公共 API 只是让调用方遍历结果时，返回 `impl Iterator`，由调用方决定 collect、计数还是只取前几个：

```rust
impl Inventory {
    // ✅ 调用方可以 .count()、.take(10)，需要时再 collect，不会被迫分配
    pub fn low_stock(&self, threshold: u32) -> impl Iterator<Item = &Item> {
        self.items.iter().filter(move |item| item.qty < threshold)
    }
}
```

这些情况返回 `Vec<T>` 更合适：大多数调用方本来就要 `Vec`；实现里本来就构造了 `Vec`；结果需要随机访问；函数的目的就是构建一个新集合。返回已有的 `Vec` 字段时返回 `&[T]`。应用代码返回 `Vec<T>` 更简单就直接返回。

---

## 4. 具名字段优先于元组

```rust
// ❌ 调用方只能靠 .0 / .1 / .2 猜含义，两个 u32 顺序弄反了编译器也发现不了
fn bounds(&self) -> (u32, u32, bool)
pub struct Span(usize, usize);

// ✅ 字段名就是文档
pub struct Bounds {
    pub min: u32,
    pub max: u32,
    pub inclusive: bool,
}
fn bounds(&self) -> Bounds

pub struct Span {
    pub start: usize,
    pub end: usize,
}
```

例外：
- 单字段的 newtype（`struct Port(u16)`）
- 非常局部、一眼能看懂的场景：私有辅助函数返回 `(key, value)`、`.enumerate()` / `.zip()` 产出的元组当场解构

---

## 5. 库的公共 API：给以后的修改留余地

只针对会被其他 crate 依赖的公共 API。应用内部的类型随时可以改，不需要这些。

- **以后可能加变体的公共 enum 加 `#[non_exhaustive]`**，加变体时不会破坏下游，错误枚举是典型。例外：描述固定集合的枚举（`Color { Red, Green, Blue }`）和两值枚举（`Visibility { Visible, Hidden }`）。
- **字段全是 `pub` 的公共 struct**：加任何字段（哪怕是私有字段）都会让下游的结构体字面量编译失败。以后可能加字段的就加 `#[non_exhaustive]`，外部只能通过构造函数或 Builder 创建。例外：字段固定的类型（`Point { x, y }`），以及要让调用方写 `..Default::default()` 的配置结构体（`#[non_exhaustive]` 会禁止外部 crate 用这个语法）。
- **`pub const fn` 是兼容性承诺**：以后去掉 `const` 是破坏性变更。只在确定以后的实现也能保持 const 时才加。

`#[non_exhaustive]` 只限制其他 crate；本 crate 内 match 自己的枚举仍然可以、也应该列出所有变体（见 [misc.md](misc.md)）。
