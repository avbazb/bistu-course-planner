"""Populate the Artifact Tool-authored export template without extra runtime dependencies."""
from __future__ import annotations

import base64
import copy
import io
import math
import struct
import zipfile
import zlib
from xml.etree import ElementTree as ET
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DRAW = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
ET.register_namespace("x", MAIN)
ET.register_namespace("xdr", DRAW)
ET.register_namespace("a", "http://schemas.openxmlformats.org/drawingml/2006/main")
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")


def tag(name):
    return "{" + MAIN + "}" + name


def png_data(encoded):
    if not isinstance(encoded, str) or len(encoded) > 20_000_000:
        raise ValueError("课表图片无效或过大")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ValueError("课表图片编码无效") from None
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or len(raw) < 33:
        raise ValueError("仅支持 PNG 课表图片")
    offset, dimensions, has_data = 8, None, False
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(raw):
            break
        kind = raw[offset + 4:offset + 8]
        data = raw[offset + 8:end - 4]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != struct.unpack(">I", raw[end - 4:end])[0]:
            break
        if offset == 8:
            if kind != b"IHDR" or length != 13:
                break
            dimensions = struct.unpack(">II", data[:8])
            if not all(1 <= n <= 30000 for n in dimensions) or dimensions[0] * dimensions[1] > 90_000_000:
                raise ValueError("课表图片尺寸过大")
        elif kind == b"IHDR":
            break
        if kind == b"IDAT":
            has_data = True
        if kind == b"IEND":
            if length == 0 and end == len(raw) and dimensions and has_data:
                return raw, dimensions
            break
        offset = end
    raise ValueError("课表 PNG 文件不完整")


def detail_rows(catalog, assignments, days, slots):
    if not isinstance(assignments, dict) or set(assignments) != {course["id"] for course in catalog}:
        raise ValueError("导出方案与当前课程清单不一致，请刷新后重试")
    if sum(value == "self-study" for value in assignments.values()) > 2:
        raise ValueError("最多只能选择两门自主学习课程")
    rows = []
    for course in catalog:
        choice = assignments[course["id"]]
        if choice is not None and not isinstance(choice, str):
            raise ValueError("导出班次格式不正确")
        options = course["options"]
        index = next((i for i, option in enumerate(options) if option["id"] == choice), None)
        if choice == "self-study":
            option, status = {}, "自主学习"
        elif choice is None and not options:
            option, status = {}, "无课表记录"
        elif index is not None:
            option, status = options[index], "已排课"
        else:
            raise ValueError("导出班次不存在，请重新计算后重试")
        # 明细始终保留选中班级的所有上课记录，不能随单周预览而漏掉其他周。
        for event in option.get("events") or [{}]:
            start, end = event.get("start"), event.get("end")
            rows.append([
                course["code"], course["name"], option.get("class_number", ""),
                index + 1 if index is not None else None, option.get("teaching_class_id", ""),
                event.get("teacher") or option.get("teacher", ""),
                days[event["day"]] if "day" in event else "",
                start, end, slots[start - 1]["start"] if start else "",
                slots[end - 1]["end"] if end else "", event.get("weeks_text", ""),
                event.get("room", ""), option.get("capacity"), course["credits"], course["hours"],
                status, course.get("option_source", ""),
            ])
    return rows


def write_value(cell, value):
    for child in list(cell):
        cell.remove(child)
    cell.attrib.pop("t", None)
    if value is None:
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError("导出数值无效")
        ET.SubElement(cell, tag("v")).text = str(value)
    else:
        # inlineStr 保留前导零，并保证以 = 等字符开头的数据不会执行为公式。
        cell.set("t", "inlineStr")
        node = ET.SubElement(ET.SubElement(cell, tag("is")), tag("t"))
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = "".join(c for c in str(value) if ord(c) >= 32 or c in "\n\r\t")


def xml_bytes(node):
    return ET.tostring(node, encoding="utf-8", xml_declaration=True)


def set_dimension(sheet, reference):
    dimension = sheet.find(tag("dimension"))
    if dimension is None:
        dimension = ET.Element(tag("dimension"))
        sheet.insert(1 if sheet.find(tag("sheetPr")) is not None else 0, dimension)
    dimension.set("ref", reference)


