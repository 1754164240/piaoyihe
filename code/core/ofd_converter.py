#!/usr/bin/env python3
"""
OFD 文件转换模块

该模块负责将 OFD 发票文件渲染为图片，供合并、预览等功能复用。
转换通过第三方库 ofd2pdf（内部调用 ofd-cli 可执行文件）完成，不解析 OFD 内部字段。
渲染结果按文件指纹缓存到系统临时目录，避免合并预览等高频调用重复渲染。
"""

import hashlib
import os
import re
import shutil
import tempfile
from typing import List, Optional

# 支持的 OFD 文件扩展名
OFD_EXTENSIONS = {'.ofd'}

# 渲染分辨率（DPI），发票类文档使用 200 以保证清晰度
DEFAULT_DPI = 200

# 渲染结果文件名形如 <prefix>_doc1_page1.png
_PAGE_RE = re.compile(r"_doc(\d+)_page(\d+)\.(?:png|jpg|jpeg|bmp|tiff|webp)$", re.IGNORECASE)


class OfdConversionError(RuntimeError):
    """OFD 渲染失败时抛出的异常"""


def is_ofd_file(file_path: str) -> bool:
    """
    判断文件是否为 OFD 文件

    功能描述:
        根据文件扩展名判断是否为 OFD 文件（不区分大小写），
        空值或非字符串输入返回 False。

    参数:
        file_path: 文件路径

    返回值:
        bool: 是 OFD 文件返回 True，否则返回 False
    """
    if not isinstance(file_path, str) or not file_path:
        return False
    return os.path.splitext(file_path)[1].lower() in OFD_EXTENSIONS


def _cache_key(ofd_path: str) -> str:
    """
    根据 OFD 文件路径、修改时间和大小生成缓存键

    功能描述:
        将文件绝对路径、修改时间纳秒值与文件大小拼接后做 SHA1，
        用于标识文件内容版本，文件变化时缓存键随之改变。

    参数:
        ofd_path: OFD 文件路径

    返回值:
        str: 缓存键（SHA1 十六进制字符串）
    """
    stat = os.stat(ofd_path)
    raw = f"{os.path.abspath(ofd_path)}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


def _list_rendered_pages(cache_dir: str) -> List[str]:
    """
    列出缓存目录中已渲染的页面图片，按文档号、页码升序排列

    参数:
        cache_dir: 缓存目录

    返回值:
        List[str]: 已渲染页面图片的绝对路径列表，无结果返回空列表
    """
    if not os.path.isdir(cache_dir):
        return []

    pages = []
    for name in os.listdir(cache_dir):
        match = _PAGE_RE.search(name)
        if not match:
            continue
        pages.append((
            int(match.group(1)),
            int(match.group(2)),
            os.path.join(cache_dir, name)
        ))

    pages.sort(key=lambda item: (item[0], item[1]))
    return [path for _, _, path in pages]


def render_ofd_pages(ofd_path: str, dpi: float = DEFAULT_DPI,
                     cache_root: Optional[str] = None) -> List[str]:
    """
    将 OFD 文件渲染为图片列表（带本地缓存）

    功能描述:
        调用 ofd2pdf 的 render_ofd 将 OFD 每页渲染为 PNG 图片。
        渲染结果缓存到 cache_root/<文件指纹> 目录；命中缓存时直接返回，
        避免合并预览等高频调用重复触发渲染。文件变化（修改时间/大小改变）会重新渲染。

    参数:
        ofd_path: OFD 文件路径
        dpi: 渲染分辨率，默认 200
        cache_root: 缓存根目录，默认使用系统临时目录下的 piaoyihe_ofd_cache

    返回值:
        List[str]: 按页序排列的图片路径列表

    异常:
        OfdConversionError: 文件不存在、ofd2pdf 未安装或渲染失败时抛出
    """
    if not os.path.isfile(ofd_path):
        raise OfdConversionError(f"OFD 文件不存在: {ofd_path}")

    try:
        from ofd2pdf import render_ofd
    except ImportError as exc:
        raise OfdConversionError("未安装 ofd2pdf，无法处理 OFD 文件") from exc

    if cache_root is None:
        cache_root = os.path.join(tempfile.gettempdir(), "piaoyihe_ofd_cache")

    cache_dir = os.path.join(cache_root, _cache_key(ofd_path))

    cached = _list_rendered_pages(cache_dir)
    if cached:
        return cached

    # 无有效缓存：清理可能残留的半成品后重新渲染
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)
    os.makedirs(cache_dir, exist_ok=True)

    try:
        pages = render_ofd(ofd_path, cache_dir, dpi=dpi, image_format="png", prefix="page")
    except Exception as exc:
        shutil.rmtree(cache_dir, ignore_errors=True)
        raise OfdConversionError(f"OFD 渲染失败: {exc}") from exc

    result = [str(p) for p in pages]
    if not result:
        shutil.rmtree(cache_dir, ignore_errors=True)
        raise OfdConversionError("OFD 未渲染出任何页面")
    return result