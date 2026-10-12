# PythonPDFLayoutSystem 技术文档

> 本文档由代码实读整理，对应工作区当前状态（`master` 上的 `8af9962` **之后的未提交工作树**）。
> 所有函数签名、参数、返回值均取自实际代码；标为"实测"的结论均附可复现的观测数据。
>
> **已完成批次**：基础设施（`.gitignore` + 字体说明 + `.pyproj` 入口）、
> 批次 0（修 7.1 / 7.15 / 7.17 / 7.18）、批次 1（抽 `create_spacer`，8.2）、
> 批次 2（抽 `create_band`，修 7.3 / 7.4，8.1）、
> 批次 3（`Style` 下沉 + `from_style` + `create_text_block`，8.3 / 8.4）。
> 批次 4 承载"矩形包围内容"，前置分析见 8.11；批次 6（分页）暂缓。
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
┌─ 顶层：功能 ────────────────────────────────────────────────┐
│  ResumeCore.py     Profiles / SkillsAwards / Details /      │
│                    Section / Resume                         │
│                    → 领域数据模型 + 数据到 PDF 的编排        │
│  ResumeTemplate.py STYLES / generate_*_template / fill_*    │
│                    → 简历版式词汇：姓名、节标题、节详情      │
└─────────────────────────────────────────────────────────────┘
                            ↓ 依赖
┌─ 中层：快捷调用 ────────────────────────────────────────────┐
│  split_column_advanced()   传入已构造对象的左右分栏          │
│  create_columns()          按数量/宽度/比例创建 N 栏         │
│  create_columns_balanced() 等宽分栏                          │
└─────────────────────────────────────────────────────────────┘
                            ↓ 依赖
┌─ 底层：基本构件 ────────────────────────────────────────────┐
│  AlignX / AlignY / Color / Padding                          │
│  LayoutObject（几何、父子、wrap、缓存）                      │
│  TextObject / ImageObject / RectangleObject（渲染）          │
│  LayerManager / objectRegister（全局registry）              │
└─────────────────────────────────────────────────────────────┘
```

**分层违规（批次 2 已消除）**：`split_column_advanced`（中层能力）原本住在 `ResumeTemplate.py`
（顶层文件）里，`ResumeCore.py` 因此不得不 `from ResumeTemplate import ...` 才能分栏。
批次 2 已把它连同新的 `create_band` 一起移入引擎（见 3.4），依赖方向恢复正常。

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

#### `class AlignX(Enum)`
水平对齐。成员：`LEFT="left"`、`CENTER="center"`、`RIGHT="right"`、`NONE="none"`。

| 值 | `get_absolute_x()` 行为 |
| --- | --- |
| `LEFT` | 贴父内容区左边界 |
| `CENTER` | 在父内容区水平居中 |
| `RIGHT` | 贴父内容区右边界 |
| `NONE` | `父内容区左边界 + _x` |

#### `class AlignY(Enum)`
垂直对齐。成员：`TOP="top"`、`VCENTER="vcenter"`、`BOTTOM="bottom"`、`NONE="none"`、`FLOW="flow"`。

| 值 | `get_absolute_y()` 行为 |
| --- | --- |
| `TOP` | 贴父内容区上边界 |
| `VCENTER` | 在父内容区垂直居中 |
| `BOTTOM` | 贴父内容区下边界 |
| `NONE` | `父内容区上边界 + _y` |
| `FLOW` | 紧贴前一个 FLOW 兄弟的底边；无前驱则贴父内容区上边界 |

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
    wrap_width: bool = False,
    wrap_height: bool = False,
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
  "wrap": {"width","height","height_set_by_wrap","width_set_by_wrap"},
  "geom_cache_valid": bool,
}
```

#### 尺寸推算（wrap_content）