def make_workbook(template_path, catalog, request, days, slots):
    if not isinstance(request, dict):
        raise ValueError("导出请求格式不正确")
    week = request.get("week", 0)
    max_week = max([17] + [week for course in catalog for option in course["options"] for event in option["events"] for week in event["weeks"]])
    if type(week) is not int or not 0 <= week <= max_week:
        raise ValueError("导出周次无效")
    rows = detail_rows(catalog, request.get("assignments"), days, slots)
    png, (width, height) = png_data(request.get("image"))
    with zipfile.ZipFile(template_path) as template:
        parts = {name: template.read(name) for name in template.namelist()}
    details = ET.fromstring(parts["xl/worksheets/sheet2.xml"])
    data = details.find(tag("sheetData"))
    sample = next(row for row in data if row.get("r") == "5")
    for row in list(data):
        if int(row.get("r")) >= 5:
            data.remove(row)
    for number, values in enumerate(rows, 5):
        row = copy.deepcopy(sample)
        row.set("r", str(number))
        # 教师/教室可能包含多个值，行高按现有列宽容纳文本。
        row.set("ht", str(max(48, max(sum(max(1, math.ceil(len(line) / limit)) for line in str(value or "").split("\n")) for value, limit in zip(values, [12,20,12,8,32,14,8,8,8,10,10,18,14,12,8,8,12,10,14,18])) * 16)))
        for index, (cell, value) in enumerate(zip(row, values)):
            cell.set("r", chr(65 + index) + str(number))
            write_value(cell, value)
        data.append(row)
    last = 4 + len(rows)
    set_dimension(details, "A1:R" + str(last))
    parts["xl/worksheets/sheet2.xml"] = xml_bytes(details)
    table = ET.fromstring(parts["xl/tables/table1.xml"])
    table.set("ref", "A4:R" + str(last))
    auto_filter = ET.Element(tag("autoFilter"), {"ref": table.get("ref")})
    table.insert(0, auto_filter)
    parts["xl/tables/table1.xml"] = xml_bytes(table)

    parts["xl/media/image.png"] = png
    drawing = ET.fromstring(parts["xl/drawings/drawing1.xml"])
    # 高分辨率 PNG 按 1/3 显示，保持图片导出与 Excel 第一页的比例一致。
    extent = drawing.find("{" + DRAW + "}oneCellAnchor/{" + DRAW + "}ext")
    extent.set("cx", str(round(width / 3 * 9525)))
    extent.set("cy", str(round(height / 3 * 9525)))
    drawing.find(".//{" + DRAW + "}cNvPr").set("name", "学期课表" if not week else f"第{week}周课表")
    parts["xl/drawings/drawing1.xml"] = xml_bytes(drawing)

    calendar = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    sheet_data = calendar.find(tag("sheetData"))
    last_image_row = max(1, math.ceil(height / 3 / 20))
    sample_row = next(iter(sheet_data))
    for row in list(sheet_data):
        sheet_data.remove(row)
    for index in range(1, last_image_row + 1):
        row = copy.deepcopy(sample_row)
        row.set("r", str(index))
        for cell in row:
            cell.set("r", "".join(c for c in cell.get("r") if c.isalpha()) + str(index))
        sheet_data.append(row)
    set_dimension(calendar, f"A1:R{last_image_row}")
    for column in calendar.find(tag("cols")):
        # 模板为 18 个等宽辅助列，只承担图片边界和打印范围，不限制课表的星期列。
        column.set("width", str((width / 3 / 18 - 5) / 7))
    calendar.find(tag("sheetViews") + "/" + tag("sheetView")).set("zoomScale", "60")
    properties = calendar.find(tag("sheetPr"))
    if properties is None:
        properties = ET.Element(tag("sheetPr"))
        calendar.insert(0, properties)
    ET.SubElement(properties, tag("pageSetUpPr"), {"fitToPage": "1"})
    margins = calendar.find(tag("pageMargins"))
    if margins is None:
        margins = ET.SubElement(calendar, tag("pageMargins"))
    margins.attrib.update({"left":"0.2","right":"0.2","top":"0.2","bottom":"0.2","header":"0","footer":"0"})
    ET.SubElement(calendar, tag("pageSetup"), {"paperSize":"8","orientation":"portrait","fitToWidth":"1","fitToHeight":"1"})
    # 页边距和打印设置必须在 drawing 之前，满足 SpreadsheetML 元素顺序。
    image_ref = calendar.find(tag("drawing"))
    calendar.remove(image_ref)
    calendar.append(image_ref)
    parts["xl/worksheets/sheet1.xml"] = xml_bytes(calendar)
    workbook = ET.fromstring(parts["xl/workbook.xml"])
    names = workbook.find(tag("definedNames"))
    if names is None:
        names = ET.Element(tag("definedNames"))
        workbook.insert(list(workbook).index(workbook.find(tag("sheets"))) + 1, names)
    ET.SubElement(names, tag("definedName"), {"name":"_xlnm.Print_Area","localSheetId":"0"}).text = "'可视化课表'!$A$1:$R$" + str(last_image_row)
    parts["xl/workbook.xml"] = xml_bytes(workbook)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    return output.getvalue()
