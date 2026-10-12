# -*- coding: utf-8 -*-
"""Интерактивный генератор деревянного поддона для SolidWorks.

Создаёт две уникальные детали-бруса и сборку из экземпляров этих деталей.
Размеры вводятся в миллиметрах; SolidWorks API использует метры.
"""

from pathlib import Path
import ctypes
from ctypes import wintypes
import traceback

import clr
import pythoncom
import win32com.client
from System import Convert


# ============================================================
# НАСТРОЙКИ
# ============================================================

SW_API_DIR = Path(r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist")
SLDWORKS_DLL = SW_API_DIR / "SolidWorks.Interop.sldworks.dll"
SWCONST_DLL = SW_API_DIR / "SolidWorks.Interop.swconst.dll"

# При необходимости замените пути на шаблоны вашей организации.
PART_TEMPLATE = Path(r"D:\KTO-PDM\!SW_Stuff\Templates\Деталь.prtdot")
ASSEMBLY_TEMPLATE = Path(r"D:\KTO-PDM\!SW_Stuff\Templates\Сборка.asmdot")
BASE_PLANE_NAME = "Спереди"
OUTPUT_FOLDER_NAME = "SolidWorks_Pallet"


if not SLDWORKS_DLL.exists():
    raise FileNotFoundError(f"Не найдена DLL SolidWorks:\n{SLDWORKS_DLL}")
if not SWCONST_DLL.exists():
    raise FileNotFoundError(f"Не найдена DLL констант SolidWorks:\n{SWCONST_DLL}")

clr.AddReference(str(SLDWORKS_DLL))
clr.AddReference(str(SWCONST_DLL))

from SolidWorks.Interop.sldworks import SldWorks
from SolidWorks.Interop.swconst import (
    swEndConditions_e,
    swSaveAsOptions_e,
    swSaveAsVersion_e,
    swStandardViews_e,
)


# ============================================================
# ОБЩИЕ ФУНКЦИИ
# ============================================================

def mm(value):
    """Переводит миллиметры в метры для SolidWorks API."""
    return float(value) / 1000.0


def sw_int(value):
    return Convert.ToInt32(value)


def flag_com_methods(com_object, *method_names):
    """Исправляет неверное определение методов pywin32 в отдельных TLB SolidWorks."""
    flag_method = getattr(com_object, "_FlagAsMethod", None)
    if flag_method is not None:
        for method_name in method_names:
            flag_method(method_name)


def fmt(value):
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:g}".replace(".", "_")


def get_desktop():
    """Возвращает реальный системный рабочий стол Windows."""
    buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    result = ctypes.windll.shell32.SHGetFolderPathW(
        None, 0x10, None, 0, buffer
    )
    if result == 0 and buffer.value:
        return Path(buffer.value)
    return Path.home() / "Desktop"


def read_positive_float(prompt, default=None):
    suffix = f" [{fmt(default)}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return float(default)
        try:
            value = float(raw.replace(",", "."))
            if value > 0:
                return value
        except ValueError:
            pass
        print("Введите число больше 0.")


def read_nonnegative_float(prompt, default=None):
    suffix = f" [{fmt(default)}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return float(default)
        try:
            value = float(raw.replace(",", "."))
            if value >= 0:
                return value
        except ValueError:
            pass
        print("Введите число не меньше 0.")


def read_distances(prompt):
    while True:
        raw = input(prompt).strip().replace(",", ".")
        try:
            values = [float(item) for item in raw.split()]
            if values and all(value > 0 for value in values):
                return values
        except ValueError:
            pass
        print("Введите одно или несколько положительных чисел через пробел.")


def round_pallet_size(value):
    """Округляет габарит вверх до целого кратного 5 мм."""
    return float((int(value / 5.0 + 0.999999999) * 5))


# ============================================================
# РАСЧЁТ ГЕОМЕТРИИ ПОДДОНА
# ============================================================

