# 迭代器与 Option/Result 组合子

## 核心原则

**Rust 的 Iterator 不只是语法糖，编译器会对其做零开销抽象优化（常常等价于手写循环甚至更快）。能用迭代器清楚表达"从一个集合算出另一个值"时，就不要手写累加器。**

---

## Part 1：Iterator 链式调用

### 反模式：for 循环 + 可变累加器

```rust
// ❌ C 语言风格：mut 累加器 + for 循环
let mut result = Vec::new();
for user in &users {
    if user.is_active() {
        result.push(user.name.clone());
    }
}

// ❌ 更糟糕的：多个嵌套循环和累加器
let mut total = 0;
for dept in &departments {
    for emp in &dept.employees {
        if emp.salary > 100_000 {
            total += emp.salary;
        }
    }
}
```

### 正确做法

```rust
// ✅ 清晰表达意图，编译器优化更好
let result: Vec<&str> = users.iter()
    .filter(|u| u.is_active())
    .map(|u| u.name.as_str())
    .collect();

// ✅ 多层嵌套 → flat_map
let total: u64 = departments.iter()
    .flat_map(|dept| dept.employees.iter())
    .filter(|emp| emp.salary > 100_000)
    .map(|emp| emp.salary)
    .sum();
```

### 什么时候 for 循环更好

迭代器链不是越长越好。下面这些情况用 `for` 更清楚：

- 循环体里要 `.await`：迭代器适配器的闭包里不能 `.await`
- 循环体里要用 `?` 提前返回，而且不只是收集结果（只收集结果时用 `collect::<Result<Vec<_>, _>>()`，见 Part 3）
- 一次遍历要更新多个累加器，或者有复杂的 `break` / `continue`
- 循环的目的是副作用（打日志、写文件、发请求），不产出新值。这时 `for` 比 `.for_each()` 更直接
- 链条长到要在中间加注释才能看懂

### 常用 Iterator 方法速查

下表中 `f` / `pred` 代表闭包或函数，如 `.map(|x| x * 2)`、`.filter(|u| u.is_active())`。

| 目标 | 方法 |
|---|---|
| 转换每个元素 | `.map(f)` |
| 过滤元素 | `.filter(pred)` |
| 展开嵌套迭代器 | `.flat_map(f)` |
| 聚合为单个值 | `.fold(init, f)` |
| 求和 / 求积 | `.sum()` / `.product()` |
| 找第一个满足条件的 | `.find(pred)` → `Option<T>` |
| 判断是否存在 | `.any(pred)` / `.all(pred)` |
| 收集到集合 | `.collect::<Vec<_>>()` / `.collect::<HashMap<_, _>>()` |
| 带索引 | `.enumerate()` |
| 跳过/取前N个 | `.skip(n)` / `.take(n)` |
| 去重 | `.collect::<HashSet<_>>()`，或收集成 Vec 排序后调用 `Vec::dedup()` |
| 链接两个迭代器 | `.chain(other_iter)` |
| 压缩两个迭代器 | `.zip(other_iter)` |
| 转换并过滤（同时） | `.filter_map(f)` |

---

## Part 2：Option / Result 组合子

### 反模式：多层 match 嵌套（箭头型代码）

```rust
// ❌ 意图被嵌套淹没
fn get_user_city(user_id: u64) -> Option<String> {
    match find_user(user_id) {
        Some(user) => {
            match user.address {
                Some(addr) => {
                    match addr.city {
                        Some(city) => Some(city.to_uppercase()),
                        None => None,
                    }
                }
                None => None,
            }
        }
        None => None,
    }
}

// ❌ Result 版本同样丑陋，还用 as 静默截断了端口号
fn parse_config(s: &str) -> Result<Config, Error> {
    match s.parse::<toml::Table>() {
        Ok(t) => match t.get("port") {
            Some(p) => match p.as_integer() {
                Some(n) => Ok(Config { port: n as u16 }),  // 70000 会变成 4464
                None => Err(Error::InvalidPort),
            },
            None => Err(Error::MissingPort),
        },
        Err(e) => Err(Error::Parse(e)),
    }
}
```

### 正确做法：组合子链

```rust
// ✅ 意图一目了然
fn get_user_city(user_id: u64) -> Option<String> {
    find_user(user_id)
        .and_then(|user| user.address)
        .and_then(|addr| addr.city)
        .map(|city| city.to_uppercase())
}

// ✅ Result 版本：? 串联，数值收窄用 try_from
fn parse_config(s: &str) -> Result<Config, Error> {
    let table = s.parse::<toml::Table>().map_err(Error::Parse)?;
    let port = table.get("port")
        .ok_or(Error::MissingPort)?
        .as_integer()
        .ok_or(Error::InvalidPort)?;
    let port = u16::try_from(port).map_err(|_| Error::InvalidPort)?;
    Ok(Config { port })
}
```

### Option 组合子速查

| 目标 | 方法 |
|---|---|
| 转换内部值 | `.map(f)` |
| 链接可能返回 None 的操作 | `.and_then(f)` |
| None 时提供默认值 | `.unwrap_or(default)` |
| None 时惰性计算默认 | `.unwrap_or_else(f)` |
| None 时返回错误 | `.ok_or(err)` / `.ok_or_else(f)` |
| 过滤（不满足条件变 None） | `.filter(pred)` |
| 解包或 panic（仅限有理由时） | `.expect("说明为什么不会是 None")` |
| 两个 Option 取第一个 Some | `.or(other_option)` / `.or_else(f)` |

### Result 组合子速查

| 目标 | 方法 |
|---|---|
| 转换 Ok 值 | `.map(f)` |
| 转换 Err 值 | `.map_err(f)` |
| 链接可能失败的操作 | `.and_then(f)` |
| 提取值或默认 | `.unwrap_or(default)` |
| Err 时提供备选 Result | `.or_else(f)` |
| 添加错误上下文（anyhow） | `.context("doing xyz")` |

### `?` 操作符的本质

`?` 等价于：
```rust
// 这两段代码完全等价
let x = some_result?;

let x = match some_result {
    Ok(v) => v,
    Err(e) => return Err(From::from(e)),
};
```

只要实现了 `From<SourceErr> for TargetErr`（thiserror 的 `#[from]` 会自动生成），`?` 就能自动转换错误类型。

---

## Part 3：收集 Result 的惯用法

```rust
// 想把 Vec<Result<T, E>> 转成 Result<Vec<T>, E>
let results: Vec<Result<i32, _>> = strings.iter()
    .map(|s| s.parse::<i32>())
    .collect();

// ✅ 直接 collect 到 Result<Vec<T>, E>，遇到第一个 Err 就短路
let numbers: Result<Vec<i32>, _> = strings.iter()
    .map(|s| s.parse::<i32>())
    .collect();
```
