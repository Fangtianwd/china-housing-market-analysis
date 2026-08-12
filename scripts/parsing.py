# -*- coding: utf-8 -*-
"""
parsing.py - 统计局公告页解析的共享基础层

fetch_data.py（按城市查询）与 validate_full_data.py（全量校验）
共用这里的表格定位、前置文本收集与行提取逻辑，避免双解析器分叉。
"""
import html as html_mod
from typing import List


def normalize(s: str) -> str:
    """规范化字符串：解码 HTML 实体，统一全角/空白。"""
    s = html_mod.unescape(str(s))
    s = s.replace(" ", " ").replace("　", " ")
    s = s.replace("\t", " ").replace("\n", " ").replace("\r", " ")
    return " ".join(s.split())


def compact(s: str) -> str:
    """移除所有空白。"""
    return "".join(normalize(s).split())


def extract_row(tr) -> List[str]:
    """提取表格行文本（跳过空单元格）。"""
    return [normalize(cell.get_text()) for cell in tr.find_all(["th", "td"]) if normalize(cell.get_text())]


def looks_like_header(cells: List[str]) -> bool:
    """判断是否为表头行。"""
    for cell in cells:
        value = normalize(cell)
        if any(keyword in value for keyword in ("城市", "环比", "同比", "定基")):
            return True
    return False


def find_header(table) -> List[str]:
    """查找表头行。"""
    for tr in table.find_all("tr"):
        row = extract_row(tr)
        if row and looks_like_header(row):
            return row
    return []


def find_content_tables(soup):
    """按选择器降级链定位正文表格。"""
    tables = soup.select(".detail-text-content .txt-content .trs_editor_view table")
    if not tables:
        tables = soup.select(".trs_editor_view table")
    if not tables:
        tables = soup.find_all("table")
    return tables


def collect_preceding_text(table, levels: int = 4) -> List[str]:
    """收集表格前若干层兄弟节点的文本（用于识别表名）。"""
    preceding: List[str] = []
    node = table
    for _ in range(levels):
        count = 0
        for sibling in node.find_previous_siblings():
            text = normalize(sibling.get_text())
            if text:
                preceding.insert(0, text)
                count += 1
                if count >= levels:
                    break
        node = node.parent
        if node is None:
            break
    return preceding
