# PythonPDFLayoutSystem 技术文档

> 本文档由代码实读整理，对应工作区当前状态（`master` 上 `f2556a2` **之后的未提交工作树**）。
> 所有函数签名、参数、返回值均取自实际代码；标为"实测"的结论均附可复现的观测数据。
>
> **已完成批次**：基础设施（`.gitignore` + 字体说明 + `.pyproj` 入口）、
> 批次 0（修 7.1 / 7.15 / 7.17 / 7.18）、批次 1（抽 `create_spacer`，8.2）、
> 批次 2（抽 `create_band`，修 7.3 / 7.4，8.1）、
> 批次 3（`Style` 下沉 + `from_style` + `create_text_block`，8.3 / 8.4）、
> **批次 4 全部完成**：4.1 四轴枚举 · 4.2 两趟遍历（修 7.19 / 7.20）·
> 4.3 几何属性 property 化（8.5）· 4b 内容固有宽度（修 7.21）·
> 4.4 删 `wrap_*` 兼容面（修 7.6 / 7.10 的引擎侧）。
> **批次 5 已完成**：真实文本测量（修 7.7）· 分段样式（`TextRun` + `measure_text`）·
> Markdown 内联语法 · P1 时序。批次 6（分页）暂缓。
>
> ⚠️ **中层与顶层文件不在 `master` 上**（`ResumeTemplate.py` / `ResumeCore.py` 属功能分支）。
> 因此有一部分改动**无法在 `master` 完成**，集中记录在 `SKILLS.md` 的
> 「只在功能分支处理的事项」一节。

---

## 0. 阅读顺序建议

| 想做什么 | 先读 |
| --- | --- |
| 了解整体分层与数据流 | 第 1、2 章 |
| 调用引擎/模板写代码 | 第 3、4 章 |
| 动引擎内部几何逻辑 | 第 3.2 ~ 3.5 节 |
| 判断重构该动哪里 | 第 7 章（已知缺陷）、第 8 章（重构方向） |
| 跑测试 | 第 9 章 |
| **调版面参数 / 查"某处不对该拧哪里"** | **第 11 章（中层调参手册）** |

---

## 1. 当前项目状态（重构前先确认）

### 1.1 Git

```
分支：master（唯一分支，跟踪 origin/master）
远端：https://github.com/Rimuru40965535/PythonPDFLayoutSystem.git
提交：仅 3 个
  d5552dc 第一次提交
  5244616 添加项目文件。
  e924897 添加 .gitattributes、.gitignore、README.md 和 LICENSE.txt
标签：无
```

工作树未提交内容：

```
 D PythonPDFLayoutSystem.py     ← 已删除（旧入口）
 M README.md
 M main.py
?? LayoutEngine.py              ← 未跟踪
?? ResumeTemplate.py            ← 未跟踪
?? ResumeCore.py                ← 未跟踪
?? SKILLS.md                    ← 未跟踪
?? Resources/                   ← 未跟踪
?? resume_template_v2_test.pdf  ← 未跟踪（生成物）
?? test_layout_engine_cached.pdf← 未跟踪（生成物）
```

### 1.2 可运行性实测

| 入口 | 结果 |
| --- | --- |
| `py LayoutEngine.py` | ✅ 退出码 0，生成 `test_layout_engine_cached.pdf` |
| `py ResumeTemplate.py` | ✅ 退出码 0，生成 `resume_template_v2_test.pdf` |
| `py ResumeCore.py` | ✅ 退出码 0，生成 `output/{姓名}_{职位}_{公司}.pdf` |

> 上面是**当前工作树**的实测结果。三个入口此前均不可用：
> `ResumeCore.py` 曾因 `from ResumeTemplateV2 import ...` 直接抛 `ModuleNotFoundError`
> （导入断裂，批次 0 修复，详见 7.1）。
>
> 两个测试 PDF 与 `output/` **已被 `.gitignore` 忽略**（`*.pdf` 与 `output/` 规则）——
> 它们随代码变化且可由测试入口复现，不入库。

### 1.3 解释器与依赖

```
Python 3.14 (C:\Users\28375\AppData\Local\Python\pythoncore-3.14-64\python.exe)
fpdf2 2.8.8          ← 已安装，可用
```

注意：DSH 自带运行时（3.12）**没有** fpdf2，跑测试必须用 `py`。

### 1.4 资源缺口

`Resources/` 实际只有 6 个字体文件（`LXGWWenKai*.ttf`）。

> **字体不入库**（基础设施批次起）：`.gitignore` 已加入 `Resources/*.ttf`。
> 字体约 117 MB，属本地资源；获取方式写在 README 的「资源获取」一节
> （霞鹜文楷 LXGW WenKai，SIL OFL 1.1，可免费商用）。
> **缺少字体会导致中文渲染为空白且不报错** —— 引擎静默降级到内置 helvetica。
> 只忽略 `*.ttf`，未来补充的图标/照片仍应正常入库。

但代码引用了以下**并不存在**的图片：

```
.\Resources\icon.png                          (ResumeTemplate.py:1383)
.\Resources\icon_Education_History.png        (ResumeTemplate.py:1402, ResumeCore.py:1168)
.\Resources\icon_Project_History.png          (ResumeTemplate.py:1465, ResumeCore.py:1196)
.\Resources\woman_student.png                 (ResumeCore.py:553)
.\Resources\photo_1.png                       (ResumeCore.py:1144)
.\Resources\telephone.png / email.png / locate.png
.\Resources\social_media.png / contact_address.png / website.png  (ResumeCore.py:578-603)
```

图片缺失时引擎静默降级（`calculate_image_size` 返回 `(0.0, 0.0)`，`render` 回退为拉伸填满），
所以 PDF 仍能生成，但看不到图标。**这是当前样张与预期效果不一致的主因之一**，排查视觉问题前先确认这一点。

### 1.5 历史遗留（已清理）

`Module_PythonPDFLayoutSystem/__pycache__/` 里曾留有 3.14 的 `.pyc`：

```
Colors、LayoutObject、Utils、PaddingsAligns、LayoutEngineV2、LayoutEngine、ResumeCore
```

说明引擎曾按 `Colors / LayoutObject / Utils / PaddingsAligns` 拆分，后来合并进单文件 `LayoutEngine.py`。
这些 `.pyc` 已无源码、**不被任何模块导入**（全库 grep 无引用），属于死文件。

**已于批次 0 删除整个 `Module_PythonPDFLayoutSystem/` 目录。**
（该目录被 `.gitignore` 的 `__pycache__/` 与 `*.pyc` 规则忽略，删除不影响版本库内容。）

---

## 2. 架构概览

### 2.1 分层（对应 `SKILLS.md` 的定义）

```
┌─ 顶层：面向使用者与开发人员 ────────────────────────────────┐
│  ResumeCore.py     Profiles / SkillsAwards / Details /      │
│                    Section / Resume                         │
│                    → 领域数据模型 + 数据到 PDF 的流程编排    │
└─────────────────────────────────────────────────────────────┘
                            ↓ 依赖
┌─ 中层：调用与便捷封装（feature_resume_sub_templates）────────┐
│  ResumeTemplate.py STYLES / 结果句柄 / add_* 子模板方法      │
│                    → 简历版式词汇：姓名、节标题、节详情      │
│                    → 挂在 LayoutObject 上，调用形如          │
│                      node.add_details(...) -> DetailsHandle  │
└─────────────────────────────────────────────────────────────┘
                            ↓ 依赖
┌─ 底层：基本构件（master）────────────────────────────────────┐
│  AlignX / AlignY / SizeX / SizeY / Color / Padding          │
│  LayoutObject（几何、父子、两趟布局、缓存）                  │
│  Style / TextRun / measure_text                             │
│  TextObject / ImageObject / RectangleObject（渲染）          │
│  快捷构件：create_band / create_columns / create_spacer /    │
│            create_text_block / split_column_advanced        │
│  LayerManager / objectRegister（全局registry）              │
└─────────────────────────────────────────────────────────────┘
```

**三层与 Git 分支的对应**：底层只在 `master` 演进；中层与顶层在本分支演进
（`ResumeTemplate.py` / `ResumeCore.py` 目前仍未跟踪，见 1.1）。

**分层违规（批次 2 已消除）**：`split_column_advanced`（横向布局能力）原本住在
`ResumeTemplate.py` 里，`ResumeCore.py` 因此不得不 `from ResumeTemplate import ...`
才能分栏。批次 2 已把它连同新的 `create_band` 一起移入引擎（见 3.4），依赖方向恢复正常。

**中层的调用形态（2026-10-13 起重写）**：`ResumeTemplate.py` 把 `add_*` 子模板方法
挂到 `LayoutObject` 上，得到 `节点.add_details(...)` 的方法风格 API，并返回结果句柄
（见第 4 章）。方法不定义在引擎里，是因为模板必须认识"节标题 / 详情 / Style"这类
**简历词汇**，而引擎刻意对领域词汇零知识。

### 2.2 依赖图

```
ResumeCore.py
   ├─→ LayoutEngine.py     (构件 + layer_manager + objectRegister)
   └─→ ResumeTemplate.py   (Style/STYLES + generate_* + fill_*)   ← 已断，见 7.1

ResumeTemplate.py
   └─→ LayoutEngine.py     (LayoutObject 家族 + create_columns + layer_manager)

LayoutEngine.py
   └─→ fpdf2（运行时按需，不在模块顶层导入）
```

`LayoutEngine.py` **不在模块顶层 import fpdf**，只在 `render` 时由调用方把 `pdf` 实例传进来。
`ImageObject._calculate_wrap_height` 是唯一例外（第 1428 行 `from fpdf import FPDF` 临时实例化，见 7.6）。

### 2.3 坐标系与布局模型

- 长度单位是 **mm**，原点在页面左上角（fpdf2 默认）。
- 每个 `LayoutObject` 同时持有两套坐标：
  - **构造坐标**（`_x`, `_y`, `_width`, `_height`）：相对父元素内容区左上角；
  - **绝对坐标**（`get_absolute_x/y()`）：对齐与父偏移叠加后的最终位置。
- `get_effective_width/height()` 是"裁剪后"的尺寸：不小于 0、不超过父可用空间。
  **渲染只看 effective 值，不看构造值。**
- `AlignY.FLOW` 是流式模式：`get_absolute_y()` 让对象紧贴**前一个 FLOW 兄弟**的底边。
  这是右栏能自上而下堆叠节标题/节详情的唯一机制。
- `wrap_width` / `wrap_height` 为 `True` 时，尺寸由内容反推（见 3.4）。

### 2.4 三层缓存

引擎性能依赖三套独立缓存，改动几何逻辑时必须同步维护：

| 缓存 | 失效方法 | 传播方向 |
| --- | --- | --- |
| 几何缓存 `_geom_cache_valid` + 4 个 `_cached_*` | `invalidate_geom_cache()` | 向上（父） |
| 几何缓存（子树） | `invalidate_geom_cache_subtree()` | 向下（子） |
| wrap 缓存 `_wrap_cache_valid` / `_height_set_by_wrap` | `invalidate_wrap_cache()` | 向上（父） |

> ⚠️ `get_effective_height()` 在**返回前**才把 `_geom_cache_valid` 置 `True`（第 845 行），
> 而 `get_absolute_x/y()`、`get_effective_width()` 只写各自的 `_cached_*` 字段、不置标志。
> 也就是说"缓存有效"的判定权全部集中在 `get_effective_height()`。这是刻意设计，但极易误改。

---

## 3. LayoutEngine.py API

754 行的引擎，分 11 节。以下按节给出公开接口。

### 3.1 枚举、颜色、边距

#### 【四轴设计】批次 4 引入

每个元素在两条轴上各有两种**独立**属性，共四轴：

| 轴 | 尺寸（元素自身多大） | 位置（元素落在父内容区的哪里） |
| --- | --- | --- |
| 水平 | `SizeX` | `AlignX` |
| 垂直 | `SizeY` | `AlignY` |

**两轴严格分离**：尺寸枚举只决定"多大"，对齐枚举只决定"在哪"。
因此 `CONTENT`（内容定尺寸）与 `FLOW`（流式接续定位）可以**同时**成立 ——
一个高度由内容决定的元素，位置依然可以接在前一个 `FLOW` 兄弟下方。
这正是批次 5「文本按实际行数定高」所需要的形态。

> 旧实现把两轴混在一起：`wrap_width` / `wrap_height` 两个布尔量管尺寸，
> 而 `get_effective_height()` 里又混进了 `align_y == FLOW` 的位置判断 —— 那正是 7.19 的温床。

#### `class SizeX(Enum)` / `class SizeY(Enum)` —— 批次 4.1 新增

两个枚举成员相同，各自管一条轴的尺寸：

| 值 | 含义 |
| --- | --- |
| `FILL` | 撑满父元素内容区 |
| `FIXED` | 使用代码中写死的 `width` / `height`，**不另行计算、不被裁剪** |
| `CONTENT` | 由内容圈定（`SizeX` 取子元素最大宽 + 左右 padding；`SizeY` 取子元素高之和 + 上下 padding），再对传入约束夹紧 |

构造参数解析：**显式 `size_x` / `size_y` 优先**；未给则按声明值推断 ——
`width` / `height` 大于 0 推成 `FIXED`，否则 `FILL`。

> ✅ **批次 4.4 起 `wrap_width` / `wrap_height` 已彻底删除**（构造参数、兼容属性、
> `_calculate_wrap_height` 垫片全部移除）。它们只是 `SizeX.CONTENT` / `SizeY.CONTENT`
> 的旧写法，长期并存会让"谁是真相"含糊 —— 而真相只有 `_size_x` / `_size_y`。
>
> 迁移写法：`wrap_width=True` → `size_x=SizeX.CONTENT`；
> `wrap_height=True` → `size_y=SizeY.CONTENT`。
> 读取用 `size_x` / `size_y`（都是 property，赋值会触发失效）。

> ⚠️ **`width == 0` 不再等价于 `FILL`**（`width` 是纯数值，`FILL` 是显式枚举值）。
> 旧实现里 `_width == 0` 一个值承担了两种含义（"没给"和"要撑满"），
> 这正是 7.21（`wrap_width` 不可用）的根源。

#### `class LayoutCycleError(RuntimeError)` —— 批次 4.1 新增

布局循环依赖错误的专门类型（旧代码用的是裸 `RuntimeError`，测试无法区分错误种类）。两种情形：

1. **结构循环**：元素成为自己的祖先（对象树被接成了环）。
2. **尺寸循环**：`SizeY`（或 `SizeX`）为 `CONTENT` 的父元素，**直接子元素**却是 `FILL` ——
   父的尺寸由内容决定，而子元素的尺寸又要填满父的内容区，两者互为前提。

情形 2 是**结构性**矛盾，与可用空间数值无关，因此在遍历的进入方向即可判定并报错。

#### `class AlignX(Enum)`
水平对齐（只决定位置）。成员：`LEFT="left"`、`CENTER="center"`、`RIGHT="right"`、`NONE="none"`。

| 值 | 落点 |
| --- | --- |
| `LEFT` | 贴父内容区左边界 |
| `CENTER` | 在父内容区水平居中 |
| `RIGHT` | 贴父内容区右边界 |
| `NONE` | `父内容区左边界 + x` |

#### `class AlignY(Enum)`
垂直对齐（只决定位置）。成员：`TOP="top"`、`VCENTER="vcenter"`、`BOTTOM="bottom"`、`NONE="none"`、`FLOW="flow"`。

| 值 | 落点 |
| --- | --- |
| `TOP` | 贴父内容区上边界 |
| `VCENTER` | 在父内容区垂直居中 |
| `BOTTOM` | 贴父内容区下边界 |
| `NONE` | `父内容区上边界 + y` |
| `FLOW` | 紧贴前一个 `FLOW` 兄弟的底边；无前驱则贴父内容区上边界 |

> ✅ **批次 4.1 起，`AlignX` / `AlignY` 不新增成员** —— `wrap` 属于尺寸轴，不属于对齐轴。
> 测试入口有断言固化这一点（防止后来又把它塞回对齐枚举）。

#### `class Color`
```python
Color(r: int, g: int, b: int, a: int = 0)
```
| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `is_light() -> bool` | `bool` | `(r+g+b)/3 > 200`。用于调试边框选深浅色 |
| `to_RGBA() -> str` | `str` | `"(r,g,b,a)"` 字符串 |

> 注意：`a` **不参与** `is_light()`，也不传给 fpdf（fpdf2 的 `set_fill_color` 只收 r,g,b）。
> `a` 目前是纯装饰字段。

预定义实例（模块级单例，**可变对象共享**）：

| 名称 | 值 | 名称 | 值 |
| --- | --- | --- | --- |
| `RimuruBlue` | `(207,239,252,0)` | `White` | `(255,255,255,0)` |
| `Red` | `(255,0,0,0)` | `Black` | `(0,0,0,0)` |
| `Green` | `(0,255,0,0)` | `Gray` | `(200,200,200,0)` |
| `Blue` | `(0,0,255,0)` | `LightGray` | `(230,230,230,0)` |
| `Yellow` | `(255,255,0,0)` | | |

#### `class Padding`
```python
Padding(left: float = 0, top: float = 0, right: float = 0, bottom: float = 0)
```
**注意参数顺序是 left-top-right-bottom（LTRB），不是 CSS 的 TRBL。**

| 类方法 | 等价于 |
| --- | --- |
| `Padding.all(v)` | `Padding(v, v, v, v)` |
| `Padding.rectangle(h, v)` | `Padding(h, v, h, v)` |
| `Padding.horizontal(v)` | `Padding(v, 0, v, 0)` |
| `Padding.vertical(v)` | `Padding(0, v, 0, v)` |
| `Padding.left(v)` | `Padding(v, 0, 0, 0)` |
| `Padding.right(v)` | `Padding(0, 0, v, 0)` |
| `Padding.top(v)` | `Padding(0, v, 0, 0)` |
| `Padding.bottom(v)` | `Padding(0, 0, 0, v)` |

> ⚠️ `Padding` 是**可变对象**，但 7 个类方法名与实例属性名（`left/right/top/bottom`）重名。
> 类方法遮蔽只发生在类上，实例属性访问 `p.left` 正常返回数值，功能无误，但阅读时容易混淆。

#### `class Style` —— 批次 3 从模板层移入

```python
Style(
    font_name: str = "helvetica",
    font_size: float = 12,
    bold: bool = False,
    italic: bool = False,
    color: Color = Black,
    fill_color: Color = White,
    image_path: str = "",
    padding: Padding = Padding.all(0),
    fit_mode="cover",
)
```

纯数据类，只描述"长什么样"，不含位置信息。所有属性为公有。

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `get_font_style()` | `str` | `"B"` / `"I"` / `"BI"` / `""`，fpdf 兼容 |
| `__repr__()` | `str` | 调试字符串 |

**为什么它属于底层**：样式与"简历"无关；而且"样式 → 渲染参数"的翻译
（见 `from_style`）本来就是引擎职责。它原先住在 `ResumeTemplate.py`，是分层违规。

> ⚠️ `padding: Padding = Padding.all(0)` 是**可变默认参数**（缺陷 7.10）。
> 这是从模板层**原样搬运**过来的既有行为 —— 批次 3 刻意不修，
> 以维持"纯搬运、输出不变"的验收前提。修正归入批次 4 的可变默认值审计。
>
> 迁移自 `ResumeTemplate.Style`，字段名与顺序、默认值**逐项一致**，
> 测试入口有字段快照断言固化这一点。

### 3.2 构件：`class LayoutObject`

```python
LayoutObject(
    name: str,
    x: float = 0,
    y: float = 0,
    width: float = 0,
    height: float = 0,
    color: Color = White,
    parent: Optional['LayoutObject'] = None,
    padding: Optional[Union[Padding, float]] = None,   # float → Padding.all(float)
    align_x: AlignX = AlignX.NONE,
    align_y: AlignY = AlignY.NONE,
    layer: int = 0,
    size_x: Optional[SizeX] = None,
    size_y: Optional[SizeY] = None,
)
```

**副作用**：构造时立即 `layer_manager.add_object(self, layer)`；`name` 非空时立即写入全局 `objectRegister`。

#### 图层属性

| 成员 | 签名 | 说明 |
| --- | --- | --- |
| `layer` | `@property -> int` / `@layer.setter` | 赋值时自动从旧图层摘除、挂到新图层；`< 0` 抛 `ValueError` |
| `move_to_layer` | `(layer: int) -> None` | `layer` 属性赋值的别名 |
| `remove_from_layers` | `() -> None` | 仅从图层摘除，不解除父子关系，不注销 registry |

#### 父子关系

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `add_child` | `(child: LayoutObject) -> LayoutObject` | 传入的 `child` | 设置 `child.parent`、追加到 `children`，并使自身 wrap 缓存 + 几何缓存失效 |
| `remove_child` | `(child: LayoutObject) -> bool` | 是否移除成功 | 解除父子关系并使缓存失效 |
| `get_child` | `(name: str) -> Optional[LayoutObject]` | 直接子元素（仅一层） | 线性查找 |
| `find_by_name` | `(name: str) -> Optional[LayoutObject]` | 自身或任意深度后代 | 深度优先递归 |
| `get_previous_sibling` | `() -> Optional[LayoutObject]` | 前一个兄弟（不限对齐） | |
| `get_previous_flow_sibling` | `() -> Optional[LayoutObject]` | 前一个 `align_y == FLOW` 的兄弟 | FLOW 布局的核心 |
| `get_flow_children` | `() -> List[LayoutObject]` | 所有 `align_y == FLOW` 的子元素 | **过滤式**，不保证返回全部子元素 |

> ✅ **缺陷 7.3 已修（批次 2）**：`split_column_advanced` 原先绕过 `add_child`，
> 直接 `container.children.append(...)` 并单独赋 `parent`，因此不触发缓存失效，
> 靠末尾手动 `parent.invalidate_wrap_cache()` 兜底（且**几何缓存仍未失效**）。
> 移入引擎后改为走 `create_band` → `add_child`，失效由机制保证。