| 方法 | 签名 | 返回 | 说明 |
| --- | --- | --- | --- |
| `wrap_content` | `(force: bool = False) -> float` | 计算出的高度 | 走 `_calculate_wrap_height()`；`_height > 0` 时直接采用 `_height` 并跳过计算 |
| `wrap_content_width` | `(force: bool = False) -> float` | 计算出的宽度 | 走 `_calculate_wrap_width()` |
| `invalidate_wrap_cache` | `() -> None` | — | 清标志并**向上传播到父** |
| `is_wrapped` | `() -> bool` | `wrap_width or wrap_height` | |
| `is_height_wrapped` | `() -> bool` | `_wrap_height` | |
| `is_width_wrapped` | `() -> bool` | `_wrap_width` | |
| `get_wrap_status` | `() -> Dict[str, Any]` | 缓存状态快照 | |
| `_calculate_wrap_height` | `() -> float` | 内部，子类各自重写 | 见 3.3 |
| `_calculate_wrap_width` | `() -> float` | 内部 | 取子元素最大宽度 + 左右 padding，再夹到父可用宽 |

**防循环**：`_is_wrapping` 标志。`wrap_content()` 在重入时抛 `RuntimeError`；
`_calculate_wrap_*()` 在重入时返回当前 `_height`/`_width`（软降级）。

**优先级约定**：`_height > 0` ⇒ 显式高度胜出，wrap 不生效。
这就是 `fill_section_details_data` 用 `desc_obj._height = description_height` 调参能work的原因。

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

三者共同点：都继承 `LayoutObject`，都重写 `_calculate_wrap_height()`，都重写 `render()` 与 `render_debug()`。

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
    wrap_width: bool = False, wrap_height: bool = False,
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
    wrap_width: bool = False, wrap_height: bool = False,
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
    wrap_width: bool = False, wrap_height: bool = False,
)
```

只多了一个 `_calculate_wrap_height()` 重写（无内容，仅累加子元素 + padding）。

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

## 4. ResumeTemplate.py API

### 4.1 `class Style`

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
    fit_mode = "cover",
)
```

纯数据类，"长什么样"的属性集合，不含位置信息。

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `get_font_style()` | `str` | `"B"` / `"I"` / `"BI"` / `""`，fpdf 兼容 |
| `__repr__()` | `str` | 调试字符串 |

> ⚠️ `padding: Padding = Padding.all(0)` 是**可变默认参数**，全部 `Style` 实例共享同一个 `Padding` 对象。
> 当前无代码改写它，所以未爆雷，但是个隐患。见 7.10。

### 4.2 `STYLES` 字典

模块级样式表，键 → 用途：

| 键 | 用途 | 关键属性 |
| --- | --- | --- |
| `left_column` | 左栏底色 | `fill_color=RimuruBlue` |
| `profile_photo` | 证件照 | `fit_mode="cover"` |
| `name_image` | 姓名旁图标 | `image_path=""`（待填） |
| `name_text` | 姓名文字 | LXGW 22pt 粗体 |
| `profile_text` | 联系方式文字 | LXGW 12pt 粗体 |
| `contact_text` | 联系方式（备用） | LXGW 10pt |
| `skillsawards_title` | 技能/证书/荣誉标题 | LXGW 14pt |
| `skillsawards_text` | 技能/证书/荣誉正文 | LXGW 10pt |
| `section_title_image` | 节标题图标 | `image_path=""`（待填） |
| `section_title_text` | 节标题文字 | LXGW 22pt 粗体，深蓝 |
| `detail_key_1` | 详情关键词（组1） | LXGW 13pt 粗体 |
| `detail_time_1` | 详情时间（组1） | LXGW 7pt，`padding=Padding.top(5)` |
| `detail_tags_1` | 详情标签（组1） | LXGW 8pt |
| `detail_key_2` | 详情关键词（组2，备选） | LXGW 12pt 粗体 |
| `detail_time_2` | 详情时间（组2） | LXGW 8pt |
| `detail_tags_2` | 详情标签（组2） | LXGW 8pt |
| `detail_description` | 详情描述正文 | LXGW 10pt |

> `name_image`、`section_title_image` 的 `image_path` 为空，需由调用方 `set_image()` 填充。
> 组2（`_2` 系列）已定义但**当前无代码使用**。

### 4.3 模板生成函数