def calculate_direction(
    center_distances,
    first_edge_to_support,
    last_support_to_edge,
    first_margin,
    last_margin,
    beam_width,
):
    """Возвращает габарит и координаты осей брусьев для одного направления."""
    machine_size = (
        first_edge_to_support + sum(center_distances) + last_support_to_edge
    )
    raw_pallet_size = first_margin + machine_size + last_margin
    pallet_size = round_pallet_size(raw_pallet_size)
    delta = pallet_size - raw_pallet_size
    adjusted_last_support_to_edge = last_support_to_edge + delta

    if adjusted_last_support_to_edge < 0:
        raise ValueError("После округления последний отступ стал отрицательным.")

    first_support_center = first_margin + first_edge_to_support
    support_centers = [first_support_center]
    for distance in center_distances:
        support_centers.append(support_centers[-1] + distance)

    beam_centers = [
        beam_width / 2.0,
        *support_centers,
        pallet_size - beam_width / 2.0,
    ]
    for left, right in zip(beam_centers, beam_centers[1:]):
        if right - left < beam_width - 1e-9:
            raise ValueError("Соседние брусья пересекаются. Проверьте размеры.")

    return {
        "machine_size": machine_size,
        "raw_pallet_size": raw_pallet_size,
        "pallet_size": pallet_size,
        "delta": delta,
        "adjusted_last_support_to_edge": adjusted_last_support_to_edge,
        "support_centers": support_centers,
        "beam_centers": beam_centers,
        "start_faces": [center - beam_width / 2.0 for center in beam_centers],
        "dimension_distances": [
            right - left
            for left, right in zip(
                [center - beam_width / 2.0 for center in beam_centers],
                [center - beam_width / 2.0 for center in beam_centers][1:],
            )
        ],
    }


def input_direction(title):
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)
    beam_height = read_positive_float("Высота бруса, мм", 70)
    beam_width = read_positive_float("Ширина бруса, мм", 50)
    center_distances = read_distances("Расстояния между центрами опор, мм (через пробел): ")
    first_edge_to_support = read_nonnegative_float(
        "От первого габарита оборудования до центра первой опоры, мм"
    )
    last_support_to_edge = read_nonnegative_float(
        "От центра последней опоры до последнего габарита оборудования, мм"
    )
    first_margin = read_nonnegative_float("Отступ поддона в начале, мм", 100)
    last_margin = read_nonnegative_float("Отступ поддона в конце, мм", 100)
    return {
        "beam_height": beam_height,
        "beam_width": beam_width,
        **calculate_direction(
            center_distances,
            first_edge_to_support,
            last_support_to_edge,
            first_margin,
            last_margin,
            beam_width,
        ),
    }


def print_direction_result(name, data):
    print(f"\n{name}: габарит {fmt(data['pallet_size'])} мм")
    print("  Центры брусьев: " + " | ".join(fmt(x) for x in data["beam_centers"]))


# ============================================================
# SOLIDWORKS: ПОДГОТОВКА И ДЕТАЛЬ
# ============================================================

def check_environment():
    for label, path in (
        ("Шаблон детали", PART_TEMPLATE),
        ("Шаблон сборки", ASSEMBLY_TEMPLATE),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} не найден:\n{path}")


def connect_solidworks():
    sw = SldWorks()
    if sw is None:
        raise RuntimeError("Не удалось получить интерфейс SldWorks.")
    sw.Visible = True
    return sw


def create_new_document(sw, template, document_name):
    print(f"  Создание: {document_name}")
    if sw.NewDocument(str(template), 0, 0.0, 0.0) is None:
        raise RuntimeError(f"NewDocument не создал документ: {document_name}")
    document = sw.IActiveDoc2
    if document is None:
        raise RuntimeError(f"Не удалось получить созданный документ: {document_name}")
    return document


def create_rectangle_sketch(model, width_mm, height_mm):
    model.ClearSelection2(True)
    if not model.Extension.SelectByID2(
        BASE_PLANE_NAME, "PLANE", 0, 0, 0, False, 0, None, 0
    ):
        raise RuntimeError(f"Не удалось выбрать плоскость '{BASE_PLANE_NAME}'.")
    manager = model.SketchManager
    manager.InsertSketch(True)
    manager.CreateCornerRectangle(
        -mm(width_mm) / 2.0,
        -mm(height_mm) / 2.0,
        0.0,
        mm(width_mm) / 2.0,
        mm(height_mm) / 2.0,
        0.0,
    )
    manager.InsertSketch(True)
    model.EditRebuild3()
    sketch = model.Extension.GetLastFeatureAdded()
    if sketch is None:
        raise RuntimeError("Не удалось получить созданный эскиз.")
    return sketch


def create_extrusion(model, sketch, length_mm):
    model.ClearSelection2(True)
    if not sketch.Select2(False, 0):
        raise RuntimeError("Не удалось выбрать эскиз для выдавливания.")
    blind = sw_int(swEndConditions_e.swEndCondBlind)
    extrusion = model.FeatureManager.FeatureExtrusion2(
        True, False, False, blind, blind, mm(length_mm), 0.0,
        False, False, False, False, 0.0, 0.0, False, False,
        False, False, True, True, True, 0, 0.0, False,
    )
    if extrusion is None:
        raise RuntimeError("Не удалось создать выдавливание.")


