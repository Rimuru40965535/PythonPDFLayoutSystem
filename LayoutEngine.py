"""
================================================================================
PDF 排版引擎
================================================================================
功能概述：
    1. 基于矩形区域的布局管理
    2. 支持父子层级、内边距 (padding)
    3. 【四轴设计】尺寸与位置分离：
         SizeX / SizeY 决定"元素多大"（FILL / FIXED / CONTENT）
         AlignX / AlignY 决定"元素在哪"（含流式 FLOW）
    4. 【两趟遍历】先测量尺寸，再计算位置：
         趟 1 进入方向传约束、定 FILL/FIXED；退出方向收尺寸、定 CONTENT
         趟 2 只读对齐轴，算出绝对坐标
    5. 支持分栏 / 横向带布局（create_band / create_columns）
    6. 内容渲染：文本、图像、矩形
    7. 图层管理：按图层索引组织和渲染对象
    8. 调试渲染模式（显示边框、名称、尺寸）
    9. 对象注册表（按名称查找）

设计要点：
    - **约束向下传、尺寸向上收**：子元素的可用空间是作为参数拿到的，
      不再回头问父容器。这消除了旧实现里"父子互相递归"造成的循环依赖。
    - **CONTENT 与 FLOW 可以共存**：尺寸由内容决定的元素，位置依然可以
      接在前一个 FLOW 兄弟下方。这是两轴分离带来的能力。
    - **定死的尺寸不动**：FIXED 不因父容器装不下而被裁剪，装不下是溢出问题。
    - **循环依赖显式报错**：结构成环时抛 LayoutCycleError（含完整路径），
      而不是静默返回 0。

变更记录（批次 4）：
    - 4.1  新增 SizeX / SizeY 尺寸枚举与 LayoutCycleError
    - 4.2  以两趟遍历取代惰性 wrap 缓存，修 7.19 / 7.20
    - 4.3  几何属性改 property，改动自动触发失效
    - 4b   新增内容固有宽度路径（_source_w），修 7.21
    - 4.4  删除 wrap_width / wrap_height 兼容面，尺寸方式只由 size_* 表达

================================================================================
"""

from enum import Enum
from typing import Optional, Union, List, Tuple, Dict, Any, Callable
from collections import defaultdict
import inspect
import os
import time
from functools import wraps


# ============================================================================
# 计时器装饰器
# ============================================================================

