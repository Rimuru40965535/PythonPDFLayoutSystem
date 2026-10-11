# PythonPDFLayoutSystem 技术文档

> 本文档由代码实读整理，对应工作区当前状态（git `master` @ `d5552dc` 之后的未提交工作树）。
> 所有函数签名、参数、返回值均取自实际代码，不含推测。

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
| `py ResumeCore.py` | ❌ **退出码 1，`ModuleNotFoundError: No module named 'ResumeTemplateV2'`** |

`ResumeCore.py:65` 从 `ResumeTemplateV2` 导入，但文件已更名为 `ResumeTemplate.py`。
**结果：一条完整简历的生成链路（`Resume.Generate`）当前不可运行。** 详见 7.1。

### 1.3 解释器与依赖

```
Python 3.14 (C:\Users\28375\AppData\Local\Python\pythoncore-3.14-64\python.exe)
fpdf2 2.8.8          ← 已安装，可用
```

注意：DSH 自带运行时（3.12）**没有** fpdf2，跑测试必须用 `py`。

### 1.4 资源缺口

`Resources/` 实际只有 6 个字体文件（`LXGWWenKai*.ttf`）。

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

**当前的分层违规**：`split_column_advanced`（中层能力）住在 `ResumeTemplate.py`（顶层文件）里，
`ResumeCore.py` 因此不得不 `from ResumeTemplate import ...` 才能分栏。第 8 章第 1 项即针对此点。

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

> ⚠️ `split_column_advanced` 绕过 `add_child`，直接 `container.children.append(...)`
> （`ResumeTemplate.py:313, 323`），因此不会触发缓存失效，靠末尾手动 `parent.invalidate_wrap_cache()` 兜底。
> 见 7.3。

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