def save_document(model, filename):
    filename.parent.mkdir(parents=True, exist_ok=True)
    flag_com_methods(model, "ClearSelection2", "EditRebuild3")
    model.ClearSelection2(True)
    model.EditRebuild3()
    save_version = sw_int(swSaveAsVersion_e.swSaveAsCurrentVersion)
    save_options = sw_int(swSaveAsOptions_e.swSaveAsOptions_Silent)

    if hasattr(model, "_FlagAsMethod"):
        # Для позднего COM-вызова SaveAs требует экспортные данные и ByRef
        # параметры ошибок. Старый SaveAs3 имеет ровно три простых параметра.
        flag_com_methods(model, "SaveAs3")
        result = model.SaveAs3(str(filename), save_version, save_options)
    else:
        extension = model.Extension
        flag_com_methods(extension, "SaveAs")
        result = extension.SaveAs(
            str(filename), save_version, save_options, None,
        )
    if not filename.exists():
        raise RuntimeError(f"SolidWorks не сохранил файл {filename}. Результат: {result!r}")


def create_beam(sw, length_mm, width_mm, height_mm, filename):
    """Создаёт брус: локальные X/Y — сечение, локальная Z — длина."""
    print(f"  Деталь {filename.name}: {fmt(length_mm)} x {fmt(width_mm)} x {fmt(height_mm)}")
    model = create_new_document(sw, PART_TEMPLATE, filename.name)
    sketch = create_rectangle_sketch(model, width_mm, height_mm)
    create_extrusion(model, sketch, length_mm)
    save_document(model, filename)
    return model


# ============================================================
# SOLIDWORKS: СБОРКА
# ============================================================

def component_matrix(x_axis, y_axis, z_axis, origin):
    """Матрица IMathTransform из образов локальных осей компонента.

    В массиве AddComponents3 три вектора ориентации идут последовательно;
    передавать их транспонированными нельзя — это меняет направление брусьев.
    """
    return (
        *x_axis,
        *y_axis,
        *z_axis,
        *origin,
        1.0, 0.0, 0.0, 0.0,
    )


def insert_components(assembly, placements):
    """Пакетно вставляет компоненты с точными матрицами положения.

    AddComponents3 принимает плоский массив из 16 чисел на каждый компонент.
    Это избавляет от MathUtility, который недоступен через используемый COM-мост.
    """
    names = tuple(str(filename) for filename, _ in placements)
    transforms = tuple(
        value
        for _, matrix in placements
        for value in matrix
    )
    coordinate_systems = tuple("" for _ in placements)

    # AddComponents3 требует SAFEARRAY(BSTR), SAFEARRAY(Double) и
    # SAFEARRAY(BSTR). Обычные tuple pywin32 передаёт как SAFEARRAY(VARIANT),
    # который SolidWorks в некоторых версиях молча игнорирует.
    names_arg = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_BSTR, names
    )
    transforms_arg = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, transforms
    )
    coordinate_systems_arg = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_BSTR, coordinate_systems
    )

    # pywin32 ошибочно распознаёт AddComponents3 как свойство в некоторых
    # версиях TLB SolidWorks. Явно помечаем его вызываемым COM-методом.
    flag_com_methods(assembly, "AddComponents3")
    components = assembly.AddComponents3(
        names_arg, transforms_arg, coordinate_systems_arg
    )
    if components is None:
        raise RuntimeError("SolidWorks не вставил компоненты в сборку.")

    flag_com_methods(assembly, "GetComponentCount")
    component_count = assembly.GetComponentCount(False)
    if component_count < len(placements):
        raise RuntimeError(
            "SolidWorks вернул успешный вызов AddComponents3, но добавил "
            f"только {component_count} из {len(placements)} компонентов."
        )
    return components