所有 `generate_*` 函数遵循统一约定：
- **返回值**：新建的 `content` 对象（`ResumeTemplate.py` 中一律为 `LayoutObject`）。
- **副作用**：立即 `root.add_child(content)` 并级联创建全部子节点，**注册到全局 `objectRegister`**。
- **命名约定**：`f"{root.name}_{模板标识}_{index}_..."`，因此必须用**挂载点的 name** 去 `find_by_name`。

#### `generate_basic_subtemplate(...)`

```python
generate_basic_subtemplate(
    root: LayoutObject,
    ratio: list = None,              # 默认 [1.0, 2.5]
    left_padding: Padding = None,    # 默认 Padding.all(0)
    right_padding: Padding = None,   # 默认 Padding.left(5)
    layer: int = 0,
) -> LayoutObject                    # 返回 {root.name}_split_container
```

产出结构：

```
root
└── {root}_split_container : LayoutObject
    ├── {root}_left_column  : RectangleObject   (fill = STYLES["left_column"].fill_color)
    └── {root}_right_column : LayoutObject      (color = Green)
```

约束：**同一份简历中只应调用一次**。返回的 `content` 需自行 `find_by_name` 取回。

#### `generate_profile_template(...)`

```python
generate_profile_template(
    root, index,
    icon_style: Style = None,        # 默认 STYLES["name_image"]
    text_style: Style = None,        # 默认 STYLES["profile_text"]
    icon_width: float = 4,
    gap: float = 0,
    layer: int = 0,
    content_height = 20,
) -> LayoutObject                    # 返回 {root}_profile_{index}_content
```

产出结构：

```
{root}_profile_{index}_content : LayoutObject   (height=content_height, align_x=CENTER, align_y=FLOW)
└── {root}_profile_{index}_split : LayoutObject (padding=Padding.left(3))
    ├── {root}_profile_{index}_icon_range : LayoutObject (width=icon_width)
    │   └── {root}_profile_{index}_icon   : ImageObject  (fit_mode="cover", align=VCENTER, layer+1)
    └── {root}_profile_{index}_text_range : LayoutObject (x=icon_width+gap)
        └── {root}_profile_{index}_text   : TextObject   (align_x=LEFT, align_y=VCENTER, layer+1)
```

宽高计算：`content_w` 从 `content.get_content_area()` 取；若 `<= 0` 则回退到 `root` 的内容宽，
再回退到硬编码 `150`。`right_width = content_w - icon_width - gap`，为负则归零并令 `gap = 0`。

#### `generate_profile_photo_template(...)`

```python
generate_profile_photo_template(
    root, index,
    icon_style: Style = None,        # 默认 STYLES["profile_photo"]
    photo_width: float = 30,
    layer: int = 0,
) -> LayoutObject                    # 返回 {root}_profile_photo_{index}_content
```

```
{root}_profile_photo_{index}_content : LayoutObject (height = photo_width * 1.6, align_x=CENTER, align_y=FLOW)
└── {root}_profile_photo_{index}_photo : ImageObject (width=photo_width, align=CENTER/VCENTER, layer+1)
```

> ⚠️ `photo` 构造时 `parent=root`（第 655 行），但随后被 `content.add_child(photo)` 重新挂到 `content` 下。
> 实际父子关系正确，但构造参数有误导性。

#### `generate_section_title_template(...)`

```python
generate_section_title_template(
    root, index,
    icon_style: Style = None,        # 默认 STYLES["section_title_image"]
    text_style: Style = None,        # 默认 STYLES["section_title_text"]
    icon_width: float = 10,
    gap: float = 0,
    layer: int = 0,
) -> LayoutObject                    # 返回 {root}_section_title_{index}_content
```

```
{root}_section_title_{index}_content : LayoutObject (height=15, align_x=CENTER, align_y=FLOW)
├── {root}_section_title_{index}_split : LayoutObject (height=15-0.5, align=NONE)
│   ├── ..._icon_range : LayoutObject (padding=Padding.bottom(3))
│   │   └── ..._icon : ImageObject (fit_mode="contain", align=CENTER/BOTTOM, layer+1)
│   └── ..._text_range : LayoutObject (x=icon_width+gap)
│       └── ..._text : TextObject (align_x=LEFT, align_y=BOTTOM, layer+1)
└── {root}_dividing_line : RectangleObject (height=0.5, align_y=BOTTOM)
```