def timer(func):
    """渲染计时装饰器（调试用）"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        start = time.perf_counter()
        result = func(self, *args, **kwargs)
        end = time.perf_counter()
        print(f"  >>> {self.name} 渲染时间: {end - start:.4f} 秒")
        return result
    return wrapper


# ============================================================================
# 1. 对齐方式枚举与尺寸方式枚举
# ============================================================================
#
# 【四轴设计】每个元素在两条轴上各有两种独立属性：
#
#     轴    | 尺寸（元素自身多大）  | 位置（元素落在父内容区的哪里）
#     ------+----------------------+--------------------------------
#      水平 | SizeX                | AlignX
#      垂直 | SizeY                | AlignY
#
# 两轴严格分离：
#     - 尺寸枚举只决定"多大"，不决定"在哪"
#     - 对齐枚举只决定"在哪"，不决定"多大"
#
# 因此 wrap（内容定尺寸）与 flow（流式接续定位）可以**同时**成立 ——
# 一个高度由内容决定的元素，位置依然可以接在前一个 FLOW 兄弟下方。
# 这正是批次 5「文本按实际行数定高」所需要的形态。
# ============================================================================

class SizeX(Enum):
    """
    水平尺寸计算方式

    FILL    : 撑满父元素内容区宽度
    FIXED   : 使用代码中写死的 width，不另行计算、不被裁剪
    CONTENT : 由内容圈定（子元素最大宽 + 左右 padding），再对传入约束夹紧
    """
    FILL = "fill"
    FIXED = "fixed"
    CONTENT = "content"


class SizeY(Enum):
    """
    垂直尺寸计算方式

    FILL    : 撑满父元素内容区高度
    FIXED   : 使用代码中写死的 height，不另行计算、不被裁剪
    CONTENT : 由内容圈定（子元素高之和 + 上下 padding），再对传入约束夹紧
    """
    FILL = "fill"
    FIXED = "fixed"
    CONTENT = "content"


class AlignX(Enum):
    """水平对齐方式枚举（只决定位置，不决定尺寸）"""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    NONE = "none"


class AlignY(Enum):
    """垂直对齐方式枚举（只决定位置，不决定尺寸）"""
    TOP = "top"
    VCENTER = "vcenter"
    BOTTOM = "bottom"
    NONE = "none"
    FLOW = "flow"


class LayoutCycleError(RuntimeError):
    """
    布局循环依赖错误

    两种情形：
        1. 结构循环：元素成为自己的祖先（对象树被接成了环）
        2. 尺寸循环：SizeY/SizeX 为 CONTENT 的父元素，直接子元素却是 FILL ——
           父的高度由内容决定，而子元素的高度又要填满父的内容区，两者互为前提。
    """


class LayoutError_CONTENT_FILL(LayoutCycleError):
    """
    尺寸循环：CONTENT 父元素拥有直接的 FILL 子元素

    父的尺寸由内容决定，而该子元素的尺寸又要填满父的内容区 —— 两者互为前提。
    这是**结构性**矛盾，与约束的数值大小无关，因此在遍历的进入方向即可判定。
    """

    def __init__(self, parent, bad_children, axis: str):
        size_attr = "size_x" if axis == "X" else "size_y"
        axis_cn = "水平" if axis == "X" else "垂直"
        child_lines = "、".join(
            f"{c.name}({getattr(c, size_attr).value})" for c in bad_children
        )
        super().__init__(
            f"布局错误: 尺寸循环依赖（{axis_cn}轴）\n"
            f"  父元素    : {parent.name}  ({size_attr}={getattr(parent, size_attr).value})\n"
            f"  冲突子元素: {child_lines}\n"
            f"  原因      : 父的尺寸由内容决定，而该子元素的尺寸又要填满父的内容区，"
            f"两者互为前提。\n"
            f"  修法      : 把冲突子元素改为 Size{axis}.CONTENT 或 Size{axis}.FIXED，"
            f"或把父元素改为 Size{axis}.FILL / Size{axis}.FIXED。"
        )


# ============================================================================
# 2. 颜色类
# ============================================================================

class Color:
    """颜色类，用于存储 RGBA 颜色值"""
    def __init__(self, r: int, g: int, b: int, a: int = 0):
        self.r = r
        self.g = g
        self.b = b
        self.a = a
    
    def is_light(self) -> bool:
        return (self.r + self.g + self.b) / 3 > 200

    def to_RGBA(self) -> str:
        return f"({self.r},{self.g},{self.b},{self.a})"


RimuruBlue = Color(207, 239, 252, 0)
Red = Color(255, 0, 0, 0)
Green = Color(0, 255, 0, 0)
Blue = Color(0, 0, 255, 0)
Yellow = Color(255, 255, 0, 0)
White = Color(255, 255, 255, 0)
Black = Color(0, 0, 0, 0)
Gray = Color(200, 200, 200, 0)
LightGray = Color(230, 230, 230, 0)


# ============================================================================
# 3. 边距类 (Padding)
# ============================================================================

class Padding:
    """内边距类"""
    
    def __init__(self, left: float = 0, top: float = 0, right: float = 0, bottom: float = 0):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
    
    @classmethod
    def all(cls, value: float):
        return cls(value, value, value, value)
    
    @classmethod
    def rectangle(cls, horizontal: float, vertical: float):
        return cls(horizontal, vertical, horizontal, vertical)
    
    @classmethod
    def horizontal(cls, value: float):
        return cls(value, 0, value, 0)
    
    @classmethod
    def vertical(cls, value: float):
        return cls(0, value, 0, value)
    
    @classmethod
    def left(cls, value: float):
        return cls(value, 0, 0, 0)
    
    @classmethod
    def right(cls, value: float):
        return cls(0, 0, value, 0)
    
    @classmethod
    def top(cls, value: float):
        return cls(0, value, 0, 0)
    
    @classmethod
    def bottom(cls, value: float):
        return cls(0, 0, 0, value)


# ============================================================================
# 3.5 样式类 (Style)
# ============================================================================

class Style:
    """
    样式类 - 纯数据类，用于存储排版样式属性

    所有属性均为公有，除构造函数和调试方法外无任何方法。
    样式类不包含位置信息，只包含"长什么样"的属性。

    本类原先定义在模板层（ResumeTemplate.py），批次 3 移入引擎：
    "样式"是与领域无关的底层概念（它只描述"长什么样"），
    而"样式 → 渲染参数"的翻译（见 TextObject.from_style / ImageObject.from_style）
    也属于引擎职责。

    属性列表：
        font_name: 字体名称 (str)
        font_size: 字号 (float)
        bold: 是否粗体 (bool)
        italic: 是否斜体 (bool)
        color: 文字颜色 (Color)
        fill_color: 填充颜色 (Color)
        image_path: 图片路径 (str)
        padding: 内边距 (Padding)
        fit_mode: 图片适配模式 (str) — 仅 ImageObject 使用

    注意：
        `padding` 的默认值曾是 `Padding.all(0)` 这一**可变对象**（缺陷 7.10），
        会导致所有 Style 实例共享同一个 Padding。批次 4.4 已改为
        `field(default_factory=...)` 语义 —— 每次构造都新建。
    """

    def __init__(
        self,
        font_name: str = "helvetica",
        font_size: float = 12,
        bold: bool = False,
        italic: bool = False,
        color: Color = Black,
        fill_color: Color = White,
        image_path: str = "",
        padding: Optional[Padding] = None,
        fit_mode="cover"
    ):
        """
        初始化样式对象

        Args:
            font_name: 字体名称
            font_size: 字号 (mm)
            bold: 是否粗体
            italic: 是否斜体
            color: 文字颜色
            fill_color: 填充颜色
            image_path: 图片路径 (仅用于 ImageObject)
            padding: 内边距。None 表示新建 Padding.all(0)（**每次新建**，不共享）
            fit_mode: 图片适配模式 (仅用于 ImageObject)
        """
        self.font_name = font_name
        self.font_size = font_size
        self.bold = bold
        self.italic = italic
        self.color = color
        self.fill_color = fill_color
        self.image_path = image_path
        self.padding = Padding.all(0) if padding is None else padding
        self.fit_mode = fit_mode

    def get_font_style(self) -> str:
        """
        获取 FPDF 兼容的字体样式字符串

        Returns:
            str: "B" 粗体, "I" 斜体, "BI" 粗斜体, "" 常规
        """
        style = ""
        if self.bold:
            style += "B"
        if self.italic:
            style += "I"
        return style

    def __repr__(self) -> str:
        return (f"Style(font='{self.font_name}', size={self.font_size}, "
                f"bold={self.bold}, italic={self.italic})")


# ============================================================================
# 4. 图层管理器 (LayerManager)
# ============================================================================

class LayerManager:
    """图层管理器"""
    
    def __init__(self):
        self._layers: Dict[int, List[Any]] = defaultdict(list)
        self._cache_valid: bool = False
    
    def add_object(self, obj: Any, layer: int) -> None:
        if layer < 0:
            raise ValueError(f"图层索引必须 >= 0，收到: {layer}")
        self._layers[layer].append(obj)
        self._cache_valid = False
    
    def remove_object(self, obj: Any) -> bool:
        for layer, objects in self._layers.items():
            if obj in objects:
                objects.remove(obj)
                self._cache_valid = False
                return True
        return False
    
    def get_layer(self, layer: int) -> List[Any]:
        return self._layers.get(layer, []).copy()
    
    def get_layer_reference(self, layer: int) -> List[Any]:
        return self._layers.get(layer, [])
    
    def get_all_layers(self) -> Dict[int, List[Any]]:
        return {k: v.copy() for k, v in self._layers.items()}
    
    def get_sorted_layers(self) -> List[int]:
        return sorted(self._layers.keys())
    
    def get_layer_count(self) -> int:
        return len([k for k, v in self._layers.items() if v])
    
    def get_total_object_count(self) -> int:
        return sum(len(v) for v in self._layers.values())
    
    def has_layer(self, layer: int) -> bool:
        return layer in self._layers and bool(self._layers[layer])
    
    def get_layers_in_range(self, start: int, end: int) -> Dict[int, List[Any]]:
        result = {}
        for layer in range(start, end):
            if layer in self._layers and self._layers[layer]:
                result[layer] = self._layers[layer].copy()
        return result
    
    def get_objects_in_range(self, start: int, end: int) -> List[Any]:
        result = []
        for layer in range(start, end):
            if layer in self._layers:
                result.extend(self._layers[layer])
        return result
    
    def render_layers(self, pdf, is_fill: bool = False,
                      render_func: Optional[Callable] = None) -> None:
        for layer in sorted(self._layers.keys()):
            for obj in self._layers[layer]:
                if render_func is not None:
                    render_func(obj, pdf, is_fill)
                elif hasattr(obj, 'render'):
                    obj.render(pdf, is_fill)
    
    def render_layer(self, pdf, layer: int, is_fill: bool = False,
                     render_func: Optional[Callable] = None) -> None:
        if layer not in self._layers:
            return
        for obj in self._layers[layer]:
            if render_func is not None:
                render_func(obj, pdf, is_fill)
            elif hasattr(obj, 'render'):
                obj.render(pdf, is_fill)
    
    def render_layers_debug(self, pdf, is_fill: bool = False, has_border: bool = True,
                            show_name: bool = True, show_bounds: bool = True) -> None:
        for layer in sorted(self._layers.keys()):
            for obj in self._layers[layer]:
                if hasattr(obj, 'render_debug'):
                    obj.render_debug(pdf, is_fill, has_border, show_name, show_bounds)
    
    def clear(self) -> None:
        self._layers.clear()
        self._cache_valid = False
    
    def clear_layer(self, layer: int) -> None:
        if layer in self._layers:
            self._layers[layer].clear()
            self._cache_valid = False
    
    def get_layer_info(self) -> Dict[int, Dict[str, Any]]:
        info = {}
        for layer, objects in self._layers.items():
            if objects:
                info[layer] = {
                    'count': len(objects),
                    'objects': [obj.name if hasattr(obj, 'name') else str(obj)
                               for obj in objects]
                }
        return info
    
    def print_layer_info(self) -> None:
        print("\n图层信息:")
        print("-" * 50)
        info = self.get_layer_info()
        if not info:
            print("  (无对象)")
        else:
            for layer in sorted(info.keys()):
                layer_info = info[layer]
                print(f"  图层 {layer}: {layer_info['count']} 个对象")
                for obj_name in layer_info['objects']:
                    print(f"    - {obj_name}")
        print("-" * 50)
    
    def __iter__(self):
        for layer in sorted(self._layers.keys()):
            yield layer, self._layers[layer]
    
    def items(self):
        return self.__iter__()
    
    def __len__(self):
        return len(self._layers)
    
    def __contains__(self, layer: int):
        return layer in self._layers


# 全局图层管理器实例
layer_manager = LayerManager()


# ============================================================================
# 5. 对象注册表
# ============================================================================

objectRegister: dict = {}


def find_object_by_name(name: str = ""):
    """通过名称在注册表中查找对象"""
    return objectRegister.get(name)


# ============================================================================
# 6. 核心布局类 (LayoutObject)
# ============================================================================

class LayoutObject:
    """
    排版对象基类，表示一个矩形区域，可包含子对象
    
    核心功能：
        1. 父子层级管理（add_child, find_by_name）
        2. 内边距 (padding) 控制内容区域
        3. 水平/垂直对齐 (align_x, align_y)
        4. 流式布局 (align_y=FLOW)
        5. 图层管理支持 (layer)
        6. 调试渲染 (render_debug)
        7. 自动注册到全局注册表
        8. wrap_content 支持
        9. 几何缓存（新增）
    """
    
    def __init__(self,
                 name: str,
                 x: float = 0,
                 y: float = 0,
                 width: float = 0,
                 height: float = 0,
                 color: Color = White,
                 parent: Optional['LayoutObject'] = None,
                 padding: Optional[Union[Padding, float]] = None,
                 align_x: AlignX = AlignX.NONE,
                 align_y: AlignY = AlignY.NONE,
                 layer: int = 0,
                 size_x: Optional[SizeX] = None,
                 size_y: Optional[SizeY] = None):
        # 基本属性
        # 注意：形参 width/height 与即将建立的同名 property 不同名空间，故此处安全；
        # 但构造函数体内必须用 _width/_height，否则会触发 setter 的失效逻辑。
        self.name = name
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self.color = color
        self.parent = parent
        self.children: List['LayoutObject'] = []
        self._flow_clipped = False
        
        # 处理内边距
        # 构造期直接写私有字段（_padding / _align_*），不走公开 property ——
        # 否则每构造一个对象都要向上无效化整条祖先链。
        if padding is None:
            self._padding = Padding()
        elif isinstance(padding, (int, float)):
            self._padding = Padding.all(float(padding))
        else:
            self._padding = padding
        
        # 对齐方式
        self._align_x = align_x
        self._align_y = align_y
        
        # 图层支持
        self._layer = layer
        layer_manager.add_object(self, layer)
        
        # ---- 尺寸轴（四轴设计，批次 4） ----
        # 推断规则：显式 size_* 优先；未给则「声明值 > 0 -> FIXED，否则 FILL」
        # 注意：批次 4.4 起 `wrap_width` / `wrap_height` 两个布尔参数**已删除**，
        #       它们只是 SizeX.CONTENT / SizeY.CONTENT 的旧写法，并存只会让"谁是真相"含糊。
        self._size_x = self._resolve_size(
            explicit=size_x,
            declared=width,
            fill=SizeX.FILL, fixed=SizeX.FIXED,
            axis="X", name=name,
        )
        self._size_y = self._resolve_size(
            explicit=size_y,
            declared=height,
            fill=SizeY.FILL, fixed=SizeY.FIXED,
            axis="Y", name=name,
        )
        
        # ---- 两趟遍历（批次 4.2） ----
        # 趟 1 测量：约束向下传、尺寸向上收；趟 2 定位：只读对齐轴
        self._layout_valid = False        # 自身与子树的尺寸/位置是否已算好
        self._constraint_w = 0.0          # 父内容区能提供的宽
        self._constraint_h = 0.0          # 父内容区能提供的高
        self._content_overflows = False   # CONTENT 内容超出约束（被夹紧）
        self._laid_out_w = 0.0            # 趟 1 算出的尺寸
        self._laid_out_h = 0.0
        self._laid_out_x = 0.0            # 趟 2 算出的绝对位置
        self._laid_out_y = 0.0
        # FILL 退化规则：父元素在对应轴上是否为 CONTENT（由 _measure 在递归前设置）
        self._in_content_parent_x = False
        self._in_content_parent_y = False
        self._pdf = None                  # 测量期传入的 pdf，供内容尺寸估算使用
        
        # 自动注册到全局注册表
        if name:
            objectRegister[name] = self
    
    # ------------------------------------------------------------------------
    # 6.0 尺寸轴（四轴设计，批次 4）
    # ------------------------------------------------------------------------
    
    @staticmethod
    def _resolve_size(explicit, declared, fill, fixed,
                      axis: str, name: str):
        """
        解析尺寸方式：显式枚举优先，否则由声明值推断

        推断规则：
            未给 size_* 且 声明值 > 0  -> FIXED（定死的尺寸）
            未给 size_* 且 声明值 <= 0 -> FILL （撑满父内容区）

        想表达"由内容决定"必须显式给 `size_x` / `size_y`（批次 4.4 起
        不再有 `wrap_*` 布尔参数作为简写）。
        """
        if explicit is None:
            return fixed if declared > 0 else fill
        # 必须按轴分别校验：SizeX 与 SizeY 是不同枚举，
        # 但 isinstance(x, (SizeX, SizeY)) 对两者都成立，不能用来分轴。
        expected = SizeX if axis == "X" else SizeY
        if not isinstance(explicit, expected):
            raise TypeError(
                f"size_{axis.lower()} 必须是 Size{axis} 枚举，"
                f"收到 {type(explicit).__name__}"
            )
        return explicit
    
    @property
    def width(self) -> float:
        """
        声明的宽度数值

        批次 4.2 起这是**公开尺寸声明**：赋正值会把尺寸方式同步为 SizeX.FIXED，
        赋 0 则退回 SizeX.FILL，然后触发失效重算。
        这样"先构造、后声明尺寸"的旧写法（如 ResumeCore 的 content_obj._height = N）
        才能正确生效 —— 直接写 _width 会绕过尺寸方式解析。
        """
        return self._width
    
    @width.setter
    def width(self, value: float) -> None:
        self._width = value
        if self._size_x != SizeX.CONTENT:
            self._size_x = SizeX.FIXED if value > 0 else SizeX.FILL
        self.invalidate_geom_cache()
    
    @property
    def height(self) -> float:
        """声明的宽度数值（语义同 width，作用于 SizeY）"""
        return self._height
    
    @height.setter
    def height(self, value: float) -> None:
        self._height = value
        if self._size_y != SizeY.CONTENT:
            self._size_y = SizeY.FIXED if value > 0 else SizeY.FILL
        self.invalidate_geom_cache()
    
    @property
    def x(self) -> float:
        """声明的横向偏移（无父容器时即绝对 x）"""
        return self._x
    
    @x.setter
    def x(self, value: float) -> None:
        self._x = value
        self.invalidate_geom_cache()
    
    @property
    def y(self) -> float:
        """声明的纵向偏移（无父容器时即绝对 y）"""
        return self._y
    
    @y.setter
    def y(self, value: float) -> None:
        self._y = value
        self.invalidate_geom_cache()
    
    @property
    def padding(self) -> Padding:
        """
        内边距

        批次 4.3 起是 property：赋值会触发失效。内边距影响内容区，
        因此 CONTENT 元素的内容尺寸与所有子元素的位置都可能随之变化。
        """
        return self._padding
    
    @padding.setter
    def padding(self, value: Padding) -> None:
        if self._padding is not value:
            self._padding = value
            self.invalidate_geom_cache()
    
    @property
    def align_x(self) -> AlignX:
        """水平对齐方式（只决定位置，不决定尺寸）"""
        return self._align_x
    
    @align_x.setter
    def align_x(self, value: AlignX) -> None:
        if self._align_x != value:
            self._align_x = value
            self.invalidate_geom_cache()
    
    @property
    def align_y(self) -> AlignY:
        """垂直对齐方式（只决定位置，不决定尺寸）"""
        return self._align_y
    
    @align_y.setter
    def align_y(self, value: AlignY) -> None:
        if self._align_y != value:
            self._align_y = value
            self.invalidate_geom_cache()
    
    def set_size(self, width: Optional[float] = None,
                 height: Optional[float] = None) -> 'LayoutObject':
        """
        显式设置尺寸（会同步尺寸方式并触发失效）

        这是"先构造、后声明尺寸"的推荐写法。直接写 `_width` / `_height`
        会**绕过尺寸方式解析** —— 构造时若 width/height 为 0，尺寸方式被推成 FILL，
        之后直接写私有字段不会改回 FIXED，FILL 会覆盖它。

        Args:
            width: 新宽度。None 表示不改。> 0 置 SizeX.FIXED，== 0 置 SizeX.FILL
            height: 新高度。语义同 width，作用于 SizeY

        Returns:
            LayoutObject: self（支持链式调用）
        """
        if width is not None:
            self.width = width
        if height is not None:
            self.height = height
        return self
    
    def set_position(self, x: Optional[float] = None,
                     y: Optional[float] = None) -> 'LayoutObject':
        """显式设置偏移（相对父内容区左上方）。None 表示不改。返回 self。"""
        if x is not None:
            self.x = x
        if y is not None:
            self.y = y
        return self
    
    def set_align(self, align_x: Optional[AlignX] = None,
                  align_y: Optional[AlignY] = None) -> 'LayoutObject':
        """显式设置对齐方式。None 表示不改。返回 self。"""
        if align_x is not None:
            self.align_x = align_x
        if align_y is not None:
            self.align_y = align_y
        return self
    
    def set_padding(self, padding: Optional[Union[Padding, float]] = None,
                    ) -> 'LayoutObject':
        """显式设置内边距。float 会转成 Padding.all。None 表示不改。返回 self。"""
        if padding is not None:
            if isinstance(padding, (int, float)):
                self.padding = Padding.all(float(padding))
            else:
                self.padding = padding
        return self
    
    @property
    def size_x(self) -> SizeX:
        """水平尺寸计算方式"""
        return self._size_x
    
    @size_x.setter
    def size_x(self, value: SizeX) -> None:
        if self._size_x != value:
            self._size_x = value
            self.invalidate_geom_cache()
    
    @property
    def size_y(self) -> SizeY:
        """垂直尺寸计算方式"""
        return self._size_y
    
    @size_y.setter
    def size_y(self, value: SizeY) -> None:
        if self._size_y != value:
            self._size_y = value
            self.invalidate_geom_cache()
    
    # 批次 4.4 起 `wrap_width` / `wrap_height` 两个兼容属性已**删除**。
    # 它们只是 SizeX.CONTENT / SizeY.CONTENT 的旧写法，长期并存会让
    # "谁是真相"含糊 —— 而真相只有 `_size_x` / `_size_y`。
    # 迁移写法：wrap_width=True  -> size_x=SizeX.CONTENT
    #           wrap_height=True -> size_y=SizeY.CONTENT
    # 属性的读写入口请改用 `size_x` / `size_y`（都是 property，赋值会触发失效）。
    
    # ------------------------------------------------------------------------
    # 6.1 图层属性
    # ------------------------------------------------------------------------
    
    @property
    def layer(self) -> int:
        return self._layer
    
    @layer.setter
    def layer(self, value: int) -> None:
        if value < 0:
            raise ValueError(f"图层索引必须 >= 0，收到: {value}")
        if self._layer != value:
            layer_manager.remove_object(self)
            self._layer = value
            layer_manager.add_object(self, value)
    
    def move_to_layer(self, layer: int) -> None:
        self.layer = layer
    
    def remove_from_layers(self) -> None:
        layer_manager.remove_object(self)
    
    # ------------------------------------------------------------------------
    # 6.2 【新增】几何缓存管理
    # ------------------------------------------------------------------------
    
    def invalidate_geom_cache(self) -> None:
        """
        使布局缓存失效（递归向上传播到父元素）

        批次 4.2 起，尺寸与位置由 layout() 的两趟遍历统一计算，
        因此"几何缓存"只剩一个布尔标记 _layout_valid：
        失效即表示自身与子树的尺寸/位置需要整体重算。

        当以下情况发生时应调用此方法：
            1. 子元素被添加或移除
            2. 自身尺寸、对齐方式、内边距被修改
            3. 尺寸方式（size_x / size_y）被修改
        """
        self._layout_valid = False
        
        # 向上传播到父元素：子树的尺寸会传导给祖先（CONTENT 父要重算）
        if self.parent is not None:
            self.parent.invalidate_geom_cache()
    
    def invalidate_geom_cache_subtree(self) -> None:
        """
        [兼容] 使自身及所有子树的布局缓存失效（向下传播）

        批次 4.2 起，失效只需一个布尔标记，而 layout() 会重算整棵树，
        因此"向上传播"的 invalidate_geom_cache() 已足够。
        此方法保留为兼容入口，语义等同于 invalidate_geom_cache()。
        """
        self.invalidate_geom_cache()
    
    # ------------------------------------------------------------------------
    # 6.3 两趟遍历（批次 4.2）
    # ------------------------------------------------------------------------
    #
    # 【为什么是两趟】
    #   旧实现的尺寸计算是"惰性 + 互相递归"：子元素在测量阶段就去问父元素
    #   get_parent_available_area() -> parent.get_effective_height()，
    #   而父的高度正要靠子元素算出来 —— 自指，于是 wrap_height 只能塌缩成 padding（7.19）。
    #
    #   新实现把两个量分开传播：
    #       趟 1 测量：constraint 向下传、size 向上收
    #       趟 2 定位：只读对齐轴 + 已定的 size
    #   子元素的约束是**作为参数拿到**的，不再回头问父容器，
    #   因此那条造成循环的回边根本不存在。
    # ------------------------------------------------------------------------
    
    def layout(self, pdf=None, force: bool = False) -> 'LayoutObject':
        """
        从自身开始跑两趟布局（趟 1 测量尺寸，趟 2 计算位置）

        根节点没有父容器，因此它的约束就是它自己声明的尺寸。
        若自身是 CONTENT 且没有约束，会回退到声明尺寸。

        Args:
            pdf: 可选的 FPDF 实例。文本/图片的 CONTENT 尺寸需要它才能精确测量；
                 不传时退回估算（并打印提示）。纯几何的 CONTENT 不需要它。
            force: 强制重算，忽略缓存

        Returns:
            LayoutObject: self（支持链式调用）
        """
        if self._layout_valid and not force:
            return self
        
        # 根节点的约束 = 自身声明尺寸（没有父容器给它别的约束）
        cx = self._width if self._width > 0 else 0.0
        cy = self._height if self._height > 0 else 0.0
        
        self._measure(cx, cy, [], pdf)
        # 先标记有效：定位阶段（_place）会查询父元素的内容区，
        # 那些查询属于纯读取，不应再触发一次布局。
        self._layout_valid = True
        self._place()
        return self
    
    def _source_w(self, pdf):
        """
        本元素的内容固有宽度（内容 + 左右 padding）

        子类按需覆盖以表达"我的内容天然有多宽"（如文本的字符串宽度）。
        """
        if not self.children:
            return self.padding.left + self.padding.right
        return (max(c._contribution_w() for c in self.children)
                + self.padding.left + self.padding.right)
    
    def _contribution_w(self) -> float:
        """
        本元素对"父元素 CONTENT 宽度"的贡献

        | 自身 SizeX | 贡献 |
        | --- | --- |
        | `FIXED` | 声明宽度（不随父变化） |
        | `FILL`，但父宽由内容决定 | **自身内容固有宽度**（此时 FILL 已退化为按内容定尺寸） |
        | `FILL`，其余情况 | 0（宽度由父内容区决定，自身没有固有宽度） |
        | `CONTENT` | 自身的内容固有宽度 |

        注意不能直接用 `_laid_out_w`：退出方向要求子元素**先算完**，
        而 FILL 子元素的尺寸来自父的内容区 —— 那正是父在算的东西。
        """
        if self._size_x == SizeX.FIXED:
            return self._width
        if self._size_x == SizeX.FILL and not self._in_content_parent_x:
            return 0.0
        return self._source_w(self._pdf)
    
    def _source_h(self, pdf):
        """本元素的内容固有高度（内容 + 上下 padding）。子类按需覆盖。"""
        if not self.children:
            return self.padding.top + self.padding.bottom
        return (sum(c._layout_size_h() for c in self.children)
                + self.padding.top + self.padding.bottom)
    
    def _layout_size_w(self) -> float:
        """趟 1 已算出的尺寸（内部使用，不触发任何计算）"""
        return self._laid_out_w
    
    def _layout_size_h(self) -> float:
        """趟 1 已算出的尺寸（内部使用，不触发任何计算）"""
        return self._laid_out_h
    
    def _measure(self, constraint_w: float, constraint_h: float, path: list, pdf):
        """
        趟 1：测量尺寸

        进入方向（背离根）：确定 FIXED / FILL 的尺寸，把约束传给子元素
        退出方向（朝向根）：确定 CONTENT 的尺寸（内容 + padding，再对约束夹紧）
        """
        if any(o is self for o in path):
            chain = " > ".join([o.name for o in path] + [self.name])
            raise LayoutCycleError(
                f"结构循环依赖：元素成为自己的祖先\n  路径：{chain}"
            )
        
        self._constraint_w = constraint_w
        self._constraint_h = constraint_h
        self._content_overflows = False
        # 供 FILL 退化规则使用：本元素在测量期内需要 pdf 来估算内容尺寸
        self._pdf = pdf
        
        # ---- 结构性冲突检查：结论是「不需要」 ----
        #
        # 【为什么 CONTENT 父 + FILL 子不是循环】
        #   关键在于 FILL 子元素需要的是**约束**，不是「父的最终尺寸」。
        #   约束是作为参数往下传的，因此这个环在设计上就已经断开了：
        #
        #       水平轴：子宽 = min(父最终内容区宽, 传入约束) —— 收缩包裹，良定义
        #       垂直轴：子高 = 传入约束                        —— 父再收缩包裹并夹紧
        #
        #   两个轴都是确定性的。若父收缩后的尺寸小于子元素所占，那是**溢出**
        #   （`_content_overflows` 会置位），不是循环。
        #
        #   旧实现之所以在这里撞墙，是因为它回头问 `parent.get_effective_height()`，
        #   而那时父的尺寸尚未确定 —— 是**实现方式**造成的环，不是语义上的环。
        #   两趟遍历把约束改成传参之后，这个问题自然消失。
        #
        #   `LayoutError_CONTENT_FILL` 因此不再被触发；保留该类型以备将来需要
        #   对某些组合做显式限制。真正的**结构循环**（元素成为自己的祖先）
        #   仍然会报错，见本方法开头。
        
        # ---- 进入方向：定 FIXED 与 FILL ----
        # 定死值优先：代码里写死的尺寸不另行计算，也不被裁剪（装不下是溢出问题）
        if self._size_x == SizeX.FIXED:
            self._laid_out_w = self._width
        elif self._size_x == SizeX.FILL:
            if self._in_content_parent_x:
                # 【退化规则】父元素是 CONTENT（尺寸由内容决定）时，FILL 子元素
                # 拿到的"约束"没有意义 —— 那个约束正是由本子元素参与决定的。
                # 因此退化为"按内容定尺寸"，与安卓 wrap_content 父强制
                # match_parent 子退化是同一个处理。
                # 若不退化，则"CONTENT 父只有 FILL 子"会收敛到 0，完全不可用。
                self._laid_out_w = self._source_w(self._pdf)
            else:
                self._laid_out_w = max(constraint_w, 0.0)
        # SizeX == CONTENT：此轮不定，留给退出方向
        
        if self._size_y == SizeY.FIXED:
            self._laid_out_h = self._height
        elif self._size_y == SizeY.FILL:
            if self._in_content_parent_y:
                self._laid_out_h = self._source_h(self._pdf)
            else:
                self._laid_out_h = max(constraint_h, 0.0)
        
        # ---- 推算子元素的约束 ----
        if self._size_x == SizeX.CONTENT:
            # CONTENT 的 padding 是"容器内留白"，在退出方向加到尺寸上。
            # 若此处先扣 padding，就等于要求"父尺寸必须先定"，循环立刻回来。
            child_cw = max(constraint_w, 0.0)
        else:
            child_cw = max(self._laid_out_w - self.padding.left - self.padding.right, 0.0)
        
        if self._size_y == SizeY.CONTENT:
            child_ch = max(constraint_h, 0.0)
        else:
            child_ch = max(self._laid_out_h - self.padding.top - self.padding.bottom, 0.0)
        
        path = path + [self]
        for child in self.children:
            # 【退化规则的前提】子元素需要知道"父的这条轴是否由内容决定"，
            # 以便在 FILL 时退化为按内容定尺寸。标记设在子元素上，递归时读取。
            child._in_content_parent_x = (self._size_x == SizeX.CONTENT)
            child._in_content_parent_y = (self._size_y == SizeY.CONTENT)
            child._measure(child_cw, child_ch, path, pdf)
        
        # ---- 退出方向：定 CONTENT ----
        if self._size_x == SizeX.CONTENT:
            desired_w = self._source_w(pdf)
            self._laid_out_w = min(desired_w, max(constraint_w, 0.0)) \
                if constraint_w > 0 else desired_w
            self._content_overflows = desired_w > self._laid_out_w + 1e-9
        
        if self._size_y == SizeY.CONTENT:
            desired_h = self._source_h(pdf)
            self._laid_out_h = min(desired_h, max(constraint_h, 0.0)) \
                if constraint_h > 0 else desired_h
            self._content_overflows = desired_h > self._laid_out_h + 1e-9
    
    def _content_rect_local(self):
        """内容区（相对自身的局部坐标）"""
        return (self.padding.left, self.padding.top,
                max(self._laid_out_w - self.padding.left - self.padding.right, 0.0),
                max(self._laid_out_h - self.padding.top - self.padding.bottom, 0.0))
    
    def _place(self):
        """
        趟 2：计算绝对位置

        趟 1 已把全树尺寸定完，因此本趟不再需要传参 —— 可用空间直接向父容器
        取它的内容区（纯查询，不触发任何计算）。本趟只读对齐轴。
        """
        if self.parent is None:
            # 根节点：外框原点 = 声明的 (x, y)
            ax, ay = self._x, self._y
            avail_x, avail_y = ax, ay
            avail_w, avail_h = self._laid_out_w, self._laid_out_h
        else:
            # 父容器内容区（纯查询）
            avail_x, avail_y, avail_w, avail_h = self.parent.get_content_area()
            
            if self.align_x == AlignX.CENTER:
                ax = avail_x + (avail_w - self._laid_out_w) / 2
            elif self.align_x == AlignX.RIGHT:
                ax = avail_x + avail_w - self._laid_out_w
            elif self.align_x == AlignX.LEFT:
                ax = avail_x
            else:  # NONE
                ax = avail_x + self._x
            
            if self.align_y == AlignY.FLOW:
                prev_flow = self.get_previous_flow_sibling()
                ay = avail_y if prev_flow is None \
                    else prev_flow._laid_out_y + prev_flow._laid_out_h
            elif self.align_y == AlignY.VCENTER:
                ay = avail_y + (avail_h - self._laid_out_h) / 2
            elif self.align_y == AlignY.BOTTOM:
                ay = avail_y + avail_h - self._laid_out_h
            elif self.align_y == AlignY.TOP:
                ay = avail_y
            else:  # NONE
                ay = avail_y + self._y
        
        self._laid_out_x = ax
        self._laid_out_y = ay
        
        # FLOW 溢出裁剪：属于"溢出策略"，不属于尺寸计算，故放在本趟
        self._flow_clipped = False
        if self.align_y == AlignY.FLOW and self.parent is not None:
            bottom = avail_y + avail_h
            if ay + self._laid_out_h > bottom:
                self._flow_clipped = True
                self._laid_out_h = max(bottom - ay, 0.0)
        
        for child in self.children:
            child._place()
    
    def invalidate_wrap_cache(self) -> None:
        """
        [兼容] 使布局缓存失效（向上传播）

        批次 4.2 起与 invalidate_geom_cache() 等价 —— 两者都只是把
        _layout_valid 置 False，尺寸与位置会在下次 layout() 时整体重算。
        """
        self.invalidate_geom_cache()
    
    def is_wrapped(self) -> bool:
        return self._size_x == SizeX.CONTENT or self._size_y == SizeY.CONTENT
    
    def is_height_wrapped(self) -> bool:
        return self._size_y == SizeY.CONTENT
    
    def is_width_wrapped(self) -> bool:
        return self._size_x == SizeX.CONTENT
    
    def get_wrap_status(self) -> Dict[str, Any]:
        return {
            "size_x": self._size_x.value,
            "size_y": self._size_y.value,
            "layout_valid": self._layout_valid,
            "laid_out_width": self._laid_out_w,
            "laid_out_height": self._laid_out_h,
            "content_overflows": self._content_overflows,
        }
    # 6.4 父子关系管理
    # ------------------------------------------------------------------------
    
    def add_child(self, child: 'LayoutObject') -> 'LayoutObject':
        """
        添加子对象，使 wrap 缓存和几何缓存失效
        """
        child.parent = self
        self.children.append(child)
        
        # 使 wrap 缓存失效
        self.invalidate_wrap_cache()
        # 使几何缓存失效
        self.invalidate_geom_cache()
        
        return child
    
    def remove_child(self, child: 'LayoutObject') -> bool:
        """
        移除子对象，使 wrap 缓存和几何缓存失效
        """
        if child in self.children:
            self.children.remove(child)
            child.parent = None
            
            self.invalidate_wrap_cache()
            self.invalidate_geom_cache()
            
            return True
        return False
    
    def get_child(self, name: str) -> Optional['LayoutObject']:
        for child in self.children:
            if child.name == name:
                return child
        return None
    
    def find_by_name(self, name: str) -> Optional['LayoutObject']:
        if self.name == name:
            return self
        for child in self.children:
            result = child.find_by_name(name)
            if result:
                return result
        return None
    
    def get_previous_sibling(self) -> Optional['LayoutObject']:
        if self.parent is None:
            return None
        siblings = self.parent.children
        for i, sibling in enumerate(siblings):
            if sibling is self:
                return siblings[i - 1] if i > 0 else None
        return None
    
    def get_previous_flow_sibling(self) -> Optional['LayoutObject']:
        if self.parent is None:
            return None
        siblings = self.parent.children
        for i, sibling in enumerate(siblings):
            if sibling is self:
                for j in range(i - 1, -1, -1):
                    if siblings[j].align_y == AlignY.FLOW:
                        return siblings[j]
                return None
        return None
    
    def get_flow_children(self) -> List['LayoutObject']:
        return [child for child in self.children if child.align_y == AlignY.FLOW]
    
    # ------------------------------------------------------------------------
    # 6.5 几何查询（批次 4.2：全部改为读取两趟遍历的结果）
    # ------------------------------------------------------------------------
    #
    # 这些方法现在都是**纯读取**：若布局尚未算好，会触发一次 layout()，
    # 然后返回结果。它们不再"边算边问父容器"，因此不存在自指。
    # ------------------------------------------------------------------------
    
    def _ensure_layout(self):
        """若布局未算好，从根节点跑一次两趟遍历"""
        if self._layout_valid:
            return
        self._layout_root().layout()
    
    def _layout_root(self) -> 'LayoutObject':
        """向上找到根节点（没有父元素的那个）"""
        node = self
        while node.parent is not None:
            node = node.parent
        return node
    
    def get_parent_available_area(self) -> Tuple[float, float, float, float]:
        """
        [兼容] 父元素内容区的绝对矩形

        批次 4.2 起，尺寸计算不再需要它（约束是 layout() 传下去的），
        保留为纯查询接口。真正的规则是：**约束由父容器主动传给子元素**，
        而不是子元素回头来问。
        """
        if self.parent is None:
            return (0.0, 0.0, self._width, self._height)
        return self.parent.get_content_area()
    
    def get_absolute_x(self) -> float:
        """
        获取对象的绝对 X 坐标

        由趟 2（_place）算出。对齐规则见 AlignX。
        """
        self._ensure_layout()
        if self.parent is None:
            return self._x
        return self._laid_out_x
    
    def get_absolute_y(self) -> float:
        """
        获取对象的绝对 Y 坐标

        由趟 2（_place）算出。对齐规则见 AlignY。
        """
        self._ensure_layout()
        if self.parent is None:
            return self._y
        return self._laid_out_y
    
    def get_effective_width(self) -> float:
        """
        获取对象的有效宽度

        由趟 1（_measure）算出。取值规则见 SizeX：
            FIXED   -> 代码里写死的 width，不另行计算、不被裁剪
            FILL    -> 父内容区宽
            CONTENT -> 内容固有宽（子元素最大宽 + 左右 padding），再对约束夹紧
        """
        self._ensure_layout()
        return self._laid_out_w
    
    def get_effective_height(self) -> float:
        """
        获取对象的有效高度

        由趟 1（_measure）算出。取值规则见 SizeY。
        """
        self._ensure_layout()
        return self._laid_out_h
    
    def get_content_area(self) -> Tuple[float, float, float, float]:
        """获取当前对象的内容区域（绝对坐标）"""
        abs_x = self.get_absolute_x()
        abs_y = self.get_absolute_y()
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()
        
        content_x = abs_x + self.padding.left
        content_y = abs_y + self.padding.top
        content_w = eff_w - self.padding.left - self.padding.right
        content_h = eff_h - self.padding.top - self.padding.bottom
        
        return (content_x, content_y, content_w, content_h)
    
    def get_layout_info(self) -> dict:
        """获取布局信息（用于调试）"""
        return {
            "name": self.name,
            "constructed": {
                "x": self._x, "y": self._y,
                "w": self._width, "h": self._height
            },
            "effective": {
                "x": self.get_absolute_x(), "y": self.get_absolute_y(),
                "w": self.get_effective_width(), "h": self.get_effective_height()
            },
            "align": {
                "x": self.align_x.value, "y": self.align_y.value
            },
            "flow_clipped": getattr(self, '_flow_clipped', False),
            "layer": self._layer,
            "size_mode": {
                "x": self._size_x.value,
                "y": self._size_y.value,
            },
            "layout_valid": self._layout_valid,
            "constraint": {
                "w": self._constraint_w, "h": self._constraint_h
            },
            "content_overflows": self._content_overflows,
        }
    
    # ------------------------------------------------------------------------
    # 6.6 渲染方法
    # ------------------------------------------------------------------------
    
    @timer
    def render(self, pdf, is_fill: bool = False):
        """渲染当前对象及其所有子对象到 PDF"""
        print(f"  >>> 正在渲染PDF文件。现在渲染LayoutObject节点：{self.name}")
        
        last_y = self.get_absolute_y()
        
        for child in self.children:
            child_y = child.render(pdf, is_fill)
            if child_y is not None:
                last_y = child_y

        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")
        return last_y
    
    @timer
    def render_debug(self, pdf, is_fill: bool = False, has_border: bool = True,
                 show_name: bool = True, show_bounds: bool = True,
                 name_offset_y: float = 2, bounds_offset_y: float = 6):
        """
        调试渲染：绘制矩形边框、填充颜色、显示对象名称和尺寸

        Returns:
            float | None: 最后渲染到的 y 坐标（语义与 render() 一致）。
                pdf 为 None、或有效尺寸非正时返回 None。
        """
        print(f"  >>> 正在渲染PDF文件。现在渲染LayoutObject节点：{self.name}")

        if pdf is None:
            return None
    
        if len(pdf.pages) == 0:
            pdf.add_page()
    
        abs_x = self.get_absolute_x()
        abs_y = self.get_absolute_y()
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()
    
        if eff_w <= 0 or eff_h <= 0:
            return None

        last_y = abs_y
        auto_page_break = pdf.auto_page_break
        pdf.set_auto_page_break(auto=False)
    
        try:
            if is_fill and has_border:
                style = 'DF'
            elif is_fill:
                style = 'F'
            else:
                style = 'D'
        
            if is_fill:
                pdf.set_fill_color(self.color.r, self.color.g, self.color.b)
            if has_border:
                if self.color.is_light():
                    pdf.set_draw_color(100, 100, 100)
                else:
                    pdf.set_draw_color(self.color.r, self.color.g, self.color.b)
        
            pdf.rect(abs_x, abs_y, eff_w, eff_h, style)
        
            if show_name or show_bounds:
                pdf.set_text_color(0, 0, 0)
            
                if eff_h > 20:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=9)
                        pdf.set_xy(abs_x + 2, abs_y + name_offset_y)
                        display_name = self._get_display_name()
                        if len(display_name) > 25:
                            display_name = display_name[:23] + ".."
                        pdf.cell(eff_w - 4, 5, display_name, align='C')
                
                    if show_bounds:
                        pdf.set_font(family="helvetica", style="", size=6)
                        pdf.set_xy(abs_x + 2, abs_y + eff_h - bounds_offset_y)
                        info = self._get_bounds_info()
                        pdf.cell(eff_w - 4, 4, info, align='C')
            
                elif eff_h > 12:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=7)
                        pdf.set_xy(abs_x + 2, abs_y + (eff_h - 4) / 2)
                        display_name = self._get_display_name()
                        if len(display_name) > 20:
                            display_name = display_name[:18] + ".."
                        pdf.cell(eff_w - 4, 4, display_name, align='C')
                
                elif eff_h > 6:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=5)
                        pdf.set_xy(abs_x + 2, abs_y + (eff_h - 3) / 2)
                        display_name = self._get_display_name()
                        if len(display_name) > 12:
                            display_name = display_name[:10] + ".."
                        pdf.cell(eff_w - 4, 3, display_name, align='C')
        
            for child in self.children:
                child_y = child.render_debug(pdf, is_fill, has_border, show_name, show_bounds,
                                 name_offset_y, bounds_offset_y)
                if child_y is not None:
                    last_y = child_y
    
        finally:
            pdf.set_auto_page_break(auto=auto_page_break)
        
        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")
        return last_y

    def _get_display_name(self) -> str:
        name = self.name
        if self._size_y == SizeY.CONTENT:
            name += " [H↕]"
        if self._size_x == SizeX.CONTENT:
            name += " [W↔]"
        return name

    def _get_bounds_info(self) -> str:
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()
        info = f"{eff_w:.1f}x{eff_h:.1f}"
        if getattr(self, '_flow_clipped', False):
           info += "[CLIPPED]" 
        return info
    
    def __repr__(self) -> str:
        size_marker = ""
        if self._size_y == SizeY.CONTENT:
            size_marker += ", content_h"
        if self._size_x == SizeX.CONTENT:
            size_marker += ", content_w"
        return (f"LayoutObject(name='{self.name}', layer={self._layer}, "
                f"size=({self._width}x{self._height}){size_marker})")

    def get_true_height(self):
        None


# ============================================================================
# 7. 内容渲染对象
# ============================================================================

class TextObject(LayoutObject):
    """文本渲染对象"""
    
    def __init__(
        self,
        name: str,
        x: float = 0,
        y: float = 0,
        width: float = 0,
        height: float = 0,
        text: str = "",
        font_name: str = "helvetica",
        font_size: float = 12,
        font_style: str = "",
        text_color: Color = Black,
        color: Color = White,
        parent: Optional[LayoutObject] = None,
        padding: Optional[Union[Padding, float]] = None,
        align_x: AlignX = AlignX.NONE,
        align_y: AlignY = AlignY.NONE,
        multi_line: bool = False,
        line_height: Optional[float] = None,
        layer: int = 0,
        size_x: Optional[SizeX] = None,
        size_y: Optional[SizeY] = None,
    ):
        super().__init__(
            name=name, x=x, y=y, width=width, height=height,
            color=color, parent=parent, padding=padding,
            align_x=align_x, align_y=align_y, layer=layer,
            size_x=size_x, size_y=size_y,
        )
        
        self._text = text
        self.font_name = font_name
        self.font_size = font_size
        self.font_style = font_style
        self.text_color = text_color
        self.multi_line = multi_line
        self._line_height = line_height
        
        self._cached_width = 0.0
        self._cached_height = 0.0
        self._cache_valid = False
    
    @classmethod
    def from_style(
        cls,
        name: str,
        style: Optional[Style] = None,
        text: str = "",
        **overrides,
    ) -> 'TextObject':
        """
        按样式对象构造文本对象

        把"样式 → 渲染参数"的翻译集中在此处，避免调用点反复手抄
        font_name / font_size / font_style / text_color / padding 等参数。

        字段映射：
            Style.font_name   -> font_name
            Style.font_size   -> font_size
            Style.bold+italic -> font_style（经 get_font_style()，得 "B"/"I"/"BI"/""）
            Style.color       -> **text_color**（文字颜色）
            Style.fill_color  -> color（背景填充色）
            Style.padding     -> padding
            Style.image_path  -> 忽略（仅 ImageObject 使用）
            Style.fit_mode    -> 忽略（仅 ImageObject 使用）

        其余参数（align_x / align_y / multi_line / line_height / width / height /
        parent / layer / size_x / size_y 等）通过 overrides 传入。

        Args:
            name: 对象名称
            style: 样式对象。None 表示使用 Style() 的全默认值
            text: 文本内容
            **overrides: 覆盖或补充其它构造参数，**优先级高于 style**

        Returns:
            TextObject: 新建的文本对象（未挂载到任何父元素）

        Example:
            >>> t = TextObject.from_style("Title", STYLES["name_text"],
            ...                           text="张三", align_x=AlignX.CENTER)
        """
        st = style if style is not None else Style()

        params = {
            "text": text,
            "font_name": st.font_name,
            "font_size": st.font_size,
            "font_style": st.get_font_style(),
            "text_color": st.color,
            "color": st.fill_color,
            "padding": st.padding,
        }
        params.update(overrides)
        return cls(name=name, **params)
    
    def set_text(self, text: str) -> 'TextObject':
        """
        设置文本内容（修改后使几何缓存和 wrap 缓存失效）
        """
        self._text = text
        self._cache_valid = False
        self.invalidate_wrap_cache()
        # 【新增】几何缓存失效
        self.invalidate_geom_cache()
        return self
    
    def get_text(self) -> str:
        return self._text
    
    def append_text(self, text: str) -> 'TextObject':
        self._text += text
        self._cache_valid = False
        self.invalidate_wrap_cache()
        # 【新增】几何缓存失效
        self.invalidate_geom_cache()
        return self
    
    def calculate_text_size(self, pdf) -> Tuple[float, float]:
        if not self._text:
            return (0.0, 0.0)
        
        old_font_family = pdf.font_family
        old_font_style = pdf.font_style
        old_font_size = pdf.font_size_pt
        
        try:
            pdf.set_font(self.font_name, self.font_style, self.font_size)
            text_width = pdf.get_string_width(self._text)
            line_height = self._line_height or (self.font_size * 0.6)
            effective_width = self.get_effective_width()
            if effective_width > 0 and text_width > effective_width:
                approx_lines = max(1, int(text_width / effective_width) + 1)
                text_height = approx_lines * line_height
            else:
                text_height = line_height
            
            self._cached_width = text_width
            self._cached_height = text_height
            self._cache_valid = True
            
            return (text_width, text_height)
        finally:
            try:
                pdf.set_font(old_font_family, old_font_style, old_font_size)
            except:
                pass
    
    def get_cached_text_size(self) -> Tuple[float, float]:
        if not self._cache_valid:
            return (0.0, 0.0)
        return (self._cached_width, self._cached_height)
    
    def _source_w(self, pdf=None) -> float:
        """
        文本的内容固有宽度（字符串宽度 + 左右 padding）

        批次 4b 新增，用于让 SizeX.CONTENT 的父元素能收窄到文本宽度
        （这是缺陷 7.21 的修复点）。

        宽度目前按字符类别估算（真实测量属批次 5）：
            CJK / 全角标点 -> 1.0 × 字号
            其余字符        -> 0.5 × 字号
        批次 5 会改为用外部 pdf 的 get_string_width 做精确测量；
        那时把 `_estimate_text_width` 换成真实调用即可，接口不变。
        """
        if self.children:
            return super()._source_w(pdf)
        pad = self.padding.left + self.padding.right
        if not self._text:
            return pad
        return self._estimate_text_width(self._text) + pad
    
    def _estimate_text_width(self, text: str) -> float:
        """
        按字符类别估算文本宽度（无外部 pdf 时的回退）

        pdf 实例只在渲染时才有，而尺寸测量发生在渲染之前，
        因此这里必须有一个不依赖 pdf 的估算。
        """
        wide = 0
        for ch in text:
            # CJK 统一表意文字、全角标点、假名等按全宽计
            o = ord(ch)
            if (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF
                    or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF
                    or 0xFE30 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60
                    or 0xFFE0 <= o <= 0xFFE6):
                wide += 1
        narrow = len(text) - wide
        return (wide * 1.0 + narrow * 0.5) * self.font_size
    
    def _source_h(self, pdf=None) -> float:
        """
        文本的内容固有高度（不含对父约束的夹紧）

        批次 4.2 起由 _measure 的退出方向调用，取代表格外的旧 wrap 高度计算。
        注意：这里**不**做任何对父可用空间的裁剪 —— 裁剪发生在测量退出方向（夹紧）
        与定位阶段（FLOW 溢出裁剪）。旧实现在这里就地裁剪，正是 7.19 的成因之一。

        行数目前仍是估算（真实测量属批次 5）。pdf 参数在此保留，
        批次 5 会用 pdf.multi_cell(dry_run=True) 做精确测量。
        """
        if self.children:
            # 有子元素时按容器处理
            return super()._source_h(pdf)
        
        line_height = self._line_height or (self.font_size * 0.6)
        text_height = self.font_size * 0.6
        if self.multi_line and self._text:
            approx_lines = max(1, len(self._text) // 20 + 1)
            text_height = approx_lines * line_height
        return text_height + self.padding.top + self.padding.bottom
    
    
    @timer
    def render(self, pdf, is_fill: bool = False) -> float:
        """渲染文本"""
        print(f"  >>> 正在渲染PDF文件。现在渲染TextObject节点：{self.name}:{self._text}")
        
        abs_x = self.get_absolute_x()
        abs_y = self.get_absolute_y()
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()
        
        if eff_w <= 0 or eff_h <= 0 or not self._text:
            return abs_y
        
        if is_fill:
            pdf.set_fill_color(self.color.r, self.color.g, self.color.b)
            pdf.rect(abs_x, abs_y, eff_w, eff_h, 'F')
        
        pdf.set_text_color(self.text_color.r, self.text_color.g, self.text_color.b)
        pdf.set_font(self.font_name, self.font_style, self.font_size)
        
        line_height = self._line_height or (self.font_size * 0.6)
        
        if self.multi_line:
            pdf.set_xy(abs_x, abs_y)
            align_map = {AlignX.LEFT: 'L', AlignX.CENTER: 'C', AlignX.RIGHT: 'R', AlignX.NONE: 'L'}
            pdf.multi_cell(
                w=eff_w, h=line_height, txt=self._text,
                border=0, align=align_map.get(self.align_x, 'L'), fill=False
            )
            return pdf.get_y()
        
        text_width = pdf.get_string_width(self._text)
        
        if self.align_x == AlignX.CENTER:
            x_offset = (eff_w - text_width) / 2
        elif self.align_x == AlignX.RIGHT:
            x_offset = eff_w - text_width
        else:
            x_offset = 0
        
        y_offset = (eff_h - line_height) / 2 if eff_h > line_height else 0
        
        pdf.set_xy(abs_x + x_offset, abs_y + y_offset)
        pdf.cell(text_width, line_height, self._text)

        for child in self.children:
            child_y = child.render(pdf, is_fill)
            if child_y is not None:
                last_y = child_y

        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")
        return abs_y + line_height

    @timer
    def render_debug(self, pdf, is_fill: bool = False, has_border: bool = True,
                 show_name: bool = True, show_bounds: bool = True,
                 name_offset_y: float = 2, bounds_offset_y: float = 6):
        """调试渲染，名称后追加 ':text'

        Returns:
            float | None: 最后渲染到的 y 坐标（语义与 TextObject.render() 一致）。
                pdf 为 None 时返回 None。
        """
        print(f"  >>> 正在渲染PDF文件。现在渲染TextObject节点：{self.name}")

        if pdf is None:
            return None
    
        super().render_debug(pdf, is_fill, has_border, False, show_bounds,
                            name_offset_y, bounds_offset_y)
    
        if show_name:
            abs_x = self.get_absolute_x()
            abs_y = self.get_absolute_y()
            eff_w = self.get_effective_width()
            eff_h = self.get_effective_height()
        
            if eff_w > 0 and eff_h > 6:
                pdf.set_text_color(0, 0, 0)
            
                if eff_h > 20:
                    font_size = 9
                    y_offset = name_offset_y
                elif eff_h > 12:
                    font_size = 7
                    y_offset = (eff_h - 4) / 2
                else:
                    font_size = 5
                    y_offset = (eff_h - 3) / 2
            
                pdf.set_font(family="helvetica", style="B", size=font_size)
                pdf.set_xy(abs_x + 2, abs_y + y_offset)
            
                if eff_h > 20:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=9)
                        pdf.set_xy(abs_x + 2, abs_y + name_offset_y)
                        display_name = self._get_display_name()
                        if len(display_name) > 25:
                            display_name = display_name[:23] + "..:text"
                        pdf.cell(eff_w - 4, 5, display_name, align='C')
                
                    if show_bounds:
                        pdf.set_font(family="helvetica", style="", size=6)
                        pdf.set_xy(abs_x + 2, abs_y + eff_h - bounds_offset_y)
                        info = self._get_bounds_info()
                        pdf.cell(eff_w - 4, 4, info, align='C')
            
                elif eff_h > 12:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=7)
                        pdf.set_xy(abs_x + 2, abs_y + (eff_h - 4) / 2)
                        display_name = self._get_display_name()
                        if len(display_name) > 20:
                            display_name = display_name[:18] + "..:text"
                        pdf.cell(eff_w - 4, 4, display_name, align='C')
                
                elif eff_h > 6:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=5)
                        pdf.set_xy(abs_x + 2, abs_y + (eff_h - 3) / 2)
                        display_name = self._get_display_name()
                        if len(display_name) > 12:
                            display_name = display_name[:10] + "..:text"
                        pdf.cell(eff_w - 4, 3, display_name, align='C')

        last_y = self.get_absolute_y()
        for child in self.children:
            child_y = child.render_debug(pdf, is_fill, has_border, show_name, show_bounds,
                                 name_offset_y, bounds_offset_y)
            if child_y is not None:
                last_y = child_y
        
        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")
        return last_y


class ImageObject(LayoutObject):
    """图像渲染对象"""
    
    def __init__(
        self,
        name: str,
        x: float = 0,
        y: float = 0,
        width: float = 0,
        height: float = 0,
        image_path: str = "",
        keep_aspect_ratio: bool = True,
        fit_mode: str = "contain",
        color: Color = White,
        parent: Optional[LayoutObject] = None,
        padding: Optional[Union[Padding, float]] = None,
        align_x: AlignX = AlignX.NONE,
        align_y: AlignY = AlignY.NONE,
        layer: int = 0,
        size_x: Optional[SizeX] = None,
        size_y: Optional[SizeY] = None,
    ):
        super().__init__(
            name=name, x=x, y=y, width=width, height=height,
            color=color, parent=parent, padding=padding,
            align_x=align_x, align_y=align_y, layer=layer,
            size_x=size_x, size_y=size_y,
        )
        
        self._image_path = image_path
        self.keep_aspect_ratio = keep_aspect_ratio
        self.fit_mode = fit_mode
        
        self._cached_image_width = 0.0
        self._cached_image_height = 0.0
        self._cached_render_width = 0.0
        self._cached_render_height = 0.0
        self._cache_valid = False
    
    @classmethod
    def from_style(
        cls,
        name: str,
        style: Optional[Style] = None,
        image_path: str = "",
        **overrides,
    ) -> 'ImageObject':
        """
        按样式对象构造图像对象

        字段映射：
            Style.image_path -> image_path（若 image_path 实参非空，以实参优先）
            Style.fill_color -> color（背景填充色）
            Style.fit_mode   -> **fit_mode**（注意字段名不同：Style 叫 fit_mode，
                                 ImageObject 的构造参数也叫 fit_mode，此处显式映射）
            Style.padding    -> padding
            Style.font_name / font_size / bold / italic / color -> 忽略（纯文本属性）

        其余参数（keep_aspect_ratio / align_x / align_y / width / height /
        parent / layer / wrap_* 等）通过 overrides 传入。

        Args:
            name: 对象名称
            style: 样式对象。None 表示使用 Style() 的全默认值
            image_path: 图片路径。非空时覆盖 style.image_path
            **overrides: 覆盖或补充其它构造参数，**优先级高于 style**

        Returns:
            ImageObject: 新建的图像对象（未挂载到任何父元素）

        Example:
            >>> img = ImageObject.from_style("Photo", STYLES["profile_photo"],
            ...                              image_path=".\\\\Resources\\\\photo_1.png",
            ...                              align_x=AlignX.CENTER)
        """
        st = style if style is not None else Style()

        params = {
            "image_path": image_path if image_path else st.image_path,
            "fit_mode": st.fit_mode,
            "color": st.fill_color,
            "padding": st.padding,
        }
        params.update(overrides)
        return cls(name=name, **params)
    
    def set_image(self, image_path: str) -> 'ImageObject':
        """
        设置图像路径（修改后使几何缓存和 wrap 缓存失效）
        """
        self._image_path = image_path
        self._cache_valid = False
        self.invalidate_wrap_cache()
        # 【新增】几何缓存失效
        self.invalidate_geom_cache()
        return self
    
    def get_image(self) -> str:
        return self._image_path
    
    def calculate_image_size(self, pdf) -> Tuple[float, float]:
        if not self._image_path or not os.path.exists(self._image_path):
            return (0.0, 0.0)
        
        try:
            info = pdf.image_info(self._image_path)
            img_width = info['w']
            img_height = info['h']
            
            self._cached_image_width = img_width
            self._cached_image_height = img_height
            
            eff_w = self.get_effective_width()
            eff_h = self.get_effective_height()
            
            if self.keep_aspect_ratio and img_width > 0 and img_height > 0:
                aspect_ratio = img_width / img_height
                
                if self.fit_mode == "stretch":
                    render_w, render_h = eff_w, eff_h
                elif self.fit_mode == "cover":
                    if eff_w / eff_h > aspect_ratio:
                        render_w = eff_w
                        render_h = eff_w / aspect_ratio
                    else:
                        render_w = eff_h * aspect_ratio
                        render_h = eff_h
                else:
                    if eff_w / eff_h < aspect_ratio:
                        render_w = eff_w
                        render_h = eff_w / aspect_ratio
                    else:
                        render_w = eff_h * aspect_ratio
                        render_h = eff_h
            else:
                render_w, render_h = eff_w, eff_h
            
            self._cached_render_width = render_w
            self._cached_render_height = render_h
            self._cache_valid = True
            
            return (render_w, render_h)
        except Exception as e:
            return (0.0, 0.0)
    
    def get_cached_image_size(self) -> Tuple[float, float, float, float]:
        if not self._cache_valid:
            return (0.0, 0.0, 0.0, 0.0)
        return (self._cached_image_width, self._cached_image_height,
                self._cached_render_width, self._cached_render_height)
    
    def _source_h(self, pdf=None) -> float:
        """
        图片的内容固有高度（不含对父约束的夹紧）

        无子元素时按图片宽高比推算；有子元素时按容器处理。
        注意：这里**不**再内部构造临时 FPDF 实例（那是缺陷 7.6）。
        批次 4.2 起优先使用外部传入的 pdf；未传时用 Pillow 直接读图片头部，
        两者都不可用时退回"高度 = 宽度"的保守估算。
        """
        if self.children:
            return super()._source_h(pdf)
        
        pad = self.padding.top + self.padding.bottom
        if not self._image_path or not os.path.exists(self._image_path):
            return pad
        
        ratio = self._image_aspect_ratio(pdf)
        if ratio is None:
            # 无法取得宽高比：保守退回"高 = 宽"
            return (self._width if self._width > 0 else 0.0) + pad
        
        if self._width > 0 and ratio > 0:
            return self._width / ratio + pad
        return pad
    
    def _image_aspect_ratio(self, pdf=None):
        """
        取图片宽高比 (w/h)。优先用外部 pdf，其次用 Pillow，都不可用则返回 None。
        """
        if pdf is not None and self._image_path and os.path.exists(self._image_path):
            try:
                info = pdf.image_info(self._image_path)
                if info.get('h'):
                    return info['w'] / info['h']
            except Exception:
                pass
        try:
            from PIL import Image
            with Image.open(self._image_path) as im:
                w, h = im.size
                if h:
                    return w / h
        except Exception:
            pass
        return None
    
    
    @timer
    def render(self, pdf, is_fill: bool = False) -> Tuple[float, float]:
        """将图像渲染到 PDF"""
        print(f"  >>> 正在渲染PDF文件。现在渲染ImageObject节点：{self.name}:{self._image_path}")

        if not self._image_path or not os.path.exists(self._image_path):
            return (0.0, 0.0)
        
        abs_x = self.get_absolute_x()
        abs_y = self.get_absolute_y()
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()
        
        if eff_w <= 0 or eff_h <= 0:
            return (0.0, 0.0)
        
        if is_fill:
            pdf.set_fill_color(self.color.r, self.color.g, self.color.b)
            pdf.rect(abs_x, abs_y, eff_w, eff_h, 'F')
        
        if not self._cache_valid:
            self.calculate_image_size(pdf)
        
        if self._cache_valid:
            render_w = self._cached_render_width
            render_h = self._cached_render_height
        else:
            render_w, render_h = eff_w, eff_h
        
        x_offset = (eff_w - render_w) / 2
        y_offset = (eff_h - render_h) / 2
        
        try:
            pdf.image(self._image_path, x=abs_x + x_offset, y=abs_y + y_offset,
                     w=render_w, h=render_h)
        except Exception as e:
            pass

        for child in self.children:
            child_y = child.render(pdf, is_fill)
            if child_y is not None:
                last_y = child_y

        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")
        return (render_w, render_h)
    
    @timer
    def render_debug(self, pdf, is_fill: bool = False, has_border: bool = True,
                 show_name: bool = True, show_bounds: bool = True,
                 name_offset_y: float = 2, bounds_offset_y: float = 6):
        """调试渲染，名称后追加 ':image'

        Returns:
            Tuple[float, float] | None: 与 ImageObject.render() 一致，返回
                (渲染宽, 渲染高)。pdf 为 None 时返回 None。
        """
        print(f"  >>> 正在渲染PDF文件。现在渲染ImageObject节点：{self.name}")
        
        if pdf is None:
            return None
    
        super().render_debug(pdf, is_fill, has_border, False, show_bounds,
                        name_offset_y, bounds_offset_y)
    
        # 尺寸在此处取好：返回值需要它，且不能只在 if show_name 分支内赋值
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()

        if show_name:
            abs_x = self.get_absolute_x()
            abs_y = self.get_absolute_y()
        
            if eff_w > 0 and eff_h > 6:
                pdf.set_text_color(0, 0, 0)
            
                if eff_h > 20:
                    font_size = 9
                    y_offset = name_offset_y
                elif eff_h > 12:
                    font_size = 7
                    y_offset = (eff_h - 4) / 2
                else:
                    font_size = 5
                    y_offset = (eff_h - 3) / 2
            
                pdf.set_font(family="helvetica", style="B", size=font_size)
                pdf.set_xy(abs_x + 2, abs_y + y_offset)
            
                if eff_h > 20:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=9)
                        pdf.set_xy(abs_x + 2, abs_y + name_offset_y)
                        display_name = self._get_display_name()
                        if len(display_name) > 25:
                            display_name = display_name[:23] + "..:image"
                        pdf.cell(eff_w - 4, 5, display_name, align='C')
                
                    if show_bounds:
                        pdf.set_font(family="helvetica", style="", size=6)
                        pdf.set_xy(abs_x + 2, abs_y + eff_h - bounds_offset_y)
                        info = self._get_bounds_info()
                        pdf.cell(eff_w - 4, 4, info, align='C')
            
                elif eff_h > 12:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=7)
                        pdf.set_xy(abs_x + 2, abs_y + (eff_h - 4) / 2)
                        display_name = self._get_display_name()
                        if len(display_name) > 20:
                            display_name = display_name[:18] + "..:image"
                        pdf.cell(eff_w - 4, 4, display_name, align='C')
                
                elif eff_h > 6:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=5)
                        pdf.set_xy(abs_x + 2, abs_y + (eff_h - 3) / 2)
                        display_name = self._get_display_name()
                        if len(display_name) > 12:
                            display_name = display_name[:10] + "..:image"
                        pdf.cell(eff_w - 4, 3, display_name, align='C')
        
        for child in self.children:
            child.render_debug(pdf, is_fill, has_border, show_name, show_bounds,
                                 name_offset_y, bounds_offset_y)
                
        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")
        # 与 ImageObject.render() 一致：返回渲染尺寸，不受子元素影响
        return (eff_w, eff_h)


class RectangleObject(LayoutObject):
    """矩形渲染对象"""
    
    def __init__(
        self,
        name: str,
        x: float = 0,
        y: float = 0,
        width: float = 0,
        height: float = 0,
        color: Color = Gray,
        parent: Optional[LayoutObject] = None,
        padding: Optional[Union[Padding, float]] = None,
        align_x: AlignX = AlignX.NONE,
        align_y: AlignY = AlignY.NONE,
        layer: int = 0,
        size_x: Optional[SizeX] = None,
        size_y: Optional[SizeY] = None,
    ):
        super().__init__(
            name=name, x=x, y=y, width=width, height=height,
            color=color, parent=parent, padding=padding,
            align_x=align_x, align_y=align_y, layer=layer,
            size_x=size_x, size_y=size_y,
        )
    
    
    @timer
    def render(self, pdf, is_fill: bool = False) -> Tuple[float, float]:
        """将矩形渲染到 PDF"""
        print(f"  >>> 正在渲染PDF文件。现在渲染RectangleObject节点：{self.name}:{self.color.to_RGBA()}")
        
        abs_x = self.get_absolute_x()
        abs_y = self.get_absolute_y()
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()
        
        if eff_w <= 0 or eff_h <= 0:
            return (0.0, 0.0)

        '''
        if is_fill:
            pdf.set_fill_color(self.color.r, self.color.g, self.color.b)
            pdf.rect(abs_x, abs_y, eff_w, eff_h, 'F')\
        '''

        pdf.set_fill_color(self.color.r, self.color.g, self.color.b)
        pdf.rect(abs_x, abs_y, eff_w, eff_h, 'F')

        for child in self.children:
            child_y = child.render(pdf, is_fill)
            if child_y is not None:
                last_y = child_y

        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")
        return (eff_w, eff_h)
    
    @timer
    def render_debug(self, pdf, is_fill: bool = False, has_border: bool = True,
                 show_name: bool = True, show_bounds: bool = True,
                 name_offset_y: float = 2, bounds_offset_y: float = 6):
        """调试渲染，名称后追加 ':rect'

        Returns:
            Tuple[float, float] | None: 与 RectangleObject.render() 一致，返回
                (有效宽, 有效高)。pdf 为 None 时返回 None。
        """
        print(f"  >>> 正在渲染PDF文件。现在渲染RectangleObject节点：{self.name}")

        if pdf is None:
            return None
    
        super().render_debug(pdf, is_fill, has_border, False, show_bounds,
                        name_offset_y, bounds_offset_y)
    
        # 尺寸在此处取好：返回值需要它，且不能只在 if show_name 分支内赋值
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()

        if show_name:
            abs_x = self.get_absolute_x()
            abs_y = self.get_absolute_y()
        
            if eff_w > 0 and eff_h > 6:
                pdf.set_text_color(0, 0, 0)
            
                if eff_h > 20:
                    font_size = 9
                    y_offset = name_offset_y
                elif eff_h > 12:
                    font_size = 7
                    y_offset = (eff_h - 4) / 2
                else:
                    font_size = 5
                    y_offset = (eff_h - 3) / 2
            
                pdf.set_font(family="helvetica", style="B", size=font_size)
                pdf.set_xy(abs_x + 2, abs_y + y_offset)
            
                if eff_h > 20:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=9)
                        pdf.set_xy(abs_x + 2, abs_y + name_offset_y)
                        display_name = self._get_display_name()
                        if len(display_name) > 25:
                            display_name = display_name[:23] + "..:rect"
                        pdf.cell(eff_w - 4, 5, display_name, align='C')
                
                    if show_bounds:
                        pdf.set_font(family="helvetica", style="", size=6)
                        pdf.set_xy(abs_x + 2, abs_y + eff_h - bounds_offset_y)
                        info = self._get_bounds_info()
                        pdf.cell(eff_w - 4, 4, info, align='C')
            
                elif eff_h > 12:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=7)
                        pdf.set_xy(abs_x + 2, abs_y + (eff_h - 4) / 2)
                        display_name = self._get_display_name()
                        if len(display_name) > 20:
                            display_name = display_name[:18] + "..:rect"
                        pdf.cell(eff_w - 4, 4, display_name, align='C')
                
                elif eff_h > 6:
                    if show_name:
                        pdf.set_font(family="helvetica", style="B", size=5)
                        pdf.set_xy(abs_x + 2, abs_y + (eff_h - 3) / 2)
                        display_name = self._get_display_name()
                        if len(display_name) > 12:
                            display_name = display_name[:10] + "..:rect"
                        pdf.cell(eff_w - 4, 3, display_name, align='C')

        for child in self.children:
            child.render_debug(pdf, is_fill, has_border, show_name, show_bounds,
                                 name_offset_y, bounds_offset_y)
                
        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")
        # 与 RectangleObject.render() 一致：返回自身的有效尺寸
        return (eff_w, eff_h)


# ============================================================================
# 10. 分栏 / 横向带
# ============================================================================

def create_band(
    parent: LayoutObject,
    cells: List[Union[float, LayoutObject]],
    gap: float = 0,
    padding: Optional[Union[Padding, float]] = None,
    height: float = 0,
    names: Optional[List[str]] = None,
    colors: Optional[List[Color]] = None,
    layer: int = 0,
    container_name: Optional[str] = None,
) -> LayoutObject:
    """
    横向带构件 —— 把若干个"格子"并排放在一个流式行里

    这是本引擎横向布局的基础构件。`create_columns` 与 `split_column_advanced`
    都是它的包装。

    cells 的两种元素形式：
        - float  -> 视为比例权重，在带内新建一个空 LayoutObject 作为格子
        - LayoutObject -> 直接复用该对象作为格子

    宽度分配（严格按比例，不做任何"剩余空间均分"）：
        可用宽 = 父内容区宽 - gap * (n - 1)
        比例权重 cell -> 可用宽 * (w / sum(权重))
        已构造对象   -> 保留其自身 _width，由 gap 与前面的格子决定 x

    坐标系：
        带容器放在父内容区原点，尺寸 = (父内容区宽, height)。
        格子 x 依次累加，相邻格子之间留 gap；格子 height 统一为 height。

    Args:
        parent: 父容器。带容器会通过 add_child 挂载到它下面
        cells: 格子列表，元素为比例权重 (float) 或已构造对象 (LayoutObject)
        gap: 相邻格子之间的横向间距 (mm)
        padding: 带容器自身的内边距，默认 Padding()
        height: 格子与带容器的高度 (mm)。0 表示取父内容区高
        names: 新建格子的名字，长度须等于 cells 长度
        colors: 新建格子的颜色，长度须等于 cells 长度，默认 Gray
        layer: 图层索引
        container_name: 带容器的名字，默认 "{parent.name}_band"

    Returns:
        LayoutObject: **新建的带容器**（注意：不是传入的 parent）

    Raises:
        ValueError: cells 为空；高度或可用宽度非正；names/colors 长度不匹配

    Example:
        >>> # 左栏固定 6mm 图标，右栏占满剩余
        >>> create_band(cell, [BandCell...])          # 见 split_column_advanced
        >>> # 三栏按 2:1:2 比例
        >>> create_band(row, [2.0, 1.0, 2.0], gap=0, height=10)
    """
    if not cells:
        raise ValueError("create_band: cells 不能为空")

    n = len(cells)

    if names is not None and len(names) != n:
        raise ValueError(f"create_band: names 长度必须等于 cells 长度 ({n})")
    if colors is not None and len(colors) != n:
        raise ValueError(f"create_band: colors 长度必须等于 cells 长度 ({n})")

    cell_names = names if names is not None else [f"{parent.name}_band_{i}" for i in range(n)]
    cell_colors = colors if colors is not None else [Gray] * n

    if padding is None:
        band_padding = Padding()
    elif isinstance(padding, (int, float)):
        band_padding = Padding.all(float(padding))
    else:
        band_padding = padding

    _, _, content_w, content_h = parent.get_content_area()

    if content_w <= 0:
        raise ValueError(f"create_band: 父容器 '{parent.name}' 没有可用宽度")

    band_height = height if height > 0 else content_h
    if band_height <= 0:
        raise ValueError(
            f"create_band: 高度必须为正。height 传入了 {height}，"
            f"而父容器 '{parent.name}' 的内容区高为 {content_h}"
        )

    total_gap = gap * (n - 1)
    usable_width = content_w - total_gap
    if usable_width <= 0:
        raise ValueError(
            f"create_band: {n} 个格子之间的间距合计 {total_gap} "
            f"已占满父容器 '{parent.name}' 的可用宽 {content_w}"
        )

    # ---- 按顺序横向排放格子 ----
    band = LayoutObject(
        name=container_name if container_name is not None else f"{parent.name}_band",
        x=0,
        y=0,
        width=content_w,
        height=band_height,
        color=White,
        parent=parent,
        padding=band_padding,
        align_x=AlignX.NONE,
        align_y=AlignY.NONE,
        layer=layer,
    )
    parent.add_child(band)

    # 比例权重总和（仅对 float 形式的格子有意义）
    weight_sum = sum(c for c in cells if isinstance(c, (int, float)))

    cursor = 0.0
    for i, cell in enumerate(cells):
        if isinstance(cell, (int, float)):
            if weight_sum <= 0:
                raise ValueError("create_band: 比例权重之和必须大于 0")
            obj = LayoutObject(
                name=cell_names[i],
                x=0,
                y=0,
                width=usable_width * (float(cell) / weight_sum),
                height=band_height,
                color=cell_colors[i],
                parent=None,
                padding=Padding(),
                align_x=AlignX.NONE,
                align_y=AlignY.NONE,
                layer=layer,
            )
        else:
            # 已构造对象：保留其自身宽度，只接管位置、高度与尺寸方式
            obj = cell
            obj._height = band_height
            # 关键：格子宽度是**被创建者显式定死的**，必须声明为 FIXED。
            # 否则若构造时 width=0（先建后设宽，如 split_column_advanced），
            # 尺寸方式会被推成 FILL，把这里定死的宽度覆盖掉。
            if obj._width > 0:
                obj._size_x = SizeX.FIXED
            if band_height > 0:
                obj._size_y = SizeY.FIXED

        # 构造期赋值直接写私有字段，末尾统一失效一次，避免逐项触发向上传播
        obj._align_x = AlignX.NONE
        obj._align_y = AlignY.NONE
        obj._x = cursor
        obj._y = 0
        obj.invalidate_geom_cache()

        band.add_child(obj)
        cursor += obj._width + gap

    return band


def split_column_advanced(
    parent: LayoutObject,
    left_obj: LayoutObject,
    right_obj: LayoutObject,
    ratio: list = None,
    gap: float = 0,
    padding: Padding = None,
    layer: int = 0,
) -> LayoutObject:
    """
    进阶分栏函数 - 支持传入已构造好的左右对象

    与 create_columns 的区别：
        - 传入的是已构造好的对象，而不是类
        - 支持左右对象不同类型 (LayoutObject / RectangleObject / 任意子类)
        - 左右对象直接挂载到分栏容器下，无需额外包装

    本函数是 create_band 的包装：左栏宽度 = 可用宽 * ratio[0]/sum(ratio)，
    右栏保留自身宽度。

    Args:
        parent: 父容器 (LayoutObject)
        left_obj: 已构造好的左栏对象
        right_obj: 已构造好的右栏对象
        ratio: 左右比例列表，如 [1.0, 2.5]，默认 [1.0, 2.5]
        gap: 栏间距 (mm)，默认 0
        padding: 分栏容器的内边距，默认 Padding.all(0)
        layer: 图层索引

    Returns:
        LayoutObject: 传入的 parent 对象 (支持链式调用)

    Example:
        >>> left = RectangleObject(name="Left", color=Blue)
        >>> right = LayoutObject(name="Right")
        >>> split_column_advanced(root, left, right, ratio=[1.0, 2.5])
    """
    if ratio is None:
        ratio = [1.0, 2.5]

    if len(ratio) != 2:
        raise ValueError(f"ratio must have exactly 2 elements, got {len(ratio)}")

    if padding is None:
        padding = Padding.all(0)

    # ---- 获取父容器的内容区域 ----
    _, _, content_w, content_h = parent.get_content_area()

    if content_w <= 0 or content_h <= 0:
        raise ValueError(f"Parent '{parent.name}' has no available space")

    # ---- 计算左右栏宽度 ----
    # 直接在构造之后设定宽度，因此必须同步声明尺寸方式为 FIXED ——
    # 这些宽度是调用方显式定死的，不该被 FILL 覆盖（见 create_band 里的同类处理）。
    total_ratio = sum(ratio)
    total_width = content_w - gap
    left_obj._width = total_width * (ratio[0] / total_ratio)
    right_obj._width = total_width * (ratio[1] / total_ratio)
    left_obj._size_x = SizeX.FIXED
    right_obj._size_x = SizeX.FIXED

    # ---- 交给 create_band 排放 ----
    # 格局：带容器挂到 parent 下，左右对象作为"已构造格子"并排
    create_band(
        parent=parent,
        cells=[left_obj, right_obj],
        gap=gap,
        padding=padding,
        height=content_h,
        layer=layer,
        container_name=f"{parent.name}_split_container",
    )

    return parent

def create_columns(
    parent: LayoutObject,
    num_columns: int = 2,
    column_widths: Optional[List[float]] = None,
    column_ratios: Optional[List[float]] = None,
    gap: float = 5,
    padding: Optional[Union[Padding, float]] = None,
    names: Optional[List[str]] = None,
    colors: Optional[List[Color]] = None,
    layer: int = 0,
) -> LayoutObject:
    """
    在父对象中创建分栏

    宽度分配语义（与 create_band 的"严格按比例"不同，此处刻意保留）：
        - column_widths 给定：总和超出可用宽则等比缩小；
          不足则把剩余空间**按栏数均分**追加到每栏；相等则原样使用
        - column_ratios 给定：按比例分配
        - 都不给：等宽

    实现上是两趟：先算出各栏宽度（沿用上述语义），再交给 create_band 排放。
    create_band 只做"严格按比例"，所以剩余量均分这一步必须留在本函数里。

    注意：各栏由 create_band 创建，因此格子名为 names 指定值或 "Column_{i}"，
    而**返回的是新建的带容器**（名为 "{parent.name}_band"），不再是 parent。

    Args:
        parent: 父容器
        num_columns: 栏数
        column_widths: 各栏宽度，与 column_ratios 互斥
        column_ratios: 各栏比例，与 column_widths 互斥
        gap: 栏间距 (mm)
        padding: 各栏内边距
        names: 各栏名字
        colors: 各栏颜色，默认 Gray
        layer: 图层索引

    Returns:
        LayoutObject: 新建的带容器
    """
    if num_columns < 1:
        raise ValueError(f"num_columns must be >= 1, got {num_columns}")
    
    if column_widths is not None and len(column_widths) != num_columns:
        raise ValueError(f"column_widths length must equal num_columns")
    
    if column_ratios is not None and len(column_ratios) != num_columns:
        raise ValueError(f"column_ratios length must equal num_columns")
    
    if column_widths is not None and column_ratios is not None:
        raise ValueError("column_widths and column_ratios cannot both be specified")
    
    parent_content = parent.get_content_area()
    _, _, content_w, content_h = parent_content
    
    if content_w <= 0 or content_h <= 0:
        raise ValueError(f"Parent '{parent.name}' has no available space")
    
    total_gap = gap * (num_columns - 1)
    usable_width = content_w - total_gap
    
    if usable_width <= 0:
        raise ValueError(f"Not enough space for {num_columns} columns")
    
    # ---- 第一趟：算出各栏宽度（本函数独有语义） ----
    if column_widths is not None:
        total_width = sum(column_widths)
        if total_width > usable_width:
            scale = usable_width / total_width
            widths = [w * scale for w in column_widths]
        elif total_width < usable_width:
            remaining = usable_width - total_width
            ratio = 1 / num_columns
            widths = [w + remaining * ratio for w in column_widths]
        else:
            widths = column_widths.copy()
    elif column_ratios is not None:
        total_ratio = sum(column_ratios)
        if total_ratio <= 0:
            raise ValueError("column_ratios sum must be > 0")
        widths = [usable_width * (r / total_ratio) for r in column_ratios]
    else:
        widths = [usable_width / num_columns] * num_columns
    
    if names is not None and len(names) != num_columns:
        raise ValueError(f"names length must equal num_columns")
    col_names = names if names else [f"Column_{i}" for i in range(num_columns)]
    
    if colors is not None and len(colors) != num_columns:
        raise ValueError(f"colors length must equal num_columns")
    col_colors = colors if colors else [Gray] * num_columns
    
    if padding is None:
        col_padding = Padding()
    elif isinstance(padding, (int, float)):
        col_padding = Padding.all(float(padding))
    else:
        col_padding = padding

    # ---- 第二趟：构造各栏并交给 create_band 排放 ----
    # 注意：此处刻意**不再**执行 `parent.children = []`。
    # 那会静默丢弃父元素既有子元素，且绕过 remove_child 使父指针悬空（缺陷 7.4）。
    cols = [
        LayoutObject(
            name=col_names[i],
            x=0,
            y=0,
            width=widths[i],
            height=content_h,
            color=col_colors[i],
            parent=None,
            padding=col_padding,
            align_x=AlignX.NONE,
            align_y=AlignY.NONE,
            layer=layer,
        )
        for i in range(num_columns)
    ]

    return create_band(
        parent=parent,
        cells=cols,
        gap=gap,
        padding=Padding(),
        height=content_h,
        layer=layer,
    )


def create_columns_balanced(
    parent: LayoutObject,
    num_columns: int = 2,
    gap: float = 5,
    padding: Optional[Union[Padding, float]] = None,
    layer: int = 0,
) -> LayoutObject:
    """创建等宽分栏（create_columns 的等宽包装，返回新建的带容器）"""
    return create_columns(
        parent=parent,
        num_columns=num_columns,
        gap=gap,
        padding=padding,
        layer=layer,
    )


def create_spacer(
    name: str,
    height: float,
    parent: Optional[LayoutObject] = None,
    layer: int = 0,
) -> LayoutObject:
    """
    创建一个纯留白对象（垂直间距）

    等价于一个 width=0、align_x=CENTER、align_y=FLOW 的 LayoutObject。
    在流式布局中，它只占据 height 指定的纵向空间，不渲染任何内容。

    设计说明：
        - 不暴露 color 参数：LayoutObject.render() 在 is_fill=False 时不绘制任何内容，
          留白对象的 color 对输出没有影响，暴露它只会让调用点出现无意义的取值。
        - 不暴露 padding 参数：留白对象高度由 height 显式给定（_height > 0），
          get_effective_height() 走 min(_height, avail_h) 分支，padding 不参与计算。
        - 不暴露 align_y 参数：留白的语义就是"接在流式序列的下一个位置"，
          固定为 AlignY.FLOW。
        - name 保持必填：留白对象同样会写入 objectRegister，
          自动命名会改变上层依赖的名字，属于不必要的风险。

    Args:
        name: 对象名称（会注册到 objectRegister）
        height: 留白高度 (mm)
        parent: 父容器。非空时自动挂载（调用 add_child，会正确使缓存失效）
        layer: 图层索引

    Returns:
        LayoutObject: 新建的留白对象

    Example:
        >>> create_spacer("Lead_Above_All", 10, root)
        >>> create_spacer(f"Lead_Between_{i}", 5, root)
    """
    spacer = LayoutObject(
        name=name,
        x=0,
        y=0,
        width=0,
        height=height,
        color=White,
        parent=parent,
        padding=Padding.all(0),
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=layer,
    )

    if parent is not None:
        parent.add_child(spacer)

    return spacer


def create_text_block(
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
) -> TextObject:
    """
    创建一个文本块并挂载到父容器

    与直接构造 TextObject 的区别：
        - 走 TextObject.from_style，样式参数由 Style 对象统一提供
        - height 是**显式参数**，不再由调用方把常量写死在构造里
        - 自动挂载（走 add_child，缓存失效正确触发）

    ⚠️ **height=0 的语义**：取父容器的可用高度，**不是**"按内容自动撑高"。
        "按内容自动撑高"需要真实的行数测量，属于批次 5 的范围。
        因此若希望文本块高度贴合内容，目前仍须显式给出 height。

    Args:
        parent: 父容器
        name: 对象名称
        text: 文本内容
        style: 样式对象。None 表示 Style() 的全默认值
        height: 文本块高度 (mm)。0 表示取父容器可用高
        multi_line: 是否自动换行（pdf.multi_cell）
        line_height: 行高。None 表示由字号推出（font_size * 0.6）
        align_x: 水平对齐，默认 LEFT
        align_y: 垂直对齐，默认 FLOW（接在流式序列的下一个位置）
        padding: 内边距。None 表示沿用 style.padding
        layer: 图层索引

    Returns:
        TextObject: 新建并已挂载的文本对象
    """
    overrides = {
        "width": 0,
        "height": height,
        "multi_line": multi_line,
        "line_height": line_height,
        "align_x": align_x,
        "align_y": align_y,
        "layer": layer,
    }
    # padding 为 None 时让 from_style 沿用 style.padding，不覆盖
    if padding is not None:
        overrides["padding"] = padding

    block = TextObject.from_style(name, style, text=text, **overrides)
    parent.add_child(block)
    return block


# ============================================================================
# 11. 测试入口
# ============================================================================

if __name__ == "__main__":
    from fpdf import FPDF
    
    print("=" * 60)
    print("PDF 排版引擎 - 综合测试 (缓存优化版)")
    print("=" * 60)
    
    pdf = FPDF()
    pdf.add_page()

    try:
        pdf.add_font("LXGW", '', ".\\Resources\\LXGWWenkai-Regular.ttf")
        pdf.add_font("LXGW", 'B', ".\\Resources\\LXGWWenkai-Bold.ttf")
        font_name = "LXGW"
    except:
        font_name = "helvetica"
        print("  注意: 中文字体未找到，使用 helvetica")
    
    root = LayoutObject(
        name="Root",
        x=0, y=0,
        width=210, height=297,
        color=White,
        padding=Padding.all(10),
        layer=0
    )
    
    title = TextObject(
        name="Title",
        x=0, y=0,
        width=0, height=25,
        text="PDF 排版引擎测试 (含缓存优化)",
        font_name=font_name,
        font_size=18,
        font_style="B",
        text_color=Black,
        color=RimuruBlue,
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=1
    )
    root.add_child(title)
    
    divider = RectangleObject(
        name="Divider",
        x=0, y=0,
        width=0, height=2,
        color=Gray,
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=2
    )
    root.add_child(divider)
    
    body = TextObject(
        name="Body",
        x=0, y=0,
        width=0, height=20,
        text="这是一个综合测试，包含布局、文本、矩形、图层管理和缓存优化功能。",
        font_name=font_name,
        font_size=12,
        text_color=Black,
        color=Green,
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        layer=3
    )
    root.add_child(body)
    
    container = LayoutObject(
        name="Container",
        x=0, y=0,
        width=0, height=80,
        color=White,
        align_x=AlignX.CENTER,
        align_y=AlignY.FLOW,
        padding=Padding.all(5),
        layer=4
    )
    root.add_child(container)
    
    create_columns(
        parent=container,
        num_columns=2,
        gap=5,
        padding=3,
        colors=[Color(255, 240, 240, 0), Color(240, 255, 240, 0)],
        layer=5
    )
    
    # 注意：create_columns 现在会先建一个带容器，各栏挂在带容器之下，
    # 因此 Column_0 不再是 container 的直接子元素。取栏要用 find_by_name（深度优先），
    # 不能用 get_child（只看直接子元素）。这与 split_column_advanced 的既有格局一致。
    col0 = container.find_by_name("Column_0")
    col1 = container.find_by_name("Column_1")
    
    if col0:
        col0_text = TextObject(
            name="Col0Text",
            x=0, y=0,
            width=0, height=0,
            text="左栏内容",
            font_name=font_name,
            font_size=11,
            text_color=Black,
            color=White,
            align_x=AlignX.CENTER,
            align_y=AlignY.FLOW,
            layer=6
        )
        col0.add_child(col0_text)
    
    if col1:
        col1_text = TextObject(
            name="Col1Text",
            x=0, y=0,
            width=0, height=0,
            text="右栏内容",
            font_name=font_name,
            font_size=11,
            text_color=Black,
            color=White,
            align_x=AlignX.CENTER,
            align_y=AlignY.FLOW,
            layer=6
        )
        col1.add_child(col1_text)
    
    # ---- 渲染并计时 ----
    print("\n【开始渲染】")
    start = time.perf_counter()
    render_ret = root.render(pdf, is_fill=False)
    elapsed = time.perf_counter() - start
    print(f"\n【渲染完成】总耗时: {elapsed:.4f} 秒")
    
    output_path = "test_layout_engine_cached.pdf"
    pdf.output(output_path)
    print(f"PDF 已生成: {output_path}")
    
    # ---- 回归契约断言 ----
    # 1) get_true_height() 目前是未实现的占位（函数体只有一行 None），
    #    此处用断言把"返回 None"这一事实固定下来，避免被误当作已实现的高度接口调用。
    assert root.get_true_height() is None, "get_true_height() 仍是未实现的占位，应返回 None"
    print("  ✅ get_true_height() 占位契约通过（返回 None）")
    
    # 2) 渲染返回值契约。render() 与 render_debug() 现在返回同类值：
    #      LayoutObject / TextObject -> 数值 y（最后渲染到的位置）
    #      ImageObject / RectangleObject -> (宽, 高) 二元组
    #    这里接受这两种形态，但拒绝 None —— 那说明渲染根本没返回值（缺陷 7.11 的一半）。
    #    注意 render_debug 曾在四个实现里都没有 return，于是一律返回 None；
    #    方案 A 已修，两者现在一致。
    def _render_ret_ok(v):
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float)):
            return True
        return (isinstance(v, tuple) and len(v) == 2
                and all(isinstance(x, (int, float)) for x in v))

    assert _render_ret_ok(render_ret), \
        (f"渲染应返回值（数值 y 或 (宽, 高) 二元组），实际返回 "
         f"{type(render_ret).__name__}: {render_ret!r}")
    print(f"  ✅ 渲染返回值契约通过（{render_ret!r}）")
    
    # 3) create_columns 曾会清空父元素既有子元素（旧实现里的 `parent.children = []`），
    #    属已知缺陷 7.4（同时绕过 remove_child，使被丢弃子元素的父指针悬空）。
    #    批次 2 已修复：现在走 create_band -> add_child，既有子元素被保留。
    _probe_parent = LayoutObject(name="ProbeParent", width=100, height=50)
    _kept = TextObject(name="ProbeKept", text="x", font_size=10)
    _probe_parent.add_child(_kept)
    assert _probe_parent.children == [_kept], "add_child 后应保留子元素"
    create_columns(parent=_probe_parent, num_columns=2, gap=0)
    assert _kept in _probe_parent.children, \
        "缺陷 7.4 已修：create_columns 不应丢弃父元素既有子元素"
    assert _kept.parent is _probe_parent, "被保留的子元素父指针不应悬空"
    # 父元素下应有两个子元素：既有子元素 + create_columns 新建的带容器
    # （各栏挂在带容器之下，不直接是父元素的子元素）
    assert len(_probe_parent.children) == 2, \
        f"父元素应有既有子元素 + 带容器共 2 个，实际 {len(_probe_parent.children)}"
    _probe_band = _probe_parent.children[1]
    assert _probe_band.name == "ProbeParent_band", \
        f"带容器应有默认名 ProbeParent_band，实际 {_probe_band.name}"
    assert [c.name for c in _probe_band.children] == ["Column_0", "Column_1"], \
        "两栏应挂在带容器之下"
    print("  ✅ create_columns 保留父元素既有子元素（缺陷 7.4 已修）")
    
    # 4) create_spacer 构件契约（批次 1）
    #    留白对象是流式布局里的纯占位元素，必须满足：
    #      - 高度由 height 显式给定，有效高度等于该值；
    #      - align_x/align_y 固定为 CENTER/FLOW，宽度交给父容器决定；
    #      - padding 不参与有效高度计算（这是"不暴露 padding 参数"的依据）；
    #      - 传入 parent 时自动挂载，走 add_child（因此缓存失效被正确触发）；
    #      - 不传入 parent 时保持游离，父指针为 None。
    _sp_root = LayoutObject(name="SpacerRoot", width=100, height=200,
                            padding=Padding.all(5))
    _sp = create_spacer("SpacerA", 7, _sp_root)
    assert _sp._height == 7, "留白构造高度应为 7"
    assert _sp.align_x == AlignX.CENTER, "留白的 align_x 应为 CENTER"
    assert _sp.align_y == AlignY.FLOW, "留白的 align_y 应为 FLOW"
    assert _sp._width == 0, "留白的构造宽度应为 0（由父容器决定有效宽度）"
    assert _sp in _sp_root.children, "传入 parent 时留白应被自动挂载"
    assert _sp.parent is _sp_root, "留白的父指针应指向传入的 parent"
    assert _sp.get_effective_height() == 7, \
        f"留白有效高度应为 7，实际 {_sp.get_effective_height()}"
    # padding 不参与计算：即使被外部改写也不应影响有效高度（批次 1 去掉 padding 参数的依据）
    _sp.padding = Padding.all(10)
    assert _sp.get_effective_height() == 7, \
        f"padding 不应影响留白有效高度，实际 {_sp.get_effective_height()}"
    _sp_free = create_spacer("SpacerFree", 3)
    assert _sp_free.parent is None, "不传 parent 时留白应保持游离"
    assert _sp_free.get_effective_height() == 3, "游离留白的有效高度应等于 height"
    print("  ✅ create_spacer 构件契约通过")
    
    # 5) create_band 构件契约（批次 2）
    #    横向带是引擎的横向布局基础构件，create_columns / split_column_advanced 都是它的包装。
    #    注意 BandRoot 有 Padding.all(10)，所以父内容区宽 = 120 - 20 = 100，高 = 100 - 20 = 80。
    print("  --- create_band ---")
    _bd_root = LayoutObject(name="BandRoot", width=120, height=100,
                            padding=Padding.all(10))
    assert _bd_root.get_content_area()[2] == 100, "前提：BandRoot 内容区宽应为 100"
    assert _bd_root.get_content_area()[3] == 80, "前提：BandRoot 内容区高应为 80"
    # 5.1 比例分宽：可用宽 = 100，比例 2:1:2 -> 40/20/40
    _bd = create_band(_bd_root, [2.0, 1.0, 2.0], gap=0, height=30)
    assert _bd.parent is _bd_root and _bd in _bd_root.children, \
        "create_band 应把带容器挂到 parent 下"
    assert _bd._width == 100, f"带容器宽应等于父内容区宽 100，实际 {_bd._width}"
    _bw = [c._width for c in _bd.children]
    assert _bw == [40.0, 20.0, 40.0], f"2:1:2 应得 [40,20,40]，实际 {_bw}"
    assert [c._x for c in _bd.children] == [0.0, 40.0, 60.0], \
        f"gap=0 时 x 应依次累加，实际 {[c._x for c in _bd.children]}"
    assert all(c._height == 30 for c in _bd.children), "格子高度应等于 height"
    print(f"    ✅ 比例分宽通过（{_bw}）")
    # 5.2 gap 累加 x：可用宽 = 100 - 2*(3-1) = 96，比例 1:1:1 -> 32 每格
    _bd2 = create_band(_bd_root, [1.0, 1.0, 1.0], gap=2, height=30,
                       container_name="BandGap")
    _unit = (100 - 2 * 2) / 3
    _bw2 = [round(c._width, 6) for c in _bd2.children]
    assert _bw2 == [round(_unit, 6)] * 3, f"1:1:1 应均分 {_unit}，实际 {_bw2}"
    _bx2 = [round(c._x, 6) for c in _bd2.children]
    _exp_x2 = [0.0, round(_unit + 2, 6), round(_unit * 2 + 4, 6)]
    assert _bx2 == _exp_x2, f"gap=2 时 x 应为 {_exp_x2}，实际 {_bx2}"
    print(f"    ✅ gap 累加 x 通过（每格 {_unit}，x={_bx2}）")
    # 5.3 height=0 取父内容区高（80，不是构造高 100）
    _bd3 = create_band(_bd_root, [1.0, 1.0], gap=0, height=0,
                       container_name="BandAutoH")
    assert _bd3._height == 80, f"height=0 应取父内容区高 80，实际 {_bd3._height}"
    assert all(c._height == 80 for c in _bd3.children), "格子高度应随 height=0 取父内容区高"
    print("    ✅ height=0 取父内容区高通过")
    # 5.4 传入已构造对象：保留其自身宽度，只接管位置与高度
    _pre_l = RectangleObject(name="PreLeft", width=25, height=999, color=Red)
    _pre_r = LayoutObject(name="PreRight", width=0, height=999)
    _bd4 = create_band(_bd_root, [_pre_l, _pre_r], gap=5, height=40,
                       container_name="BandPrebuilt")
    assert _bd4.children == [_pre_l, _pre_r], "传入的对象应被直接复用，不新建"
    assert _pre_l._width == 25, "已构造对象的宽度应被保留，而非按比例重算"
    assert (_pre_l._x, _pre_r._x) == (0.0, 30.0), \
        f"已构造对象的 x 应为 0 与 25+5=30，实际 {(_pre_l._x, _pre_r._x)}"
    assert _pre_l._height == 40 and _pre_r._height == 40, "已构造对象的高度应被 height 接管"
    print("    ✅ 复用已构造对象通过")
    # 5.5 错误路径
    for _bad, _desc in (
        (lambda: create_band(_bd_root, [], height=10), "cells 为空"),
        (lambda: create_band(_bd_root, [1.0, 1.0], gap=999, height=10), "间距占满可用宽"),
        (lambda: create_band(_bd_root, [1.0], height=10, names=["a", "b"]), "names 长度不匹配"),
        (lambda: create_band(_bd_root, [1.0], height=10, colors=[Red, Blue]), "colors 长度不匹配"),
    ):
        try:
            _bad()
        except ValueError:
            pass
        else:
            raise AssertionError(f"create_band 应对「{_desc}」抛 ValueError")
    print("    ✅ 错误路径通过（4 项）")
    # 5.6 create_columns / split_column_advanced 都返回新建的带容器（不再是 parent）
    _cc_root = LayoutObject(name="CCRoot", width=100, height=80)
    _cc_ret = create_columns(parent=_cc_root, num_columns=2, gap=0)
    assert _cc_ret is not _cc_root, "create_columns 现在返回新建的带容器，而非 parent"
    assert _cc_ret.parent is _cc_root, "返回的带容器应挂在 parent 下"
    assert [c.name for c in _cc_ret.children] == ["Column_0", "Column_1"], \
        "各栏名字应保持 Column_{i} 约定"
    print("    ✅ 包装函数返回带容器通过")
    # 5.7 split_column_advanced：左栏按比例，右栏保留自身宽度；返回 parent 以兼容旧调用
    _sc_root = LayoutObject(name="SCRoot", width=140, height=60)
    _sc_l = RectangleObject(name="SCLeft", width=1, height=1)
    _sc_r = LayoutObject(name="SCRight", width=1, height=1)
    _sc_ret = split_column_advanced(_sc_root, _sc_l, _sc_r, ratio=[1.0, 2.5], gap=0)
    assert _sc_ret is _sc_root, "split_column_advanced 应返回 parent（链式调用兼容）"
    _sc_container = _sc_root.find_by_name("SCRoot_split_container")
    assert _sc_container is not None, "应创建 {parent}_split_container"
    assert _sc_container.children == [_sc_l, _sc_r], "左右对象应挂到分栏容器下"
    assert round(_sc_l._width, 6) == round(140 * (1.0 / 3.5), 6), \
        f"左栏宽应为 140*1/3.5，实际 {_sc_l._width}"
    assert round(_sc_r._width, 6) == round(140 * (2.5 / 3.5), 6), \
        f"右栏宽应为 140*2.5/3.5，实际 {_sc_r._width}"
    assert _sc_l.parent is _sc_container and _sc_r.parent is _sc_container, \
        "左右对象的父指针应指向分栏容器"
    print("    ✅ split_column_advanced 包装通过")
    
    # 6) Style 与 from_style 工厂（批次 3）
    print("  --- Style / from_style ---")
    # 6.1 Style 字段名与默认值快照。Style 从模板层搬运而来，这里固化"搬运无损"。
    _style_names = [n for n in inspect.signature(Style.__init__).parameters if n != "self"]
    assert _style_names == ["font_name", "font_size", "bold", "italic", "color",
                            "fill_color", "image_path", "padding", "fit_mode"], \
        f"Style 字段名或顺序变了: {_style_names}"
    _d = Style()
    assert (_d.font_name, _d.font_size, _d.bold, _d.italic) == ("helvetica", 12, False, False)
    assert _d.color is Black and _d.fill_color is White
    assert _d.image_path == "" and _d.fit_mode == "cover"
    print("    ✅ Style 字段快照通过")
    # 6.2 get_font_style 四种组合
    for _b, _i, _exp in ((True, True, "BI"), (True, False, "B"),
                         (False, True, "I"), (False, False, "")):
        _got = Style(bold=_b, italic=_i).get_font_style()
        assert _got == _exp, f"bold={_b} italic={_i} 应为 {_exp!r}，实际 {_got!r}"
    print("    ✅ get_font_style 四种组合通过")
    # 6.3 TextObject.from_style 的字段映射
    _st = Style(font_name="Courier", font_size=17, bold=True, italic=True,
                color=Red, fill_color=Green, padding=Padding.all(3))
    _t = TextObject.from_style("T1", _st, text="hi")
    assert _t.get_text() == "hi"
    assert _t.font_name == "Courier" and _t.font_size == 17
    assert _t.font_style == "BI", f"bold+italic 应为 'BI'，实际 {_t.font_style!r}"
    assert _t.text_color is Red, "Style.color 应映射到 text_color"
    assert _t.color is Green, "Style.fill_color 应映射到 color"
    assert _t.padding.left == 3 and _t.padding.top == 3
    print("    ✅ TextObject.from_style 字段映射通过")
    # 6.4 overrides 优先级高于 style
    _t2 = TextObject.from_style("T2", _st, text="x", font_size=99, text_color=Blue,
                                align_x=AlignX.CENTER)
    assert _t2.font_size == 99, "overrides 应覆盖 style.font_size"
    assert _t2.text_color is Blue, "overrides 应覆盖 style.color"
    assert _t2.align_x == AlignX.CENTER
    assert _t2.font_name == "Courier", "未覆盖的字段应仍来自 style"
    print("    ✅ overrides 优先级通过")
    # 6.5 style=None 使用全默认值
    _t3 = TextObject.from_style("T3")
    assert _t3.font_name == "helvetica" and _t3.font_size == 12
    assert _t3.font_style == "" and _t3.text_color is Black and _t3.color is White
    assert _t3.get_text() == ""
    print("    ✅ style=None 全默认值通过")
    # 6.6 返回对象可继续链式调用
    assert _t3.set_text("chained") is _t3 and _t3.get_text() == "chained"
    print("    ✅ from_style 返回对象可链式调用通过")
    # 6.7 ImageObject.from_style 的字段映射
    _ist = Style(image_path="a.png", fill_color=Yellow, fit_mode="contain",
                 padding=Padding.all(2), font_size=33, bold=True)
    _i1 = ImageObject.from_style("I1", _ist)
    assert _i1.get_image() == "a.png", "Style.image_path 应映射到 image_path"
    assert _i1.fit_mode == "contain", "Style.fit_mode 应映射到 fit_mode"
    assert _i1.color is Yellow, "Style.fill_color 应映射到 color"
    assert _i1.padding.left == 2
    assert _i1.keep_aspect_ratio is True, "未映射的字段应保持构造默认值"
    _i2 = ImageObject.from_style("I2", _ist, image_path="b.png")
    assert _i2.get_image() == "b.png", "image_path 实参应覆盖 style.image_path"
    print("    ✅ ImageObject.from_style 字段映射通过")
    
    # 7) create_text_block（批次 3）
    print("  --- create_text_block ---")
    _tb_root = LayoutObject(name="TBRoot", width=100, height=200,
                            padding=Padding.all(10))
    assert _tb_root.get_content_area()[3] == 180, "前提：TBRoot 内容区高应为 180"
    # 7.1 height=0 取父可用高（不是按内容撑高）
    _tb1 = create_text_block(_tb_root, "TB1", text="a")
    assert _tb1.parent is _tb_root and _tb1 in _tb_root.children, "应自动挂载"
    assert _tb1._height == 0, "构造高度应保持 0（不是被改成父高）"
    assert _tb1.get_effective_height() == 180, \
        f"height=0 应取父内容区高 180，实际 {_tb1.get_effective_height()}"
    print("    ✅ height=0 取父可用高通过")
    # 7.2 height=N 生效。用独立父容器：FLOW 模式下前驱会吃掉全部可用高，
    #     同容器里放第二个块会被截断 —— 那是引擎的既有语义（见技术文档 7.19 一节的截断描述），
    #     不是 create_text_block 的问题。此处隔离以单独验证 height 参数。
    _tb2_root = LayoutObject(name="TBRoot2", width=100, height=200,
                             padding=Padding.all(10))
    _tb2 = create_text_block(_tb2_root, "TB2", text="b", height=25)
    assert _tb2._height == 25, f"构造高度应为 25，实际 {_tb2._height}"
    assert _tb2.get_effective_height() == 25, \
        f"有效高应为 25，实际 {_tb2.get_effective_height()}"
    print("    ✅ 显式 height 通过")
    # 7.2b 同容器内 height=0 的块会吃掉全部可用高，把后随 FLOW 兄弟挤成 0
    _tb1b = create_text_block(_tb_root, "TB1b", text="b2", height=20)
    assert _tb1b.get_effective_height() == 0, \
        f"前驱占满后，后随块应被截断为 0，实际 {_tb1b.get_effective_height()}"
    assert _tb1b._flow_clipped is True, "被截断时应置 _flow_clipped"
    print("    ✅ 同容器后随块被截断的现状已固化（FLOW 既有语义）")
    # 7.3 样式与其它参数透传（独立父容器，避免受 7.2b 的截断影响）
    _tb3_root = LayoutObject(name="TBRoot3", width=100, height=200,
                             padding=Padding.all(10))
    _tb3 = create_text_block(_tb3_root, "TB3", text="c", style=_st,
                             height=12, multi_line=True, align_x=AlignX.RIGHT,
                             align_y=AlignY.TOP, padding=Padding.all(1), layer=3)
    assert _tb3.font_name == "Courier" and _tb3.font_style == "BI"
    assert _tb3.text_color is Red and _tb3.color is Green
    assert _tb3.padding.left == 1, "显式 padding 应覆盖 style.padding"
    assert _tb3.multi_line is True and _tb3.align_x == AlignX.RIGHT
    assert _tb3.align_y == AlignY.TOP and _tb3.layer == 3
    assert _tb3._line_height is None, "未传 line_height 时应保持 None（运行时按字号推）"
    print("    ✅ 参数透传与 padding 覆盖通过")
    # 7.4 padding=None 时沿用 style.padding
    _tb4 = create_text_block(_tb3_root, "TB4", text="d", style=_st, height=10,
                             align_y=AlignY.TOP)
    assert _tb4.padding.left == 3, "padding 未传时应沿用 style.padding"
    print("    ✅ padding=None 沿用样式通过")
    # 7.5 style=None 可省略
    _tb5 = create_text_block(_tb3_root, "TB5", text="e", height=8,
                             align_y=AlignY.TOP)
    assert _tb5.font_name == "helvetica" and _tb5.font_size == 12
    print("    ✅ style=None 通过")
    # 7.6 每次调用挂载一个新对象，父元素子元素唯一
    _tb_ids = [id(c) for c in _tb_root.children]
    assert len(_tb_ids) == len(set(_tb_ids)), "create_text_block 不应重复挂载同一对象"
    assert len(_tb_root.children) == 2, f"TBRoot 应有 2 个块，实际 {len(_tb_root.children)}"
    assert len(_tb3_root.children) == 3, f"TBRoot3 应有 3 个块，实际 {len(_tb3_root.children)}"
    print("    ✅ 挂载唯一性通过")
    
    # 8) 四轴设计：尺寸枚举与对齐枚举分离（批次 4.1）
    print("  --- 四轴：SizeX / SizeY ---")
    # 8.1 四个枚举的成员集合。对齐枚举**不新增成员**（wrap 不属于对齐轴）。
    assert [m.name for m in SizeX] == ["FILL", "FIXED", "CONTENT"]
    assert [m.name for m in SizeY] == ["FILL", "FIXED", "CONTENT"]
    assert [m.name for m in AlignX] == ["LEFT", "CENTER", "RIGHT", "NONE"], \
        "对齐轴不应新增成员 —— wrap 属于尺寸轴"
    assert [m.name for m in AlignY] == ["TOP", "VCENTER", "BOTTOM", "NONE", "FLOW"], \
        "对齐轴不应新增成员 —— wrap 属于尺寸轴"
    print("    ✅ 枚举成员集合通过（对齐轴未污染）")
    # 8.2 声明值 -> 尺寸方式的推断（批次 4.4 起不再有 wrap_* 简写）
    _map_cases = [
        (dict(width=0),  "size_x", "FILL"),
        (dict(width=50), "size_x", "FIXED"),
        (dict(height=0),  "size_y", "FILL"),
        (dict(height=30), "size_y", "FIXED"),
    ]
    for _i, (_kw, _attr, _exp) in enumerate(_map_cases):
        _o = LayoutObject(name=f"AXIS_MAP_{_i}", **_kw)
        assert getattr(_o, _attr).name == _exp, \
            f"{_kw} -> {_attr} 应为 {_exp}，实际 {getattr(_o, _attr).name}"
    print("    ✅ 声明值→尺寸方式 推断映射通过（4 例）")
    # 8.3 显式 size_* 直接生效
    _o = LayoutObject(name="AXIS_EXPLICIT", width=50, size_x=SizeX.CONTENT)
    assert _o.size_x == SizeX.CONTENT, "显式 size_x 应直接生效（不因 width=50 变 FIXED）"
    _o2 = LayoutObject(name="AXIS_EXPLICIT2", size_y=SizeY.CONTENT)
    assert _o2.size_y == SizeY.CONTENT
    print("    ✅ 显式 size_* 生效通过")
    # 8.4 wrap_width / wrap_height 兼容属性已删除（批次 4.4）
    _o = LayoutObject(name="AXIS_NOCOMPAT", width=0, height=0)
    assert not hasattr(_o, "wrap_width"), "wrap_width 兼容属性应已删除"
    assert not hasattr(_o, "wrap_height"), "wrap_height 兼容属性应已删除"
    import inspect as _inspect
    for _cls in (LayoutObject, TextObject, ImageObject, RectangleObject):
        _params = _inspect.signature(_cls.__init__).parameters
        assert "wrap_width" not in _params and "wrap_height" not in _params, \
            f"{_cls.__name__}.__init__ 不应再有 wrap_* 形参"
    print("    ✅ wrap_width / wrap_height 兼容面已彻底移除通过")
    # 8.5 size_* setter 触发失效（内容定尺寸只能靠它设置）
    _o = LayoutObject(name="AXIS_SET", width=0, height=0)
    assert _o.size_y == SizeY.FILL
    _o.size_y = SizeY.CONTENT
    assert _o.size_y == SizeY.CONTENT and _o._layout_valid is False
    print("    ✅ size_* setter 生效通过")
    # 8.6 缺陷 7.10：Style.padding 不再是可变默认参数（每个实例独立）
    _sa, _sb = Style(), Style()
    assert _sa.padding is not _sb.padding, \
        "Style 的 padding 默认值曾共享同一个 Padding 对象（缺陷 7.10），现已改为每次新建"
    _sa.padding.left = 99
    assert _sb.padding.left == 0, "改一个 Style 的 padding 不应影响另一个"
    assert Style().padding.left == 0, "后续新建的 Style 也不应受影响"
    print("    ✅ Style.padding 可变默认已修通过（缺陷 7.10）")
    # 8.5 size_* setter 触发布局失效
    _o = LayoutObject(name="AXIS_INVAL", width=10, height=10)
    _o.get_effective_height()          # 先跑一次布局
    assert _o._layout_valid is True
    _o.size_y = SizeY.CONTENT
    assert _o._layout_valid is False, "改 size_y 应使布局失效"
    print("    ✅ size_* setter 失效通过")
    # 8.6 类型校验
    try:
        LayoutObject(name="AXIS_BAD", size_y=SizeX.FILL)
    except TypeError:
        pass
    else:
        raise AssertionError("size_y 传入 SizeX 应抛 TypeError")
    print("    ✅ 尺寸轴类型校验通过")
    # 8.7 LayoutCycleError 是可捕获的专门类型
    assert issubclass(LayoutCycleError, RuntimeError)
    print("    ✅ LayoutCycleError 类型通过")
    
    # 9) 两趟遍历（批次 4.2）
    print("  --- 两趟遍历 ---")
    # 9.1 FIXED 不被父约束裁剪（"定死的尺寸不动"）
    #     旧实现会 min(_width, avail_w)，把定死值改小；新实现不裁剪，装不下就是溢出。
    _fx_root = LayoutObject(name="FX_Root", width=100, height=100)
    _fx = LayoutObject(name="FX_Child", width=150, height=999,
                       align_x=AlignX.NONE, align_y=AlignY.NONE)
    _fx_root.add_child(_fx)
    _fx_root.layout()
    assert _fx.get_effective_width() == 150, \
        f"FIXED 宽度不应被父可用宽 100 裁剪，实际 {_fx.get_effective_width()}"
    assert _fx.get_effective_height() == 999, \
        f"FIXED 高度不应被父可用高裁剪，实际 {_fx.get_effective_height()}"
    print("    ✅ FIXED 不被父约束裁剪通过")
    # 9.2 FILL 撑满父内容区
    _fl_root = LayoutObject(name="FL_Root", width=100, height=100,
                            padding=Padding.all(10))
    _fl = LayoutObject(name="FL_Child", width=0, height=0,
                       align_x=AlignX.NONE, align_y=AlignY.NONE)
    _fl_root.add_child(_fl)
    _fl_root.layout()
    assert _fl.get_effective_width() == 80 and _fl.get_effective_height() == 80, \
        f"FILL 应为父内容区 80x80，实际 {_fl.get_effective_width()}x{_fl.get_effective_height()}"
    print("    ✅ FILL 撑满父内容区通过")
    # 9.3 CONTENT 包围内容（这一批的核心能力，旧实现塌缩为 padding）
    _ct_root = LayoutObject(name="CT_Root", width=200, height=300)
    _ct = LayoutObject(name="CT_Box", width=0, height=0, size_y=SizeY.CONTENT,
                       padding=Padding.all(5), align_x=AlignX.NONE, align_y=AlignY.NONE)
    _ct_root.add_child(_ct)
    for _i, _h in enumerate((10, 20, 15)):
        _ct.add_child(LayoutObject(name=f"CT_C{_i}", width=0, height=_h,
                                   align_x=AlignX.NONE, align_y=AlignY.NONE))
    _ct_root.layout()
    assert _ct.get_effective_height() == 55, \
        f"CONTENT 高应为 (10+20+15) + padding(5+5) = 55，实际 {_ct.get_effective_height()}"
    print("    ✅ CONTENT 包围内容通过（55 = 45 内容 + 10 padding）")
    # 9.4 包围高与父高无关（这是 7.19 的根治验收）
    _heights = []
    for _ph in (100, 300, 800):
        _r = LayoutObject(name=f"CT_Root_{_ph}", width=200, height=_ph)
        _b = LayoutObject(name=f"CT_Box_{_ph}", width=0, height=0, size_y=SizeY.CONTENT,
                          padding=Padding.all(5), align_x=AlignX.NONE, align_y=AlignY.NONE)
        _r.add_child(_b)
        for _i, _h in enumerate((10, 20, 15)):
            _b.add_child(LayoutObject(name=f"CT_{_ph}_C{_i}", width=0, height=_h,
                                      align_x=AlignX.NONE, align_y=AlignY.NONE))
        _r.layout()
        _heights.append(_b.get_effective_height())
    assert len(set(_heights)) == 1, \
        f"包围高应与父高无关，实际随父高变化：{_heights}"
    print(f"    ✅ 包围高与父高无关通过（父高 100/300/800 下均为 {_heights[0]}）")
    # 9.5 CONTENT 对约束夹紧 + 溢出标记
    _cl_root = LayoutObject(name="CL_Root", width=200, height=30)
    _cl = LayoutObject(name="CL_Box", width=0, height=0, size_y=SizeY.CONTENT,
                       align_x=AlignX.NONE, align_y=AlignY.NONE)
    _cl_root.add_child(_cl)
    _cl.add_child(LayoutObject(name="CL_C", width=0, height=100,
                               align_x=AlignX.NONE, align_y=AlignY.NONE))
    _cl_root.layout()
    assert _cl.get_effective_height() == 30, \
        f"CONTENT 应被约束夹紧到 30，实际 {_cl.get_effective_height()}"
    assert _cl._content_overflows is True, "内容超出约束时应置 _content_overflows"
    print("    ✅ CONTENT 夹紧与溢出标记通过")
    # 9.6 CONTENT 父 + 直接 FILL 子 —— **不报错**，由"退化规则"处理
    #     两趟遍历把约束改成传参后，这个组合不再是循环：
    #     FILL 子需要的是**约束**而不是"父的最终尺寸"，而约束是传下去的。
    #     父由内容决定时，FILL 子退化为"按内容定尺寸"（同安卓 wrap_content 父的语义）。
    _cf_root = LayoutObject(name="CF_Root", width=200, height=200)
    _cf = LayoutObject(name="CF_Box", width=0, height=0, size_y=SizeY.CONTENT,
                       padding=Padding.all(5), align_x=AlignX.NONE, align_y=AlignY.NONE)
    _cf_root.add_child(_cf)
    _cf.add_child(TextObject(name="CF_T", width=0, height=0, text="中文", font_size=10,
                             align_x=AlignX.NONE, align_y=AlignY.NONE))
    _cf_root.layout()          # 不应抛错
    _cf_t = _cf.children[0]
    assert _cf_t.get_effective_height() > 0, \
        "CONTENT 父下的 FILL 子应退化为按内容定高，而不是被压成 0"
    assert abs(_cf.get_effective_height() - (_cf_t.get_effective_height() + 10)) < 1e-9, \
        (f"CONTENT 父高应为 子高 + padding(10)，"
         f"实际 {_cf.get_effective_height()} vs 子 {_cf_t.get_effective_height()}")
    print(f"    ✅ CONTENT 父 + FILL 子 由退化规则处理通过（父高 {_cf.get_effective_height():.2f}）")
    # 9.7 结构循环：元素成为自己的祖先
    _cy_a = LayoutObject(name="CY_A", width=50, height=50)
    _cy_b = LayoutObject(name="CY_B", width=50, height=50)
    _cy_a.add_child(_cy_b)
    _cy_b.children.append(_cy_a)      # 人为接成环
    try:
        _cy_a.layout()
    except LayoutCycleError as _e:
        assert "CY_A" in str(_e) and "CY_B" in str(_e), "报错信息应含整条路径"
    else:
        raise AssertionError("结构循环应抛 LayoutCycleError")
    print("    ✅ 结构循环报错通过（含路径）")
    # 9.8 失效传导：add_child / height / size_y 之后重算必须拿到新值
    _iv_root = LayoutObject(name="IV_Root", width=200, height=300)
    _iv = LayoutObject(name="IV_Box", width=0, height=0, size_y=SizeY.CONTENT,
                       align_x=AlignX.NONE, align_y=AlignY.NONE)
    _iv_root.add_child(_iv)
    _iv.add_child(LayoutObject(name="IV_C0", width=0, height=10,
                               align_x=AlignX.NONE, align_y=AlignY.NONE))
    _iv_root.layout()
    _h0 = _iv.get_effective_height()
    _iv.add_child(LayoutObject(name="IV_C1", width=0, height=25,
                               align_x=AlignX.NONE, align_y=AlignY.NONE))
    _h1 = _iv.get_effective_height()
    assert _h1 == _h0 + 25, f"加子元素后包围高应从 {_h0} 增到 {_h0+25}，实际 {_h1}"
    _iv.children[0].height = 40
    _h2 = _iv.get_effective_height()
    assert _h2 == _h1 + 30, f"改子元素高后包围高应变为 {_h1+30}，实际 {_h2}"
    _iv_root.remove_child(_iv)
    print("    ✅ 失效传导通过（加子/改子元素后包围高正确重算）")
    # 9.9 FLOW 溢出裁剪仍在（既有语义保留）
    _fz_root = LayoutObject(name="FZ_Root", width=100, height=50)
    _fz_root.add_child(LayoutObject(name="FZ_A", width=0, height=40,
                                    align_x=AlignX.NONE, align_y=AlignY.FLOW))
    _fz_b = LayoutObject(name="FZ_B", width=0, height=30, size_y=SizeY.FIXED,
                         align_x=AlignX.NONE, align_y=AlignY.FLOW)
    _fz_root.add_child(_fz_b)
    _fz_root.layout()
    assert _fz_b._flow_clipped is True, "超出父内容区的 FLOW 元素应被裁剪"
    assert _fz_b.get_effective_height() == 10, \
        f"应裁剪到剩余 10，实际 {_fz_b.get_effective_height()}"
    print("    ✅ FLOW 溢出裁剪通过")
    
    # 10) 几何属性 property 化 + 显式接口（批次 4.3）
    print("  --- 几何属性 property 与显式接口 ---")
    # 10.1 padding setter 触发失效，且改动对 CONTENT 尺寸生效
    _pd_root = LayoutObject(name="PD_Root", width=200, height=300)
    _pd = LayoutObject(name="PD_Box", width=0, height=0, size_y=SizeY.CONTENT,
                       padding=Padding.all(5), align_x=AlignX.NONE, align_y=AlignY.NONE)
    _pd_root.add_child(_pd)
    _pd.add_child(LayoutObject(name="PD_C", width=0, height=30,
                               align_x=AlignX.NONE, align_y=AlignY.NONE))
    _pd_root.layout()
    assert _pd.get_effective_height() == 40, \
        f"padding 5+5 + 内容 30 应为 40，实际 {_pd.get_effective_height()}"
    _pd.padding = Padding.all(12)
    assert _pd._layout_valid is False, "改 padding 应使布局失效"
    assert _pd.get_effective_height() == 54, \
        f"padding 12+12 + 内容 30 应为 54，实际 {_pd.get_effective_height()}"
    print("    ✅ padding setter 失效并生效通过（40 → 54）")
    # 10.2 align setter 触发失效，且改动对位置生效
    _al_root = LayoutObject(name="AL_Root", width=100, height=100)
    _al = LayoutObject(name="AL_C", width=20, height=20,
                       align_x=AlignX.LEFT, align_y=AlignY.TOP)
    _al_root.add_child(_al)
    _al_root.layout()
    assert _al.get_absolute_x() == 0.0, f"LEFT 应为 0，实际 {_al.get_absolute_x()}"
    _al.align_x = AlignX.RIGHT
    assert _al._layout_valid is False, "改 align_x 应使布局失效"
    assert _al.get_absolute_x() == 80.0, \
        f"RIGHT 应为 100-20=80，实际 {_al.get_absolute_x()}"
    _al.align_y = AlignY.BOTTOM
    assert _al.get_absolute_y() == 80.0, \
        f"BOTTOM 应为 100-20=80，实际 {_al.get_absolute_y()}"
    print("    ✅ align setter 失效并生效通过（LEFT→RIGHT、TOP→BOTTOM）")
    # 10.3 四个显式接口触发失效、返回 self
    _if_root = LayoutObject(name="IF_Root", width=200, height=300)
    _if = LayoutObject(name="IF_C", width=0, height=0,
                       align_x=AlignX.NONE, align_y=AlignY.NONE)
    _if_root.add_child(_if)
    _if.add_child(LayoutObject(name="IF_C0", width=0, height=20,
                               align_x=AlignX.NONE, align_y=AlignY.NONE))
    _if_root.layout()
    assert _if.size_y == SizeY.FILL and _if.get_effective_height() == 300
    # set_size：> 0 置 FIXED，== 0 退回 FILL
    assert _if.set_size(height=50) is _if, "set_size 应返回 self"
    assert _if._layout_valid is False and _if.size_y == SizeY.FIXED, \
        f"set_size(height=50) 后应为 FIXED，实际 {_if.size_y.name}"
    assert _if.get_effective_height() == 50, f"应为 50，实际 {_if.get_effective_height()}"
    _if.set_size(height=0)
    assert _if.size_y == SizeY.FILL, "set_size(height=0) 应退回 FILL"
    assert _if.get_effective_height() == 300, f"FILL 应为 300，实际 {_if.get_effective_height()}"
    # 显式的 CONTENT 模式**不应**被 height 赋值覆盖（那是调用方明确表达的意图）
    _ct_keep = LayoutObject(name="IF_CT", width=0, height=0, size_y=SizeY.CONTENT,
                            align_x=AlignX.NONE, align_y=AlignY.NONE)
    _ct_keep.height = 50
    assert _ct_keep.size_y == SizeY.CONTENT, \
        "显式 CONTENT 不应被 height 赋值改成 FIXED"
    _ct_keep.size_y = SizeY.FIXED
    _ct_keep.height = 50
    assert _ct_keep.size_y == SizeY.FIXED
    print("    ✅ 显式 CONTENT 不被 height 赋值覆盖通过")
    # set_position / set_align / set_padding
    assert _if.set_position(x=7, y=9) is _if
    assert _if._x == 7 and _if._y == 9
    assert _if.set_align(align_x=AlignX.CENTER) is _if
    assert _if.align_x == AlignX.CENTER
    assert _if.set_padding(3) is _if
    assert _if.padding.left == 3 and _if.padding.bottom == 3, \
        "set_padding(float) 应转成 Padding.all"
    assert _if.set_padding(Padding.left(6)) is _if
    assert _if.padding.left == 6 and _if.padding.top == 0
    print("    ✅ set_size / set_position / set_align / set_padding 通过")
    # 10.4 不变量：直接写私有字段会绕过尺寸方式解析（这是公开接口存在的理由）
    #      注意必须在**有父容器**时验证：游离对象没有约束可填，FILL 会退回声明值。
    _raw_root = LayoutObject(name="RAW_Root", width=100, height=300)
    _raw = LayoutObject(name="RAW_C", width=0, height=0, size_y=SizeY.FILL,
                        align_x=AlignX.NONE, align_y=AlignY.NONE)
    _raw_root.add_child(_raw)
    _raw_root.layout()
    assert _raw.get_effective_height() == 300, "FILL 应撑满父内容区"
    _raw._height = 42                      # 故意绕过 property
    assert _raw.size_y == SizeY.FILL, "直接写 _height 不应改变尺寸方式"
    assert _raw.get_effective_height() == 300, \
        "直接写 _height 后 FILL 仍覆盖它，有效高不应变成 42"
    _raw.height = 42                       # 走公开 property
    assert _raw.size_y == SizeY.FIXED, "写 height 应同步为 FIXED"
    assert _raw.get_effective_height() == 42
    print("    ✅ 「直接写私有字段会绕过尺寸方式」的不变量已固化")
    
    # 11) 内容固有宽度 / 收窄包围盒（批次 4b，修 7.21）
    print("  --- SizeX.CONTENT 收窄包围盒 ---")
    # 11.1 无固有宽度的子元素 -> 收窄到 padding；有 FIXED 子元素 -> 收窄到该宽度
    def _shrink(extra_w):
        _r = LayoutObject(name=f"SH_root_{extra_w}", width=200, height=300)
        _b = RectangleObject(name=f"SH_box_{extra_w}", width=0, height=20,
                             size_x=SizeX.CONTENT, align_x=AlignX.NONE, align_y=AlignY.NONE)
        _r.add_child(_b)
        _b.add_child(LayoutObject(name=f"SH_c0_{extra_w}", width=0, height=10,
                                  align_x=AlignX.NONE, align_y=AlignY.NONE))
        if extra_w:
            _b.add_child(LayoutObject(name=f"SH_c1_{extra_w}", width=extra_w, height=10,
                                      align_x=AlignX.NONE, align_y=AlignY.NONE))
        _r.layout()
        return _b.get_effective_width()
    assert _shrink(0) == 0.0, f"无固有宽度的子元素应使包围宽为 0，实际 {_shrink(0)}"
    assert _shrink(30) == 30.0, f"应收窄到 FIXED 子元素的 30，实际 {_shrink(30)}"
    print("    ✅ 收窄到内容固有宽通过（0 / 30，旧实现三条路径全返回 0）")
    # 11.2 文本固有宽度按字符类别估算
    _tw_latin = TextObject(name="TW_latin", width=0, height=0, text="Hello World", font_size=12)
    _tw_cjk = TextObject(name="TW_cjk", width=0, height=0, text="中文测试", font_size=12)
    assert _tw_latin._source_w(None) == 11 * 0.5 * 12, \
        f"11 个半角字符应为 66，实际 {_tw_latin._source_w(None)}"
    assert _tw_cjk._source_w(None) == 4 * 1.0 * 12, \
        f"4 个全角字符应为 48，实际 {_tw_cjk._source_w(None)}"
    assert TextObject(name="TW_e", width=0, height=0, text="")._source_w(None) == 0
    print("    ✅ 文本固有宽度估算通过（半角 0.5×、全角 1.0× 字号）")
    # 11.3 双向 CONTENT 包围文本：宽高都收窄到文本固有尺寸 + padding
    _bb_root = LayoutObject(name="BB_root", width=200, height=300)
    _bb = RectangleObject(name="BB_box", width=0, height=0, size_x=SizeX.CONTENT,
                          size_y=SizeY.CONTENT, padding=Padding.all(3),
                          align_x=AlignX.NONE, align_y=AlignY.NONE)
    _bb_root.add_child(_bb)
    _bb.add_child(TextObject(name="BB_t", width=0, height=0, text="中文测试", font_size=12,
                             align_x=AlignX.NONE, align_y=AlignY.NONE))
    _bb_root.layout()
    _bb_t = _bb.children[0]
    assert abs(_bb.get_effective_width() - (_bb_t._source_w(None) + 6)) < 1e-9, \
        f"包围宽应为 文本固有宽+6={_bb_t._source_w(None)+6}，实际 {_bb.get_effective_width()}"
    assert abs(_bb.get_effective_height() - (_bb_t._source_h(None) + 6)) < 1e-9, \
        f"包围高应为 文本固有高+6={_bb_t._source_h(None)+6}，实际 {_bb.get_effective_height()}"
    print(f"    ✅ 双向包围文本通过（{_bb.get_effective_width():.2f} x {_bb.get_effective_height():.2f}）")
    # 11.4 包围盒受祖辈约束夹紧 + 溢出标记
    _cl2_root = LayoutObject(name="CL2_root", width=30, height=300)
    _cl2 = RectangleObject(name="CL2_box", width=0, height=0, size_x=SizeX.CONTENT,
                           align_x=AlignX.NONE, align_y=AlignY.NONE)
    _cl2_root.add_child(_cl2)
    _cl2.add_child(TextObject(name="CL2_t", width=0, height=0, text="很长的一段中文文本内容",
                              font_size=12, align_x=AlignX.NONE, align_y=AlignY.NONE))
    _cl2_root.layout()
    assert _cl2.get_effective_width() == 30, \
        f"包围宽应被祖辈约束夹紧到 30，实际 {_cl2.get_effective_width()}"
    assert _cl2._content_overflows is True, "内容超出约束时应置 _content_overflows"
    print("    ✅ 包围盒受祖辈约束夹紧通过")
    # 11.5 FILL 子元素在 CONTENT 父下退化为按内容定尺寸（同安卓 wrap_content 语义）
    _dg_root = LayoutObject(name="DG_root", width=200, height=300)
    _dg = LayoutObject(name="DG_box", width=0, height=0, size_x=SizeX.CONTENT,
                       size_y=SizeY.CONTENT, align_x=AlignX.NONE, align_y=AlignY.NONE)
    _dg_root.add_child(_dg)
    _dg_t = TextObject(name="DG_t", width=0, height=0, text="退化规则", font_size=10,
                       align_x=AlignX.NONE, align_y=AlignY.NONE)
    _dg.add_child(_dg_t)
    _dg_root.layout()
    assert _dg_t._size_x == SizeX.FILL and _dg_t._size_y == SizeY.FILL, "前提：子元素默认 FILL"
    assert _dg_t.get_effective_width() > 0 and _dg_t.get_effective_height() > 0, \
        "CONTENT 父下的 FILL 子应退化为按内容定尺寸，不能被压成 0"
    print(f"    ✅ FILL 子退化规则通过（子 {_dg_t.get_effective_width():.2f} "
          f"x {_dg_t.get_effective_height():.2f}）")
    
    print("\n✅ 回归契约断言全部通过")