def create_assembly(
    sw, length_data, width_data, longitudinal_file, transverse_file, assembly_file
):
    """Создаёт сборку: X — длина, Y — высота, Z — ширина (в отрицательную сторону)."""
    create_new_document(sw, ASSEMBLY_TEMPLATE, assembly_file.name)
    # pythonnet возвращает IActiveDoc2 только как базовый ModelDoc2. Получаем
    # тот же активный COM-документ через pywin32: он вызывает методы сборки
    # поздним связыванием, поэтому AddComponents3 доступен без CLR-приведения.
    late_bound_sw = win32com.client.GetActiveObject("SldWorks.Application")
    assembly = late_bound_sw.ActiveDoc
    if assembly is None:
        raise RuntimeError("Не удалось получить активный документ сборки.")
    print("\nСоздание сборки:")

    # Проверенная ориентация продольных экземпляров текущего шаблона.
    longitudinal_axes = (
        (0.0, 0.0, -1.0),
        (0.0, 1.0, 0.0),
        (1.0, 0.0, 0.0),
    )
    placements = []
    # Сечение детали симметрично относительно начала координат, поэтому
    # в матрицу передаём центры сечений, не внешние грани.
    # Снизу лежат короткие поперечные брусья, сверху — продольные.
    lower_layer_center_y = length_data["beam_height"] / 2.0
    upper_layer_center_y = (
        length_data["beam_height"] + width_data["beam_height"] / 2.0
    )
    for index, center_y in enumerate(width_data["beam_centers"], start=1):
        placements.append(
            (
                longitudinal_file,
                component_matrix(
                    *longitudinal_axes,
                    (
                        0.0,
                        mm(upper_layer_center_y),
                        -mm(center_y),
                    ),
                ),
            )
        )
        print(f"  Продольный брус {index}: Z={fmt(center_y)} мм")

    # Проверенная ориентация поперечных экземпляров нижнего слоя.
    transverse_axes = (
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, -1.0),
    )
    for index, center_x in enumerate(length_data["beam_centers"], start=1):
        placements.append(
            (
                transverse_file,
                component_matrix(
                    *transverse_axes,
                    (
                        mm(center_x),
                        mm(lower_layer_center_y),
                        0.0,
                    ),
                ),
            )
        )
        print(f"  Поперечный брус {index}: X={fmt(center_x)} мм")

    insert_components(assembly, placements)
    flag_com_methods(assembly, "EditRebuild3", "ShowNamedView2", "ViewZoomtofit2")
    assembly.EditRebuild3()
    try:
        assembly.ShowNamedView2("", sw_int(swStandardViews_e.swIsometricView))
        assembly.ViewZoomtofit2()
    except Exception:
        pass
    save_document(assembly, assembly_file)
    return assembly


# ============================================================
# ТОЧКА ВХОДА
# ============================================================

def main():
    print("=" * 64)
    print("SOLIDWORKS — ГЕНЕРАТОР ПОДДОНА")
    print("=" * 64)
    print("Все размеры в миллиметрах. Габарит округляется вверх до 5 мм.")

    length_data = input_direction("НАПРАВЛЕНИЕ 1 — ДЛИНА ПОДДОНА (X)")
    width_data = input_direction("НАПРАВЛЕНИЕ 2 — ШИРИНА ПОДДОНА (Y)")
    pallet_length = length_data["pallet_size"]
    pallet_width = width_data["pallet_size"]
    pallet_height = width_data["beam_height"] + length_data["beam_height"]

    print_direction_result("ДЛИНА", length_data)
    print_direction_result("ШИРИНА", width_data)
    print(f"\nИтоговый габарит: {fmt(pallet_length)} x {fmt(pallet_width)} x {fmt(pallet_height)} мм")
    if input("\nСоздать детали и сборку? [Y/N]: ").strip().lower() not in ("y", "yes", "д", "да"):
        print("Создание отменено.")
        return

    check_environment()
    output_dir = get_desktop() / OUTPUT_FOLDER_NAME
    longitudinal_file = output_dir / (
        f"Beam_L_{fmt(pallet_length)}x{fmt(width_data['beam_width'])}x{fmt(width_data['beam_height'])}.SLDPRT"
    )
    transverse_file = output_dir / (
        f"Beam_W_{fmt(pallet_width)}x{fmt(length_data['beam_width'])}x{fmt(length_data['beam_height'])}.SLDPRT"
    )
    assembly_file = output_dir / f"Pallet_{fmt(pallet_length)}x{fmt(pallet_width)}.SLDASM"

    sw = connect_solidworks()
    print("\nСоздание деталей:")
    create_beam(sw, pallet_length, width_data["beam_width"], width_data["beam_height"], longitudinal_file)
    create_beam(sw, pallet_width, length_data["beam_width"], length_data["beam_height"], transverse_file)
    create_assembly(sw, length_data, width_data, longitudinal_file, transverse_file, assembly_file)

    print("\nГОТОВО")
    print(f"Папка: {output_dir}")
    print(f"  {longitudinal_file.name}")
    print(f"  {transverse_file.name}")
    print(f"  {assembly_file.name}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
    except Exception:
        print("\nКРИТИЧЕСКАЯ ОШИБКА")
        traceback.print_exc()
    finally:
        input("\nНажмите Enter для выхода...")
