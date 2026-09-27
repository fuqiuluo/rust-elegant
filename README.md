# rust-elegant

让 Claude Code 和 Codex 写出地道 Rust 代码的 Agent Skill。

AI 写 Rust 常见的毛病：`&String` 当参数、到处 `.unwrap()`、借用报错就 `.clone()`、`Arc<Mutex<T>>` 满天飞、`_ => {}` 吞掉枚举变体、凭记忆写出早已改名的 crate API……这些代码能跑，但有经验的 Rust 工程师一看就难受。rust-elegant 在 agent 写、改、review Rust 代码时自动加载，给它一套具体的规范、反模式诊断表和 before/after 示例。

## 覆盖内容

| 主题 | 内容 |
|---|---|
| [类型设计](references/type-design.md) | 行为归位到 `impl`、`FromStr`/`Display`/`TryFrom` 等标准 trait、trait 抽象、配置结构体与 Builder、Newtype、`&str`/`&[T]` 参数 |
| [错误处理](references/error-handling.md) | thiserror 与 anyhow 的选择、`.unwrap()`/`.expect()`/`Box<dyn Error>` 的适用场景、`LazyLock` |
| [所有权](references/ownership.md) | 常见借用冲突的正确解法、锁与原子类型的选择、什么时候 clone 是合理的 |
| [迭代器](references/iterators.md) | 迭代器链与 Option/Result 组合子，以及什么时候 `for` 循环更好 |
| [项目结构](references/project-structure.md) | 先模块后 Workspace、扁平 `crates/` 布局、crate 依赖方向 |
| [注释](references/comments.md) | Rustdoc 惯例（`# Errors`/`# Panics`/`# Safety`）、`// SAFETY:` 注释、不写废话和横幅 |
| [杂项](references/misc.md) | match 穷尽性、`_name` 与 `let _ =` 的 drop 时机、避免无效分配、宏的使用时机、依赖版本幻觉 |

## 设计原则

- **默认做法 + 例外，不是教条。** 每条规则都写明了例外情况，比如外部 `#[non_exhaustive]` 枚举必须写 `_`、`main` 里用 `Box<dyn Error>` 没问题，避免 agent 机械套用规则。
- **只管本次改动的代码。** 已有代码遵循项目现有约定，发现问题只指出，不顺手重构。
- **写完用 cargo 验证。** 要求 agent 改完跑 `cargo clippy` 和 `cargo test`，并给出对应的 clippy lint 配置。
- **示例经过编译核对。** reference 里的关键示例用 stable rustc 编译验证过，标着"❌ 编译报错"的例子确认会报错；用 `{ ... }` 省略实现的片段是示意代码。

## 安装

需要 Python 3.8+，只用标准库，支持 Linux、macOS 和 Windows。

### 一键安装

不需要 clone，脚本会自己从 GitHub 下载 skill 文件。

macOS / Linux：

```sh
curl -fsSL https://raw.githubusercontent.com/fuqiuluo/rust-elegant/main/install.py | python3 -
```

Windows（PowerShell）：

```powershell
irm https://raw.githubusercontent.com/fuqiuluo/rust-elegant/main/install.py | python -
```

默认会自动检测本机装了 Claude Code 还是 Codex，给检测到的工具安装；两个都没检测到时两个都装。要传参数，写在最后的 `-` 后面，例如只给 Codex 安装：

```sh
curl -fsSL https://raw.githubusercontent.com/fuqiuluo/rust-elegant/main/install.py | python3 - --target codex
```

### 从源码安装

```sh
git clone https://github.com/fuqiuluo/rust-elegant.git
cd rust-elegant
python3 install.py            # Windows 上用 py install.py 或 python install.py
```

加上 `--link` 会创建指向 clone 目录的符号链接，之后 `git pull` 就能更新 skill。Windows 没开启开发者模式时无法创建符号链接，脚本会自动改为复制。

### 参数

| 参数 | 说明 |
|---|---|
| `--target auto\|claude\|codex\|all` | 给哪个工具安装，默认 `auto`（自动检测） |
| `--project [DIR]` | 安装到项目目录（默认当前目录），而不是用户目录 |
| `--link` | 用符号链接代替复制（需要从 clone 运行） |
| `--uninstall` | 卸载 |
| `--force` | 目标位置已有同名但不是本 skill 的目录时，强制覆盖 |
| `--ref REF` | 一键安装时下载的分支或 tag，默认 `main` |
| `--dry-run` | 只打印将要执行的操作 |

### 安装位置

| 工具 | 用户级（默认） | 项目级（`--project`） |
|---|---|---|
| Claude Code | `~/.claude/skills/rust-elegant` | `<项目>/.claude/skills/rust-elegant` |
| Codex | `$CODEX_HOME/skills/rust-elegant`（默认 `~/.codex/skills`） | `<项目>/.agents/skills/rust-elegant` |

Windows 上 `~` 指 `%USERPROFILE%`。项目级安装可以提交到仓库，团队成员 clone 后就能用。

Codex 也会读取 `~/.agents/skills`。如果那里已经有一份 rust-elegant，安装脚本会提示你删掉，避免加载两份。

### 手动安装

把 `SKILL.md` 和 `references/` 复制到上表中的目录即可：

```sh
mkdir -p ~/.claude/skills/rust-elegant
cp -r SKILL.md references ~/.claude/skills/rust-elegant/
```

### 更新与卸载

- 更新：重新运行一遍安装命令，会覆盖旧版本。用 `--link` 安装的，在 clone 目录里 `git pull` 即可。
- 卸载：`python3 install.py --uninstall`，或直接删除安装目录。

## 使用

安装后新开一个会话即可生效。写、改、review Rust 代码时 agent 会自动加载这个 skill，也可以手动调用：

- Claude Code：输入 `/rust-elegant`
- Codex：输入 `$rust-elegant`，或用 `/skills` 选择

## 目录结构

```
rust-elegant/
├── SKILL.md            # 入口：适用范围、诊断表、检查清单、cargo 验证流程
├── references/         # 各专题的详细规范和 before/after 示例
│   ├── comments.md
│   ├── error-handling.md
│   ├── iterators.md
│   ├── misc.md
│   ├── ownership.md
│   ├── project-structure.md
│   └── type-design.md
└── install.py          # 一键安装脚本
```
