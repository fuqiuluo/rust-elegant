# 所有权设计规范

## 核心原则

**借用检查器报错时，第一反应不是"怎么绕过去"，而是"我的数据流设计有问题吗？"**

`.clone()` 和 `Arc<Mutex<T>>` 是工具，不是万能胶。用来逃避借用检查器的 clone/锁会掩盖真正的设计问题，并在性能敏感路径上造成严重损耗。

---

## 反模式：借用报错就 clone

```rust
// ❌ 借用检查器报错 → 无脑 clone
fn process(data: &mut Vec<Item>) {
    let snapshot = data.clone();  // "先 clone 一份就好了"
    for item in &snapshot {
        if item.needs_update() {
            data.push(item.updated()); // 现在可以编译了，但复制了整个 Vec
        }
    }
}

// ✅ 重新设计：先收集需要新增的，再一次性修改
fn process(data: &mut Vec<Item>) {
    let updates: Vec<Item> = data.iter()
        .filter(|item| item.needs_update())
        .map(|item| item.updated())
        .collect();
    data.extend(updates);
}
```

---

## 反模式：`Arc<Mutex<T>>` 满天飞

```rust
// ❌ 每个字段都套 Arc<Mutex<>>：只读的 config、单个计数器也要抢锁
struct AppState {
    users:   Arc<Mutex<HashMap<UserId, User>>>,
    config:  Arc<Mutex<Config>>,
    counter: Arc<Mutex<u64>>,
}

// ✅ 整个 AppState 放进一个 Arc 共享，字段按访问模式选原语
struct AppState {
    users:   Mutex<HashMap<UserId, User>>,  // 共享可变 → 默认 Mutex
    config:  Config,                         // 启动后只读 → 不需要锁
    counter: AtomicU64,                      // 单值计数 → Atomic
}

let state = Arc::new(AppState { /* ... */ });
```

字段各自再套一层 `Arc` 只在它需要被单独拿出去共享时才有意义。

---

## 选择正确原语的决策树

```
数据需要跨线程共享？
  └─ 否 → 不需要 Arc：先考虑借用或调整所有权；确实需要多个所有者再用 Rc
  └─ 是 → 需要可变访问吗？
           └─ 否（只读） → Arc<T>，不需要任何锁
           └─ 是 → 什么访问模式？
                    ├─ 单一计数/标志 → Atomic*
                    ├─ 消息传递（生产者-消费者）→ channel (mpsc/broadcast)
                    ├─ 共享可变状态 → Mutex<T>（默认选择）
                    └─ 读远多于写、读临界区较长，且 profile 证明 Mutex 是瓶颈 → RwLock<T>
```

`RwLock` 不是 `Mutex` 的免费升级：它本身开销更大，读者/写者谁优先取决于平台（std 不保证），同样会死锁。没有测量数据时用 `Mutex`。

---

## 常见借用冲突的正确解法

### 问题一：持有集合元素的引用时修改集合

```rust
// ❌ 编译报错：active 引用在 push 之后还要用，而 push 可能重新分配、让引用悬垂
fn add_and_report(tasks: &mut Vec<Task>, new: Task) {
    let active = tasks.iter().find(|t| t.active);
    tasks.push(new);
    if let Some(t) = active {
        println!("active: {}", t.name);
    }
}

// ✅ 解法一：调整顺序，先用完引用再修改
fn add_and_report(tasks: &mut Vec<Task>, new: Task) {
    if let Some(t) = tasks.iter().find(|t| t.active) {
        println!("active: {}", t.name);
    }
    tasks.push(new);
}

// ✅ 解法二：顺序不能换时，记住索引而不是引用
fn add_and_report(tasks: &mut Vec<Task>, new: Task) {
    let active = tasks.iter().position(|t| t.active);
    tasks.push(new);
    if let Some(i) = active {
        println!("active: {}", tasks[i].name);
    }
}
```

冲突的本质是"引用在修改**之后**还要用"。只在修改前用到的引用不会报错，比如 `let first = &v[0]; v.push(first.clone());` 能编译（two-phase borrow）。

### 问题二：遍历字段时调用 `&mut self` 方法

```rust
struct Stats { samples: Vec<i32>, total: i64 }

impl Stats {
    fn add(&mut self, x: i32) {
        self.total += i64::from(x);
    }

    // ❌ 编译报错：self.add 要借用整个 self，而 self.samples 正被遍历
    fn recompute(&mut self) {
        for x in &self.samples {
            self.add(*x);
        }
    }
}
```

编译器能区分同一个结构体的不同字段：方法体里同时借用 `&self.samples` 和 `&mut self.total` 是允许的。报错是因为方法调用 `self.add()` 借用了**整个** `self`。

```rust
// ✅ 解法一：逻辑简单时直接操作字段
fn recompute(&mut self) {
    for x in &self.samples {
        self.total += i64::from(*x);
    }
}

// ✅ 解法二：逻辑复杂时，让辅助函数只接收它需要的字段
fn add_to(total: &mut i64, x: i32) {
    *total += i64::from(x);
}

fn recompute(&mut self) {
    for x in &self.samples {
        Self::add_to(&mut self.total, *x);
    }
}
```

字段多时可以先解构：`let Self { samples, total, .. } = self;`，之后分别使用。

### 问题三：同一个值被多个 `move` 闭包捕获

```rust
// ❌ 编译报错：data 已被移入 f1
let data = expensive_data();
let f1 = move || use_data(&data);
let f2 = move || use_data(&data);

// ✅ 闭包在当前作用域内调用 → 去掉 move，两个闭包共享借用
let data = expensive_data();
let f1 = || use_data(&data);
let f2 = || use_data(&data);

// ✅ 线程不需要活得比当前函数久 → scoped thread 直接借用
std::thread::scope(|s| {
    s.spawn(|| use_data(&data));
    s.spawn(|| use_data(&data));
});

// ✅ 闭包必须是 'static（如 thread::spawn、tokio::spawn）→ 才用 Arc
let data = Arc::new(expensive_data());
let h1 = thread::spawn({
    let data = Arc::clone(&data);
    move || use_data(&data)
});
let h2 = thread::spawn({
    let data = Arc::clone(&data);
    move || use_data(&data)
});
```

按这个顺序选：借用 → scoped thread → `Rc`（单线程多所有者）→ `Arc`。

---

## clone 是否合理的判断标准

- ✅ 合理：`Arc::clone(&x)` / `Rc::clone(&x)`，只增加引用计数，不复制数据
- ✅ 合理：小而便宜的值（短字符串、小结构体），且不在热路径上
- ✅ 合理：确实需要两份独立的数据，之后会各自修改或交给不同的所有者
- ❌ 不合理：大型集合（Vec、HashMap）在热路径上 clone
- ❌ 不合理：clone 的唯一目的是让借用检查器闭嘴，并没有真正需要两份数据
- ❌ 不合理：每次调用函数都 clone 一个 String，而函数其实只需要 `&str`

`Copy` 类型（`i32`、`bool` 等）直接按值传递，不需要写 `.clone()`。