> ⚠️ `dividing_line` 的 name 用 `{root}_dividing_line`，**不含 index**（第 836 行）。
> 多个节标题会互相覆盖 `objectRegister` 里的同名条目，`find_by_name` 只能找到最后一个。

#### `generate_section_details_template(...)`

```python
generate_section_details_template(
    root, index,
    key_style: Style = None,         # 默认 STYLES["detail_key_1"]
    time_style: Style = None,        # 默认 STYLES["detail_time_1"]
    tags_style: Style = None,        # 默认 STYLES["detail_tags_1"]
    desc_style: Style = None,        # 默认 STYLES["detail_description"]
    brief_ratio: list = None,        # 默认 [2.0, 1.0, 2.0]
    brief_height: float = 10,
    layer: int = 0,
) -> LayoutObject                    # 返回 {root}_section_details_{index}_content
```

```
{root}_section_details_{index}_content : LayoutObject (align=CENTER/FLOW)
├── ..._brief : LayoutObject (height=brief_height, align=CENTER/FLOW)
│   ├── ..._brief_col_0 : LayoutObject  → ..._key          : TextObject (LEFT/VCENTER)
│   ├── ..._brief_col_1 : LayoutObject  → ..._during_time  : TextObject (CENTER/VCENTER, padding=time_style.padding)
│   └── ..._brief_col_2 : LayoutObject  → ..._tags         : TextObject (RIGHT/VCENTER, padding=Padding.right(1.5))
└── ..._details : LayoutObject (align=CENTER/FLOW)
    └── ..._description : TextObject (multi_line=True, height=50, line_height=font_size*0.6, align=LEFT/FLOW)
```

三栏按 `brief_ratio` 等分 `brief_w`，无间距（`gap_total = 0`），`col_2` 额外加 `Padding.right(1.5)`。
`brief_w <= 0` 时同样回退到 `root` 内容宽、再回退到硬编码 `150`。

> ⚠️ `_description` 的 `height` 硬编码为 `50`，**必须**由 `fill_section_details_data` 改写，
> 否则该条详情固定占用 50mm。见 7.8。

#### `generate_summary_template(...)`

```python
generate_summary_template(
    root, index,
    desc_style: Style = None,        # 默认 STYLES["detail_description"]
    layer: int = 0,
) -> LayoutObject                    # 返回 {root}_section_details_{index}_content
```

结构与 `generate_section_details_template` 的 `content → details → description` 部分**完全一致**，
只是没有 `brief` 三栏。注意它与 details 模板**共用同一套命名前缀** `{root}_section_details_{index}`，
所以两者的 `index` 必须在同一命名空间内错开。见 7.2。

### 4.4 数据填充函数

约定：全部通过全局 `root.find_by_name(...)` 定位，找不到就**静默跳过**（`if obj:` 保护），不报错。

#### `fill_profile_data(root, index, name: str, image_path: str = "")`
填充 `{root}_profile_{index}_icon`（仅当 `image_path` 非空）与 `{root}_profile_{index}_text`。

#### `fill_section_title_data(root, index, title: str, image_path: str = "")`
填充 `{root}_section_title_{index}_icon` 与 `{root}_section_title_{index}_text`。

#### `fill_section_details_data(...)`

```python
fill_section_details_data(
    root, index,
    key: str, during_time: str, tags: str, description: str,
    brief_height = 10,
    description_height: float = 50,
) -> None
```

填充四处，并**直接改写两个 `_height`**：

```
{root}_section_details_{index}_content._height = description_height + brief_height
{root}_section_details_{index}_description._height = description_height
```

这是当前唯一的"高度调参"手段。因为 `_height > 0` 时 wrap 不生效（3.2 节优先级约定），
所以必须在填充阶段显式给出高度，否则文本块会按硬编码的 50mm 占位。

#### `fill_summary_data(...)`

```python
fill_summary_data(root, index, description: str, description_height: float = 50) -> None
```
同上，但只改 `content._height` 与 `description._height`（不涉及 `brief_height`）。