#### 几何查询（渲染的真相来源）

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `get_parent_available_area()` | `(x, y, w, h)` | 父内容区的**绝对**坐标；无父时返回自身构造坐标 |
| `get_absolute_x()` | `float` | 按 `align_x` + 父内容区偏移计算，带缓存 |
| `get_absolute_y()` | `float` | 按 `align_y` 计算，`FLOW` 走前驱兄弟链，带缓存 |
| `get_effective_width()` | `float` | wrap 优先；否则 `min(_width, 父可用宽)`；`_width <= 0` 时取满父可用宽 |
| `get_effective_height()` | `float` | wrap 优先；否则 `min(_height, 父可用高)`；`FLOW` 额外扣减前驱已占高度，并置 `_flow_clipped` |
| `get_content_area()` | `(x, y, w, h)` | 自身内容区绝对坐标 = 绝对坐标 + padding 内缩 |
| `get_layout_info()` | `dict` | 调试快照，见下 |

`get_layout_info()` 返回结构：

```python
{
  "name": str,
  "constructed": {"x","y","w","h"},        # 构造值
  "effective":   {"x","y","w","h"},        # 生效值
  "align":       {"x","y"},                # 枚举的 .value 字符串
  "flow_clipped": bool,
  "layer": int,
  "size_mode": {"x": "fill|fixed|content", "y": "..."},
  "layout_valid": bool,
  "constraint": {"w", "h"},
  "content_overflows": bool,
}
```

#### 尺寸计算：两趟遍历（批次 4.2 起）

