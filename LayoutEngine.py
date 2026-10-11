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
        """调试渲染：绘制矩形边框、填充颜色、显示对象名称和尺寸"""
        print(f"  >>> 正在渲染PDF文件。现在渲染LayoutObject节点：{self.name}")

        if pdf is None:
            return
    
        if len(pdf.pages) == 0:
            pdf.add_page()
    
        abs_x = self.get_absolute_x()
        abs_y = self.get_absolute_y()
        eff_w = self.get_effective_width()
        eff_h = self.get_effective_height()
    
        if eff_w <= 0 or eff_h <= 0:
            return
    
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
                child.render_debug(pdf, is_fill, has_border, show_name, show_bounds,
                                 name_offset_y, bounds_offset_y)
    
        finally:
            pdf.set_auto_page_break(auto=auto_page_break)
            print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")

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
        """调试渲染，名称后追加 ':text'"""
        print(f"  >>> 正在渲染PDF文件。现在渲染TextObject节点：{self.name}")

        if pdf is None:
            return
    
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

        for child in self.children:
            child.render_debug(pdf, is_fill, has_border, show_name, show_bounds,
                                 name_offset_y, bounds_offset_y)
        
        print(f"  >>> 正在渲染PDF文件。节点渲染完成：{self.name}")


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
        """调试渲染，名称后追加 ':image'"""
        print(f"  >>> 正在渲染PDF文件。现在渲染ImageObject节点：{self.name}")
        
        if pdf is None:
            return
    
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
        """调试渲染，名称后追加 ':rect'"""
        print(f"  >>> 正在渲染PDF文件。现在渲染RectangleObject节点：{self.name}")

        if pdf is None:
            return
    
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


# ============================================================================
# 10. 分栏功能
# ============================================================================

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
    """在父对象中创建分栏"""
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
    
    parent.children = []
    
    _, content_y, _, _ = parent_content
    cumulative_width = 0
    
    for i in range(num_columns):
        col_x = cumulative_width + gap * i
        col_w = widths[i]
        
        col = LayoutObject(
            name=col_names[i],
            x=col_x,
            y=0,
            width=col_w,
            height=content_h,
            color=col_colors[i],
            parent=parent,
            padding=col_padding,
            align_x=AlignX.NONE,
            align_y=AlignY.NONE,
            layer=layer,
        )
        parent.add_child(col)
        cumulative_width += col_w
    
    return parent


def create_columns_balanced(
    parent: LayoutObject,
    num_columns: int = 2,
    gap: float = 5,
    padding: Optional[Union[Padding, float]] = None,
    layer: int = 0,
) -> LayoutObject:
    """创建等宽分栏"""
    return create_columns(
        parent=parent,
        num_columns=num_columns,
        gap=gap,
        padding=padding,
        layer=layer,
    )


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
    
    col0 = container.get_child("Column_0")
    col1 = container.get_child("Column_1")
    
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
    
    # 2) render() 的返回值契约不统一（LayoutObject/TextObject 返回 float，
    #    ImageObject/RectangleObject 返回 tuple）。此处只锁定 LayoutObject.render 的行为。
    #    注意：本测试的 Root 最后一个子节点是 Container，最终向上冒泡的即为 LayoutObject.render 的值。
    assert isinstance(render_ret, float), \
        f"LayoutObject.render() 应返回 float（最后渲染到的 y），实际返回 {type(render_ret).__name__}"
    print(f"  ✅ LayoutObject.render() 返回 float 契约通过（{render_ret:.2f}）")
    
    # 3) create_columns 当前会清空父元素既有子元素（LayoutEngine.py:1822），
    #    属于已知缺陷（技术文档 7.4）。此处固化现状，防止在无意识的情况下改变行为；
    #    批次 2 修复该缺陷时，本断言应同步改为"既有子元素被保留"。
    _probe_parent = LayoutObject(name="ProbeParent", width=100, height=50)
    _kept = TextObject(name="ProbeKept", text="x", font_size=10)
    _probe_parent.add_child(_kept)
    assert _probe_parent.children == [_kept], "add_child 后应保留子元素"
    create_columns(parent=_probe_parent, num_columns=2, gap=0)
    assert _kept not in _probe_parent.children, \
        "已知缺陷 7.4 现状：create_columns 会丢弃父元素既有子元素"
    print("  ✅ create_columns 清空父元素的现状已固化（技术文档 7.4）")
    
    print("\n✅ 回归契约断言全部通过")