---

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
> ⚠️ `skills: List[str] = []` 等三个**可变默认参数**，与 `Style.padding` 同类隐患（见 7.10）。

#### `@dataclass Details`

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `key` | `str` | `""` | 学校/项目/公司名 |
| `during_time` | `str` | `""` | 起讫时间 |
| `tags` | `str` | `""` | 专业/技术栈 |
| `description` | `str` | `""` | 详情描述 |
| `description_height` | `float` | `12.0` | **手动调参的排版高度（mm）** |

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
    summary_height: float = 30.0,
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

`Generate` 的完整流程：校验 `profile.is_empty()` → 建 PDF/加页 → 注册 LXGW 字体（失败静默吞掉）
→ 设置元数据 → 建 `Root`（210×297，padding 10）→ `generate_basic_subtemplate`
→ 取左右栏 → `_fill_left_column()` → `_fill_right_column()` → 渲染 → 输出到 `output_dir`。

`_fill_left_column()` 顺序：上方留白 → 证件照 → 照片/姓名间留白 → 头像+姓名 → 姓名/联系人间留白
→ 联系方式（每条 + 间隔留白）→ 技能/证书/荣誉（各自标题 + 正文 + 间隔留白）→ 底部留白。

`_fill_right_column()` 顺序：上方留白 → 遍历 `sections`（节标题 + 标题/详情间留白 + 各详情 +
详情间留白）→ 节间留白 → 个人总结（标题 + 留白 + 正文）→ 底部留白。

> ⚠️ `_fill_right_column` 里 `section_details_index` 被**递增两次**（第 1008 行与第 1029 行），
> 导致节内第 2 条详情之后的编号跳号（0,1,3,4,...）。模板本身仍能生成，
> 但 `Details` 与模板实例的索引不再一一对应。见 7.12。

---

## 6. 命名与查找约定

模板的一切都靠**名字字符串**连接，这是本项目最容易踩坑的地方。

规则：`{挂载点.name}_{模板标识}_{index}_{部件}`

| 部件名 | 所属模板 | 类型 |
| --- | --- | --- |
| `profile_{i}_content` | `generate_profile_template` | `LayoutObject` |
| `profile_{i}_split` | 同上 | `LayoutObject` |
| `profile_{i}_icon_range` / `profile_{i}_icon` | 同上 | `LayoutObject` / `ImageObject` |
| `profile_{i}_text_range` / `profile_{i}_text` | 同上 | `LayoutObject` / `TextObject` |
| `profile_photo_{i}_content` / `profile_photo_{i}_photo` | `generate_profile_photo_template` | `LayoutObject` / `ImageObject` |
| `section_title_{i}_content` | `generate_section_title_template` | `LayoutObject` |
| `section_title_{i}_split` / `_icon_range` / `_icon` / `_text_range` / `_text` | 同上 | |
| `dividing_line` | 同上（**无 index**） | `RectangleObject` |
| `section_details_{i}_content` | details / summary 模板 | `LayoutObject` |
| `section_details_{i}_brief` / `_brief_col_0..2` | `generate_section_details_template` | `LayoutObject` |
| `section_details_{i}_key` / `_during_time` / `_tags` | 同上 | `TextObject` |
| `section_details_{i}_details` / `_description` | 两者共用 | `LayoutObject` / `TextObject` |
| `skills_title_content` / `skills_title` / `skills_text_content` / `skills_text` | `ResumeCore._fill_left_column` | |
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

### 7.2 details 与 summary 模板共用命名空间（逻辑级）

- **位置**：`ResumeTemplate.py:905`（`prefix = f"{root.name}_section_details_{index}"`）
  与 `ResumeTemplate.py:1121`（**同一个 prefix 表达式**）
- **现象**：`generate_summary_template` 产出的节点名与 `generate_section_details_template` 完全相同。
- **风险**：若两者用了相同的 `index`，`objectRegister` 相互覆盖，
  `fill_summary_data` 可能改到 details 模板的对象上。
- **当前缓解**：`ResumeCore._fill_right_column` 让 `section_details_index` 在 summary 之前已经递增过，
  所以恰好不撞号——这是**巧合**，不是设计。

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