### 3.4 中层：分栏

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
) -> LayoutObject          # 返回传入的 parent，支持链式
```

行为要点：

1. `column_widths` 与 `column_ratios` **互斥**，同时给出抛 `ValueError`。
2. 宽度分配（`usable = content_w - gap*(n-1)`）：
   - `column_widths` 给定：总和超出则等比缩小；不足则**把剩余空间均分加到每栏**；相等则原样使用。
   - `column_ratios` 给定：按比例分配。
   - 都不给：等宽。
3. **破坏性**：第 1822 行 `parent.children = []` 会**清空父元素已有子元素**
   （直接赋值列表，不走 `remove_child`，故父指针残留且缓存不失效）。见 7.4。
4. `names` 默认 `["Column_0", "Column_1", ...]`；`colors` 默认全 `Gray`。
5. 子栏尺寸为 `width × content_h`，`align_x/align_y` 均强制为 `NONE`。

#### `create_columns_balanced(...)`

```python
create_columns_balanced(parent, num_columns=2, gap=5, padding=None, layer=0) -> LayoutObject
```
等宽分栏，内部直接转发 `create_columns`。

#### `split_column_advanced(...)` —— 在 `ResumeTemplate.py`，不在引擎里

```python
split_column_advanced(
    parent: LayoutObject,
    left_obj: LayoutObject,
    right_obj: LayoutObject,
    ratio: list = None,        # 默认 [1.0, 2.5]，必须恰好 2 个元素
    gap: float = 0,
    padding: Padding = None,   # 默认 Padding.all(0)
    layer: int = 0,
) -> LayoutObject              # 返回 parent
```

与 `create_columns` 的区别：接收**已构造好的对象**（可为不同子类），直接挂载，不额外包装。

行为要点：
- 自动创建一个 `{parent.name}_split_container` 容器，尺寸 = 父内容区，`align_x/y = NONE`。
- 左栏：`_x=0, _y=0, _width=left_width, _height=content_h`；右栏：`_x=left_width+gap`。
- **直接改写传入对象的 `_x/_y/_width/_height` 与 `align_*`**，并直接 `container.children.append(...)`。
- `content_w <= 0` 或 `content_h <= 0` 时抛 `ValueError`。
- 末尾只调用 `parent.invalidate_wrap_cache()`，**不调用几何缓存失效**。

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

### 7.3 绕过 `add_child` 直接挂载（一致性级）

- **位置**：`ResumeTemplate.py:306-323`（`split_column_advanced`）
- **现象**：`container.children.append(left_obj)` 直接改列表，`left_obj.parent = container` 单独赋值。
- **后果**：`add_child` 里的 wrap + 几何缓存失效**都不会触发**；末尾只补了 `parent.invalidate_wrap_cache()`，
  **几何缓存没失效**。若左右栏在分栏前已被查询过几何值，会返回脏数据。
- **同类**：`LayoutEngine.py:1822` `parent.children = []`（见 7.4）。

### 7.4 `create_columns` 清空父元素子节点（破坏级）

- **位置**：`LayoutEngine.py:1822` `parent.children = []`
- **现象**：调用 `create_columns(parent=...)` 会**丢弃 parent 已有的全部子元素**。
- **后果**：被丢弃的子元素 `parent` 指针仍指向原 parent（悬空引用），
  且它们的 wrap/几何缓存未失效。调用方若先 `add_child(title)` 再 `create_columns`，title 就消失了。

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

### 7.11 渲染返回值契约不统一

| 类 | `render()` 返回 |
| --- | --- |
| `LayoutObject` | `float`（last_y） |
| `TextObject` | `float`（`abs_y + line_height` 或 `pdf.get_y()`） |
| `ImageObject` | `Tuple[float, float]` |
| `RectangleObject` | `Tuple[float, float]` |

`LayoutObject.render` 里的 `last_y` 会被 tuple 覆盖，父元素拿到的"最后 y"含义漂移。

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

---

## 8. 重构方向（按优先级）

> 本章是**建议**，不是已实施内容。采纳与否、先后顺序待定。

### 原则

**能下沉到 `LayoutEngine.py` 的，必须满足两个条件**：
1. **与"简历"无关**——不知道"姓名""联系方式""节标题"是什么；
2. **在至少两个不同上层场景里会重复出现**。

不满足的（如"节标题 = 图标 + 文字 + 分割线"）留在 `ResumeTemplate.py`。

### 8.1 【核心】把 `split_column_advanced` 下沉为引擎的"横向带"构件

- **现状**：分栏能力住在 `ResumeTemplate.py`，`ResumeCore.py` 为了分栏必须依赖模板层。
  引擎已有 `create_columns`，但它是"按数量造空栏"，`split_column_advanced` 是"按比例装已有对象"，
  两者在比例计算、`cumulative_x` 累加、`content_area` 取值上高度重复。
- **建议**：在 `LayoutEngine.py` 新增

  ```python
  def layout_band(
      parent: LayoutObject,
      cells,                          # List[LayoutObject] | List[tuple] | List[float]
      ratio: Optional[List[float]] = None,
      gap: float = 0,
      padding: Optional[Padding] = None,
      height: float = 0,              # 0 → 取父内容区高
      layer: int = 0,
      container_name: Optional[str] = None,
  ) -> LayoutObject:                  # 返回 parent
  ```

  统一承担：按比例算宽 → 累加 x → 建容器 → 挂载 → **通过 `add_child` 正确失效缓存**。
  然后 `split_column_advanced(...)` 变成一个 3 行的兼容包装（保留旧签名，行为不变），
  `create_columns(...)` 改为内部调用 `layout_band`。
- **收益**：`ResumeCore.py` 不再需要为了分栏 import 模板层；两处重复的比例/累加逻辑归一；
  顺手修掉 7.3、7.4。
- **风险**：`create_columns` 的"宽度不足时把剩余均分"语义与 `split_column_advanced` 的"严格按比例"不同，
  统一时必须显式区分（建议 `layout_band` 只做严格按比例，剩余均分作为 `create_columns` 的私有策略保留）。

### 8.2 【核心】下沉"留白"/间距构件

- **现状**：`ResumeCore` 里出现了 **14 次**几乎逐字相同的代码块（507, 531, 560, 624, 641, 733, 821,
  908, 933, 972, 1017, 1035, 1070, 1101 行，批次 0 前的行号）：

  ```python
  root.add_child(LayoutObject(
      name="Lead_...", x=0, y=0, width=0, height=<间距>,
      color=<随手写的白/蓝/绿/黄>, align_x=AlignX.CENTER, align_y=AlignY.FLOW,
      padding=Padding.all(0) 或 Padding.all(10), layer=0,
  ))
  ```

  纯噪声：颜色无意义（`align_y=FLOW` 时若不 `is_fill` 根本不画），`padding` 有时 `0` 有时 `10` 更是不一致。
- **建议**：引擎层加一个工厂

  ```python
  def create_spacer(name: str, height: float, parent=None, layer: int = 0) -> LayoutObject
  ```

  `ResumeCore` 里 12 处全部替换为 `create_spacer(...)`。
- **收益**：`_fill_left_column` / `_fill_right_column` 各瘦身数十行，间距参数一眼可读。
- **顺带修复**：那些 `Padding.all(10)` 会让 FLOW 间距实际变成 `10 + height` 的嫌疑，需要一并核对。

### 8.3 【核心】下沉"单块内容"构件（取代 7.8 的手工 `_height` 调参）

- **现状**：`generate_section_details_template` 与 `generate_summary_template` 的
  `content → details → description` 结构**逐行相同**；高度靠外部改写 `_height` 传入。
- **建议**：
  1. 引擎层提供 `create_text_block(parent, name, style, text, height, ...)`，
     把 `Style → TextObject 参数` 的翻译集中一处（目前这段翻译在 6 个模板函数里各写一遍）。
  2. 模板层让 `generate_summary_template` 复用 details 模板的 `details` 部分，
     并给它**独立命名前缀**（如 `_summary_{index}`），从根上消除 7.2。
  3. `height` 改为模板函数的显式参数，默认值不再硬编码 `50`（消除 7.8）。

### 8.4 【核心】把 `Style` 与"样式→对象"翻译下沉

- **现状**：`Style.get_font_style()` 是纯引擎概念（fpdf 的 `"B"/"I"/"BI"`），却住在模板层。
  且 `TextObject` 的 7 个参数（`font_name/font_size/font_style/text_color/padding/align_*/multi_line`）
  在每个 `generate_*` 里都要手抄一遍。
- **建议**：把 `Style` 移入 `LayoutEngine.py`（或引擎内的 `Style` 基类），
  并提供 `TextObject.from_style(name, style, text="", **overrides)` / `ImageObject.from_style(...)`。
- **收益**：模板函数体量下降约 40%；样式定义与渲染参数解耦；`ResumeTemplate` 只剩"简历词汇 + STYLES 表"。
- **注意**：这是**破坏性 API 变更**，`ResumeCore.py` 的 `STYLES["..."].get_font_style()` 等调用需同步。
  建议保留 `Style.get_font_style()` 为兼容别名。

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

- 统一 `render()` 返回值为 `float`（元素底边 y），或在 `LayoutObject` 里明确文档化 tuple 情形。
- `timer` 改为受模块级开关控制（`DEBUG_TIMING = False`），并改用 `logging` 而非 `print`。

### 8.9 配置与全局状态

- 抽出 `create_document(...)`：集中建 `FPDF`、注册字体（当前在 3 个 `__main__` + `Resume.Generate`
  里各写一遍，且字体路径 `.\Resources\...` 是**相对当前工作目录**的，换目录就失败）。
- 给 `layer_manager` / `objectRegister` 加 `reset()`，或改为挂在 `root` 上的实例，
  支持同进程生成多份文档。

### 8.10 建议的重构批次

| 批次 | 内容 | 风险 | 可验证性 | 状态 |
| --- | --- | --- | --- | --- |
| **0** | 修 7.1 导入；修 7.15 换行；修 7.17 重复挂载；修 7.18 末尾间距 | 极低 | 三个入口都能跑通 | ✅ **已完成** |
| **1** | 抽 `create_spacer`（8.2） | 低 | 输出 PDF 应与重构前**逐字节一致** | 待办 |
| **2** | 抽 `layout_band`，`split_column_advanced` 变包装（8.1） | 中 | 同上，逐字节比对 | 待办 |
| **3** | 抽 `create_text_block` / `from_style`（8.3、8.4） | 中 | 同上 | 待办 |
| **4** | 几何属性改 property（8.5） | 高 | 需新老 PDF 对比 + 缓存失效单测 | 待办 |
| **5** | 真实行数测量（8.7），去掉 `description_height` | 高 | 视觉验收 | 待办 |

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

批次 0 的实测结果：

| 产物 | 规范化后 |
| --- | --- |
| `test_layout_engine_cached.pdf` | **完全一致**（19316 字节） |
| `resume_template_v2_test.pdf` | **完全一致**（61370 字节） |
| `output/利姆露_*.pdf` | 相差 5 字节 —— 即 7.17、7.18 两处修复带来的预期变化 |

**这就是批次 1~3 的验收基线**：除了被有意修复的缺陷之外，
规范化后的 PDF 必须逐字节一致。任何未预期的差异都说明重构改变了行为，需要逐条解释。

> 📌 **给下一批次的提示**：批次 0 用的参考副本是临时文件，已随探查目录一并删除。
> 批次 1 动工前，请先**以当前工作树的输出为新基线**：
> 跑一遍三个入口，把 `test_layout_engine_cached.pdf`、`resume_template_v2_test.pdf`、
> `output/*.pdf` 复制到工作区外的临时目录，然后才开始改代码。

---

## 9. 测试入口

沿用项目传统：单元测试写在**各文件自己的 `if __name__ == "__main__":` 里**，可覆盖旧测试。

| 命令（在项目根目录执行） | 覆盖 | 产出 |
| --- | --- | --- |
| `py LayoutEngine.py` | 几何、流式、分栏、图层、缓存、三种渲染对象 | `test_layout_engine_cached.pdf` |
| `py ResumeTemplate.py` | 全部 `generate_*` + `fill_*` + `split_column_advanced` | `resume_template_v2_test.pdf` |
| `py ResumeCore.py` | 完整 `Resume.Generate` 链路 | `output/{姓名}_{职位}_{公司}.pdf` |

注意事项：

1. **必须用 `py`**（3.14 + fpdf2 2.8.8）。DSH 自带运行时没有 fpdf2。
2. 字体路径是相对路径 `.\Resources\...`，**必须在项目根目录执行**，否则字体会静默降级为 helvetica，
   中文变空白。
3. `Resources/` 缺全部图片资源（1.4 节），图片相关的视觉验收目前无法进行。
4. 三个入口都会在 stdout 打印大量渲染日志（7.13），建议重定向到文件再读尾部。

---

## 10. 附录：模块常量速查

```python
# LayoutEngine.py
AlignX: LEFT / CENTER / RIGHT / NONE
AlignY: TOP / VCENTER / BOTTOM / NONE / FLOW

Color: RimuruBlue Red Green Blue Yellow White Black Gray LightGray

Padding: .all(v) .rectangle(h,v) .horizontal(v) .vertical(v)
         .left(v) .right(v) .top(v) .bottom(v)

layer_manager: LayerManager()          # 全局单例
objectRegister: dict                   # 全局注册表
find_object_by_name(name="") -> Optional[Any]

# 默认值
line_height 默认 = font_size * 0.6
fill_section_details_template: brief_height=10, brief_ratio=[2.0,1.0,2.0], description height=50
generate_basic_subtemplate:    ratio=[1.0, 2.5], right_padding=Padding.left(5)
split_column_advanced:         ratio=[1.0, 2.5], gap=0
create_columns:                num_columns=2, gap=5
Resume:                        summary_height=30.0
```
