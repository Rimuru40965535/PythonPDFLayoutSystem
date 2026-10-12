"""
================================================================================
PDF 排版引擎 - 完整实现 (缓存优化版)
================================================================================
功能概述：
    1. 基于矩形区域的布局管理
    2. 支持父子层级、内边距 (padding)
    3. 支持水平/垂直对齐 (居中、靠左、靠右、靠上、靠下)
    4. 支持流式布局 (紧挨上一个子元素放置)
    5. 支持分栏布局 (等宽、指定宽度、按比例)
    6. 自动尺寸约束（子元素不超出父元素内容区域）
    7. 流式布局自动截断（超出父元素可用空间的子元素会被裁剪）
    8. 内容渲染：文本、图像、矩形
    9. 图层管理：按图层索引组织和渲染对象
    10. 调试渲染模式（显示边框、名称、尺寸）
    11. 对象注册表（按名称查找）
    12. wrap_content 支持（高度由内容决定）
    13. 几何缓存（消除递归渲染的指数级复杂度）

修复记录：
    - 修复 wrap_content 循环依赖问题
    - 拆分公共逻辑到 _calculate_wrap_height()
    - 添加缓存失效机制
    - 添加几何缓存（_geom_cache），将渲染从 O(4^d) 降到 O(n)

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
# 1. 对齐方式枚举
# ============================================================================

class AlignX(Enum):
    """水平对齐方式枚举"""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    NONE = "none"


class AlignY(Enum):
    """垂直对齐方式枚举"""
    TOP = "top"
    VCENTER = "vcenter"
    BOTTOM = "bottom"
    NONE = "none"
    FLOW = "flow"


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
        padding 的默认值是 Padding.all(0) 这一**可变对象**（缺陷 7.10）。
        这是从模板层原样搬运过来的既有行为，本批次刻意不做修正，
        以免破坏"纯搬运、输出不变"的验收前提。修正归入批次 4 的可变默认值审计。
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
        padding: Padding = Padding.all(0),
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
            padding: 内边距
            fit_mode: 图片适配模式 (仅用于 ImageObject)
        """
        self.font_name = font_name
        self.font_size = font_size
        self.bold = bold
        self.italic = italic
        self.color = color
        self.fill_color = fill_color
        self.image_path = image_path
        self.padding = padding
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
                 wrap_width: bool = False,
                 wrap_height: bool = False):
        # 基本属性
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
        if padding is None:
            self.padding = Padding()
        elif isinstance(padding, (int, float)):
            self.padding = Padding.all(float(padding))
        else:
            self.padding = padding
        
        # 对齐方式
        self.align_x = align_x
        self.align_y = align_y
        
        # 图层支持
        self._layer = layer
        layer_manager.add_object(self, layer)
        
        # ---- wrap_content 相关属性 ----
        self._wrap_width = wrap_width
        self._wrap_height = wrap_height
        self._wrap_cache_valid = False
        self._cached_wrap_width = 0.0
        self._cached_wrap_height = 0.0
        self._is_wrapping = False
        self._height_set_by_wrap = False
        self._width_set_by_wrap = False
        
        # ---- 【新增】几何缓存 ----
        # 缓存四个几何计算的返回值，避免重复递归计算
        self._geom_cache_valid = False          # 缓存是否有效
        self._cached_abs_x = None               # get_absolute_x 的缓存
        self._cached_abs_y = None               # get_absolute_y 的缓存
        self._cached_eff_w = None               # get_effective_width 的缓存
        self._cached_eff_h = None               # get_effective_height 的缓存
        
        # 自动注册到全局注册表
        if name:
            objectRegister[name] = self
    
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
        使几何缓存失效（递归向上传播到父元素）
        
        当以下情况发生时应调用此方法：
            1. 子元素被添加或移除
            2. 自身尺寸、对齐方式、内边距被修改
            3. 子元素的几何发生变化
        """
        if not self._geom_cache_valid and self._cached_abs_x is None:
            # 快速路径：如果自身缓存已经无效，可能父元素也无效
            # 但仍然需要向上传播（因为父元素可能还有效）
            pass
        
        self._geom_cache_valid = False
        self._cached_abs_x = None
        self._cached_abs_y = None
        self._cached_eff_w = None
        self._cached_eff_h = None
        
        # 向上传播到父元素
        if self.parent is not None and hasattr(self.parent, 'invalidate_geom_cache'):
            self.parent.invalidate_geom_cache()
    
    def invalidate_geom_cache_subtree(self) -> None:
        """
        使自身及所有子树的几何缓存失效（向下传播）
        
        当父元素的尺寸或位置发生变化时，需要让所有子元素失效。
        与 invalidate_geom_cache() 不同，此方法只向下传播，不向上传播。
        """
        self._geom_cache_valid = False
        self._cached_abs_x = None
        self._cached_abs_y = None
        self._cached_eff_w = None
        self._cached_eff_h = None
        
        for child in self.children:
            child.invalidate_geom_cache_subtree()
    
    # ------------------------------------------------------------------------
    # 6.3 wrap_content 相关方法
    # ------------------------------------------------------------------------
    
    def _calculate_wrap_height(self) -> float:
        """内部方法：计算 wrap_content 高度"""
        if self._is_wrapping:
            return self._height
        
        if self._height > 0:
            self._cached_wrap_height = self._height
            self._wrap_cache_valid = True
            return self._height
        
        self._is_wrapping = True
        
        try:
            total_height = 0.0
            flow_children = self.get_flow_children()
            
            if not flow_children:
                total_height = self.padding.top + self.padding.bottom
            else:
                for child in flow_children:
                    if child._wrap_height:
                        child_height = child._calculate_wrap_height()
                    else:
                        child_height = child.get_effective_height()
                    total_height += child_height
            
            total_height += self.padding.top + self.padding.bottom
            
            if self.parent:
                _, avail_y, _, avail_h = self.get_parent_available_area()
                if total_height > avail_h:
                    self._flow_clipped = True
                    total_height = avail_h
                else:
                    self._flow_clipped = False
            
            self._height = total_height
            self._height_set_by_wrap = True
            self._cached_wrap_height = total_height
            self._wrap_cache_valid = True
            
            return total_height
        finally:
            self._is_wrapping = False
    
    def _calculate_wrap_width(self) -> float:
        """内部方法：计算 wrap_content 宽度"""
        if self._is_wrapping:
            return self._width
        
        if self._width > 0:
            self._cached_wrap_width = self._width
            self._wrap_cache_valid = True
            return self._width
        
        self._is_wrapping = True
        
        try:
            max_width = 0.0
            for child in self.children:
                if child._wrap_width:
                    child_width = child._calculate_wrap_width()
                else:
                    child_width = child.get_effective_width()
                if child_width > max_width:
                    max_width = child_width
            
            total_width = max_width + self.padding.left + self.padding.right
            
            if self.parent:
                _, _, avail_w, _ = self.get_parent_available_area()
                if total_width > avail_w:
                    total_width = avail_w
            
            self._width = total_width
            self._width_set_by_wrap = True
            self._cached_wrap_width = total_width
            self._wrap_cache_valid = True
            
            return total_width
        finally:
            self._is_wrapping = False
    
    def wrap_content(self, force: bool = False) -> float:
        """计算并设置 wrap_content 高度"""
        if self._is_wrapping:
            raise RuntimeError(f"检测到循环依赖: {self.name} 正在 wrap_content 计算中")
        
        if not force and self._wrap_cache_valid and self._height_set_by_wrap:
            return self._cached_wrap_height
        
        if self._height > 0:
            self._cached_wrap_height = self._height
            self._wrap_cache_valid = True
            return self._height
        
        result = self._calculate_wrap_height()
        # 尺寸变化后，几何缓存失效
        self.invalidate_geom_cache()
        return result
    
    def wrap_content_width(self, force: bool = False) -> float:
        """计算并设置 wrap_content 宽度"""
        if self._is_wrapping:
            raise RuntimeError(f"检测到循环依赖: {self.name} 正在 wrap_content 计算中")
        
        if not force and self._wrap_cache_valid and self._width_set_by_wrap:
            return self._cached_wrap_width
        
        if self._width > 0:
            self._cached_wrap_width = self._width
            self._wrap_cache_valid = True
            return self._width
        
        result = self._calculate_wrap_width()
        self.invalidate_geom_cache()
        return result
    
    def invalidate_wrap_cache(self) -> None:
        """使 wrap_content 缓存失效（向上传播）"""
        self._wrap_cache_valid = False
        self._height_set_by_wrap = False
        self._width_set_by_wrap = False
        
        if self.parent and hasattr(self.parent, 'invalidate_wrap_cache'):
            self.parent.invalidate_wrap_cache()
    
    def is_wrapped(self) -> bool:
        return self._wrap_height or self._wrap_width
    
    def is_height_wrapped(self) -> bool:
        return self._wrap_height
    
    def is_width_wrapped(self) -> bool:
        return self._wrap_width
    
    def get_wrap_status(self) -> Dict[str, Any]:
        return {
            "wrap_width": self._wrap_width,
            "wrap_height": self._wrap_height,
            "cache_valid": self._wrap_cache_valid,
            "height_set_by_wrap": self._height_set_by_wrap,
            "width_set_by_wrap": self._width_set_by_wrap,
            "cached_width": self._cached_wrap_width,
            "cached_height": self._cached_wrap_height,
        }
    
    # ------------------------------------------------------------------------
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
    # 6.5 布局计算（核心） - 已添加几何缓存
    # ------------------------------------------------------------------------
    
    def get_parent_available_area(self) -> Tuple[float, float, float, float]:
        """获取父元素的可用空间（绝对坐标）"""
        if self.parent is None:
            return (self._x, self._y, self._width, self._height)
        
        # 通过缓存的方法获取父元素的几何信息（内部已缓存）
        parent_abs_x = self.parent.get_absolute_x()
        parent_abs_y = self.parent.get_absolute_y()
        parent_eff_w = self.parent.get_effective_width()
        parent_eff_h = self.parent.get_effective_height()
        
        available_x = parent_abs_x + self.parent.padding.left
        available_y = parent_abs_y + self.parent.padding.top
        available_w = parent_eff_w - self.parent.padding.left - self.parent.padding.right
        available_h = parent_eff_h - self.parent.padding.top - self.parent.padding.bottom
        
        return (available_x, available_y, available_w, available_h)
    
    def get_absolute_x(self) -> float:
        """
        获取对象的绝对 X 坐标（带缓存）
        
        对齐规则：
            - CENTER: 在父元素可用空间中水平居中
            - RIGHT: 靠父元素可用空间右边界
            - LEFT: 靠父元素可用空间左边界
            - NONE: 使用构造时的 _x 值
        """
        # ---- 【新增】缓存命中检查 ----
        if self._geom_cache_valid and self._cached_abs_x is not None:
            return self._cached_abs_x
        
        # ---- 原逻辑 ----
        if self.parent is None:
            result = self._x
        else:
            avail_x, _, avail_w, _ = self.get_parent_available_area()
            effective_width = self.get_effective_width()
            
            if self.align_x == AlignX.CENTER:
                result = avail_x + (avail_w - effective_width) / 2
            elif self.align_x == AlignX.RIGHT:
                result = avail_x + avail_w - effective_width
            elif self.align_x == AlignX.LEFT:
                result = avail_x
            else:  # NONE
                result = avail_x + self._x
        
        # ---- 【新增】写入缓存 ----
        self._cached_abs_x = result
        # 注意：不在这里设置 _geom_cache_valid，由 get_effective_width 统一管理
        return result
    
    def get_absolute_y(self) -> float:
        """
        获取对象的绝对 Y 坐标（带缓存）
        
        对齐规则：
            - VCENTER: 在父元素可用空间中垂直居中
            - BOTTOM: 靠父元素可用空间下边界
            - TOP: 靠父元素可用空间上边界
            - FLOW: 紧挨上一个 FLOW 子元素放置
            - NONE: 使用构造时的 _y 值
        """
        # ---- 【新增】缓存命中检查 ----
        if self._geom_cache_valid and self._cached_abs_y is not None:
            return self._cached_abs_y
        
        # ---- 原逻辑 ----
        if self.parent is None:
            result = self._y
        else:
            _, avail_y, _, avail_h = self.get_parent_available_area()
            effective_height = self.get_effective_height()
            
            if self.align_y == AlignY.FLOW:
                prev_flow = self.get_previous_flow_sibling()
                if prev_flow is None:
                    result = avail_y
                else:
                    prev_abs_y = prev_flow.get_absolute_y()
                    prev_eff_h = prev_flow.get_effective_height()
                    result = prev_abs_y + prev_eff_h
            elif self.align_y == AlignY.VCENTER:
                result = avail_y + (avail_h - effective_height) / 2
            elif self.align_y == AlignY.BOTTOM:
                result = avail_y + avail_h - effective_height
            elif self.align_y == AlignY.TOP:
                result = avail_y
            else:  # NONE
                result = avail_y + self._y
        
        # ---- 【新增】写入缓存 ----
        self._cached_abs_y = result
        return result
    
    def get_effective_width(self) -> float:
        """计算对象的有效宽度（带缓存）"""
        # ---- 【新增】缓存命中检查 ----
        if self._geom_cache_valid and self._cached_eff_w is not None:
            return self._cached_eff_w
        
        # ---- 原逻辑 ----
        # wrap_content 支持
        if self._wrap_width:
            if self._wrap_cache_valid and self._width_set_by_wrap:
                result = self._cached_wrap_width
            else:
                result = self._calculate_wrap_width()
        elif self.parent is None:
            result = self._width
        else:
            _, _, avail_w, _ = self.get_parent_available_area()
            if self._width <= 0:
                result = avail_w
            else:
                result = min(self._width, avail_w)
        
        # ---- 【新增】写入缓存 ----
        self._cached_eff_w = result
        return result
    
    def get_effective_height(self) -> float:
        """计算对象的有效高度（带缓存）"""
        # ---- 【新增】缓存命中检查 ----
        if self._geom_cache_valid and self._cached_eff_h is not None:
            return self._cached_eff_h
        
        # ---- 原逻辑 ----
        # wrap_content 支持
        if self._wrap_height:
            if self._wrap_cache_valid and self._height_set_by_wrap:
                result = self._cached_wrap_height
            else:
                result = self._calculate_wrap_height()
        elif self.parent is None:
            result = self._height
        else:
            _, avail_y, _, avail_h = self.get_parent_available_area()
            
            base_height = self._height if self._height > 0 else avail_h
            constrained_height = min(base_height, avail_h)
            
            # FLOW 模式额外检查
            if self.align_y == AlignY.FLOW:
                prev_flow = self.get_previous_flow_sibling()
                
                if prev_flow is None:
                    top_y = avail_y
                else:
                    prev_abs_y = prev_flow.get_absolute_y()
                    prev_eff_h = prev_flow.get_effective_height()
                    top_y = prev_abs_y + prev_eff_h
                
                remaining_height = (avail_y + avail_h) - top_y
                
                if remaining_height <= 0:
                    self._flow_clipped = True
                    result = 0.0
                else:
                    final_height = min(constrained_height, remaining_height)
                    self._flow_clipped = final_height < self._height if self._height > 0 else False
                    result = final_height
            else:
                result = constrained_height
        
        # ---- 【新增】写入缓存并标记缓存有效 ----
        self._cached_eff_h = result
        # 四个缓存都已写入，标记缓存有效
        self._geom_cache_valid = True
        return result
    
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
            "wrap": {
                "width": self._wrap_width,
                "height": self._wrap_height,
                "height_set_by_wrap": self._height_set_by_wrap,
                "width_set_by_wrap": self._width_set_by_wrap
            },
            "geom_cache_valid": self._geom_cache_valid,
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
        if self._wrap_height:
            name += " [H↕]"
        if self._wrap_width:
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
        wrap_marker = ""
        if self._wrap_height:
            wrap_marker += ", wrap_h"
        if self._wrap_width:
            wrap_marker += ", wrap_w"
        return f"LayoutObject(name='{self.name}', layer={self._layer}, size=({self._width}x{self._height}){wrap_marker})"

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
        wrap_width: bool = False,
        wrap_height: bool = False,
    ):
        super().__init__(
            name=name, x=x, y=y, width=width, height=height,
            color=color, parent=parent, padding=padding,
            align_x=align_x, align_y=align_y, layer=layer,
            wrap_width=wrap_width, wrap_height=wrap_height
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
        parent / layer / wrap_width / wrap_height 等）通过 overrides 传入。

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
    
    def _calculate_wrap_height(self) -> float:
        if self._is_wrapping:
            return self._height
        
        if self._height > 0:
            self._cached_wrap_height = self._height
            self._wrap_cache_valid = True
            return self._height
        
        self._is_wrapping = True
        
        try:
            if self.children:
                total_height = 0.0
                for child in self.get_flow_children():
                    if child._wrap_height:
                        child_height = child._calculate_wrap_height()
                    else:
                        child_height = child.get_effective_height()
                    total_height += child_height
                total_height += self.padding.top + self.padding.bottom
            else:
                text_height = self.font_size * 0.6
                if self.multi_line and self._text:
                    approx_lines = max(1, len(self._text) // 20 + 1)
                    text_height = approx_lines * (self._line_height or self.font_size * 0.6)
                total_height = text_height + self.padding.top + self.padding.bottom
            
            if self.parent:
                _, avail_y, _, avail_h = self.get_parent_available_area()
                if total_height > avail_h:
                    self._flow_clipped = True
                    total_height = avail_h
                else:
                    self._flow_clipped = False
            
            self._height = total_height
            self._height_set_by_wrap = True
            self._cached_wrap_height = total_height
            self._wrap_cache_valid = True
            
            return total_height
        finally:
            self._is_wrapping = False
    
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
        wrap_width: bool = False,
        wrap_height: bool = False,
    ):
        super().__init__(
            name=name, x=x, y=y, width=width, height=height,
            color=color, parent=parent, padding=padding,
            align_x=align_x, align_y=align_y, layer=layer,
            wrap_width=wrap_width, wrap_height=wrap_height
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
    
    def _calculate_wrap_height(self) -> float:
        if self._is_wrapping:
            return self._height
        
        if self._height > 0:
            self._cached_wrap_height = self._height
            self._wrap_cache_valid = True
            return self._height
        
        self._is_wrapping = True
        
        try:
            if self.children:
                total_height = 0.0
                for child in self.get_flow_children():
                    if child._wrap_height:
                        child_height = child._calculate_wrap_height()
                    else:
                        child_height = child.get_effective_height()
                    total_height += child_height
                total_height += self.padding.top + self.padding.bottom
            else:
                if self._width > 0 and self._image_path and os.path.exists(self._image_path):
                    try:
                        from fpdf import FPDF
                        pdf = FPDF()
                        info = pdf.image_info(self._image_path)
                        aspect_ratio = info['w'] / info['h']
                        total_height = self._width / aspect_ratio + self.padding.top + self.padding.bottom
                    except:
                        total_height = self._width + self.padding.top + self.padding.bottom
                else:
                    total_height = self.padding.top + self.padding.bottom
            
            if self.parent:
                _, avail_y, _, avail_h = self.get_parent_available_area()
                if total_height > avail_h:
                    self._flow_clipped = True
                    total_height = avail_h
                else:
                    self._flow_clipped = False
            
            self._height = total_height
            self._height_set_by_wrap = True
            self._cached_wrap_height = total_height
            self._wrap_cache_valid = True
            
            return total_height
        finally:
            self._is_wrapping = False
    
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
        wrap_width: bool = False,
        wrap_height: bool = False,
    ):
        super().__init__(
            name=name, x=x, y=y, width=width, height=height,
            color=color, parent=parent, padding=padding,
            align_x=align_x, align_y=align_y, layer=layer,
            wrap_width=wrap_width, wrap_height=wrap_height
        )
    
    def _calculate_wrap_height(self) -> float:
        if self._is_wrapping:
            return self._height
        
        if self._height > 0:
            self._cached_wrap_height = self._height
            self._wrap_cache_valid = True
            return self._height
        
        self._is_wrapping = True
        
        try:
            if self.children:
                total_height = 0.0
                for child in self.get_flow_children():
                    if child._wrap_height:
                        child_height = child._calculate_wrap_height()
                    else:
                        child_height = child.get_effective_height()
                    total_height += child_height
                total_height += self.padding.top + self.padding.bottom
            else:
                total_height = self.padding.top + self.padding.bottom
            
            if self.parent:
                _, avail_y, _, avail_h = self.get_parent_available_area()
                if total_height > avail_h:
                    self._flow_clipped = True
                    total_height = avail_h
                else:
                    self._flow_clipped = False
            
            self._height = total_height
            self._height_set_by_wrap = True
            self._cached_wrap_height = total_height
            self._wrap_cache_valid = True
            
            return total_height
        finally:
            self._is_wrapping = False
    
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
            # 已构造对象：保留其自身宽度，只接管位置与高度
            obj = cell
            obj._height = band_height

        obj.align_x = AlignX.NONE
        obj.align_y = AlignY.NONE
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
    total_ratio = sum(ratio)
    total_width = content_w - gap
    left_obj._width = total_width * (ratio[0] / total_ratio)
    right_obj._width = total_width * (ratio[1] / total_ratio)

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
    
    print("\n✅ 回归契约断言全部通过")
