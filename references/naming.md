# 命名规范

遵循标准库和 [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/naming.html) 的命名惯例。调用方看到方法名，就应该能猜出它有没有开销、会不会消耗 `self`、返回的是借用还是新值。

类型、函数、变量的大小写（`UpperCamelCase` / `snake_case` / `SCREAMING_SNAKE_CASE`）由 rustc 的 lint 检查，这里不重复。

---

## 1. 转换方法：`as_` / `to_` / `into_`

| 前缀 | 开销 | `self` 形式 | 例子 |
|---|---|---|---|
| `as_` | 没有开销，借用转借用 | `&self` / `&mut self` | `str::as_bytes`、`String::as_str` |
| `to_` | 有开销（分配、计算） | `&self`；`Copy` 类型可以用 `self` | `str::to_lowercase`、`Path::to_path_buf` |
| `into_` | 消耗 `self` | `self` | `String::into_bytes`、`PathBuf::into_os_string` |

```rust
// ❌ 叫 into_ 却只借用 self；叫 as_ 却分配了新 String
fn into_json(&self) -> String
fn as_string(&self) -> String

// ✅
fn to_json(&self) -> String
fn into_inner(self) -> T
fn as_str(&self) -> &str
```

clippy 的 `wrong_self_convention` 默认开启，会检查前缀和 `self` 形式是否对应。

能用标准 trait 表达的转换（`From`、`TryFrom`、`FromStr`、`Display`、`AsRef`）优先实现 trait，见 [type-design.md](type-design.md)。

---

## 2. Getter 和 setter

| 用途 | 命名 | 签名 |
|---|---|---|
| 读字段 | `name()`，不加 `get_` | `fn name(&self) -> &str` |
| 可变借用字段 | `name_mut()` | `fn name_mut(&mut self) -> &mut Name` |
| 设置字段 | `set_name()` | `fn set_name(&mut self, name: String)` |
| 取走值，原处留下 `None` 或默认值 | `take_name()` | `fn take_name(&mut self) -> Option<Name>` |
| 设置新值并返回旧值 | `replace_name()` | `fn replace_name(&mut self, name: Name) -> Name` |

```rust
// ❌ Java 风格
fn get_name(&self) -> &str
fn get_items_mut(&mut self) -> &mut Vec<Item>

// ✅
fn name(&self) -> &str
fn items_mut(&mut self) -> &mut Vec<Item>
```

`get` 只在有"按 key / 下标查找"语义时用，如 `HashMap::get(&k)`、`slice::get(i)`，或者类型里只有一个值可取，如 `Cell::get()`。

布尔查询用 `is_` / `has_` / `can_` 开头：`is_empty()`、`has_children()`。

---

## 3. 构造函数

| 用途 | 命名 | 例子 |
|---|---|---|
| 主构造函数 | `new()` | `Vec::new()` |
| 带额外参数的其他构造方式 | `with_xxx()` | `Vec::with_capacity(n)`、`Client::with_config(cfg)` |
| 从某种来源构造，又不是单纯的 `From` 转换（可能失败、要多个参数） | `from_xxx()` | `String::from_utf8(bytes)`、`Config::from_env()` |
| 参数多、需要校验 | `Foo::builder()` 返回 `FooBuilder`，最后 `.build()` | 见 [type-design.md](type-design.md) |

可能失败的主构造函数照样叫 `new`，返回 `Result<Self, E>`（如 `Regex::new`）。同一操作既有不会失败的版本、又有可能失败的版本时，后者加 `try_` 前缀，如 `Vec::reserve` 和 `Vec::try_reserve`。

---

## 4. 迭代器

| 返回 | 命名 |
|---|---|
| `Iterator<Item = &T>` | `iter()` |
| `Iterator<Item = &mut T>` | `iter_mut()` |
| `Iterator<Item = T>`，消耗集合 | 实现 `IntoIterator`，不要另写一个叫 `into_iter` 的普通方法 |

- 返回的迭代器类型和方法同名：`iter()` 返回 `Iter`，`iter_mut()` 返回 `IterMut`，`into_iter()` 返回 `IntoIter`
- 集合有多种遍历方式时用描述性名字：`str::chars()`、`str::lines()`、`HashMap::keys()`、`HashMap::values_mut()`
- 同时给 `&Collection` 和 `&mut Collection` 实现 `IntoIterator`，调用方才能写 `for x in &coll`
