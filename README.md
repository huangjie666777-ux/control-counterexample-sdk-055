# Control Counterexample SDK

基于 Z3 的工业控制逻辑**有界检查（Bounded Model Checking）** SDK：在设备接入前，
用符号展开找出**联锁失效**（安全条件被违反）或**卡死**（非终止状态无任何合法后继）
的最短动作路径。仅依赖 Python 3.10 与 z3-solver 4.13.4，使用时不需要激活虚拟环境：

```bash
.venv/bin/python your_script.py
```

## 模型

- 命名布尔变量、有闭区间上下界的整数变量。
- 初态条件 `init`、终止条件 `terminal`、唯一命名动作 `Action(name, guard, assigns)`。
- 表达式是结构化 AST（不执行任何调用方代码）：
  - 变量/常量：`Var("x")`、`Const(1)`、`Const(True)`
  - 整数：`Add`、`Sub`、`Mul(k, e)`（仅允许常数乘法，保持线性）
  - 比较：`Cmp(op, l, r)`，`op` 为 `== != < <= > >=`
  - 布尔组合：`And(...)`、`Or(...)`、`Not(e)`
- 构造模型时即做引用、类型与结构校验，非法模型抛 `ModelError`。

## 语义

- 每步**恰选一个**当前可执行动作；不隐式添加等待。
- 守卫和所有赋值右值都读**旧状态**，随后**同时更新**；未赋值变量保持原值。
- 赋值使整数变量越界的动作**不可执行**（守卫为真且全部赋值在界内才可执行）。
- 多个动作可执行时，每一个都是可能分支。
- 所有满足 `init` 的合法状态都参与搜索。

## 公开接口

```python
from controlcheck import (
    Model, Action, Var, Const, Add, Sub, Mul, Cmp, And, Or, Not,
    check_safety, check_deadlock,
    COUNTEREXAMPLE, NO_COUNTEREXAMPLE_IN_BOUND, INIT_UNSAT, UNKNOWN,
    SAFETY_VIOLATED, DEADLOCK,
    verify_counterexample, replay_sequence,
    ModelError, ReplayError,
)

result = check_safety(model, bound=5, property=safe, timeout_ms=10_000)
# result.status 取值：
#   COUNTEREXAMPLE                  -> result.counterexample 为最短反例
#   NO_COUNTEREXAMPLE_IN_BOUND     -> 仅在该范围内成立，不宣称全局安全
#   INIT_UNSAT                      -> 初态无解（单独报告）
#   UNKNOWN                         -> 求解未知/超时，不等同于无反例

result = check_deadlock(model, bound=5, timeout_ms=10_000)  # 非终止且无合法后继
```

`Counterexample` 含：

- `states`：每一步的完整状态（含初态与末端失败状态）；
- `actions`：每步选择的动作名；
- `reason`：`safety_violated` 或 `deadlock`。

安全条件检查覆盖**包含初态在内**的每个可达状态，`bound` 为非负步数上限。

## 语义回放

`verify_counterexample(model, result, property)` 用独立的纯 Python 解释器重放反例，
逐步核对守卫、同时赋值、边界与末端失败原因，不匹配则抛 `ReplayError`。
`replay_sequence(model, state, action_names)` 可对任意动作序列做具体回放。

每次检查都新建独立 Z3 求解器，互不污染，且不改写调用方模型。

## 模块组织

- `src/controlcheck/expressions.py` — 结构化表达式 AST；
- `src/controlcheck/model.py` — 模型定义、引用/类型/结构校验；
- `src/controlcheck/encoder.py` — Z3 符号编码与单步转移展开；
- `src/controlcheck/checker.py` — 有界搜索、最短反例、结果状态；
- `src/controlcheck/replay.py` — 具体语义回放与反例核对。

## 双门联锁演示

```bash
PYTHONPATH=src .venv/bin/python examples/double_door.py
```

缺陷版控制器允许两门同时开，2 步内找到联锁失效路径；修正版给开门动作加上
“另一门已关闭”守卫后，在给定范围内无反例。

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```