尺寸**不再有惰性缓存**。全部由 [`layout()`](#34b-两趟遍历批次-42几何核心) 的两趟遍历统一计算，
`get_effective_*()` / `get_absolute_*()` 退化为纯读取（必要时触发一次 `layout()`）。

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `layout` | `(pdf=None, force=False) -> LayoutObject` | self | 从自身开始跑两趟；pdf 供文本/图片的内容测量 |
| `_measure` | `(constraint_w, constraint_h, path, pdf)` | — | 趟 1：内部方法 |
| `_place` | `()` | — | 趟 2：内部方法 |
| `_source_w` | `(pdf=None) -> float` | 内容固有宽度 | 子类按需覆盖 |
| `_source_h` | `(pdf=None) -> float` | 内容固有高度 | 子类按需覆盖 |
| `_contribution_w` | `() -> float` | 对父 `CONTENT` 宽度的贡献 | 见 3.4b |
| `invalidate_geom_cache` | `() -> None` | — | 置失效并**向上传播到父** |
| `invalidate_wrap_cache` | `() -> None` | — | [兼容] 等价于 `invalidate_geom_cache()` |
| `is_wrapped` | `() -> bool` | `size_x` 或 `size_y` 为 `CONTENT` | |
| `is_height_wrapped` | `() -> bool` | `size_y == SizeY.CONTENT` | |
| `is_width_wrapped` | `() -> bool` | `size_x == SizeX.CONTENT` | |
| `get_wrap_status` | `() -> Dict[str, Any]` | 尺寸与失效状态快照 | |

**已删除**：`wrap_content()`、`wrap_content_width()`、`_calculate_wrap_width()`、
`_calculate_wrap_height()` 及其重入保护 `_is_wrapping`。
`wrap_content()` 的语义完全由 `layout()` 取代，两者并存只会造成"该调哪个"的困惑。

**循环依赖**：不再靠 `_is_wrapping` 静默降级，而是构建**祖先路径栈**显式检测，
发现成环就抛 `LayoutCycleError`（含完整路径 `A > B > A`）。

#### 缓存管理

| 方法 | 传播方向 | 何时该调用 |
| --- | --- | --- |
| `invalidate_geom_cache()` | 自身 + 向上到父 | 自身尺寸/对齐/padding 变化后 |
| `invalidate_geom_cache_subtree()` | 自身 + 向下到所有子 | 父尺寸变化后 |

`add_child` / `remove_child` / `set_text` / `set_image` / `wrap_content*` 内部已自动调用。

#### 渲染

| 方法 | 签名 | 返回 |
| --- | --- | --- |
| `render` | `(pdf, is_fill: bool = False)` | `last_y`（最后一个子元素的返回值），无子元素时返回自身绝对 y |
| `render_debug` | `(pdf, is_fill=False, has_border=True, show_name=True, show_bounds=True, name_offset_y=2, bounds_offset_y=6)` | `None` |
| `_get_display_name` | `() -> str` | 名称 + `[H↕]` / `[W↔]` 标记 |
| `_get_bounds_info` | `() -> str` | `"WxH"`，被 flow 截断时追加 `"[CLIPPED]"` |
| `get_true_height` | `()` | **空实现，返回 `None`**（见 7.5） |

`render()` 是**深度优先递归**：先渲染自己（基类不画任何东西），再按 `children` 的**插入顺序**递归。
注意：**图层顺序不参与 `render()` 的遍历顺序**，只影响 `layer_manager.render_layers()`。
两个渲染路径并存，行为不一致。

> `render` 与 `render_debug` 都被 `@timer` 装饰，会向 stdout 打印每个节点的耗时与名称。
> 一次简历生成的日志量因此很大，且**无法关闭**（见 7.13）。

### 3.3 渲染对象：三个子类

三者共同点：都继承 `LayoutObject`，都按需覆盖 `_source_w()` / `_source_h()`，都重写 `render()` 与 `render_debug()`。

#### `class TextObject(LayoutObject)`

```python
TextObject(
    name, x=0, y=0, width=0, height=0,
    text: str = "",
    font_name: str = "helvetica",
    font_size: float = 12,
    font_style: str = "",              # "B" / "I" / "BI" / ""
    text_color: Color = Black,
    color: Color = White,              # 背景填充色（is_fill 时使用）
    parent=None, padding=None,
    align_x=AlignX.NONE, align_y=AlignY.NONE,
    multi_line: bool = False,
    line_height: Optional[float] = None,   # None → font_size * 0.6
    layer: int = 0,
    size_x=None, size_y=None,
)
```

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `set_text` | `(text: str) -> TextObject` | self | 链式；使文本缓存/wrap/几何缓存全部失效 |
| `get_text` | `() -> str` | 文本 | |
| `append_text` | `(text: str) -> TextObject` | self | 追加 |
| `calculate_text_size` | `(pdf) -> Tuple[float, float]` | `(宽, 高)` | 临时切换 pdf 字体测量后**恢复原字体**；行数估算 `int(宽/可用宽)+1` |
| `get_cached_text_size` | `() -> Tuple[float, float]` | 缓存值，无效时 `(0,0)` | |
| `from_style` | `(name, style=None, text="", **overrides) -> TextObject` | 按样式构造（见下） |

**`TextObject.from_style(...)` —— 批次 3 新增（classmethod）**

把"样式 → 渲染参数"的翻译集中一处，避免调用点反复手抄参数：

| `Style` 字段 | → `TextObject` 参数 |
| --- | --- |
| `font_name` | `font_name` |
| `font_size` | `font_size` |
| `bold` + `italic` | `font_style`（经 `get_font_style()`，得 `"B"`/`"I"`/`"BI"`/`""`） |
| `color` | **`text_color`** |
| `fill_color` | `color`（背景填充色） |
| `padding` | `padding` |
| `image_path` / `fit_mode` | 忽略（仅 `ImageObject` 使用） |

其余参数（`align_x` / `align_y` / `multi_line` / `line_height` / `width` / `height` /
`parent` / `layer` / `wrap_*` 等）经 `**overrides` 传入，**优先级高于 `style`**。
`style=None` 表示使用 `Style()` 的全默认值（`Style` 所有字段都有默认值，故良定义）。
返回的对象**未挂载**到任何父元素。

不把 `style=` 塞进 `__init__` 是刻意的：那会引出「`style` 与显式参数谁优先」
以及「`None` 表示不覆盖」的二义。classmethod 是"我有样式对象"时的显式入口，
直接写参数仍是快路径。

`render()` 行为分歧：

- `multi_line=True`：`pdf.multi_cell(...)` 自动换行，返回 `pdf.get_y()`。
- `multi_line=False`：`pdf.cell(text_width, line_height, text)`，
  返回 `abs_y + line_height`；**`align_x` 只作用于水平偏移**，`y_offset` 用 `eff_h` 垂直居中。

> ⚠️ `multi_line=False` 分支在 `pdf.cell` 之后才遍历子元素，但**不重置光标**，且返回值 `abs_y + line_height`
> 与实际绘制位置可能不一致。同时 `calculate_text_size` 的行数估算与 `_calculate_wrap_height`
> 的 `len(text)//20+1` 是**两套不同公式**（见 7.7）。

#### `class ImageObject(LayoutObject)`

```python
ImageObject(
    name, x=0, y=0, width=0, height=0,
    image_path: str = "",
    keep_aspect_ratio: bool = True,
    fit_mode: str = "contain",        # "contain" / "cover" / "stretch"
    color: Color = White,
    parent=None, padding=None,
    align_x=AlignX.NONE, align_y=AlignY.NONE,
    layer: int = 0,
    size_x=None, size_y=None,
)
```

| `fit_mode` | 行为（`keep_aspect_ratio=True` 时） |
| --- | --- |
| `"stretch"` | 直接拉伸到 `eff_w × eff_h`，**忽略宽高比** |
| `"cover"` | 填满区域、溢出方向裁剪；取 `max` 缩放 |
| `"contain"`（其他值同理） | 完整放入区域、留白；取 `min` 缩放 |

| 方法 | 签名 | 返回 |
| --- | --- | --- |
| `set_image` | `(image_path: str) -> ImageObject` | self |
| `get_image` | `() -> str` | 路径 |
| `calculate_image_size` | `(pdf) -> Tuple[float, float]` | `(渲染宽, 渲染高)`；失败返回 `(0.0, 0.0)` |
| `get_cached_image_size` | `() -> Tuple[float,float,float,float]` | `(原图宽, 原图高, 渲染宽, 渲染高)` |
| `from_style` | `(name, style=None, image_path="", **overrides) -> ImageObject` | 按样式构造（见下） |

**`ImageObject.from_style(...)` —— 批次 3 新增（classmethod）**

| `Style` 字段 | → `ImageObject` 参数 |
| --- | --- |
| `image_path` | `image_path`（若 `image_path` 实参非空，**以实参优先**） |
| `fill_color` | `color`（背景填充色） |
| `fit_mode` | `fit_mode`（字段名相同，此处显式映射以便阅读） |
| `padding` | `padding` |
| `font_name` / `font_size` / `bold` / `italic` / `color` | 忽略（纯文本属性） |

`**overrides` 优先级高于 `style`；`style=None` 用全默认值；返回对象**未挂载**。

> `RectangleObject.from_style` **刻意不做**：矩形只用到 `fill_color`，
> 而在引擎里那已经叫 `color`，加一层单字段翻译是负收益。等确有多矩形样式表时再补。

`render()` 返回 `(render_w, render_h)` —— **与 `TextObject.render()` 返回 `float` 不一致**（见 7.11）。

图片不存在时：不抛异常、不报警、不绘制；`render()` 早退返回 `(0.0, 0.0)`。

#### `class RectangleObject(LayoutObject)`

```python
RectangleObject(
    name, x=0, y=0, width=0, height=0,
    color: Color = Gray,
    parent=None, padding=None,
    align_x=AlignX.NONE, align_y=AlignY.NONE,
    layer: int = 0,
    size_x=None, size_y=None,
)
```

没有额外覆盖 —— 它的内容固有尺寸就是基类默认的「子元素累加 + padding」。

`render()` 返回 `(eff_w, eff_h)`，并且 **`is_fill` 参数被完全忽略**：

```python
# LayoutEngine.py:1662-1663（原 is_fill 分支被注释掉）
pdf.set_fill_color(self.color.r, self.color.g, self.color.b)
pdf.rect(abs_x, abs_y, eff_w, eff_h, 'F')
```

即 `RectangleObject` 永远实心填充。见 7.9。

### 3.4 中层：横向布局

#### `create_band(...)` —— 批次 2 新增，横向布局的基础构件

```python
create_band(
    parent: LayoutObject,
    cells: List[Union[float, LayoutObject]],
    gap: float = 0,
    padding: Optional[Union[Padding, float]] = None,
    height: float = 0,
    names: Optional[List[str]] = None,
    colors: Optional[List[Color]] = None,
    layer: int = 0,
    container_name: Optional[str] = None,
) -> LayoutObject          # 返回新建的带容器
```

把若干个"格子"并排放在一个流式行里。`create_columns` 与 `split_column_advanced`
都是它的包装。

`cells` 的两种元素形式：

| 元素类型 | 含义 |
| --- | --- |
| `float` | 视为**比例权重**，在带内新建一个空 `LayoutObject` 作为格子 |
| `LayoutObject` | **直接复用**该对象作为格子（保留其自身 `_width`） |

宽度分配（**严格按比例，不做"剩余空间均分"** —— 后者是 `create_columns` 独有的语义）：

```
可用宽 = 父内容区宽 - gap * (n - 1)
比例权重格子 -> 可用宽 * (权重 / 权重之和)
已构造对象   -> 保留自身 _width，由 gap 与前面的格子决定 _x
```

行为要点：

1. 带容器尺寸 = `(父内容区宽, height)`，放在父内容区原点，`align_x/y = NONE`。
2. `height = 0` → 取父内容区高；此时若父内容区高也为 0，抛 `ValueError`。
3. 格子 `_x` 依次累加，相邻格子之间留 `gap`；格子 `_height` 统一为 `height`。
4. 已构造对象会被**接管 `_x` / `_y` / `_height` 与 `align_*`**，但宽度保留。
5. 全部挂载走 `add_child`，因此缓存失效被正确触发（对比缺陷 7.3）。
6. `container_name` 默认 `"{parent.name}_band"`。

**返回值与旧 API 的差异**：返回**新建的带容器**，不是传入的 `parent`。
`create_columns` / `create_columns_balanced` 也随之改为返回带容器（此前它们返回 `parent`）。
`split_column_advanced` 为保持链式调用兼容，**仍返回 `parent`**。

#### `create_columns(...)`

```python
create_columns(
    parent: LayoutObject,
    num_columns: int = 2,
    column_widths: Optional[List[float]] = None,
    column_ratios: Optional[List[float]] = None,
    gap: float = 5,
    padding: Optional[Union[Padding, float]] = None,
    names: Optional[List[str]] = None,
    colors: Optional[List[Color]] = None,
    layer: int = 0,
) -> LayoutObject          # 返回新建的带容器
```

实现是**两趟**：先用自己的语义算出各栏宽度，再交给 `create_band` 排放。
`create_band` 只做严格按比例，所以"剩余量均分"这一步必须留在本函数里。

行为要点：

1. `column_widths` 与 `column_ratios` **互斥**，同时给出抛 `ValueError`。
2. 宽度分配（`usable = content_w - gap*(n-1)`）：
   - `column_widths` 给定：总和超出则等比缩小；不足则**把剩余空间按栏数均分追加到每栏**；相等则原样使用。
   - `column_ratios` 给定：按比例分配。
   - 都不给：等宽。
3. 各栏挂在**带容器之下**，不再是 `parent` 的直接子元素。
   因此按名字取栏要用 `find_by_name`（深度优先），不能用 `get_child`（只看直接子元素）。
4. `names` 默认 `["Column_0", "Column_1", ...]`；`colors` 默认全 `Gray`。
5. 子栏尺寸为 `width × content_h`，`align_x/align_y` 均强制为 `NONE`。

> ✅ **缺陷 7.4 已修（批次 2）**：旧实现在此处执行 `parent.children = []`，
> 会静默丢弃父元素既有子元素。现已移除；新增格子走 `add_child`，
> 既有子元素被保留且缓存正确失效。

#### `create_columns_balanced(...)`

```python
create_columns_balanced(parent, num_columns=2, gap=5, padding=None, layer=0) -> LayoutObject
```
等宽分栏，内部直接转发 `create_columns`。

#### `split_column_advanced(...)` —— 批次 2 已移入引擎，改为 `create_band` 的包装

```python
split_column_advanced(
    parent: LayoutObject,
    left_obj: LayoutObject,
    right_obj: LayoutObject,
    ratio: list = None,        # 默认 [1.0, 2.5]，必须恰好 2 个元素
    gap: float = 0,
    padding: Padding = None,   # 默认 Padding.all(0)
    layer: int = 0,
) -> LayoutObject              # 返回 parent（保持链式调用兼容）
```

与 `create_columns` 的区别：接收**已构造好的对象**（可为不同子类），直接挂载，不额外包装。

行为要点：
- 自动创建一个 `{parent.name}_split_container` 容器，尺寸 = 父内容区，`align_x/y = NONE`。
- 左栏 `_width = (content_w - gap) * ratio[0]/sum(ratio)`；右栏 `_width = (content_w - gap) * ratio[1]/sum(ratio)`。
- 左右对象作为"已构造格子"交给 `create_band` 排放：`_x` 由 `create_band` 依次累加，
  `_height` 统一为 `content_h`，`align_x/y` 强制为 `NONE`。
- `content_w <= 0` 或 `content_h <= 0` 时抛 `ValueError`。
- **返回值仍是 `parent`**（与 `create_columns` 返回带容器不同），因为它被设计为支持链式调用。

> ✅ **缺陷 7.3 已修（批次 2）**：旧实现在 `ResumeTemplate.py` 里直接
> `container.children.append(...)` 并单独赋 `parent`，绕过 `add_child`，导致几何缓存不失效。
> 现已改为走 `create_band` → `add_child`，缓存失效由机制保证，不再依赖末尾的手工补调。
>
> 移入引擎的意义：`ResumeCore.py` 此前为了分栏必须 `import ResumeTemplate`，
> 现在可以直接从 `LayoutEngine` 取用，分层违规消除。

#### `create_spacer(...)` —— 批次 1 新增

```python
create_spacer(
    name: str,
    height: float,
    parent: Optional[LayoutObject] = None,
    layer: int = 0,
) -> LayoutObject
```

创建一个纯留白对象（垂直间距）。等价于一个 `width=0`、`align_x=CENTER`、
`align_y=FLOW`、`padding=Padding.all(0)`、`color=White` 的 `LayoutObject`。
在流式布局中只占据 `height` 指定的纵向空间，不渲染任何内容。

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `name` | `str` | 必填 | 对象名，会写入 `objectRegister` |
| `height` | `float` | 必填 | 留白高度 (mm) |
| `parent` | `Optional[LayoutObject]` | `None` | 非空时自动挂载（走 `add_child`，缓存失效正确触发） |
| `layer` | `int` | `0` | 图层索引 |

**返回**：新建的留白对象。

**刻意不暴露的参数**（附实测依据）：

| 未暴露 | 原因 |
| --- | --- |
| `color` | `LayoutObject.render()` 在 `is_fill=False` 时不绘制任何内容，留白的颜色对输出无影响。抽取前 `ResumeCore.py` 里 14 处留白分别用了 `White`/`Black`/`Blue`/`Green`/`Yellow` 五种颜色，属复制粘贴残留 |
| `padding` | 留白 `_height > 0`，`get_effective_height()` 走 `min(_height, avail_h)` 分支，padding 不参与计算。实测 `Padding.all(0)` 与 `Padding.all(10)` 的有效高/有效宽/绝对 y 完全相同 |
| `align_y` | 留白的语义就是"接在流式序列的下一个位置"，固定 `FLOW` |
| 自动命名 | 留白同样写入 `objectRegister`，自动命名会改变上层依赖的名字 |

**用途**：`ResumeCore.py` 的 `Lead_*` 系列间距对象全部改由它创建（批次 1 完成，14 处）。

#### `create_text_block(...)` —— 批次 3 新增

```python
create_text_block(
    parent: LayoutObject,
    name: str,
    text: str = "",
    style: Optional[Style] = None,
    height: float = 0,
    multi_line: bool = False,
    line_height: Optional[float] = None,
    align_x: AlignX = AlignX.LEFT,
    align_y: AlignY = AlignY.FLOW,
    padding: Optional[Union[Padding, float]] = None,
    layer: int = 0,
) -> TextObject
```

创建一个文本块并挂载到父容器。内部走 `TextObject.from_style(...)` 然后 `add_child`。

与直接构造 `TextObject` 的区别：

- 样式参数由 `Style` 对象统一提供（不再手抄 7 个参数）；
- `height` 是**显式参数**，不再由调用方把常量写死在构造里；
- 自动挂载，缓存失效正确触发。

> ⚠️ **`height=0` 的语义是"取父容器可用高度"，不是"按内容自动撑高"。**
> 后者需要真实的行数测量，属批次 5。因此想让文本块高度贴合内容，
> **目前仍须显式给出 `height`**。

**踩坑提醒（实测）**：同一流式父容器里，一个 `height=0` 的块会占满全部可用高，
**把后随的 `FLOW` 兄弟挤成 0 高**（并置 `_flow_clipped`）。这是引擎 FLOW 的既有语义，
不是 `create_text_block` 的问题；但用 `height=0` 时要意识到这一点。
测试入口已把该现状固化为断言。

`padding=None` 表示沿用 `style.padding`（与 `from_style` 一致）；给值则覆盖。

### 3.4b 两趟遍历（批次 4.2，几何核心）

**这是引擎尺寸与位置计算的唯一机制。** 旧实现（惰性求值 + 父子互相递归）已被整体替换。

#### 为什么是两趟

旧实现的尺寸计算是「子元素在测量阶段回头问父元素」，而父的尺寸正要靠子元素算出来 ——
**自指**。于是 `wrap_height=True` 只能塌缩成 padding（缺陷 7.19）。

新实现把两个量**分开传播**：

| 趟 | 方向 | 传什么 | 定下什么 |
| --- | --- | --- | --- |
| **趟 1 `_measure`** | 进入（背离根） | `constraint`（父内容区尺寸） | `FIXED` / `FILL` 的尺寸 |
| **趟 1 `_measure`** | 退出（朝向根） | `size`（已算出的尺寸） | `CONTENT` 的尺寸 |
| **趟 2 `_place`** | 进入 | 只读 `AlignX` / `AlignY` | 绝对坐标 |

**关键不变式**：尺寸阶段只把 `constraint` 往下传、只把 `size` 往回收；
位置阶段只读已经定好的 `size`。子元素的约束是**作为参数拿到**的，不再回头问父容器 ——
那条造成循环的回边根本不存在。

#### 公开接口

```python
layout(pdf=None, force=False) -> 'LayoutObject'
```

从自身开始跑两趟。根节点没有父容器，其约束就是自己声明的尺寸。
`pdf` 可选：纯几何的 `CONTENT`（矩形、嵌套容器）不需要它；
文本 / 图片的 `CONTENT` 需要它才能精确测量，不传时退回估算。

`get_effective_width/height()` 与 `get_absolute_x/y()` 现在是**纯读取**：
若布局尚未算好会触发一次 `layout()`，然后返回结果。它们不再边算边问，因此不存在自指。

#### 轴约束的传递规则

| 父的 `Size` | 传给子元素的约束 |
| --- | --- |
| `FIXED` | `父尺寸 − 父 padding` |
| `FILL` | `父尺寸 − 父 padding` |
| **`CONTENT`** | **父的 constraint 原样下传** |

`CONTENT` 那一行是消除循环的关键：padding 是「容器内留白」，
若先扣 padding 再把余量给子元素，就要求"父尺寸必须先定"，循环立刻回来。
原样下传则子元素的约束与本父的最终尺寸**无关**。

#### 内容固有尺寸的钩子

`_source_w(pdf)` / `_source_h(pdf)` —— 子类覆盖它来表达"我的内容有多大"：

| 类 | 覆盖情况 |
| --- | --- |
| `LayoutObject` | 子元素尺寸之和 / 最大值 + padding |
| `TextObject` | 叶子时按字号与估算行数；有子元素时退回基类 |
| `ImageObject` | 叶子时按图片宽高比（优先用外部 `pdf`，其次 Pillow） |

**批次 5 只需改这两个方法的文本实现**（换成真实行数测量），其余不动。

#### 报错：只有结构循环

```python
class LayoutCycleError(RuntimeError)               # 基类
class LayoutError_CONTENT_FILL(LayoutCycleError)   # 保留但**不再触发**（见下）
```

| 错误 | 触发时机 | 信息 |
| --- | --- | --- |
| **结构循环** | 进入时发现元素已在祖先路径中 | 完整路径（`A > B > A`） |

> ⚠️ **一个重要更正（批次 4b）**：原先设计过第二种报错 ——
> 「`CONTENT` 父 + 直接 `FILL` 子」被判定为尺寸循环。
> **实测后确认这个判定是错的**：`FILL` 子元素需要的是**约束**，不是「父的最终尺寸」，
> 而约束是作为参数往下传的 —— 这个环在设计上就已经断开了。
>
> | 轴 | 语义 | 是否有环 |
> | --- | --- | --- |
> | 水平 | 子宽 = min(父最终内容区宽, 传入约束) —— 收缩包裹 | 无 |
> | 垂直 | 子高 = 传入约束；父再收缩包裹并夹紧 | 无 |
>
> 旧实现之所以在这里撞墙，是因为它回头问 `parent.get_effective_height()`，
> 而那时父的尺寸尚未确定 —— 那是**实现方式**造成的环，不是语义上的环。
> 两趟遍历把约束改成传参之后，问题自然消失。
>
> `LayoutError_CONTENT_FILL` 因此不再被触发，类型保留以备将来需要。
> 真正会报错的是**结构循环**（对象树被接成了环）。

#### `FILL` 子元素在 `CONTENT` 父下的退化规则

父元素在**某条轴**上由内容决定尺寸时，该轴上的 `FILL` 子元素**退化为按内容定尺寸**。

理由：此时 `FILL` 子元素拿到的"约束"没有意义 —— 那个约束正是由本子元素参与决定的。
若不退化，「`CONTENT` 父只有 `FILL` 子」会收敛到 0，完全不可用。

这与安卓 `wrap_content` 父强制 `match_parent` 子退化的处理一致，也是 CSS
`width: fit-content` 配 `width: 100%` 子的实际表现。

退化后：
- 子元素按自身内容固有尺寸（`_source_w` / `_source_h`）定尺寸；
- 父元素再由内容决定自己的尺寸并夹紧到祖辈约束；
- 内容装不下时置 `_content_overflows`，属于**溢出**而非错误。

#### 行为变化（相对旧实现）

| 变化 | 说明 |
| --- | --- |
| **`FIXED` 不再被父约束裁剪** | 旧实现 `min(_width, avail_w)`；新实现按「定死的尺寸不动」原则不裁剪。装不下是**溢出**问题 |
| **FLOW 溢出裁剪移到趟 2** | 它属于"溢出策略"，不属于尺寸计算。旧实现把它混在尺寸函数里，是 7.19 的温床 |
| **`width` / `height` 成为公开尺寸声明** | 赋正值会把尺寸方式同步为 `FIXED`，赋 0 退回 `FILL`。**直接写 `_width` / `_height` 会绕过尺寸方式解析**（见下） |
| `get_parent_available_area()` 退化为纯查询 | 尺寸计算不再需要它；保留为兼容入口 |
| `wrap_content()` / `wrap_content_width()` | **已删除**。语义由 `layout()` 完全取代 |
| `_calculate_wrap_height()` | **已删除**（连同兼容垫片）；内容固有尺寸改由 `_source_h()` 表达 |
| `wrap_width` / `wrap_height` | **已删除**（构造参数与兼容属性）；改用 `size_x` / `size_y` |

> ⚠️ **迁移注意**：`obj._height = N` 这种"先构造、后设尺寸"的旧写法会**失效** ——
> 构造时若 `height=0`，尺寸方式被推成 `FILL`，之后直接写 `_height` 不会改回 `FIXED`，
> `FILL` 会覆盖它。请改用 `obj.height = N`（公开属性会同步尺寸方式）。
> 批次 4.2 已把 `ResumeTemplate.py` 里 4 处这类写法改为公开属性。

### 3.4c 文本片段与真实测量（批次 5）

#### `class TextRun`

一段连续文字 + 它自己的样式。这是"一段文字内部可以有多种样式"的最小单位。

```python
TextRun(text="", font_name="helvetica", font_size=12,
        bold=False, italic=False, color=Black)
```

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `get_font_style()` | `str` | `"B"` / `"I"` / `"BI"` / `""` |
| `font_key()` | `tuple` | `(font_name, font_style, font_size)` —— 测量缓存的键（颜色不影响字宽，不入键） |
| `with_text(text)` | `TextRun` | 只替换文字的副本 |
| `derive(**overrides)` | `TextRun` | 按 overrides 覆盖的副本 |
| `from_style(text, style, **overrides)` | `TextRun` | 从 `Style` 派生（字段映射同 `TextObject.from_style`） |

**不可变**：所有"修改"都返回新对象。因此 `runs` 列表可以安全共享。

#### `parse_inline_markdown(text, base=None, mono_font=None) -> List[TextRun]`

把带内联标记的文本解析成片段。支持：

| 语法 | 效果 |
| --- | --- |
| `**粗体**` | `bold=True` |
| `*斜体*` | `italic=True` |
| `` `等宽` `` | 换用 `mono_font`（未指定则保持原字体） |
| `<b>…</b>` `<i>…</i>` | HTML 风格粗体 / 斜体（读 `.md` 时常见） |
| `<c:RRGGBB>…</c>` | 指定颜色 |
| `\*` `\`` `\<` | 转义，输出字面量 |

**不支持的标记原样保留为文本**（不静默丢弃，写错时看得见）；**未闭合的标记也原样保留**。
嵌套标记暂不支持（内层会被当普通文字）。

#### `measure_text(pdf, runs, available_width, line_height_ratio=1.2) -> TextMetrics`

用真实 pdf 测量：**摊平成可断行单元 → 贪心装行**。

| 切分规则 | 说明 |
| --- | --- |
| CJK **逐字** | 中文没有空格，逐字断行是标准做法 |
| 非 CJK **按空白切词** | 拉丁文按词断行，不在词中间断开 |
| 空白单独成段 | 便于行尾丢弃 |
| `\n` | 变成硬换行单元 |

宽度在**各自的字体**下用 `pdf.get_string_width()` 测量 —— 这正是分段样式的关键。

`available_width` **为 0 或负数表示不换行**（量整段自然宽度）。

返回的 `TextMetrics`：

```python
lines: List[List[(run_index, text, x_offset, width)]]
line_heights: List[float]        # 每行 = 该行内最大字号 × line_height_ratio
line_count / total_height / max_line_width
line_top(index)                  # 第 index 行的顶边偏移
iter_pieces()                    # 按行产出片段
```

**关键设计**：渲染时**复用同一份 `lines`**，因此"测量出的行数"与"画出来的行数"
必然一致 —— **一致性由构造保证**，不依赖 fpdf 内部断行行为（缺陷 7.7 的根治）。

> 实测：可用宽 120 / 60 / 30 对同一段中文分别断出 2 / 3 / 5 行，逐行填满到接近可用宽。

#### `font_context(pdf, font_name, font_style, font_size)`

上下文管理器：临时切换字体、退出时恢复原状。测量与渲染共用，只有一处实现。

**变体缺失时优雅降级**：调用方未必把 `"B"`/`"I"`/`"BI"` 每个变体都 `add_font` 注册过，
fpdf 在字体未注册时会抛 `FPDFException`，若直接冒泡会让整份文档渲染失败。
因此退回"同字体、无样式"，并**明确打印提示**（不静默 —— 静默降级是本项目的既有教训）。

### 3.4d 文本落点与盒内对齐（批次 7，两处缺陷修复）

`render()` 把一段文字画到哪里，由两层决定：**盒子位置**（趟 2 的 `_place`）与
**文字在盒内的落点**（本节的渲染逻辑）。

#### 缺陷一：传给 `pdf.cell` 的格子高漏了单位换算

fpdf 的 `pdf.cell(w, h, txt)` 中 `w` / `h` 是**用户空间单位（mm）**，而字号是 **pt**。
旧实现在这里传了 `own_h = 字号 × line_height_ratio`（**pt 数值**），
等于把 pt 当 mm 用 —— 格子高虚高 `1 / 0.3528 ≈ 2.8346` 倍。

由于 fpdf 会把文字**垂直居中**在格子里，基线落在格子中央：

```
22pt 文字 -> own_h = 26.4（被当 mm）-> 格子高 26.4mm
                               -> 基线相对盒顶下移 15.53mm
而节标题的盒子只有 14.5mm 高    -> 文字基线直接跑到盒外
```

**修法**：`pdf.cell(_w, own_h * PT_TO_MM, txt)`，模块常量
`PT_TO_MM = 25.4 / 72.0`。

> ⚠️ 同一处的 `py = cy + line_top + (line_h - own_h)` **不需要换算**：
> `line_top` / `line_h` 来自 `measure_text`，与 `own_h` 同为 pt 数值，
> 相减得到的"行内偏移"自洽。

#### 缺陷二：`align_y` 从未被渲染读取

`_place()` 用 `align_y` 决定"盒子摆在哪"，而 `render()` 完全不读它，
文字一律贴内容区顶边 —— `VCENTER` / `BOTTOM` 对文字落点**毫无作用**
（`TOP` / `NONE` / `FLOW` 本就该顶对齐，所以只有前两者失效）。

**修法**：在 `render()` 里按同一条对齐规则分配盒内剩余空间。

#### 落点公式（受控实验标定，六个字号误差 0.00）

```
text_h_mm = m.total_height × PT_TO_MM                 # 文字块实高
inner_h   = eff_h − padding.top − padding.bottom       # 盒内可用高
dy_align  = VCENTER → (inner_h − text_h_mm) / 2
            BOTTOM  →  inner_h − text_h_mm
            TOP / NONE / FLOW → 0
            文字比盒子高时一律 0（保持"顶对齐 + 向下溢出"）

文字基线 = 盒顶 + padding.top + dy_align
           + (字号 × line_height_ratio × PT_TO_MM) / 2
           + 0.10583 × 字号
```

> 最后两项来自 fpdf 把文字垂直居中于格子：半个格子高 + 该字体的下降部
> （`0.10583 × 字号`，对 LXGW 实测标定）。
>
> 标定实验：固定格子高 10mm、取 8/12/16/24/32/40pt，拟合得
> `基线偏移 = 0.10584 × 字号 + 4.99968` —— 截距恰为 `h/2`，
> 证明 fpdf 按 mm 正确解释了格子高，问题只在调用方传错了单位。

#### 影响面

修复前（实测，节标题/姓名行等 22pt 文本）：**基线相对盒顶 15.53mm，
超出 14.5mm 高的盒子**；12pt 联系方式行 8.47mm 超出 7mm 盒子。
9 个文本块合计 **45.82mm** 的纵向虚位移。

> ⚠️ **升级影响**：所有载体的文字位置都会变。任何"为了抓住文字"而调过的盒高
> 都需要按上面的公式重新校一遍。自检入口的**第 13 节**已把该行为固化为断言
> （三种对齐落点两两不同、间距等于 `(盒内高 − 文字实高)/2`、落点落在盒内）。


### 3.5 图层与注册表

#### `class LayerManager`

| 方法 | 签名 | 返回 |
| --- | --- | --- |
| `add_object` | `(obj, layer: int) -> None` | — （`layer < 0` 抛 `ValueError`） |
| `remove_object` | `(obj) -> bool` | 是否找到并移除 |
| `get_layer` | `(layer: int) -> List` | **副本** |
| `get_layer_reference` | `(layer: int) -> List` | **原列表引用**（可原地改） |
| `get_all_layers` | `() -> Dict[int, List]` | 各层副本 |
| `get_sorted_layers` | `() -> List[int]` | 升序图层号 |
| `get_layer_count` | `() -> int` | 非空图层数 |
| `get_total_object_count` | `() -> int` | 对象总数 |
| `has_layer` | `(layer: int) -> bool` | 存在且非空 |
| `get_layers_in_range` | `(start: int, end: int) -> Dict[int, List]` | 半开区间 `[start, end)` |
| `get_objects_in_range` | `(start: int, end: int) -> List` | 半开区间 |
| `render_layers` | `(pdf, is_fill=False, render_func=None) -> None` | 按图层升序遍历全部对象 |
| `render_layer` | `(pdf, layer, is_fill=False, render_func=None) -> None` | 单图层 |
| `render_layers_debug` | `(pdf, is_fill=False, has_border=True, show_name=True, show_bounds=True) -> None` | 调试渲染 |
| `clear` / `clear_layer` | `() / (layer: int) -> None` | — |
| `get_layer_info` | `() -> Dict[int, Dict[str, Any]]` | `{layer: {"count": int, "objects": [name, ...]}}` |
| `print_layer_info` | `() -> None` | 向 stdout 打印 |
| `__iter__` / `items` | — | 产出 `(layer, objects)`，按层升序 |
| `__len__` / `__contains__` | — | 图层数 / `layer in mgr` |

> `_cache_valid` 属性被多处赋值，但**从不被读取**——无实际作用的死字段。

#### 模块级单例与函数

```python
layer_manager = LayerManager()      # 全局唯一
objectRegister: dict = {}           # 全局名称 → 对象
def find_object_by_name(name: str = "") -> Optional[Any]
```

> **重要**：这两者是**模块级全局状态**。同一进程内生成第二份简历时，
> `Root` 等名字会被后者覆盖，前一棵布局树的对象仍留在 `layer_manager` 里。
> 见 7.14。

---

## 4. ResumeTemplate.py API（中层）

> ⚠️ **本章已于 2026-10-13 整体重写**。旧的 `generate_*` / `fill_*` 共 11 个符号
> **已全部移除**，替换为挂在 `LayoutObject` 上的方法 + 结果句柄。旧描述见
> README 的「10：35 中层重构」一节。

### 4.1 分层与调用形态

`ResumeTemplate.py` 是**中层**：把引擎构件封装成"简历版式词汇"。
它与引擎的分工是：

| 层 | 文件 | 是否认识"简历词汇" |
| --- | --- | --- |
| 底层 | `LayoutEngine.py` | **否**（只有构件、几何、样式） |
| 中层 | `ResumeTemplate.py` | 是（`STYLES`、节标题、详情……） |
| 顶层 | `ResumeCore.py` | 是（`Profiles`、`Section`、`Resume`） |

因此子模板方法**不能定义在 `LayoutEngine.py` 里**：那会让引擎认识领域词汇。
做法是在导入本模块时把函数挂到 `LayoutObject` 上（第 8 节 `_install_methods`），
并断言"目标成员不存在，拒绝覆盖"。

调用形态（每个模板都是"在传入节点之下挂载一个子模板"）：

```python
root.add_split(...)              # 而不是 generate_basic_subtemplate(root=...)
column.add_detail(...)           # 而不是 generate_section_details_template(root=...)
```

**当前 13 个已挂载方法**：

| 分类 | 方法 |
| --- | --- |
| 分栏 | `add_split` / `add_basic` |
| 左栏 | `add_info` / `add_photo` / `add_highlight` |
| 右栏 | `add_section_heading` / `add_section` / `add_detail` |
| 详情部件 | `add_detail_head` / `add_detail_body` |
| 通用 | `add_bullets` / `add_text_row` / `add_spacer` |

> **旧名已全部退役、不留兼容层**：`add_profile`、`add_profile_photo`、
> `add_section_title`、`add_details`、`add_details_summary`、`add_summary`、
> `add_details_list` 调用会直接得到 `AttributeError`。
> 顶层测试入口有断言守住这一点。

#### 4.1b 共享测量实例（模板内部**不要**新建 FPDF）

"高度由内容决定"要先知道"文本按可用宽折几行"，这需要 pdf 实例。实测（30 次测量）：

| 方式 | 耗时 | 备注 |
| --- | --- | --- |
| 复用同一实例 | **23.56 ms** | 本层采用 |
| 每次新建实例 | **30 559 ms** | 注册字体 345 ms/次，净增内存 **2.5 GB** |

更致命的是**未注册字体的实例测不了中文** —— `measure_text` 内部直接调
`pdf.get_string_width`，fpdf 对 CJK 抛 `FPDFUnicodeEncodingException`，
而引擎 `font_context` 的"优雅降级"只处理*变体缺失*、不处理*编码不支持*，
异常会一路冒泡（`_source_h` 内没有 try）。

因此本层提供：

```python
measure_pdf() -> FPDF        # 惰性创建的共享测量实例（只建一次，从不 output）
reset_measure_pdf() -> None   # 丢弃它（测试 / 同进程多份文档用）
wrapped_height(text, style, available_width, line_height_ratio=1.2, pdf=None) -> float
wrapped_lines(text, style, available_width, line_height_ratio=1.2, pdf=None) -> int
```

`wrapped_*` 的 `pdf=None` 表示用共享实例；显式传入则用调用方的实例（便于确定性复现）。

> ⚠️ 这是一处模块级可变状态（与引擎的 `layer_manager` / `objectRegister` 同类，
> 见 7.14 / SKILLS.md D4）。用 `reset_measure_pdf()` 显式管理它，别当它不存在。

### 4.2 `Style` 与 `STYLES`

`Style` **只有一份**，来自 `LayoutEngine`（批次 3 已下沉）。本层只提供 `STYLES` 字典。

> 旧版本在本层重复定义了一份 `class Style` 并遮蔽引擎版本，两边会悄悄漂移；
> 现已删除。`ResumeTemplate.Style is LayoutEngine.Style` 由顶层测试入口断言守住。

`STYLES` 键一览（19 个）：

| 键 | 用途 | 关键属性 |
| --- | --- | --- |
| `left_column` | 左栏底色 | `fill_color=RimuruBlue` |
| `profile_photo` | 证件照 | `fit_mode="cover"` |
| `name_image` / `section_title_image` | 图标 | `image_path=""`，待调用方填充 |
| `name_text` | 姓名 | LXGW 22pt 粗体 |
| `profile_text` | 联系方式行 | LXGW 12pt 粗体 |
| `contact_text` | 联系方式（备用） | LXGW 10pt |
| `skillsawards_title` / `skillsawards_text` | 技能/证书/荣誉 | LXGW 14pt / 10pt |
| `section_title_text` | 节标题 | LXGW 22pt 粗体，深蓝 |
| `detail_key_1` / `detail_time_1` / `detail_tags_1` | 详情三栏（默认） | 13pt 粗 / 7pt（`Padding.top(5)`）/ 8pt |
| `detail_key_2` / `detail_time_2` / `detail_tags_2` | 详情三栏（紧凑备选） | 12pt / 8pt / 8pt，**当前无调用方** |
| `detail_description` | 详情描述 | LXGW 10pt |
| `summary_text` | 个人总结正文 | LXGW 10pt |

### 4.3 版式默认值

集中为模块常量，不再散落在各函数体内：

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `DEFAULT_RATIO` | `[1.0, 2.5]` | 基础模板左右比例 |
| `DEFAULT_TITLE_HEIGHT` | `15.0` | 节标题整体高 |
| `DEFAULT_DIVIDER_HEIGHT` | `0.5` | 节标题分隔线粗细 |
| `DEFAULT_BRIEF_HEIGHT` | `10.0` | 详情三栏高 |
| `DEFAULT_BRIEF_RATIO` | `[2.0, 1.0, 2.0]` | 详情三栏比例 |
| `DEFAULT_ICON_WIDTH` | `4.0` | 个人信息左格宽 |
| `DEFAULT_TITLE_ICON_WIDTH` | `10.0` | 节标题左格宽 |
| `DEFAULT_PHOTO_WIDTH` | `30.0` | 证件照宽 |
| `PHOTO_ASPECT` | `1.6` | 证件照高 = 宽 × 此值 |
| `DEFAULT_ROW_INSET` | `3.0` | 个人信息行左缩进（旧 split 容器的 `Padding.left(3)`） |
| `DEFAULT_ROW_PAD_Y` | `3.0` | 行内图标上下最低留白 |

两个高度推算函数：

```python
profile_content_height(style=None, icon_width=0.0) -> float
    # max(字号 × 0.5, 图标宽 + 3)。旧实现把该行写死为 20mm
skills_row_height(style=None) -> float
    # 字号 × 0.5（与历史行为一致）
```

### 4.4 结果句柄

每个生成方法返回一个 dataclass 句柄，字段就是该模板实例的公开部件。
**名字只用于调试与兼容查找，正常取用一律走属性。**

| 句柄 | 字段 |
| --- | --- |
| `BasicHandle` | `node`（分栏容器）/ `left` / `right` |
| `ProfileHandle` | `node` / `split` / `icon_range` / `icon` / `text_range` / `text` |
| `PhotoHandle` | `node` / `photo` |
| `TitleHandle` | `node` / `split` / `icon_range` / `icon` / `text_range` / `text` / `divider` |
| `DetailsHandle` | `node` / `brief` / `col_key` / `col_time` / `col_tags` / `key` / `during_time` / `tags` / `details` / `description` |
| `SummaryHandle` | `node` / `details` / `description` |
| `SectionHandle` | `node` / `title`（`TitleHandle`）/ `details`（`List[DetailsHandle]`） |

全部句柄都有 `content` 属性（= `node`）与 `fill(...)` 方法：

| 句柄 | `fill(...)` 参数 |
| --- | --- |
| `ProfileHandle` | `text` / `image_path` |
| `PhotoHandle` | `image_path` |
| `TitleHandle` | `title` / `image_path` |
| `DetailsHandle` | `key` / `during_time` / `tags` / `description` / `description_height` |
| `SummaryHandle` | `description` / `description_height` |

`DetailsHandle` 与 `SummaryHandle` 另有 **`apply(data)`**：从 dict 或 dataclass
按字段名取值（取不到用默认值），便于把结构化数据直接喂进来。

`fill` / `apply` 都返回 `self`，可链式：

```python
col.add_details(index=0, brief_ratio=[2,1,2]).apply(detail).description.set_text("...")
```

### 4.5 子模板方法

#### `add_basic(ratio=None, left_padding=None, right_padding=None, layer=0) -> BasicHandle`

基础模板（左右分栏），同一份简历只应调用一次。

```
self
└─ {self.name}_split_container
     ├─ {self.name}_left_column   : RectangleObject
     └─ {self.name}_right_column  : LayoutObject
```

宽度按 `ratio` 归一化后**定死**，再作为"已构造格子"交给引擎的 `create_band` 排放
（`split_column_advanced` 返回 `parent`，此处需要带容器本身）。挂载点必须有正的内容宽。

#### `add_profile(index=0, icon_style=None, text_style=None, icon_width=4, gap=0, content_height=None, row_inset=3.0, layer=0) -> ProfileHandle`

一行两格（图标 + 文本）。

```
{prefix}_content（高 content_height，FLOW）
└─ {prefix}_split（横带，x = row_inset）
     ├─ {prefix}_icon_range : 宽 = icon_width
     └─ {prefix}_text_range : 占满剩余
```

横带宽度 = `content 可用宽 − row_inset`，与左移量同步收窄，避免右侧溢出。
`content_height=None` 时取 `profile_content_height(text_style, icon_width)`。

#### `add_profile_photo(index=0, icon_style=None, photo_width=30, layer=0) -> PhotoHandle`

```
{self.name}_photo_{index}_content（高 = photo_width × 1.6，FLOW）
└─ ..._photo : ImageObject（居中）
```

> 节点前缀刻意用 `photo_` 而非 `profile_photo_`：后者会与 `add_profile` 的
> `{self.name}_profile_{index}_content` **撞名**（`profile_photo_0_content` vs
> `profile_0_content`），导致注册表条目互相覆盖。

#### `add_section_title(index=0, icon_style=None, text_style=None, icon_width=10, gap=0, height=15, layer=0) -> TitleHandle`

```
{prefix}_content（高 height，FLOW）
├─ {prefix}_split（高 height − 0.5）
│    ├─ {prefix}_icon_range（Padding.bottom(3)，图标 BOTTOM）
│    └─ {prefix}_text_range（文本 BOTTOM）
└─ {prefix}_divider : RectangleObject（高 0.5，BOTTOM）
```

分隔线名字**含 index**（旧版不含，多个节标题会互相覆盖注册表）。

#### `add_details(index=0, name_key=None, *, 样式…, brief_ratio=None, brief_height=10, description_height=None, key="", during_time="", tags="", description="", layer=0) -> DetailsHandle`

```
{key}_content（SizeY.CONTENT）
├─ {key}_brief（高 brief_height，FLOW）
│    └─ {key}_brief_band : 三栏，比例 brief_ratio
│         ├─ col_0 → key            (LEFT/VCENTER)
│         ├─ col_1 → during_time    (CENTER/VCENTER，padding = time_style.padding)
│         └─ col_2 → tags           (RIGHT/VCENTER，Padding.right(1.5))
└─ {key}_details（SizeY.CONTENT）
     └─ {key}_description : TextObject(multi_line，LEFT/FLOW，Padding.all(2))
```

其中 `{key}` = `{self.name}_section_details_{index if name_key is None else name_key}`。

- `name_key` 用于让**跨节**的详情互不同名（`add_section` 传 `"{节号}_{节内序号}"`）；
  同一挂载点上按相同 `index` 建多个实例会同名并互相覆盖注册表。
- `description_height=None` → 描述高度由 `SizeY.CONTENT` 自动结算；
  给正值 → 固定高度（兼容旧的手动调参）。
- `brief_ratio` 必须恰好 3 个元素，否则抛 `ValueError`。

#### `add_summary(index=0, desc_style=None, description="", description_height=None, layer=0) -> SummaryHandle`

结构与 `add_details` 的 `content → details → description` 部分相同，无三栏。
命名空间独立：`{self.name}_summary_{index}`（旧版与节详情共用
`_section_details_` 前缀，迫使调用方手工错开编号）。

#### `add_text_row(name, text="", style=None, height=None, text_padding=None, row_padding=None, align_x=LEFT, align_y=VCENTER, multi_line=False, text_width=0, row_height_ratio=0.5, layer=0) -> TextObject`

"一行文本块" = 定高容器（FLOW）+ 其中的文本。技能 / 证书 / 荣誉三段共用此形状。

```
{name}_content（高 height，FLOW，row_padding）
└─ {name} : TextObject（width=text_width，height=0 即撑满行高，text_padding）
```

`height=None` 时取 `style.font_size × row_height_ratio`（默认 0.5）。
**此处刻意用 `TextObject.from_style` 直接构造**：`create_text_block` 的参数表
不含 `width` / `size_x`，而"一行文本"需要能控制宽度轴。

#### `add_spacer(name, height, layer=0) -> LayoutObject`

引擎 `create_spacer` 的方法风格包装（`parent=self`）。

### 4.6 组合模板

#### `add_section(section, index=0, title_style=None, icon_style=None, detail_styles=None, brief_ratio=None, brief_height=10, title_detail_gap=0.0, between_details_gap=0.0, layer=0) -> SectionHandle`

一个完整章节 = `add_section_title` + N × `add_details`（编号 `"{index}_{i}"`）。

- `section` 可以是 dict 或对象，需提供 `title` / `icon` / `details`；
- `detail_styles` 是透传给 `add_details` 的样式字典（键名
  `key_style` / `time_style` / `tags_style` / `desc_style`），模块提供便捷字典
  `BRIEF_DETAIL_STYLES`；
- `details` 为空时返回 `SectionHandle(None, None, [])`，不生成任何节点。

#### `add_details_list(items, start_index=0, between_gap=0.0, **detail_kwargs) -> List[DetailsHandle]`

列表入口：同一份蓝图实例化 N 条详情。返回列表与 `items` 一一对应。
`**detail_kwargs` 透传给 `add_details`。

### 4.7 尺寸与高度的约定

| 场景 | 做法 |
| --- | --- |
| 内容决定高度（推荐） | 默认行为：`SizeY.CONTENT` |
| 固定高度 | 显式传 `description_height` / `content_height` / `height` |
| 写入尺寸 | **必须用公开属性** `obj.height = N`；直接写 `_height` 会绕过尺寸方式解析 |

> ⚠️ **踩坑（实测）**：包装容器若留在默认的 `FILL`，而它又处在 `CONTENT` 父之下，
> 会走引擎的"退化规则"去读**尚未测量**的子元素高度，整条内容会塌缩为 0 高。
> `add_detail` / `add_detail_body` 因此显式把 `content` 与 `details` 设为 `SizeY.CONTENT`。

#### 4.7b 分条目模板的尺寸规则（`add_bullets`）

这是唯一**行高由内容折行决定**的模板，尺寸规则与其余模板不同：

| 量 | 规则 |
| --- | --- |
| 整行宽 | 父内容区宽（左缩进用**行容器的 padding** 表达） |
| 正文列宽 | `父内容区宽 − indent − bullet_size − gap` |
| 行高 | **正文在该列宽下折行后的实际高度**（`wrapped_height`），随宽度自动变化 |
| 引导符 | 边长 `bullet_size` 的正方形，竖直位置 `(首行实高 − bullet_size) / 2` |

引导符的竖直位置使**正方形中心落在正文首行中心**上（实测偏差 0.00mm）；
正文只有一行时，它就等价于"整行居中"。

> ⚠️ **不要用 `create_band` 搭这个模板**：`create_band` 会把所有格子高度
> 统一成"带高"并声明 `SizeY.FIXED`（引擎行为，见 3.4），而这里引导符格与
> 正文格的高度本就不同。因此 `add_bullets` 直接手工摆放两个格子。

> ⚠️ **也不要用 `SizeY.CONTENT` 去"自动撑高"这个行容器**：`CONTENT` 轴会把父的
> constraint **原样下传**（不扣 padding），子元素会拿到父外框宽而不是内容区宽，
> 于是正文列宽多算 `indent` 而溢出。行高改为**显式算好再用 `FIXED`**。

实测（父宽 100mm、indent 1、gap 2、边长 3.2、10pt）：

| 正文长度 | 列宽 | 折行 | 行高 |
| --- | --- | --- | --- |
| 长条目 | 93.8 | 2 行 | 8.47 |
| 短条目 | 93.8 | 1 行 | 4.23 |
| 长条目（父宽 60） | 53.8 | 3 行 | 12.70 |

### 4.8 改名对照（2026-10-13 重塑）

重塑**没有改变任何版面**（S0 基线 vs S6 现状：96 个节点结构/几何/属性全部一致），
但方法名变了。旧名**不留兼容层**。

| 旧名 | 新名 | 说明 |
| --- | --- | --- |
| `add_basic` | `add_split`（+ `add_basic` 保留为双栏预设） | N 栏、各栏颜色、各栏缩进 |
| `add_profile` | `add_info(variant="name"\|"contact")` | 一套模板两个预设，不分家 |
| `add_profile_photo` | `add_photo` | |
| `add_section_title` | `add_section_heading` | |
| `add_details` | `add_detail`（容器） | 另拆出 `add_detail_head` / `add_detail_body` |
| `add_summary` | `add_detail_body(prefix=...)` | **退役** |
| `add_details_list` | 调用方自己的循环 + `add_detail` | **退役** |
| — | `add_highlight` | **新增**：重点突出信息行 |
| — | `add_bullets` | **新增**：通用分条目 |

节点名随之变化（`profile_{i}_*` → `info_{i}_*`、`section_details_{i}_brief*` 仍在
但由 `add_detail_head` 产出、个人总结由 `summary_*` 改为
`section_details_summary_0_*`）。**结构路径未变**，这也是重塑期验收的判据。

### 4.9 资源清单（`Resources/` 不入库）

**决定（2026-10-13）**：`Resources/` 下的全部素材**一律不追踪**。
`.gitignore` 规则为 `Resources/*` + `!Resources/.gitkeep`；目录本身由
`Resources/.gitkeep` 保留。理由与后果见 `SKILLS.md` 的 A2。

素材缺失是**静默降级**，不是崩溃 —— 缺字体则中文变空白（退回内置 helvetica），
缺图标则该位置留空（`ImageObject.render` 对空路径直接返回）。
因此新克隆的仓库即便 `Resources/` 为空，两个测试入口仍能退出码 0。

#### 字体（引擎与全部文本都依赖）

| 文件名 | 用途 |
| --- | --- |
| `LXGWWenkai-Regular.ttf` | 正文；`pdf.add_font("LXGW", "", ...)` |
| `LXGWWenkai-Bold.ttf` | 粗体；`pdf.add_font("LXGW", "B", ...)` |

> 霞鹜文楷（LXGW WenKai），SIL OFL 1.1，可免费商用。
> 未注册 `B`/`I`/`BI` 变体时引擎会优雅降级并**打印提示**（见 3.4c）。

#### 图标与照片

| 文件名 | 由谁引用 | 用途 |
| --- | --- | --- |
| `icon_Profile_Name.png` | `ResumeTemplate.py` 测试入口 | 姓名行左侧图标 |
| `icon_Education_History.png` | 两个文件的测试入口 | "教育背景"节标题图标 |
| `icon_Project_History.png` | 两个文件的测试入口 | "项目经历"节标题图标 |
| `telephone.png` / `email.png` / `locate.png` | `ResumeCore._contact_rows` | 电话 / 邮箱 / 城市 |
| `social_media.png` | 同上 | QQ / 微信 |
| `contact_address.png` | 同上 | 联系地址 |
| `website.png` | 同上 | 个人网站 |
| `woman_student.png` | `ResumeCore._fill_left_column` | 姓名行默认头像 |
| `photo_1.png` | `ResumeCore` 测试入口 | 证件照 |
| `man_student.png` | **无代码引用** | 备用头像 |

> ⚠️ **中层本身不依赖任何图标文件**：`ResumeTemplate.py` 里的 5 处图片引用
> 全部位于 `__main__` 测试入口内；`add_profile` / `add_section_title` 只接收
> `icon_style` 与 `image_path` 参数，`STYLES["name_image"].image_path` 等一律为空串。
> 也就是说**素材是顶层与测试的事**，中层保持对具体图标的零知识。


## 5. ResumeCore.py API

### 5.1 数据类

#### `@dataclass Profiles`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `photo` | `str` | `""` | 证件照路径 |
| `name` | `str` | `""` | 姓名 |
| `telephone` | `str` | `""` | 电话 |
| `locate` | `str` | `""` | 现居城市 |
| `email` | `str` | `""` | 邮箱 |
| `social_media_qq` | `str` | `""` | QQ |
| `social_media_wechat` | `str` | `""` | 微信 |
| `contact_address` | `str` | `""` | 联系地址 |
| `title` | `str` | `""` | 求职头衔 |
| `website` | `str` | `""` | 个人网站/GitHub |
| `summary` | `str` | `""` | 个人简介 |

| 方法 | 返回 |
| --- | --- |
| `to_dict()` | `Dict[str, Any]` |
| `is_empty()` | `bool` —— `name/telephone/email/qq/wechat` **全空**才算空 |

#### `class SkillsAwards`

```python
SkillsAwards(
    skills_title: str = "掌握技能",       skills: List[str] = [],
    qualifications_title: str = "获得证书", qualifications: List[str] = [],
    awards_title: str = "获得荣誉",        awards: List[str] = [],
)
```

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `is_empty()` | `bool` | 三个列表全空 |
| `get_char_skills()` | `str` | 用 `\n` 连接（批次 0 已修，不再有末尾换行） |
| `get_char_qualifications()` | `str` | 用 `\n` 连接（同上） |
| `get_char_awards()` | `str` | 用 `\n` 连接（同上） |

> ✅ 三个 `get_char_*` 原先用循环拼接，`if i < len(...)` 恒为真导致**每段结尾多一个 `\n`**；
> 批次 0 已改为 `'\n'.join(...)`。历史记录见 7.15。
>
| `blocks()` | `List[tuple]` | `[(块名, 标题, 条目列表), ...]`，只含非空块（供编排循环用） |

> ✅ **可变默认参数已消除（2026-10-13）**：改为 `Optional[List[str]] = None` 再在
> 函数体内 `list(...)` 复制。`Details.description_height` 与 `Resume.Lead` 同步处理，
> 见 7.10。

#### `@dataclass Details`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `key` | `str` | `""` | 学校/项目/公司名 |
| `during_time` | `str` | `""` | 起讫时间 |
| `tags` | `str` | `""` | 专业/技术栈 |
| `description` | `str` | `""` | 详情描述 |
| `description_height` | `Optional[float]` | `None` | 描述排版高度（mm）。`None` = 由引擎按真实行数**自动结算**；给正值则固定高度 |

方法：`to_dict()`、`is_empty()`（`key` 与 `description` 全空才算空）。

#### `@dataclass Section`

字段：`icon: str = ""`、`title: str = ""`、`details: List[Details] = field(default_factory=list)`。

方法：`add_detail(detail) -> Section`（链式）、`remove_detail(index) -> bool`、`to_dict()`、
`is_empty()`（`title` 与 `details` 全空才算空）。

### 5.2 间距默认值

模块级私有常量 `__Lead_default_settings__`（键名 → mm 值）：

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `Left_Column_Above_All` | 10 | 左栏上方留白 |
| `Left_Column_Below_Photo_Avove_Name` | 5 | 照片下方、姓名上方 |
| `Left_Column_Below_Name_Above_Contacts` | 5 | 姓名下方、联系方式上方 |
| `Left_Column_Between_Contacs` | 5 | 联系方式之间 |
| `Left_Column_Below_Contacts_Above_Skills&Awards` | 5 | 联系方式下方、技能上方 |
| `Left_Column_Between_Skills&Awards` | 5 | 技能/证书/荣誉之间 |
| `Left_Column_Below_All` | 5 | 左栏底部 |
| `Right_Column_Above_All` | 10 | 右栏上方 |
| `Right_Column_Between_SectionTitle_SectionDetails` | 3 | 节标题与节详情之间 |
| `Right_Column_Between_Sections` | 5 | 节之间 |
| `Right_Column_Between_Details` | 5 | 节内详情之间 |
| `Right_Column_Below_All` | 5 | 右栏底部 |

> 键名含 `&` 与拼写错误（`Above`→`Avove`、`Contacts`→`Contacs`、`Between_Sections`）。
> 因为是用 `&` 访问的字符串键，改名会影响调用方，建议保持不动作兼容处理。

### 5.3 `class Resume`

```python
Resume(
    intend_company: str = "",
    intend_job: str = "",
    profile: Optional[Profiles] = None,
    skills_awards: Optional[SkillsAwards] = None,
    sections: Optional[List[Section]] = None,
    summary_icon = "",
    summary: str = "",
    summary_title: str = "个人总结",
    summary_height: Optional[float] = None,
    Lead: dict = {},          # ← 可变默认参数（见 7.10）
)
```

构造函数副作用：向 `self.Lead` **就位补齐**所有缺省键，并对每个缺失键打印
`>>>⚠未指定间距：{key}，将该间距设定为默认值：{value}。`

| 方法 | 签名 | 返回 |
| --- | --- | --- |
| `add_section` | `(section: Section) -> Resume` | self（链式） |
| `remove_section` | `(index: int) -> bool` | 是否成功 |
| `get_file_name` | `() -> str` | `{姓名}_{职位}_{公司}.pdf`，非法字符替换为 `_` |
| `Generate` | `(debug: int = 0, output_dir: str = "./output") -> str` | 生成的 PDF 路径 |
| `get_pdf_path` | `() -> Optional[str]` | |
| `get_root` | `() -> Optional[LayoutObject]` | |
| `find` | `(name: str) -> Optional[LayoutObject]` | 委托 `root.find_by_name` |

`Generate(debug=...)` 的三种模式：

| `debug` | 行为 |
| --- | --- |
| `0` | 仅 `root.render(pdf, is_fill=False)` |
| `1` | 仅 `root.render_debug(pdf, is_fill=True, ...)` |
| 其他 | 先 `render_debug` 再 `render` |

`Generate` 的完整流程：校验 `profile.is_empty()` → 建 PDF/加页 → 注册 LXGW 字体
（失败静默吞掉）→ 设置元数据 → 建 `Root`（210×297，padding 10）→ `root.add_basic(...)`
→ 从 `BasicHandle` 直接取左右栏 → `_fill_left_column()` → `_fill_right_column()`
→ **`root.layout(pdf=pdf, force=True)`** → 渲染 → 输出到 `output_dir`。

> ⚠️ **`layout(pdf=...)` 这一步不能省**：`SizeY.CONTENT` 的高度要靠真实文本测量才能结算，
> 而精确测量需要 `pdf` 实例。旧的固定高度写法不需要它，所以旧流程没有这一步。

`_fill_left_column()` 顺序：上方留白 → 证件照 → 照片/姓名间留白 → 姓名行 →
姓名/联系人间留白 → 联系方式（`_contact_rows()` 的每一条 + 间隔留白，N 条只加 N-1 个）
→ 技能/证书/荣誉（`_fill_skills_awards()`）→ 底部留白。

`_fill_right_column()` 顺序：上方留白 → 遍历 `sections`（每节一次 `root.add_section(...)`）
→ 节间留白 → 个人总结（节标题 + 留白 + `add_summary`）→ 底部留白。

> ✅ **7.12 已消除**：编号不再由顶层手工维护，改由 `add_section` 内部按
> `"{节号}_{节内序号}"` 分配，不存在"详情编号跳号"或"跨节同名"的问题。

---

## 6. 命名与查找约定

> ⚠️ **2026-10-13 起，名字不再是取用部件的正常途径。**
> 中层返回**结果句柄**，部件一律走属性访问（`handle.description`）；
> 名字只用于调试、注册表兼容与外部查询。
> 下面的表仍有效，但调用方不该再依赖它定位对象。

规则：`{挂载点.name}_{模板标识}_{index}_{部件}`

| 部件名 | 所属方法 | 类型 |
| --- | --- | --- |
| `profile_{i}_content` | `add_profile` | `LayoutObject` |
| `profile_{i}_split` | 同上 | `LayoutObject` |
| `profile_{i}_icon_range` / `profile_{i}_icon` | 同上 | `LayoutObject` / `ImageObject` |
| `profile_{i}_text_range` / `profile_{i}_text` | 同上 | `LayoutObject` / `TextObject` |
| `photo_{i}_content` / `photo_{i}_photo` | `add_profile_photo` | `LayoutObject` / `ImageObject` |
| `section_title_{i}_content` | `add_section_title` | `LayoutObject` |
| `section_title_{i}_split` / `_icon_range` / `_icon` / `_text_range` / `_text` | 同上 | |
| `section_title_{i}_divider` | 同上（**含 index**，7.16 已修） | `RectangleObject` |
| `section_details_{i}_content` | `add_details` | `LayoutObject` |
| `section_details_{i}_brief` / `_brief_band` / `_brief_col_0..2` | 同上 | `LayoutObject` |
| `section_details_{i}_key` / `_during_time` / `_tags` | 同上 | `TextObject` |
| `section_details_{i}_details` / `_description` | 同上 | `LayoutObject` / `TextObject` |
| `section_details_{C}_{i}_*` | `add_section`（`C`=节号，`i`=节内序号） | |
| `summary_{i}_content` / `_details` / `_description` | `add_summary`（**独立命名空间**，7.2 已修） | |
| `{块名}_title_content` / `{块名}_title` / `{块名}_text_content` / `{块名}_text` | `add_text_row`（`{块名}` ∈ skills / qualifications / awards） | |
| `qualifications_*` / `awards_*` | 同上 | |
| `Lead_*` | 留白对象 | `LayoutObject` |

**关键推论**：

1. 传给 `generate_*` 的 `root` 必须与传给 `fill_*` 的 `root` **是同一个对象**（同一个 `.name`）。
2. `ResumeCore` 里左右栏的 `name` 是 `Root_left_column` / `Root_right_column`，
   因此所有填充函数的 `root` 必须传**左右栏**，不能传 `Root`。
   （`ResumeCore.py:1533` 附近的 key_names 里那批 `Root_section_title_1_content` 找不到，
   正是因为它们实际叫 `Root_right_column_section_title_1_content`。）
3. 同名节点会被后者覆盖 `objectRegister`，所以 `dividing_line`、`Lead_*` 这类固定名不可用于回查。
4. `find_by_name` 是**从 `root` 向下递归**，不是查全局注册表。传错 `root` 就是 `None`。

---

## 7. 已知缺陷与风险清单

按"重构时必须先解决"的顺序排列。每条都给出位置与复现条件。

### 7.1 `ResumeCore.py` 导入断裂（阻断级）— ✅ 批次 0 已修

- **位置**：`ResumeCore.py:65`
- **现象**：`from ResumeTemplateV2 import (...)` → `ModuleNotFoundError`，`Resume.Generate` 完全不可用。
- **原因**：文件已改名 `ResumeTemplateV2.py` → `ResumeTemplate.py`，导入未同步。
- **同处**：`ResumeCore.py:9` 的文档字符串也写着 `ResumeTemplateV2`。
- **修复**：导入改为 `from ResumeTemplate import (...)`，文档字符串同步。
  并在 `ResumeCore.py` 的测试入口加入**导入契约断言**（校验 12 个必需符号），
  模板文件名再次变更时会在测试入口立即报错，而不是运行到一半才崩。

### 7.2 details 与 summary 模板共用命名空间（逻辑级）— ✅ 功能分支已修（2026-10-13）

- **原位置**：`ResumeTemplate.py` 的 `generate_section_details_template` 与
  `generate_summary_template` 使用**同一个** `prefix = f"{root.name}_section_details_{index}"`。
- **原风险**：两者用相同 `index` 时 `objectRegister` 互相覆盖，填充可能改到另一个模板的对象上。
- **原缓解**：`ResumeCore._fill_right_column` 让 `section_details_index` 在 summary 之前已递增过，
  所以恰好不撞号——这是**巧合**，不是设计。
- **修复**：`add_summary` 改用独立命名空间 `{self.name}_summary_{index}`，
  不再与节详情共用前缀；顶层测试入口断言 `Root_right_column_summary_0_description` 存在。

### 7.3 绕过 `add_child` 直接挂载（一致性级）— ✅ 批次 2 已修

- **原位置**：`ResumeTemplate.py:306-323`（`split_column_advanced`）
- **现象**：`container.children.append(left_obj)` 直接改列表，`left_obj.parent = container` 单独赋值。
- **后果**：`add_child` 里的 wrap + 几何缓存失效**都不会触发**；末尾只补了 `parent.invalidate_wrap_cache()`，
  **几何缓存没失效**。若左右栏在分栏前已被查询过几何值，会返回脏数据。
- **修复**：`split_column_advanced` 移入 `LayoutEngine.py` 并改为 `create_band` 的包装，
  对象挂载走 `add_child`，失效由机制保证，不再依赖手工补调。
- **同类**：`LayoutEngine.py` 的 `parent.children = []`（见 7.4，同批已修）。

### 7.4 `create_columns` 清空父元素子节点（破坏级）— ✅ 批次 2 已修

- **原位置**：`create_columns` 中的 `parent.children = []`
- **现象**：调用 `create_columns(parent=...)` 会**丢弃 parent 已有的全部子元素**。
- **后果**：被丢弃的子元素 `parent` 指针仍指向原 parent（悬空引用），
  且它们的 wrap/几何缓存未失效。调用方若先 `add_child(title)` 再 `create_columns`，title 就消失了。
- **修复**：删除该行。`create_columns` 改为两趟实现 —— 先算各栏宽度，
  再交给 `create_band` 建带容器并挂载，既有子元素被保留。
  测试入口的断言已从"固化现状"反转为"既有子元素被保留"。

### 7.5 `get_true_height()` 空实现

- **位置**：`LayoutEngine.py:1017-1018`
- **现象**：函数体只有一行 `None`（表达式语句），**隐式返回 `None`**。
- **后果**：名字暗示返回浮点高度，实际返回 `None`。任何 `h = obj.get_true_height() * 2` 都会 `TypeError`。

### 7.6 `ImageObject._calculate_wrap_height` 内部新建 FPDF 实例 — ✅ 批次 4.2 已修

- **原位置**：`ImageObject._calculate_wrap_height` 内为读图片宽高比，
  临时 `from fpdf import FPDF; pdf = FPDF()`。
- **原后果**：每次尺寸计算都构造一个 PDF 对象；且 `try/except` 吞掉所有异常后
  回退成"高 = 宽"。
- **修复**：改为 `ImageObject._source_h(pdf=None)` + `_image_aspect_ratio(pdf=None)`：
  优先用**外部传入的** `pdf`（`layout(pdf=...)` 一路传进 `_measure`），
  没有时用 Pillow 直接读图片头部，两者都不可用时才退回保守估算。
  **不再有任何地方内部 new FPDF 实例。**

### 7.7 两套不一致的文本行数估算 — ✅ 批次 5 已修

- **原位置**：`calculate_text_size` 用 `int(text_width / effective_width) + 1`；
  `_calculate_wrap_height` 用 `len(self._text) // 20 + 1`。
- **现象**：同一段文本，两个方法给出的行数不同，且**两套都不准**。
- **后果**：算出的高度与渲染时的实际换行数不匹配，多行文本会被裁切或溢出。
- **修复（批次 5）**：两者都改为调用同一个 `measure_text(pdf, runs, available_width)`。
  **渲染时复用同一份 `lines`**，因此测量行数与绘制行数的一致性**由构造保证**，
  不再依赖估算公式。测试入口 12.1 / 12.2 固化（行数随可用宽单调、总高 = 行数 × 行高）。

### 7.8 `description.height` 硬编码 50 —— ✅ 两层均已消除（功能分支 2026-10-13）

- **原位置**：`ResumeTemplate.py` 的详情/总结模板，构造时 `height=50`，
  再由 `fill_*` 回写 `content._height` 与 `description._height`。
- **原后果**：忘记调用填充函数，该块就固定占 50mm。
- **修复（引擎侧，批次 3）**：`create_text_block` 的 `height` 是显式参数，不再有硬编码常量。
- **修复（功能分支）**：`add_details` / `add_summary` **不再写死高度，也不再回写 `_height`**，
  改为 `SizeY.CONTENT` 由引擎按真实行数自动结算。
  实测自动结算值与旧固定值逐项等值（12 / 6 / 12 / 12）；
  需要固定高度时显式传 `description_height=N`。

### 7.9 `RectangleObject.render` 忽略 `is_fill`

- **位置**：`LayoutEngine.py:1656-1663`（原分支被注释，改为无条件 `'F'`）
- **后果**：`RectangleObject` 永远实心填充，`is_fill=False` 时也不例外，
  与 `TextObject` / `ImageObject` 的 `is_fill` 语义不一致。
  调试渲染时所有矩形都是实心的，会盖住下层内容。

### 7.10 可变默认参数 — ✅ 两层均已修（功能分支 2026-10-13）

| 位置 | 参数 | 状态 |
| --- | --- | --- |
| `LayoutEngine.py`（`Style.__init__`） | `padding: Padding = Padding.all(0)` | ✅ **批次 4.4 已修**：改为 `padding=None` → 构造时 `Padding.all(0)`，每次新建 |
| `ResumeCore.py`（`SkillsAwards`） | `skills` / `qualifications` / `awards: List[str] = []` | ✅ **功能分支已修**：改为 `Optional[List[str]] = None`，函数体内 `list(...)` 复制 |
| `ResumeCore.py`（`Resume.__init__`） | `Lead: dict = {}` | ✅ **功能分支已修**：改为 `Optional[dict] = None`，函数体内 `dict(...)` 复制 |
| `ResumeCore.py`（`Details`） | `description_height: float = 12.0`（不可变，但语义已变） | ✅ 改为 `Optional[float] = None`，语义见 7.8 |

- **后果**：默认对象在多次实例化间共享。此前无代码原地修改它们，所以尚未爆雷，
  但任何 `style.padding.left = 5` 或 `self.Lead["x"] = ...` 都会污染其他实例。
- **引擎侧的修法**：`padding` 默认值改为 `None`，在 `__init__` 里 `Padding.all(0) if padding is None else padding`。
  对外行为不变（默认仍是全 0），但每个实例拿到独立的 `Padding`。
  测试入口有断言固化（8.6：两个 `Style` 的 padding 必须是不同对象）。

### 7.11 渲染返回值契约不统一 — ⚠️ 部分已修

**（a）`render_debug()` 完全没有返回值 —— ✅ 已修**

- **原现象**：四个 `render_debug` 实现（`LayoutObject` / `TextObject` / `ImageObject` /
  `RectangleObject`）**末尾都没有 `return` 语句**，因此一律隐式返回 `None`。
  而它们内部明明有 `for child in self.children: child.render_debug(...)` 的递归，
  却不冒泡任何值。
- **后果**：调试路径拿不到"最后渲染到哪"。更隐蔽的是 —— 一旦把测试入口的
  `root.render(...)` 换成 `root.render_debug(...)`，
  针对返回值的断言就会以 `AssertionError: ... 实际返回 NoneType` 形式炸掉，
  而这个报错**与 `render()` 的契约毫无关系**，极易误判为回归。
- **修复**：四个实现补上返回值，语义与各自的 `render()` 对齐
  （`LayoutObject`/`TextObject` → 数值 y；`ImageObject`/`RectangleObject` → `(宽, 高)` 二元组）；
  `pdf=None` 或有效尺寸非正时显式返回 `None`。
- **顺带修掉一个隐藏崩溃**：`ImageObject` / `RectangleObject` 的 `eff_w`/`eff_h`
  原先只在 `if show_name:` 分支内赋值。由于此前函数末尾没有 `return`，
  这两变量在 `show_name=False` 时从未被读取，问题被掩盖；
  补返回值后若直接引用就会 `UnboundLocalError`。已将取尺寸提到分支之外。

**（b）`render()` 自身返回值不统一 —— 待批次 4**

| 类 | `render()` 返回 |
| --- | --- |
| `LayoutObject` | `float`（last_y） |
| `TextObject` | `float`（`abs_y + line_height` 或 `pdf.get_y()`） |
| `ImageObject` | `Tuple[float, float]` |
| `RectangleObject` | `Tuple[float, float]` |

`LayoutObject.render` 里的 `last_y` 会被 tuple 覆盖，父元素拿到的"最后 y"含义漂移。
测试入口的断言目前接受上述两种形态，但**拒绝 `None`**，因此能同时守住
`render` 与 `render_debug` 两条路径。

### 7.12 `section_details_index` 双重递增 — ✅ 功能分支已消除（2026-10-13）

- **原位置**：`ResumeCore.py` 的 `_fill_right_column`，同一循环体内两处 `+= 1`
  （一处为"详情间间距"预留编号）。
- **原后果**：节内详情编号跳号（0,1,3,4,…）。模板生成与填充用同一个 `index`，
  所以**功能正确**，但 `objectRegister` 里出现大量未使用的编号，
  `Details[i]` 与模板 index 不再对应。
- **修复**：编排改为 `root.add_section(section)` 一次落地，
  编号由 `add_section` 内部按 `"{节号}_{节内序号}"` 统一分配，不再有跳号，
  也顺带消除了"跨节详情同名"的隐患。

### 7.13 渲染日志无法关闭

- **位置**：`LayoutEngine.py:41-50`（`timer` 装饰器）遍布所有 `render` / `render_debug`
- **后果**：一次简历生成打印数千行；`self.name` 依赖被装饰对象有 `.name`，非 `LayoutObject` 会崩。

### 7.14 全局状态不可重入

- **位置**：`LayoutEngine.py:285` `layer_manager = LayerManager()`、`292` `objectRegister = {}`
- **后果**：同进程生成两份简历时，`Root` 等名字互相覆盖，`layer_manager` 累积前一份的对象。
  没有 `reset()` 接口。

### 7.15 `SkillsAwards.get_char_*` 末尾多余换行 — ✅ 批次 0 已修

- **位置**：`ResumeCore.py:173-195`（原实现）
- **现象**：`if i < len(self.skills)` 恒为 `True`（应为 `i < len(...) - 1`），每项后都加 `\n`。
- **后果**：多行文本末尾多一个空行，`pdf.multi_cell` 会多占一行高度。
- **修复**：三个方法改为 `'\n'.join(...)`，语义等价且无末尾换行。
  测试入口已加入断言：`["Python","C++"] → "Python\nC++"`、单元素 `["a"] → "a"`、空列表 `→ ""`。

### 7.16 调试/查询辅助的若干不一致 — ✅ 功能分支部分已修（2026-10-13）

- ⚠️ `LayerManager._cache_valid` 被写从不被读。（**未修，属引擎**）
- ✅ `add_section_title` 的 `divider` 命名**已含 index**，多个节标题不再互相覆盖注册表。
- ✅ `add_profile_photo` 的 `photo` 直接挂到 `content` 下，构造参数不再误导。
- ✅ 中层自检里那批"永远不会命中的名字"已定位并修正：5 个查询名漏写了
  `_right_column` 前缀，此前一直打印"未找到"却仍退出码 0（静默假通过）。

#### 7.16.1 `dividing_line` 同名对象的两套解析结果不同（批次 0 已实测确认）

原先只记为"命名缺 index、会互相覆盖注册表"，**实测发现更精确的机制**：
两者保留的是**不同**的那个对象。

以 `ResumeTemplate.py` 的测试入口为例（生成 2 个节标题，均挂在 `Root_right_column` 下）：

| 解析途径 | 保留哪一个 |
| --- | --- |
| `objectRegister[name]` | **最后注册**的那个（第 2 个节标题的） |
| `root.find_by_name(name)` | 深度优先遍历中**最先遇到**的那个（第 1 个节标题的） |

两者 `is` 比较为 `False`。这是第 6 章"命名即接口"约定的直接后果：
`objectRegister` 是"后写覆盖"的全局字典，而 `find_by_name` 是"先到先得"的树遍历，
**同一份代码里两套按名字查找的语义并不一致**。

`ResumeTemplate.py` 测试入口已加入断言固化该现状（`11.3` 节）。

### 7.17 联系方式模板被重复挂载（批次 0 已修）

- **位置**：`ResumeCore.py:_fill_left_column` 的"添加联系人文本到左栏"循环
  （修复前为第 594-603 行，其中 `root.add_child(a)` 在第 600 行）
- **现象**：

  ```python
  a = generate_profile_template(root, index, content_height=...)  # 内部已 root.add_child(content)
  root.add_child(a)                                               # ← 冗余，同一对象挂载第二次
  ```

  `generate_profile_template` 内部已在 `ResumeTemplate.py:477` 执行 `root.add_child(content)`，
  外层再挂一次，导致每条联系方式的 `profile_{index}_content` 在 `root.children` 中出现**两次**。

- **后果**（实测）：
  - `Root_left_column.children` 从 20 项膨胀到 23 项（多出 3 个重复项）。
  - 因为 `align_y=FLOW`，重复项会各占一次纵向空间，**实际挤掉了约 18mm**。
  - 复现数据（4 条联系方式）：修复前联系区块高度约 108mm，修复后 90mm。
- **影响面**：只有 `ResumeCore` 的这条循环有该问题。
  `generate_section_title_template`、`generate_section_details_template` 等
  在 `ResumeCore` 中的调用均**未**重复挂载（只赋值返回值）。
- **修复**：删除冗余的 `root.add_child(a)`，并加注释说明模板函数自带挂载。
  测试入口加入不变量断言：**父元素的直接子元素必须两两不同**
  （`ResumeCore.py` 测试入口 `6.1` 节），另加"同一父元素下不得有同名兄弟"（`6.2` 节）。
- **验证**：修复前后按 `output_dir` 生成同一份简历，
  归一化（剥离 `CreationDate`/`ModDate`/`ID`/`Producer`）后 PDF 相差 5 字节，
  左栏 FLOW 布局从"每条联系方式占两段"变为"每段一次"，总高度 108mm → 90mm，与预期一致。

### 7.18 联系方式末尾多一个间距（批次 0 已修）

- **位置**：`ResumeCore.py:_fill_left_column` 的联系方式循环
  （修复前为第 606-607 行）
- **现象**：

  ```python
  # 不在最后一个联系方式下添加联系方式之间的间距。
  if i == len(contacts_text):      # ← i ∈ [0, len-1]，该条件恒为假
      break
  ```

  写在代码里的本意（末条不加间距）从未生效，是**死代码**。
- **后果**（探针实测）：4 条联系方式会生成 **4 个** `Lead_Left_Column_Between_Contacs_*`，
  正确值应为 3 个。末条下方凭空多出 5mm（`Left_Column_Between_Contacs` 默认值），
  并把这个偏移量传递给它之后的"技能/证书/荣誉"整块内容。
- **修复**：改为 `if i == len(contacts_text) - 1: break`。
- **验证**：测试入口 `6.3` 节断言 —— 按实际填入的联系方式字段数反推期望间距数
  （`N` 条 → `N-1` 个），当前为"4 条 → 3 个间距"。
- **注意**：这与 7.17（重复挂载）是**两个独立缺陷**，恰好都在同一段循环里，但成因与影响量不同
  （7.17 多占一整块内容的高度约 18mm，7.18 多占 5mm 间距）。

### 7.19 `wrap_height=True` 使高度塌缩为 padding（父子高度自指）— ✅ 批次 4.2 已修

- **位置**：`LayoutEngine.py` 的 `get_parent_available_area()`（约 676-692 行）
  与 `get_effective_height()`（约 798-846 行）的交互
- **现象**：开启 `wrap_height` 后，**高度不是撑开到内容，而是塌缩成只剩 padding**。
  同一结构、只改 `wrap_height` 标志的实测对比：

  | 配置 | 有效高 | 组成 |
  | --- | --- | --- |
  | `height=0, wrap_height=False` | **49.00** | 5 + 10 + 20 + 15（恰好等于内容总高） |
  | `height=0, wrap_height=True` | **4.00** | 只剩 `padding.all(2)` × 2 |

- **根因**：父子高度的**循环依赖**。插桩追踪过程：

  ```
  >> _calculate_wrap_height(Box) 进入: _height=0
       get_effective_height(RB) = 300        ← 拿祖父的高度
     >> _calculate_wrap_height(Box) 进入: _is_wrapping=True   ← 重入
     << _calculate_wrap_height(Box) 返回 0                      ← 软降级
       get_effective_height(Box) = 0        ← ←← 关键：父高此时是 0
       get_effective_height(C0) = 0.0       ← 子元素被 0 高度父容器裁剪成 0
       get_effective_height(C1) = 0.0
       get_effective_height(C2) = 0.0
  << _calculate_wrap_height(Box) 返回 4.0   ← 只有 padding，子元素全被吃成 0
  ```

  子元素的有效高度被父可用高度裁剪（`min(base_height, avail_h)`），
  而父可用高度又来自父的有效高度 —— 自指。`_is_wrapping` 只防住了无限递归，
  返回 0 之后整棵子树归零。

- **为何 `wrap_height=False` 反而"看起来对"**：父元素 `_height=0` →
  `get_effective_height()` 取满父可用高 → 恰好等于内容自然高度。
  这是**巧合**（内容正好填满），一旦内容比可用空间小或大，这个巧合就破了。
- **影响**：这是"矩形包围内容"的核心阻断点。**在修好之前，该能力在引擎里是反向的** ——
  开启 wrap 比不开启更糟。
- **修法方向**：引入显式的"测量上下文"，让测量时向上找最近的**已知高度**祖先，
  而不是直接父；或者对子元素在父高待求时不做父高裁剪。
  两种方向都需要先明确 `wrap_content()` 的方向性（自底向上 vs 自顶向下），见 8.11。

### 7.20 `invalidate_wrap_cache` 后 `_height` 不复位，wrap 结果永久卡死 — ✅ 批次 4.2 已修

- **位置**：`invalidate_wrap_cache()`（约 572-579 行）与
  `_calculate_wrap_height()` 开头的 `if self._height > 0: return self._height`（约 459-462 行）
- **现象**：一旦算出过 wrap 高度，之后**即使子元素变化、缓存被正确失效，重算也拿不回新值**：

  ```
  两个子元素(10+20)后: _height=4.0
  再加一个(15)之后:    _height=4.0   wrap_cache_valid=False
  重新 wrap_content(): 4.0
  force=True 重算:     4.0          ← force 也救不回来
  ```

- **根因**：`invalidate_wrap_cache()` 清的是 `_wrap_cache_valid` / `_height_set_by_wrap`，
  但**不动 `_height`**。而 `_calculate_wrap_height()` 开头就把 `_height > 0` 当作
  "用户显式指定的高度"直接返回。第一次写进 `_height` 的 wrap 结果因此永久生效。
  当时只能手工把 `_height` 归零才能重新计算。

- **修复（批次 4.2）**：整个惰性缓存机制被两趟遍历取代。
  尺寸不再"算一次写进 `_height` 再复用"，而是每次 `layout()` 从根整体重算。
  失效只剩一个布尔标记 `_layout_valid`，`invalidate_geom_cache()` 与
  `invalidate_wrap_cache()` 现在等价（后者保留为兼容入口）。
  `_wrap_cache_valid` / `_height_set_by_wrap` / `_cached_wrap_height` / `_is_wrapping`
  等字段已全部删除。
- **验收**：测试入口 9.8 断言 —— 加子元素后包围高从 `h` 增到 `h+25`；
  再改某子元素高度后变为 `h+55`；每步都拿到新值。
- **影响**：直接打击"矩形包围内容"的核心用法 —— 动态增删内容时矩形必须跟着变。
- **与 7.19 的关系**：7.19 决定"第一次算就算不对"，7.20 决定"算错之后再也算不回来"。
  两者叠加使 `wrap_content` 实际上不可用，因此同批修复。

### 7.21 `wrap_width` 完全不可用 — ✅ 批次 4b 已修

- **位置**：`_calculate_wrap_width()`（约 499-535 行）与
  `get_effective_width()`（约 772-796 行）的交互
- **现象**：收窄包围盒完全不能工作，实测三条路径全部失败：

  | 配置 | 有效宽 |
  | --- | --- |
  | `wrap_width=True`，子元素 `width=0` | **0.00** |
  | `wrap_width=True`，再叠加一个 `width=30` 的子元素 | **0.00** |
  | `wrap_width=True`，盒子构造宽 60 或 0 | 均无改善 |

- **根因**：原理上自相矛盾 —— 收窄要求子元素宽度由自己决定，
  但引擎里子元素 `_width == 0` 的语义是"撑满父可用宽"，而父宽正是待求值。
  `_calculate_wrap_width()` 取 `max(child_width)`，而子元素宽度又是从父宽推出来的。
- **额外问题**：`_cached_wrap_width` 只在 `get_effective_width()` 的
  `self._wrap_cache_valid and self._width_set_by_wrap` 分支里被读，
  而 `_calculate_wrap_width()` 的重入保护直接返回当前 `_width`（自指的 0），
  所以这条路径基本不可能返回有意义的宽度。
- **影响**：限制了包围盒的形态 —— 只用 `wrap_height` 可以接受，
  但"紧贴内容的矩形框"离不开宽度收窄。
- **修法（批次 4b）**：为"内容固有宽度"定义了一条独立路径，不复用
  `_width == 0 → 撑满父宽` 的既有语义：

  | 新增 | 作用 |
  | --- | --- |
  | `_source_w(pdf)` | 内容固有宽度。`LayoutObject` = 子元素贡献最大值 + padding；`TextObject` 覆盖为字符串宽度 |
  | `_contribution_w()` | 本元素对**父** `CONTENT` 宽度的贡献：`FIXED` → 声明宽；`FILL`（父非 CONTENT）→ 0；`FILL`（父为 CONTENT）或 `CONTENT` → 自身固有宽 |
  | `TextObject._estimate_text_width()` | 按字符类别估算：CJK/全角 = 1.0×字号，其余 = 0.5×字号 |

  测量时 `SizeX.CONTENT` 的父元素取**子元素的固有宽贡献**，而不是子元素的"已算宽度" ——
  后者那时刻还是 0（FILL 子元素要等父定完）。

- **验收**：收窄三条路径全部可用 ——
  `子元素全无固有宽` → 0；`含 FIXED 宽 30 的子元素` → 30；
  `双向 CONTENT 包围文本` → 54 × 13.2（= 文本固有 48 × 7.2 + padding 6）。

- **顺带修正了一处错误设计**：批次 4.2 曾判定"`CONTENT` 父 + 直接 `FILL` 子"是循环并报错，
  批次 4b 实测确认**不是循环**（约束是传参的，环在设计上已断开），
  改为**退化规则**：`CONTENT` 父在某轴上的 `FILL` 子按内容定尺寸。

- **与批次 5 的关系**：`_source_w` / `_source_h` 的文本实现目前是估算。
  批次 5 把它换成基于 `pdf` 的真实测量即可，接口不变。

---

## 8. 重构方向（按优先级）

> 本章是**建议**，不是已实施内容。采纳与否、先后顺序待定。

### 原则

**能下沉到 `LayoutEngine.py` 的，必须满足两个条件**：
1. **与"简历"无关**——不知道"姓名""联系方式""节标题"是什么；
2. **在至少两个不同上层场景里会重复出现**。

不满足的（如"节标题 = 图标 + 文字 + 分割线"）留在 `ResumeTemplate.py`。

### 8.1 【核心】把 `split_column_advanced` 下沉为引擎的"横向带"构件 — ✅ 批次 2 已完成

- **原状**：分栏能力住在 `ResumeTemplate.py`，`ResumeCore.py` 为了分栏必须依赖模板层。
  引擎已有 `create_columns`，但它是"按数量造空栏"，`split_column_advanced` 是"按比例装已有对象"，
  两者在比例计算、`cumulative_x` 累加、`content_area` 取值上高度重复。
- **实施**：在 `LayoutEngine.py` 新增 [`create_band(...)`](#create_band--批次-2-新增横向布局的基础构件)
  （API 见 3.4 节），统一承担：按顺序排放格子 → 累加 x → 建带容器 → 通过 `add_child` 挂载。
  与原方案的差异：

  | 原方案 | 实际实施 |
  | --- | --- |
  | 函数名 `layout_band` | **`create_band`**（与 `create_spacer` 命名风格一致） |
  | 返回 `parent` | 返回**新建的带容器**；仅 `split_column_advanced` 为链式兼容仍返回 `parent` |
  | `ratio` 参数 + `cells` | 只保留 `cells`，比例由 `float` 元素表达（`float` = 权重） |

- **收益**：`ResumeCore.py` 不再需要为了分栏 import 模板层；两处重复的比例/累加逻辑归一；
  7.3、7.4 一并修掉。
- **风险已按原方案规避**：`create_columns` 的"宽度不足时把剩余均分"语义与
  `split_column_advanced` 的"严格按比例"确实不同，所以 `create_band` **只做严格按比例**，
  剩余均分留在 `create_columns` 里（两趟实现）。
- **验证**：三个入口退出码 0；PDF 规范化比对**三个产物全部逐字节一致**。
  引擎测试入口新增 `create_band` 断言 11 项（比例分宽、gap 累加、`height=0` 取父高、
  复用已构造对象、4 条错误路径、包装函数返回值、`split_column_advanced` 包装）。

### 8.2 【核心】下沉"留白"/间距构件 — ✅ 批次 1 已完成

- **原状**：`ResumeCore` 里出现了 **14 处**几乎逐字相同的代码块：

  ```python
  root.add_child(LayoutObject(
      name="Lead_...", x=0, y=0, width=0, height=<间距>,
      color=<随手写的白/蓝/绿/黄>, align_x=AlignX.CENTER, align_y=AlignY.FLOW,
      padding=Padding.all(0) 或 Padding.all(10), layer=0,
  ))
  ```

- **实施**：引擎层新增 [`create_spacer(name, height, parent=None, layer=0)`](#create_spacer--批次-1-新增)
  （API 见 3.4 节），`ResumeCore` 的 14 处全部替换。替换后
  `ResumeCore.py` 中 `root.add_child(LayoutObject(...))` 形式的留白字面量**归零**。
- **同时澄清了原方案里一处存疑的推断**：原文写"那些 `Padding.all(10)` 会让 FLOW 间距实际变成
  `10 + height` 的嫌疑，需要一并核对"。**实测证明该推断不成立** —— 留白 `_height > 0`，
  `get_effective_height()` 走 `min(_height, avail_h)` 分支，padding 完全不参与：

  ```
  padding=Padding.all(0)  -> 有效高=5  有效宽=80  abs_y=10
  padding=Padding.all(10) -> 有效高=5  有效宽=80  abs_y=10
  ```

  所以 `padding` 与 `color` 都是**无渲染影响的噪声**，`create_spacer` 直接不暴露这两个参数。
- **收益**：14 处各 11 行的字面量变成 14 处各 4 行的调用，间距参数一眼可读。
- **验证**：三个入口退出码 0；PDF 规范化比对**三个产物全部逐字节一致**（见 8.10 的验收基线）。
  `LayoutEngine.py` 测试入口新增 `create_spacer` 构件契约断言（高度、对齐、
  自动挂载、游离态，以及"padding 不影响有效高度"这一条）。

### 8.3 【核心】下沉"单块内容"构件（取代 7.8 的手工 `_height` 调参）

- **现状**：`generate_section_details_template` 与 `generate_summary_template` 的
  `content → details → description` 结构**逐行相同**；高度靠外部改写 `_height` 传入。
- **批次 3 已完成的引擎侧部分**：
  1. ✅ 引擎层提供 [`create_text_block(parent, name, text, style, height, ...)`](#create_text_block--批次-3-新增)，
     把 `Style → TextObject 参数` 的翻译集中一处（`from_style`）。
  2. ✅ `height` 成为**显式参数**，引擎里不再有硬编码 `50`（7.8 的成因消除）。
  3. ✅ `from_style` 让"样式 → 对象"不再需要手抄 7 个参数。
- **仍待功能分支处理**（`ResumeTemplate.py` / `ResumeCore.py` 不在 `master` 上）：
  - 让 `generate_summary_template` 复用 details 模板的 `details` 部分，
    并给它**独立命名前缀**（如 `_summary_{index}`），从根上消除 7.2；
  - 把模板层约 25 处 `TextObject(...)` / `ImageObject(...)` 换成 `from_style`；
  - 两处硬编码 `height=50` 改为显式传参（**必须传 50**，否则产物会变）。

### 8.4 【核心】把 `Style` 与"样式→对象"翻译下沉 — ✅ 批次 3 已完成

- **原状**：`Style.get_font_style()` 是纯引擎概念（fpdf 的 `"B"/"I"/"BI"`），却住在模板层。
  且 `TextObject` 的 7 个参数（`font_name/font_size/font_style/text_color/padding/align_*/multi_line`）
  在每个 `generate_*` 里都要手抄一遍。
- **实施**：`Style` 移入 `LayoutEngine.py`（放在 `Padding` 之后，与 `Color`/`Padding`
  同属底层纯数据构件），并新增 `TextObject.from_style` / `ImageObject.from_style`。
  API 见 3.1 与 3.3 节。
- **迁移原则：纯搬运**。字段名、顺序、默认值逐项一致（测试入口有字段快照断言），
  连 `padding` 的可变默认参数（缺陷 7.10）也**原样保留** —— 修它会破坏
  "输出逐字节不变"的验收前提，故归入批次 4。
- **与原方案的差异**：原建议"保留 `Style.get_font_style()` 为兼容别名"。
  实际**不需要别名** —— `Style` 整个类搬过去了，方法随之搬家。
  `RectangleObject.from_style` 刻意不做（只映射一个字段，负收益）。
- **收益**：模板函数体量可下降约 40%（待功能分支替换后兑现）；
  `ResumeTemplate` 只剩"简历词汇 + `STYLES` 表"。
- **验证**：三个入口退出码 0；PDF 规范化比对**三个产物全部逐字节一致**
  （本批只新增 API、未修改任何既有函数体）。测试入口新增 `Style` / `from_style` /
  `create_text_block` 断言共 13 项。

### 8.5 统一缓存失效入口 — ✅ 批次 4.3 已完成

- **原状**：`_x/_y/_width/_height/padding/align_x/align_y` 全是裸属性或私有属性，
  外部可以直接写（`ResumeCore.py` 的 `content_obj._height = ...`、
  `ResumeTemplate.py` 直接改 `_x/_width/align_*`），**没有任何钩子触发失效**。
- **实施**：全部改为 `@property` + setter，setter 内触发 `invalidate_geom_cache()`：

  | 属性 | setter 行为 |
  | --- | --- |
  | `padding` | 触发失效（影响内容区，进而影响 `CONTENT` 尺寸与子元素位置） |
  | `align_x` / `align_y` | 触发失效 |
  | `x` / `y` | 触发失效 |
  | `width` / `height` | 触发失效，并**同步尺寸方式**：`> 0` → `FIXED`，`== 0` → `FILL` |
  | `size_x` / `size_y` | 触发失效 |

  `width` / `height` 的"同步尺寸方式"是关键：它让"先构造、后声明尺寸"的旧写法
  （`obj.height = N`）能正确生效。**直接写 `_width` / `_height` 会绕过这一步**，
  构造时若为 0 则尺寸方式已是 `FILL`，之后写私有字段不会改回 `FIXED`，`FILL` 会覆盖它。
  测试入口 10.4 把这条不变量固化成了断言。

- **新增四个显式接口**（都返回 `self`，支持链式）：

  ```python
  set_size(width=None, height=None)
  set_position(x=None, y=None)
  set_align(align_x=None, align_y=None)
  set_padding(padding=None)          # float 会转成 Padding.all
  ```

  `None` 一律表示"不修改该轴"，因此可以只设一个方向。

- **构造期不走 property**：`__init__` 直接写 `_padding` / `_align_x` / `_align_y` 等私有字段，
  否则每构造一个对象都要向上无效化整条祖先链。`create_band` 里同理，
  逐项写私有字段后统一调一次 `invalidate_geom_cache()`。

- **收益**：从机制上消灭"忘了失效"这类 bug；调用方不必再碰私有字段。
- **验收**：三个入口退出码 0；**三个产物逐字节一致**（本次是等价重构）。
  新增断言：`padding` 改动对 `CONTENT` 尺寸生效（40 → 54）、
  `align` 改动对位置生效（LEFT→RIGHT、TOP→BOTTOM）、四个显式接口触发失效并返回 self、
  显式 `CONTENT` 不被 `height` 赋值覆盖、直接写私有字段会绕过尺寸方式。

### 8.6 修掉 wrap 宽度路径

- **现状**：`_calculate_wrap_width()` 只做 `max(child_width)`，不调用 `wrap_content_width()`，
  `_cached_wrap_width` 在 `wrap_content_width()` 里被读但那条路径基本走不到。
- **建议**：让 `get_effective_width()` 在 `_wrap_width` 时直接走 `wrap_content_width()`，
  并让 `_calculate_wrap_width` 用"当前可用宽"而非最大值（或明确文档化为"最小宽度"语义）。

### 8.7 把"行数估算"统一为一次真实测量

- **现状**：7.7 的两套公式都不准。
- **建议**：`TextObject` 缓存一次 `pdf.multi_cell(..., dry_run=True)` 或
  `pdf.get_string_width` 逐词换行的结果，`calculate_text_size` 与 `_calculate_wrap_height` 共用。
  这同时能消掉 `description_height` 这个手动调参旋钮——**这是本项目最大的易用性提升点**。

### 8.8 渲染契约与日志

- ✅ **`render_debug()` 补齐返回值**（已完成，见 7.11(a)）：四个实现现在返回与各自
  `render()` 同类值。调试与正式渲染因此可互换，测试入口切到 `render_debug` 时断言不再失效。
- **待办**：统一 `render()` 返回值为 `float`（元素底边 y），或在 `LayoutObject` 里
  明确文档化 tuple 情形（7.11(b)，归入批次 4）。
- `timer` 改为受模块级开关控制（`DEBUG_TIMING = False`），并改用 `logging` 而非 `print`。

### 8.9 配置与全局状态

- 抽出 `create_document(...)`：集中建 `FPDF`、注册字体（当前在 3 个 `__main__` + `Resume.Generate`
  里各写一遍，且字体路径 `.\Resources\...` 是**相对当前工作目录**的，换目录就失败）。
- 给 `layer_manager` / `objectRegister` 加 `reset()`，或改为挂在 `root` 上的实例，
  支持同进程生成多份文档。

### 8.10 建议的重构批次

| 批次 | 内容 | 风险 | 可验证性 | 状态 |
| --- | --- | --- | --- | --- |
| **基础设施** | `.gitignore`（生成物 + 字体）+ 字体下载说明 + `.pyproj` 入口改指 `LayoutEngine.py` | 极低 | 不影响任何 PDF | ✅ **已完成** |
| **0** | 修 7.1 导入；修 7.15 换行；修 7.17 重复挂载；修 7.18 末尾间距 | 极低 | 三个入口都能跑通 | ✅ **已完成** |
| **1** | 抽 `create_spacer`（8.2） | 低 | 输出 PDF 应与重构前**逐字节一致** | ✅ **已完成** |
| **2** | 抽 `create_band`，`create_columns` / `split_column_advanced` 变包装；修 7.3、7.4（8.1） | 中 | 同上，逐字节比对 | ✅ **已完成** |
| **3** | 抽 `create_text_block` / `from_style` / `Style` 下沉（8.3、8.4） | 中 | 同上 | ✅ **已完成** |
| **4** | **几何核心重构**：4.1 四轴枚举 · 4.2 两趟遍历（修 7.19 / 7.20）· 4.3 几何属性 property（8.5）· 4b 内容固有宽度（修 7.21）· 4.4 删 `wrap_*` 兼容面 | 高 | 逐字节比对 + 两趟遍历断言 | ✅ **已完成** |
| **4a** | 包围**固定高度**内容（矩形 / 图片 / 显式高度文本块） | 中 | 包围盒尺寸断言 | ✅ 已由 4b 的断言兑现 |
| **5** | **真实文本测量 + 分段样式**：`measure_text`（修 7.7）· `TextRun` · Markdown 内联语法 · P1 时序 | 中 | 测量行数=绘制行数、同字号分段断行一致 | ✅ **已完成** |
| **6** | **分页** —— 按页切分布局树 | 高 | 多页产物断言 | **暂缓**（多页需求出现时先在 `master` 完成） |

**批次 4 实际执行的五步**（与原计划的差异）：

| 步 | 内容 | 与原计划 |
| --- | --- | --- |
| 4.1 | 四轴枚举 | 原为"新增 `SizeX`/`SizeY`" |
| 4.2 | 两趟遍历（修 7.19 / 7.20） | 原为"几何属性改 property" —— 顺序调整，因为遍历是尺寸体系的地基 |
| 4.3 | 几何属性 property 化（8.5） | 原为 4.4 |
| 4b | 内容固有宽度（修 7.21） | 原为 4b，**提前**到 4.4 之前，因为它才是"矩形包围内容"的实现 |
| 4.4 | 删 `wrap_*` 兼容面 | 新增的一步 |

> **顺序调整的理由**：原计划先做 property 化，但"何时知道要重算"（property）与
> "重算能不能算对"（两趟遍历）必须同时成立才有意义 ——
> 只做前者会得到"失效通知发出去了、结果还是旧的"这种更难排查的状态。
> 因此把遍历重写提前，property 化随后。

### 8.10b 签出功能分支前的收尾核查（已完成）

按 `SKILLS.md` 的「底层功能完整」三条判定标准逐项核查。核查是**只读**的，
用引擎公开接口搭一个完整文档，不外改任何私有字段。

#### 判定标准 1：引擎能独立完成一次多元素排版

用纯公开接口搭出：容器 → `create_band` 按比例分栏 → 按 `Style` 建文本块 →
`runs` 分段样式 → `SizeX/Y.CONTENT` 矩形包围内容 → `create_spacer` 流式堆叠。

布局结果（自洽性核对）：

```
C_Root    210.00 x 297.00   abs=( 0.00,  0.00)
C_Body    190.00 x  82.40   abs=(10.00, 10.00)   ← CONTENT
C_Band    180.00 x  40.00   abs=(15.00, 15.00)
C_Box      22.93 x  20.40   abs=(15.00, 55.00)   ← 紧接带下方
C_BoxT     16.93 x  14.40   abs=(18.00, 58.00)
```

`C_Body` 的内容高 = 40（带）+ 20.4（包围盒）+ 6（留白）+ 10（padding）= **82.40** ✅

**全程未手工改写 `_height` / `_x` / `_width`。**

#### 判定标准 2：缓存失效不需要调用方操心

| 操作 | 结果 |
| --- | --- |
| 改子元素 `height` | ✅ 父的包围高从 10 变 40 |
| `add_child` | ✅ 变为 65 |
| 改 `padding` | ✅ 变为 75 |
| 改 `size_y` + `height` | ✅ 变为 77（`FIXED`） |
| `remove_child` 后父重算 | ✅ 回到 300 |

#### 判定标准 3：引擎自检覆盖上述能力，不依赖 `ResumeCore.py`

- 测试入口的 import 只有 `fpdf` / `inspect` / `io` —— **对中层/顶层零依赖**；
- **192 条 assert**，覆盖四轴尺寸、两趟遍历、包围内容、分栏/横向带、留白、
  文本块、缓存失效、循环报错、文本测量、分段样式、Markdown、P1 时序。

#### 核查中发现并修复的一个引擎缺口

**`create_band` 缺少 `align_y` 参数**，导致它建的带容器**无法参与纵向流式排列**
（只能绝对定位在 `avail_y`）。这不是"用法问题"而是真缺口：
几乎总要显式把它改成 `FLOW`，否则与后续兄弟重叠。

已修复：`create_band` / `create_columns` / `create_columns_balanced` 都新增
`align_y: AlignY = AlignY.NONE`（默认值保持既有行为，故既有产物逐字节不变）。

> `split_column_advanced` **不**加此参数：它是**包装层**，默认把左右对象设为
> `align_x/y = NONE` 并返回 `parent` 供链式调用。直接改它的 `align_y` 会破坏
> "左右栏各占自己那一栏"的语义。若要让分栏容器参与流式排列，
> 直接用 `create_band` 并传 `align_y=AlignY.FLOW`。

#### 核查结论

| 判定标准 | 结论 |
| --- | --- |
| 1 引擎独立完成多元素排版 | ✅ 通过（核查中发现并修复 `create_band` 的 `align_y` 缺口） |
| 2 缓存失效自动触发 | ✅ 通过 |
| 3 引擎自检独立且覆盖完整 | ✅ 通过（192 条 assert，零中层依赖） |

**底层已具备签出功能分支的条件。** 剩余待办全部记在 `SKILLS.md` 的
「只在功能分支处理的事项」一节。

> **批次 6 为何暂缓**：现阶段要排版的是简历，只需一页 A4，不涉及分页。
> 将来排毕业论文一类多页文档时再做。推迟的代价接近于零 —— 引擎已把「对象尺寸」与
> 「页面尺寸」分开（`Root` 由调用方挑，引擎从不读 `pdf` 页面尺寸），
> 因此加批次 6 新增的是"按页切分"这一层，**不需要推翻现有尺寸体系**。
>
> ⚠️ **当前是单页假设**：`render()` 完全不处理分页，`FPDF.auto_page_break` 可能在任意位置触发，
> 而 `LayoutObject` 的绝对坐标与页无关。在批次 6 落地之前，**不要假定本引擎支持多页**。

> **批次 4 为何同时承载"矩形包围内容"**：见 8.11 —— 两者是同一件事的两半，
> property 化解决"何时知道要重算"，修 7.19/7.20 解决"重算能不能算对"。
> 只做前者会得到"失效通知发出去了、结果还是旧的"这种更难排查的状态，因此必须同批。

> 批次 0 原计划只修 7.1 / 7.15 / 7.5，实际执行时：
> - 7.5（`get_true_height()` 空实现）**未修**，因为它的正确语义需要设计决策（该返回构造高还是生效高？），
>   暂以测试入口断言固化"当前返回 `None`"的现状；
> - **新增修复**了 7.17、7.18 两个在做前置探查时新发现的缺陷。

#### 验证方法（批次 1~3 沿用；批次 4 起用法有变）

生成的 PDF 内含 `CreationDate` / `ModDate` / `ID` / `Producer` 等易变字段，
**直接做字节比对会永远失败**。规范化流程：

1. 重构前先跑一遍，把生成的 PDF 另存为参考副本；
2. 重构后再跑一遍；
3. 对两份文件做**规范化**后比对——按字节以 Latin-1 读入，
   用正则把 `/CreationDate (D:...)`、`/ModDate (D:...)`、
   `/ID [<...> <...>]`、`/Producer (...)` 替换为固定占位符，再算哈希。

> ✅ **已固化为工具**：`verify_pdfs.py`（批次 4.2 新增）。
> 用法 `py verify_pdfs.py --baseline <目录>`，只读文件、不改动任何内容。
> 之所以要做成工具 —— 标准工具链里没有 pypdf / PyMuPDF，
> 而每次手工算哈希既啰嗦又容易写错。

批次 0 的实测结果（基线为批次 0 之前）：

| 产物 | 规范化后 |
| --- | --- |
| `test_layout_engine_cached.pdf` | **完全一致**（19316 字节） |
| `resume_template_v2_test.pdf` | **完全一致**（61370 字节） |
| `output/利姆露_*.pdf` | 相差 5 字节 —— 即 7.17、7.18 两处修复带来的预期变化 |

批次 1 的实测结果（基线为批次 1 之前）：

| 产物 | 规范化后 |
| --- | --- |
| `test_layout_engine_cached.pdf` | **完全一致**（19316 字节） |
| `resume_template_v2_test.pdf` | **完全一致**（61370 字节） |
| `output/利姆露_*.pdf` | **完全一致**（68478 字节） |

批次 2 的实测结果（基线为批次 2 之前）：

| 产物 | 规范化后 |
| --- | --- |
| `test_layout_engine_cached.pdf` | **完全一致**（19316 字节） |
| `resume_template_v2_test.pdf` | **完全一致**（61370 字节） |
| `output/利姆露_*.pdf` | **完全一致**（68478 字节） |

批次 1、2 都是**纯粹的等价重构**（只抽取构件、不改变行为），所以三个产物全部逐字节一致，
这正是它们追求的结果。

> ⚠️ **批次 2 的一次真实踩坑，值得记住**：`create_columns` 改为走 `create_band` 之后，
> 各栏从"`parent` 的直接子元素"变成了"带容器的子元素"，多出一层。
> 而引擎测试入口原先用 `container.get_child("Column_0")` 取栏（`get_child` 只看直接子元素），
> 于是拿到 `None`，两段文本根本没被创建 —— 引擎 PDF 从 19316 字节掉到 18071。
> **这不是引擎的问题，是测试的假设失效了。**
> 改用 `find_by_name`（深度优先）后恢复一致。
> **结论：包装层会改变树形，所有按名字取对象的地方都要检查用 `get_child` 还是 `find_by_name`。**
> 逐字节比对把这个问题挡在了提交之前。

批次 3 的实测结果（基线为批次 3 之前）：

| 产物 | 规范化后 |
| --- | --- |
| `test_layout_engine_cached.pdf` | **完全一致**（19316 字节） |
| `resume_template_v2_test.pdf` | **完全一致**（61370 字节） |
| `output/利姆露_*.pdf` | **完全一致**（68478 字节） |

批次 1、2、3 都是**纯粹的等价重构或纯新增**（只抽构件 / 只加 API，不改变既有行为），
所以三个产物全部逐字节一致，这正是它们追求的结果。

批次 4.1 / 4.2 / 4.3 的实测结果（基线为批次 4 之前）：

| 产物 | 4.1（四轴枚举） | 4.2（两趟遍历） | 4.3（property 化） |
| --- | --- | --- | --- |
| `test_layout_engine_cached.pdf` | **完全一致** | **完全一致** | **完全一致** |
| `resume_template_v2_test.pdf` | **完全一致** | **完全一致** | **完全一致** |
| `output/利姆露_*.pdf` | **完全一致** | **完全一致** | **完全一致** |

> ✅ **批次 4.2 的逐字节一致是一个很强的结果**：引擎的整棵测试树走的是**全新的两趟遍历**，
> 输出却与旧的惰性递归实现完全相同。这既证明重构是行为等价的，
> 也说明旧实现在**没有 `CONTENT` 节点**时本来就给出了正确的几何 ——
> 7.19 只在 `wrap_height` 参与时才发作。
>
> 同时它也是这一批最有价值的排错手段：4.2 期间修掉的 **4 个实现 bug**
> （padding 减两次、`_place` 原点语义、无限递归、带容器格子尺寸方式）
> **全部是被逐字节比对暴露的**，只跑"退出码 0"一个都发现不了。

> ✅ **「只增不改」是一种可验证的强约束**：批次 3 新增了 `Style` 类、两个 `from_style`
> 工厂与 `create_text_block`，**没有修改任何既有函数体**。因此逐字节基线是这个批次
> 唯一需要的验收手段 —— 它一旦不同，就说明新增代码意外影响了既有路径。

> ⚠️ **批次 2 的一次真实踩坑，值得记住**：`create_columns` 改为走 `create_band` 之后，
> 各栏从"`parent` 的直接子元素"变成了"带容器的子元素"，多出一层。
> 而引擎测试入口原先用 `container.get_child("Column_0")` 取栏（`get_child` 只看直接子元素），
> 于是拿到 `None`，两段文本根本没被创建 —— 引擎 PDF 从 19316 字节掉到 18071。
> **这不是引擎的问题，是测试的假设失效了。**
> 改用 `find_by_name`（深度优先）后恢复一致。
> **结论：包装层会改变树形，所有按名字取对象的地方都要检查用 `get_child` 还是 `find_by_name`。**
> 逐字节比对把这个问题挡在了提交之前。

**批次 1~3 的验收基线到此结束。** 这三个批次都是等价重构或纯新增，
逐字节一致是它们唯一需要的验收手段。

> ⚠️ **从批次 4 起，逐字节比对不再是充分的验收手段。** 批次 4 要修 7.19（父子高度自指）、
> 7.20（`_height` 卡死）、7.21（`wrap_width`）并实现"矩形包围内容"，
> 这些都会**有意识地改变**布局结果。
>
> 届时仍应保留基线副本，但用法从"要求完全一致"改为：
> **逐条解释每一处差异，确认它正好对应预期的那一项修复，且没有多余的连带变化。**
> 一个只有预期差异、没有意外差异的比对结果，才说明改动是受控的。

> 📌 **给下一批次的提示**：基线用的参考副本放在工作区外的临时目录
> （`%TEMP%\batch3_baseline\`），不入库。
> 批次 4 动工前请**以当前工作树的输出为新基线**重取一次：
> 跑一遍三个入口，把 `test_layout_engine_cached.pdf`、`resume_template_v2_test.pdf`、
> `output/*.pdf` 复制到工作区外的临时目录，然后才开始改代码。

### 8.11 「矩形包围内容」的实现位置与前置依赖

#### 结论

**它不单独占一批，应与"几何属性改 property"合并为批次 4，并排在该批次最前面。**

而且它实际是一项**修复**而非新增：`wrap_height` / `wrap_content()` /
`RectangleObject._calculate_wrap_height()` 名义上都已存在，但对"包围内容"这个用途是**反向的**
（见 7.19）。所以不能把它当作"新功能"来排期。

#### 现状：开启 wrap 反而塌缩

| 实验 | 结果 |
| --- | --- |
| `height=0, wrap_height=False` | 有效高 **49.00**（= 内容总高，巧合） |
| `height=0, wrap_height=True` | 有效高 **4.00**（只剩 padding） |
| 仅改盒子构造宽 60 → 0 | 均 **4.00**，无改善 |
| `wrap_width=True`，子元素 `width=0` | 有效宽 **0.00**（见 7.21） |

#### 三个阻断点及其归属

| 阻断点 | 缺陷编号 | 内容 |
| --- | --- | --- |
| A | 7.19 | `get_parent_available_area()` 向上要高度，而那个高度正是当前正在计算的值 |
| B | 7.20 | `invalidate_wrap_cache()` 不清 `_height`，`wrap_content(force=True)` 也无法重算 |
| C | 7.21 | `wrap_width` 原理上自相矛盾，完全不可用 |

还有两个会在实现阶段绊住的问题（不属于独立缺陷，但需一并决定）：

- **渲染顺序**：`RectangleObject.render()` 无条件实心填充（7.9），
  而 `render()` 按 `children` **插入顺序**遍历而非图层顺序。
  包围矩形若在子元素之后渲染就会盖住内容，必须保证先建矩形。
- **截断语义冲突**：`get_effective_height()` 在 FLOW 模式下超过父可用空间会**静默截断**
  并置 `_flow_clipped`。包围矩形的语义应当是"撑大自己"，而不是"被父容器腰斩"。
  这两者需要显式取舍。

#### 为何必须与批次 4 同批，且排在它前面

"矩形包围内容"要求一条**自底向上的尺寸传播链**：

```
子元素尺寸变化 → 矩形重算 → 矩形尺寸变化 → 兄弟元素（FLOW）下移 → 更上层重算
```

而目前：

- 尺寸变化**不会自动触发失效** —— `ResumeCore.py` 直接写 `content_obj._height = ...`，
  `ResumeTemplate.py` 直接改 `_x/_width/align_*`，都没有钩子（见 8.5）。
- 即便手动调了失效，**阻断点 B（7.20）** 会让重算卡在旧值上。

所以两者是同一件事的两半：**property 化解决"何时知道要重算"，
修 7.19/7.20 解决"重算能不能算对"。** 先做 property 而不修 B，
会得到"失效通知发出去了、结果还是旧的"这种更难排查的状态。

`wrap_content()` 的**方向性**也必须在这里一次定清楚，否则后患无穷：

- **自底向上**（包围内容）要求打破对父高的依赖；
- **自顶向下**（被父容器约束、超出即截断）是现在的行为；
- 两者不能都靠 `get_parent_available_area()` 实现，需要引入显式的**测量上下文**
  （例如测量时向上找最近的**已知高度**祖先，而不是直接父）。

#### 与批次 5 的依赖

文本是绝大多数被包围的内容，而文本高度目前是**两套都不准**的估算公式（见 7.7）：

- `calculate_text_size`：`int(text_width / effective_width) + 1`
- `_calculate_wrap_height`：`len(self._text) // 20 + 1`

这正是 `description_height` 手动调参旋钮存在的原因。
**只要文本高度还是估算的，矩形包围文本就只能靠手填高度。**

因此拆分为：

| 子批次 | 内容 | 前置 |
| --- | --- | --- |
| **4a** | 包围**固定高度**内容（矩形 / 图片 / `_height` 已给定的文本块） | 批次 4 主体完成即可交付 |
| **4b** | 修 `wrap_width`（阻断点 C，7.21），实现真正收窄 | 可与 4a 同批或拆出 |
| **5** | 真实行数测量（8.7）之后，才能包围**自动换行的长文本** | 依赖批次 5 |

#### 在批次 4 之前不要固化上层 API

在批次 4 之前**不需要改引擎**也能做出"包围固定高度内容"的效果，只是要手工持有尺寸：

```python
content_h = sum(c._height for c in box.children) + box.padding.top + box.padding.bottom
box._height = content_h
```

这本质上是 `description_height` 那个调参旋钮的翻版 —— 能用，
但正是批次 4 要消灭的东西。**不建议在批次 4 之前把它固化成上层 API**，
否则会在功能分支里留下一个将来必须拆掉的接口。

---

## 9. 测试入口

沿用项目传统：单元测试写在**各文件自己的 `if __name__ == "__main__":` 里**，可覆盖旧测试。

| 命令（在项目根目录执行） | 覆盖 | 产出 |
| --- | --- | --- |
| `py LayoutEngine.py` | 几何、流式、分栏、横向带、留白、图层、缓存、三种渲染对象 | `test_layout_engine_cached.pdf` |
| `py ResumeTemplate.py` | 全部 `generate_*` + `fill_*` + `split_column_advanced` | `resume_template_v2_test.pdf` |
| `py ResumeCore.py` | 完整 `Resume.Generate` 链路 | `output/{姓名}_{职位}_{公司}.pdf` |

注意事项：

1. **必须用 `py`**（3.14 + fpdf2 2.8.8）。DSH 自带运行时没有 fpdf2。
2. 字体路径是相对路径 `.\Resources\...`，**必须在项目根目录执行**，否则字体会静默降级为 helvetica，
   中文变空白。字体需自行下载，见 README 的「资源获取」。
3. `Resources/` 缺全部图片资源（1.4 节），图片相关的视觉验收目前无法进行。
4. 三个入口都会在 stdout 打印大量渲染日志（7.13），建议重定向到文件再读尾部。
5. **前两个入口的产物已被 `.gitignore` 忽略**（`*.pdf` 规则），它们由代码可复现，不入库。

---

## 10. 附录：模块常量速查

```python
# LayoutEngine.py
AlignX: LEFT / CENTER / RIGHT / NONE
AlignY: TOP / VCENTER / BOTTOM / NONE / FLOW

Color: RimuruBlue Red Green Blue Yellow White Black Gray LightGray

Padding: .all(v) .rectangle(h,v) .horizontal(v) .vertical(v)
         .left(v) .right(v) .top(v) .bottom(v)

Style:  # 批次 3 从模板层移入
    font_name="helvetica"  font_size=12  bold=False  italic=False
    color=Black  fill_color=White  image_path=""
    padding=Padding.all(0)  fit_mode="cover"
    .get_font_style() -> "B" / "I" / "BI" / ""

layer_manager: LayerManager()          # 全局单例
objectRegister: dict                   # 全局注册表
find_object_by_name(name="") -> Optional[Any]

# from_style 字段映射（批次 3）
Style.font_name   -> TextObject.font_name
Style.font_size   -> TextObject.font_size
Style.bold+italic -> TextObject.font_style   # 经 get_font_style()
Style.color       -> TextObject.text_color   # 注意：不是 color
Style.fill_color  -> TextObject.color / ImageObject.color
Style.padding     -> *.padding
Style.image_path  -> ImageObject.image_path  # 实参 image_path 优先
Style.fit_mode    -> ImageObject.fit_mode
# **overrides 优先级高于 style；style=None 用全默认值
# RectangleObject.from_style 刻意不做

# 文本行高（批次 5 实测更正）
行高实际由 line_height_ratio 决定，构造参数 line_height **是死参数**
（只写入 self._line_height，全库从不读取）
line_height_ratio 默认 = 1.2   → 每行高 = 该行最大字号 × 1.2
# 历史文档曾写 "line_height 默认 = font_size * 0.6"，与实现不符

# 底层默认值
split_column_advanced:         ratio=[1.0, 2.5], gap=0
create_columns:                num_columns=2, gap=5
create_band:                   gap=0, height=0（取父内容区高）, container_name="{parent.name}_band"
create_spacer:                 parent=None, layer=0
create_text_block:             height=0（取父可用高，**不是**按内容撑高）, align_x=LEFT, align_y=FLOW
                               # 参数表不含 width / size_x —— 需要控制宽度轴时直接用 from_style

# 中层默认值（ResumeTemplate.py，2026-10-13 重塑后）
DEFAULT_RATIO              = [1.0, 2.5]
DEFAULT_TITLE_HEIGHT       = 15.0      DEFAULT_DIVIDER_HEIGHT = 0.5
DEFAULT_BRIEF_HEIGHT       = 10.0      DEFAULT_BRIEF_RATIO    = [2.0, 1.0, 2.0]
DEFAULT_ICON_WIDTH         = 4.0       DEFAULT_TITLE_ICON_WIDTH = 10.0
DEFAULT_PHOTO_WIDTH        = 30.0      PHOTO_ASPECT           = 1.6
DEFAULT_ROW_INSET          = 3.0       DEFAULT_ROW_PAD_Y      = 3.0
DEFAULT_HIGHLIGHT_HEIGHT   = 9.0
DEFAULT_BULLET_SIZE        = 3.2       DEFAULT_BULLET_INDENT  = 1.0
DEFAULT_BULLET_GAP         = 2.0
profile_content_height(style, icon_width) = max(字号×0.5, 图标宽+3)
skills_row_height(style)                  = 字号×0.5
wrapped_height(text, style, width, lhr=1.2, pdf=None) -> mm   # 折行后的实际高
wrapped_lines(text, style, width, lhr=1.2, pdf=None)  -> int  # 折行数
measure_pdf() / reset_measure_pdf()                           # 共享测量实例

add_split:        ratio=[1.0, 2.5]（与 widths 互斥）；colors/paddings/insets 按栏
add_basic:        right_padding=Padding.left(5), left_padding=Padding.all(0)
add_info:         variant="contact"（另一预设 "name"）；显式参数优先于预设
add_photo:        photo_width=30（行高 = 宽 × 1.6）
add_section_heading: icon_width=10, height=15（内部 = 标题带 14.5 + 分隔线 0.5）
add_detail:       brief_height=10, brief_ratio=[2.0,1.0,2.0],
                  description_height=None（None = SizeY.CONTENT 自动结算）
add_detail_head:  ratio=[2.0,1.0,2.0]（必须 3 个元素）, height=10
add_detail_body:  height=None（None = 自动结算）
add_highlight:    height=9, 样式 STYLES["highlight_text"]（13pt 粗体白字深蓝底）
add_bullets:      bullet_size=3.2, indent=1, gap=2, bullet_kind="block"
                  bullet_kind ∈ {block, text, image}
add_text_row:     height=None（None = 字号 × row_height_ratio=0.5）
BRIEF_DETAIL_STYLES: detail_key_1 / detail_time_1 / detail_tags_1 / detail_description
Resume:           summary_height=None（None = 自动结算）, summary_title="个人总结"

# 已退役（不再挂在 LayoutObject 上）
add_profile  add_profile_photo  add_section_title  add_details
add_summary  add_details_list

# 返回值对照
create_band                -> 新建的带容器
create_columns             -> 新建的带容器
create_columns_balanced    -> 新建的带容器
split_column_advanced      -> parent         # 未变，保持链式调用兼容
create_text_block          -> 新建的 TextObject（已挂载）
from_style                 -> 新建对象（**未挂载**）
add_split                  -> SplitHandle(node/cells[]，left/right 为便捷属性)
add_basic                  -> SplitHandle（同为 SplitHandle，left/right 可用）
add_info                   -> ProfileHandle(node/split/icon_range/icon/text_range/text)
add_photo                  -> PhotoHandle(node/photo)
add_section_heading        -> TitleHandle(node/split/icon_range/icon/text_range/text/divider)
add_detail                 -> DetailsHandle(node/head/body，并转发 key/tags/description 等)
add_detail_head            -> DetailHeadHandle(node/band/三个 col/key/during_time/tags)
add_detail_body            -> DetailBodyHandle(node/description)
add_highlight              -> HighlightHandle(node/text)
add_bullets                -> BulletHandle(node/mark_cell/text_cell/text/mark)
add_section                -> SectionHandle(node/title/details[])
add_text_row               -> TextObject（容器按 {name}_content 查找）
add_spacer                 -> LayoutObject
```

---

## 11. 中层调参手册

> **用途**：跑完 PDF 之后，看到某处不对，能直接查到该改哪个参数、改多少、
> 会不会连带推开别的元素。
>
> **单位**：全部是 **mm**（引擎的长度单位，见 2.3）。字号是 **pt**。
>
> **改哪里**：参数默认值集中在 `ResumeTemplate.py` 第 1 节（模块常量，约 77–87 行）。
> 改模块常量 = 改全局默认；在调用点传参 = 只改那一个实例。
>
> ⚠️ 本手册的"影响范围/连带效应"是**按引擎几何推导并实测过结构快照**的，可以信；
> 但"这个值好不好看"必须你自己看 PDF 判断 —— 见 11.7 的待补症状表。

### 11.1 调参的三条基本规律

**规律一：容器高度一改，同栏后面所有元素一起平移。**

左栏与右栏都是 `AlignY.FLOW` 的流式序列。改任意一个元素的高度，
**它下面同栏的所有元素整体下移（或上移）相同距离**，`x` 不变。
跨栏**互不影响** —— 左栏变高不会推动右栏。

**规律二：`row_padding` 与 `row_inset` 是两回事。**

| 做法 | 效果 |
| --- | --- |
| `row_inset=3` | 整条行容器**右移 3mm 且宽度减少 3mm**（内容被挤在右侧） |
| `row_padding=Padding.left(3)` | 行容器位置与宽度不变，内容在容器内右侧留白 3mm |

对**纯左缩进**两者视觉等价。但 `row_inset` 会同时收窄宽度（文本可用宽变小、
换行可能提前）；`row_padding` 不会改变容器占位。**要缩进又不想改变占位时用 `row_inset`。**

**规律三：文本高度 = 行数 × 该行最大字号 × 1.2 + 上下 padding。**

行高系数固定为 `line_height_ratio=1.2`，**没有暴露成参数**（见 11.6）。
所以想让多行文本变矮，只能**改字号**或**减少行数**。

### 11.2 参数总览

#### 模块常量（`ResumeTemplate.py` 第 1 节）

| 常量 | 默认 | 含义 | 谁在用 |
| --- | --- | --- | --- |
| `DEFAULT_RATIO` | `[1.0, 2.5]` | 左右栏比例 | `add_basic` |
| `DEFAULT_TITLE_HEIGHT` | `15.0` | 节标题整体高 | `add_section_title` |
| `DEFAULT_DIVIDER_HEIGHT` | `0.5` | 节标题分隔线粗细 | `add_section_title` |
| `DEFAULT_BRIEF_HEIGHT` | `10.0` | 详情三栏（关键词/时间/标签）高 | `add_details` |
| `DEFAULT_BRIEF_RATIO` | `[2.0, 1.0, 2.0]` | 详情三栏横向比例 | `add_details` |
| `DEFAULT_ICON_WIDTH` | `4.0` | 个人信息行左格（图标）宽 | `add_profile` |
| `DEFAULT_TITLE_ICON_WIDTH` | `10.0` | 节标题左格（图标）宽 | `add_section_title` |
| `DEFAULT_PHOTO_WIDTH` | `30.0` | 证件照宽 | `add_profile_photo` |
| `PHOTO_ASPECT` | `1.6` | 证件照高 = 宽 × 此值 | `add_profile_photo` |
| `DEFAULT_ROW_INSET` | `3.0` | 个人信息行左缩进 | `add_profile` |
| `DEFAULT_ROW_PAD_Y` | `3.0` | 行内图标上下的最低留白 | `profile_content_height` |

#### `add_basic`（左右分栏）

| 参数 | 默认 | 效应 |
| --- | --- | --- |
| `ratio` | `[1.0, 2.5]` | 两栏宽度比。`1:2.5` → 左 54.29 / 右 135.71（Root 内容宽 190）。改它会同时改变**两栏一切内容的可用宽**，从而改变换行位置 |
| `left_padding` | `Padding.all(0)` | 左栏内边距（左栏是底色矩形；padding 会把内容往里推） |
| `right_padding` | `Padding.left(5)` | 右栏左内边距。`ResumeCore` 传的是 `Padding.left(8)` |

> ⚠️ **改 `ratio` 的连带效应最大**：右栏变窄 → 详情描述可能多折一行 →
> 该条详情变高 → 后面所有节整体下移。它是"改一处、动全篇"的参数。

#### `add_profile`（个人信息行：图标 + 文本）

| 参数 | 默认 | 效应 |
| --- | --- | --- |
| `icon_width` | `4.0` | 左格宽。**同时是图标宽高的边长**（图标是正方形），文本起点 = `row_inset + icon_width + gap` |
| `gap` | `0` | 图标与文本之间的间距 |
| `content_height` | `None` | 整行高。`None` = `max(字号×0.5, icon_width + 3)` |
| `row_inset` | `3.0` | 整行右移量，**宽度同步收窄** |
| `icon_style` | `STYLES["name_image"]` | 图标样式（`image_path` 为空，由 `.fill()` 传路径） |
| `text_style` | `STYLES["profile_text"]` | 文本样式 |

**默认高度的算法**（`profile_content_height`）：

```
content_height = max(text_style.font_size × 0.5,  icon_width + DEFAULT_ROW_PAD_Y)
```

实测值：姓名行（22pt / `icon_width=6`）→ `max(11, 9)` = **11mm**；
联系方式行（12pt / `icon_width=4`）→ `max(6, 7)` = **7mm**。

> ⚠️ **踩坑（2026-10-13 实测发现）**：`profile_content_height()` 的
> `icon_width` **默认是 0**，此时它退化成"字号×0.5"，**拿不到图标下限**。
> 所以 `content_height=profile_content_height()` 这种写法会把图标下限顶掉 ——
> 12pt 联系方式行被压成 6mm，4mm 图标上下只剩 1mm 留白（已实测确认）。
> **正确做法是不传 `content_height`**，让 `add_profile` 用它的 `icon_width` 自算。
> `ResumeCore` 原先正是犯了这个错，已修。

> **常见需求**：想让姓名行更高/更矮，改 `content_height`（传具体值），
> 或改 `icon_width`（它参与下限计算）。**只改字号不一定生效** —— 可能被图标下限顶住。

#### `add_profile_photo`（证件照）

| 参数 | 默认 | 效应 |
| --- | --- | --- |
| `photo_width` | `30.0` | 照片宽。**高 = 宽 × `PHOTO_ASPECT`** |
| `icon_style` | `STYLES["profile_photo"]` | `fit_mode="cover"` |

实测：`photo_width=30` → 行高 **48.0mm**。所以**改宽会平方级地影响占位** ——
宽 30→25，高从 48→40，整行省 8mm。

#### `add_section_title`（节标题）

| 参数 | 默认 | 效应 |
| --- | --- | --- |
| `height` | `15.0` | 整体高。内部分成"标题带（`height - 0.5`）" + "分隔线（0.5）" |
| `icon_width` | `10.0` | 左格（图标）宽。**图标是正方形，边长 = 此值** |
| `gap` | `0` | 图标与标题文字之间的间距 |
| `text_style` | `STYLES["section_title_text"]` | 标题样式（22pt 粗体深蓝） |

实测（`height=15`）：标题带高 **14.5**、分隔线高 **0.5** 且贴内容区底边；
图标区 `icon_range` 内的图标**底边对齐**且带 `Padding.bottom(3)`（视觉上抬 3mm）。

> **常见需求**："节标题离正文太近" → 改的是**上层留白**，不是 `height`
> （`height` 变高只会让标题文字区域更高，标题仍在整块底部）。

#### `add_details`（节详情：三栏 + 描述）

| 参数 | 默认 | 效应 |
| --- | --- | --- |
| `brief_height` | `10.0` | 顶部三栏高。**关键词/时间/标签都在这一行** |
| `brief_ratio` | `[2.0, 1.0, 2.0]` | 三栏宽比（左=关键词、中=时间、右=标签）。**必须恰好 3 个元素** |
| `description_height` | `None` | 描述高。`None` = 按真实行数自动结算；给值 = 固定高 |
| `key_style` / `time_style` / `tags_style` / `desc_style` | 组 1 四个样式 | 四段文字各自的样式 |

实测：`brief_height=10` 时三栏宽 **51.09 / 25.54 / 25.54**
（右栏内容宽 102.17 → 按 2:1:2 分，`col_2` 再带 `Padding.right(1.5)`）。

> **这是视觉权重最集中的地方**：关键词（学校/项目/公司名）在**左栏且比例最大**，
> 13pt 粗体；时间是中间 7pt 灰；标签是右侧 8pt 灰。
> 想让 HR 一眼看到重点 → 调 `brief_ratio`（给关键词更多宽）或 `key_style.font_size`。

#### `add_summary`（个人总结）

| 参数 | 默认 | 效应 |
| --- | --- | --- |
| `description_height` | `None` | 同 `add_details`。`ResumeCore` 原先传 `summary_height=18` |
| `desc_style` | `STYLES["summary_text"]` | 正文样式 |

#### `add_text_row`（一行文本：技能/证书/荣誉共用）

| 参数 | 默认 | 效应 |
| --- | --- | --- |
| `height` | `None` | 行高。`None` = `style.font_size × row_height_ratio` |
| `row_height_ratio` | `0.5` | 上面那个系数 |
| `row_padding` | `Padding.all(0)` | 行容器内边距（`ResumeCore` 传 `Padding.left(2)` / `left(7)`） |
| `text_padding` | `Padding.all(0)` | 文本自身内边距（`ResumeCore` 传 `left(6)`） |
| `text_width` | `0` | 文本宽。`0` = 撑满容器 |
| `multi_line` | `False` | 是否自动换行（多行内容必须开） |

> ⚠️ **`ResumeCore` 的正文行高度是"条目数 × 6"**，不是按内容结算。
> 条目多时可能不够高、条目少时会留空（见 SKILLS.md 的 M8）。

### 11.3 样式层（`STYLES`，19 个键）

改样式 = 改"长什么样"，通常比改几何参数更安全（不会连带推开元素），
**除非改字号** —— 字号会通过 11.1 规律三改变文本高度，进而推动后续元素。

| 键 | 字号 | 粗体 | 颜色 | 影响 |
| --- | --- | --- | --- | --- |
| `name_text` | 22 | ✔ | 黑 | 姓名。**同时参与姓名行高度下限** |
| `profile_text` | 12 | ✔ | 黑 | 联系方式文本 |
| `section_title_text` | 22 | ✔ | 深蓝 `(0,80,160)` | 节标题 |
| `detail_key_1` | 13 | ✔ | 黑 | 关键词（学校/项目/公司） |
| `detail_time_1` | 7 | ✘ | 灰 `(100,100,100)` | 起讫时间，带 `Padding.top(5)` |
| `detail_tags_1` | 8 | ✘ | 灰 `(80,80,80)` | 专业/技术栈 |
| `detail_description` | 10 | ✘ | 黑 | 详情描述正文 |
| `summary_text` | 10 | ✘ | 黑 | 个人总结正文 |
| `skillsawards_title` | 14 | ✘ | 灰 `(60,60,60)` | 技能/证书/荣誉标题 |
| `skillsawards_text` | 10 | ✘ | 灰 `(60,60,60)` | 技能/证书/荣誉正文 |
| `detail_key_2` / `_time_2` / `_tags_2` | 12 / 8 / 8 | — | — | **当前无调用方**，见 11.6 |
| `left_column` | — | — | `RimuruBlue` | 左栏底色（`fill_color`） |
| `profile_photo` | — | — | — | `fit_mode="cover"` |
| `name_image` / `section_title_image` | — | — | — | `image_path=""`，运行时由 `.fill()` 传 |
| `contact_text` | 10 | ✘ | 灰 | **当前无调用方** |

> **颜色值是 `Color(r, g, b, 0)`**，第 4 个参数是 alpha，当前引擎**只读 rgb**。

### 11.4 高度是怎么算出来的（自查用）

| 元素 | 高度来源 |
| --- | --- |
| 左栏 / 右栏 | 撑满 Root 内容高（`FILL`） |
| 证件照行 | `photo_width × 1.6` |
| 个人信息行 | `content_height`，默认 `max(字号×0.5, icon_width+3)` |
| 节标题 | `height`，默认 15 |
| 详情三栏 | `brief_height`，默认 10 |
| 详情描述 | **自动**：真实行数 × 该行最大字号 × 1.2 + `Padding.all(2)` 的 4mm |
| 详情容器 | **自动** = 三栏高 + 描述高 + padding |
| 个人总结 | **自动**，同描述 |
| 技能行 | 标题行 `字号×0.5`；正文行 `条目数 × 6` |

**查实际值的方法**（需要 pdf 参与精确测量）：

```python
handle.description.get_effective_height()   # 有效高
handle.node.get_layout_info()               # 全部几何 + 尺寸方式 + 溢出标志
```

`get_layout_info()` 返回的 `content_overflows` 为 `True` 表示**内容装不下**，
这正是"文本被截断/压扁"的判据。

#### 11.4b 文字在盒子里的落点（2026-10-13 实测标定）

> ⚠️ **引擎已修两处缺陷（详见 SKILLS.md 的 master 待办 D7）**：
> ① 传给 `pdf.cell` 的格子高曾漏换算单位（pt 当 mm，虚高 2.8346 倍）；
> ② 渲染器曾完全不读 `align_y`。
> 修复前文字一律偏低，**且有 4 个文本块的基线直接跑到盒子外**；
> 下方数值均为**修复后**的实测结果。

文字基线的落点公式（已用受控实验标定，六个字号误差 0.00）：

```
文字实高  text_h = 行数 × 该行最大字号 × 1.2 × 0.3528        (mm)
盒内可用  inner_h = 盒高 − padding.top − padding.bottom
对齐偏移  dy_align = VCENTER → (inner_h − text_h) / 2
                     BOTTOM  →  inner_h − text_h
                     TOP / NONE / FLOW → 0
文字基线  baseline = 盒顶 + padding.top + dy_align
                     + (字号 × 1.2 × 0.3528) / 2 + 0.10583 × 字号
```

> 最后两项来自 fpdf 把文字垂直居中于 `pdf.cell` 的格子：
> 半个格子高 + 该字体的下降部（`0.10583 × 字号`，对 LXGW 实测标定）。

**当前实际简历的落点（修复后，全部落在盒内）：**

| 节点 | 字号 | 盒高 | 文字实高 | align_y | dy | 基线 |
| --- | --- | --- | --- | --- | --- | --- |
| 姓名行 | 22 | 11.00 | 9.31 | vcenter | 0.84 | 27.83 |
| 联系方式行 | 12 | 7.00 | 5.08 | vcenter | 0.96 | 35.77 |
| 技能标题 | 14 | 7.00 | 5.93 | vcenter | 0.54 | 42.98 |
| 技能正文 | 10 | 12.00 | 8.47 | vcenter | 1.77 | 49.94 |
| 节标题 | 22 | 14.50 | 9.31 | bottom | 5.19 | 32.17 |
| 详情关键词 | 13 | 10.00 | 5.50 | vcenter | 2.25 | 41.38 |
| 详情时间 | 7 | 10.00 | 2.96 | vcenter | 1.02 | 43.24 |
| 详情标签 | 8 | 10.00 | 3.39 | vcenter | 3.31 | 40.85 |
| 详情描述 | 10 | 28.00 | 8.47 | flow | 0.00 | 50.18 |

**常用行高的「贴合值」**（盒高等于它时 `dy_align=0`，文字刚好占满盒）：

| 字号 × 行数 | 文字实高 | 加 padding 后的贴合盒高 |
| --- | --- | --- |
| 22pt × 1 行 | 9.31 | 9.31 |
| 14pt × 1 行 | 5.93 | 5.93 |
| 13pt × 1 行 | 5.50 | 5.50 |
| 12pt × 1 行 | 5.08 | 5.08 |
| 10pt × 2 行 | 8.47 | 8.47 |
| 10pt × 1 行 | 4.23 | 4.23 |
| 8pt × 1 行 | 3.39 | 3.39 |
| 7pt × 1 行 | 2.96 | 2.96（+`Padding.top(5)` → 7.96） |

> **怎么用**：想让文字在盒内**居中**就把 `align_y` 设为 `VCENTER`（多数模板已是默认）；
> 想**贴底**用 `BOTTOM`；想让盒高完全贴合文字就用上表的"贴合盒高"，
> 此时盒高不再是可调旋钮，文字一定占满。

### 11.5 与留白（`Lead`）的分工

中层**不含任何留白常量** —— 节间距、行间距都在顶层 `ResumeCore.__Lead_default_settings__`。
中层只提供 `add_spacer(name, height)` 这个动作。

> 所以"节与节之间太挤"这类问题要改 `ResumeCore` 的 `Lead`，
> **不在本手册范围内**。完整键表见第 5.2 节。

分工原则：**中层管"一个模板内部长什么样"，顶层管"模板之间的间距"。**

### 11.6 不该动的参数（避免踩坑）

| 参数 | 为什么 |
| --- | --- |
| `line_height`（`TextObject` 构造参数） | **死参数**：只被写入 `_line_height`，全库从不读取。传了不会有任何效果（见 SKILLS.md D6） |
| `add_details` 里 `key`/`time`/`tags` 的 `align_y` | 三处刻意不同（姓名行 `VCENTER`、节标题 `BOTTOM`、详情三栏 `VCENTER`）。**2026-10-13 起 `align_y` 真正生效了**，改它会实际移动文字，不再是无害参数 |
| `STYLES["detail_key_2"]` 系列 | 无调用方。要用就先在调用点显式传 `key_style=STYLES["detail_key_2"]`，别改默认 |
| `Style.padding` 的默认值 | 引擎已改为"每次新建独立 `Padding`"（修 7.10）。不要把 `None` 改回 `Padding.all(0)` |
| `create_band` 建出的横带宽度 | `add_profile` / `add_section_title` 会**显式覆盖** `band.width`（配合 `row_inset` 收窄）。改这里要同时改两处 |
| 直接写 `obj._height` | 绕过尺寸方式解析。要用公开属性 `obj.height = N` |

### 11.7 症状 → 该拧哪个旋钮

> **已按 2026-10-13 的引擎修复更新**。带 ✅ 的条目是**实测确认**的；
> 其余是"结构上必然成立"的对应关系，具体数值仍建议对着 PDF 微调。
> 看到不对时用一句话描述（如"左栏姓名下方太空"），我补精确数值。

| 你想解决的问题 | 该动的地方 | 连带效应 |
| --- | --- | --- |
| ✅ **某段文字在盒子里偏上/偏下** | **`align_y`**：`VCENTER` 居中 / `BOTTOM` 贴底 / `TOP` 贴顶 | 修复后真正生效。盒内可用高 = 盒高 − padding |
| ✅ **想让文字正好占满盒子** | 盒高设成 11.4b 表里的"贴合盒高" | 此时 `dy_align=0`，与 `align_y` 无关 |
| ✅ **文字跑到盒子外面 / 压住下面的元素** | 先确认盒高 ≥ 文字实高（11.4b 表） | 引擎已修单位缺陷；若仍溢出就是盒高真不够 |
| **左栏整体太挤 / 太空** | 左栏内容总高 = 证件照 + 姓名行 + 联系方式行 + 技能三块之和 | 改任一行高度都会推动其下所有行 |
| 姓名行太高/太矮 | `add_profile(content_height=N)`，或 `icon_width`（参与下限） | 只改字号可能被图标下限顶住 |
| 证件照太大/太小 | `add_profile_photo(photo_width=N)` | 行高 = 宽 × 1.6，**平方级影响** |
| 左栏文字离左边太近/太远 | `add_profile(row_inset=N)` | 宽度同步收窄，文本可用宽变小 |
| 技能/证书/荣誉之间太挤 | `ResumeCore` 的 `Lead["Left_Column_Between_Skills&Awards"]` | **不在中层**，见 11.5 |
| 技能正文行留空太多 | `add_text_row(height=...)`；`ResumeCore` 传的是 `条目数×6` | 该行只有一个文本块，`VCENTER` 会把它居中 |
| 左右栏宽度不合理 | `add_basic(ratio=[a, b])` | **改一处动全篇**：变窄→更多折行→后续下移 |
| 右栏正文离左栏太近 | `add_basic(right_padding=Padding.left(N))` | 只改右栏内容区，不影响左栏 |
| 节标题太高/太矮 | `add_section_title(height=N)` | 内部分成"标题带 `N−0.5`" + "分隔线 0.5" |
| ✅ **节标题文字离分隔线太远** | 节标题文字是 `BOTTOM` 对齐，会贴着标题带底边 | 想让它上浮就改 `height`（带子变高、文字仍贴底）或换 `align_y` |
| 节标题图标太大 | `add_section_title(icon_width=N)` | 图标是正方形，边长 = 此值；同时挤压标题文字宽 |
| 节标题离正文太近/太远 | `ResumeCore` 的 `Lead["Right_Column_Between_SectionTitle_SectionDetails"]` | **不在中层** |
| 详情三栏太挤 | `add_details(brief_height=N)` | 只影响该条详情的三栏，整条详情随之变高 |
| 关键词一栏太窄/太宽 | `add_details(brief_ratio=[a,b,c])` | 必须 3 个元素；影响该条详情 |
| 详情描述行距太密/太松 | **只能改字号或行数** | 行高系数 1.2 未暴露（见 11.6） |
| 详情描述下方留空太多 | `add_details(description_height=N)` 固定高度；默认自动结算 | 固定值小于实际内容高会**溢出**（`content_overflows`） |
| 某些字想加粗/变色 | `TextObject` 的**行内 Markdown**：`**粗**`、`*斜*`、`` `等宽` ``、`<c:RRGGBB>色</c>` | 已默认开启（`markdown=True`），见 3.4c |
| 个人总结太高/太矮 | `add_summary(description_height=N)` | 默认自动结算 |

> **行内 Markdown 是"引导 HR 注意力"的现成手段** —— 无需新模板，
> 只要在描述文本里写 `**关键成果**` 即可。已验证可用（3.4c 的实测）。

> ✅ **`align_y` 现在是可用的版面旋钮**：修复前它形同虚设（文字总在盒子上部偏下），
> 现在可以真正控制"文字在某一个范围内居中或任意对齐"。

### 11.8 还没做、但你知道会需要的

| 想做的事 | 现状 | 相关条目 |
| --- | --- | --- |
| 详情**分条列出**（每行一条 + 项目符号） | 描述是**一块多行文本**，条目靠 `\n` 分隔。分条需要新模板 | SKILLS.md 的视觉优化方向 |
| 单条详情内**每行独立的左缩进/符号** | 同上 | — |
| 技能正文按内容自动定高 | `ResumeCore` 用"条目数×6"估算 | SKILLS.md M8 |
| 关键词单独放大/换色之外的**行内混排** | 可用行内 Markdown，已验证 | 3.4c |