### 7.6 `ImageObject._calculate_wrap_height` 内部新建 FPDF 实例

- **位置**：`LayoutEngine.py:1426-1434`
- **现象**：为读图片宽高比，临时 `from fpdf import FPDF; pdf = FPDF()`。
- **后果**：每次 wrap 计算都构造一个 PDF 对象；且 `try/except` 吞掉所有异常后
  回退成 `total_height = self._width`（把宽度当高度用）。
- **正解**：`ImageObject` 应在 `set_image` 时缓存原始尺寸，或接受外部注入的 `pdf`。

### 7.7 两套不一致的文本行数估算

- **位置**：`LayoutEngine.py:1105-1107`（`calculate_text_size`：`int(text_width / effective_width) + 1`）
  与 `LayoutEngine.py:1150-1152`（`_calculate_wrap_height`：`len(self._text) // 20 + 1`）
- **现象**：同一段文本，两个方法给出的行数不同。
- **后果**：`wrap_height` 算出的高度与渲染时的实际换行数不匹配，
  多行文本会出现裁切或溢出。

### 7.8 `description.height` 硬编码 50（调用方必须记得改）

- **位置**：`ResumeTemplate.py:1071`、`ResumeTemplate.py:1161`
- **现象**：`height=50` 写死在构造里，靠 `fill_*` 改写 `_height` 才正确。
- **后果**：忘记调用 `fill_section_details_data` / `fill_summary_data`，该块就固定占 50mm。
- **状态**：**成因已在引擎侧消除（批次 3）** —— `create_text_block` 的 `height`
  是显式参数，不再有硬编码常量。但模板层的两处 `height=50` 调用点
  **属功能分支**，迁移时会显式传入 `50`（不能依赖新默认值 `0`）。见 `SKILLS.md`
  的「只在功能分支处理的事项」。

### 7.9 `RectangleObject.render` 忽略 `is_fill`

- **位置**：`LayoutEngine.py:1656-1663`（原分支被注释，改为无条件 `'F'`）
- **后果**：`RectangleObject` 永远实心填充，`is_fill=False` 时也不例外，
  与 `TextObject` / `ImageObject` 的 `is_fill` 语义不一致。
  调试渲染时所有矩形都是实心的，会盖住下层内容。

### 7.10 可变默认参数

| 位置 | 参数 |
| --- | --- |
| `ResumeTemplate.py:74` | `padding: Padding = Padding.all(0)` |
| `ResumeCore.py:152-155` | `skills: List[str] = []`、`qualifications`、`awards` |
| `ResumeCore.py:315` | `Lead: dict = {}` |

- **后果**：默认对象在多次实例化间共享。当前无代码原地修改它们，所以**尚未爆雷**，
  但任何 `style.padding.left = 5` 或 `self.Lead["x"] = ...` 都会污染其他实例。

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

### 7.12 `section_details_index` 双重递增

- **位置**：`ResumeCore.py:1008` 与 `1029`（同一循环体内）
- **后果**：节内详情编号跳号。模板生成与填充用同一个 `index`，所以**功能正确**，
  但 `objectRegister` 里出现大量未使用的编号，`Details[i]` 与模板 index 不再对应。

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

### 7.16 调试/查询辅助的若干不一致

- `LayerManager._cache_valid` 被写从不被读。
- `generate_section_title_template` 的 `dividing_line` 命名缺 `index`。
- `generate_profile_photo_template` 里 `photo` 构造时传 `parent=root`，随后又 `content.add_child(photo)`。
- `ResumeTemplate.py:1515` / `ResumeCore.py` 的 `key_names` 列表里有一批永远不会命中的名字（见第 6 章推论 2）。

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

### 7.19 `wrap_height=True` 使高度塌缩为 padding（父子高度自指）— 待批次 4 修

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

### 7.20 `invalidate_wrap_cache` 后 `_height` 不复位，wrap 结果永久卡死 — 待批次 4 修

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
  目前只能手工把 `_height` 归零才能重新计算。
- **影响**：直接打击"矩形包围内容"的核心用法 —— 动态增删内容时矩形必须跟着变。
- **与 7.19 的关系**：7.19 决定"第一次算就算不对"，7.20 决定"算错之后再也算不回来"。
  两者叠加使 `wrap_content` 实际上不可用，必须同批修复（批次 4）。

### 7.21 `wrap_width` 完全不可用 — 待批次 4b 修

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
- **修法方向**：需要为 `wrap_width` 定义独立的宽度传播规则
  （例如子元素宽度为 0 时在 wrap 测量上下文里改用"内容固有宽度"而非父宽），
  不能复用 `_width == 0 → 撑满父宽` 的既有语义。

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

### 8.5 统一缓存失效入口

- **现状**：`_x/_y/_width/_height/_layer/padding/align_x/align_y` 全是裸属性或私有属性，
  外部可以直接写（`ResumeCore.py:1256` `content_obj._height = ...`、
  `ResumeTemplate.py:308-323` 直接改 `_x/_width/align_*`），**没有任何钩子触发失效**。
- **建议**：把几何属性改为 `@property` + setter，setter 内自动
  `invalidate_geom_cache()` + `invalidate_wrap_cache()`。
- **收益**：从机制上消灭 7.3 / 7.4 这类"忘了失效"的 bug，外部也不必再碰 `_height`。
- **风险**：需要先确认没有代码依赖"直接写得快"的行为（例如先设 `_height` 再立刻读数）。
  建议先加 `set_size(width, height)` / `set_position(x, y)` 显式接口作为过渡。

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
| **4** | **矩形包围内容前置**：几何属性改 property（8.5）+ 统一几何计算入口 + 修 7.19 父子高度自指 + 修 7.20 `_height` 卡死 + 明确 `wrap_content` 方向性 | 高 | 需新老 PDF 对比 + 缓存失效单测 | 待办 |
| **4a** | 包围**固定高度**内容（矩形 / 图片 / 显式高度文本块） | 中 | 包围盒尺寸断言 | 待办（批次 4 内交付） |
| **4b** | 修 7.21 `wrap_width` 完全不可用（阻断点 C） | 中 | 收窄包围盒断言 | 待办 |
| **5** | 真实行数测量（8.7），去掉 `description_height` | 高 | 视觉验收 | 待办 |
| **6** | **分页** —— 按页切分布局树 | 高 | 多页产物断言 | **暂缓**（多页需求出现时先在 `master` 完成） |

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

#### 验证方法（批次 1~3 必须沿用）

生成的 PDF 内含 `CreationDate` / `ModDate` / `ID` / `Producer` 等易变字段，
**直接做字节比对会永远失败**。批次 0 采用的比对流程：

1. 重构前先跑一遍，把生成的 PDF 另存为参考副本；
2. 重构后再跑一遍；
3. 对两份文件做**规范化**后比对——按字节以 Latin-1 读入，
   用正则把 `/CreationDate (D:...)`、`/ModDate (D:...)`、
   `/ID [<...> <...>]`、`/Producer (...)` 替换为固定占位符，再算哈希。

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

# 默认值
line_height 默认 = font_size * 0.6
fill_section_details_template: brief_height=10, brief_ratio=[2.0,1.0,2.0], description height=50
generate_basic_subtemplate:    ratio=[1.0, 2.5], right_padding=Padding.left(5)
split_column_advanced:         ratio=[1.0, 2.5], gap=0
create_columns:                num_columns=2, gap=5
create_band:                   gap=0, height=0（取父内容区高）, container_name="{parent.name}_band"
create_spacer:                 parent=None, layer=0
create_text_block:             height=0（取父可用高，**不是**按内容撑高）, align_x=LEFT, align_y=FLOW
Resume:                        summary_height=30.0

# 构造函数返回值对照（批次 2 变更）
create_band                -> 新建的带容器
create_columns             -> 新建的带容器   # 此前返回 parent
create_columns_balanced    -> 新建的带容器   # 此前返回 parent
split_column_advanced      -> parent         # 未变，保持链式调用兼容
create_text_block          -> 新建的 TextObject（已挂载）
from_style                 -> 新建对象（**未挂载**）
```
