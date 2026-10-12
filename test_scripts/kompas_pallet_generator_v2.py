from pathlib import Path
import math

import pythoncom
from win32com.client import Dispatch, gencache


# ============================================================
# ВВОД И ФОРМАТИРОВАНИЕ
# ============================================================

def fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def read_positive_float(prompt: str, default=None) -> float:
    while True:
        suffix = f" [{fmt(default)}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip().replace(",", ".")
        if not raw and default is not None:
            return float(default)
        try:
            value = float(raw)
            if not math.isfinite(value) or value <= 0:
                raise ValueError
            return value
        except ValueError:
            print("  Ошибка: введите положительное число.")


def read_nonnegative_float(prompt: str, default=None) -> float:
    while True:
        suffix = f" [{fmt(default)}]" if default is not None else ""
        raw = input(f"{prompt}{suffix}: ").strip().replace(",", ".")
        if not raw and default is not None:
            return float(default)
        try:
            value = float(raw)
            if not math.isfinite(value) or value < 0:
                raise ValueError
            return value
        except ValueError:
            print("  Ошибка: введите число >= 0.")


def read_distances(prompt: str) -> list[float]:
    while True:
        raw = input(prompt).strip().replace(",", ".")
        try:
            values = [float(x) for x in raw.split()]
            if not values or any(not math.isfinite(x) or x <= 0 for x in values):
                raise ValueError
            return values
        except ValueError:
            print("  Ошибка: введите расстояния через пробел, например: 1070 460 1300 499")


# ============================================================
# ТЕХНОЛОГИЧЕСКОЕ ОКРУГЛЕНИЕ ГАБАРИТА
# ============================================================

def round_pallet_size(value: float) -> float:
    """
    Округление по согласованному правилу в пределах каждого шага 50 мм:

      остаток 0..10 мм  -> вниз к кратному 50
      остаток >10 мм    -> вверх к следующему кратному 50

    Примеры:
      1901 -> 1900
      1910 -> 1900
      1911 -> 1950
      1936 -> 1950
      4204 -> 4200
    """
    lower = math.floor((value + 1e-9) / 50.0) * 50.0
    remainder = value - lower

    if remainder <= 10.0 + 1e-9:
        return lower
    return lower + 50.0


# ============================================================
# РАСЧЁТ ОДНОГО НАПРАВЛЕНИЯ
# ============================================================

def calculate_direction(
    center_distances: list[float],
    first_edge_to_support: float,
    last_support_to_edge: float,
    first_margin: float,
    last_margin: float,
    beam_width: float,
):
    """
    Начало координат фиксировано на первом краю поддона.

    Округление НЕ двигает:
      - первый крайний брус;
      - опоры;
      - внутренние брусья.

    Вся разница raw_size -> rounded_size уходит на последний конец:
    фактически изменяется последний участок после последней опоры и
    перемещается только последний крайний брус.
    """
    machine_size = (
        first_edge_to_support
        + sum(center_distances)
        + last_support_to_edge
    )

    raw_pallet_size = first_margin + machine_size + last_margin
    pallet_size = round_pallet_size(raw_pallet_size)
    delta = pallet_size - raw_pallet_size

    adjusted_last_support_to_edge = last_support_to_edge + delta

    if adjusted_last_support_to_edge < 0:
        raise ValueError(
            "После округления расстояние от последней опоры до габарита стало отрицательным."
        )

    first_support_center = first_margin + first_edge_to_support
    support_centers = [first_support_center]

    current = first_support_center
    for distance in center_distances:
        current += distance
        support_centers.append(current)

    # Крайние брусья лежат внутри габарита поддона.
    beam_centers = [
        beam_width / 2.0,
        *support_centers,
        pallet_size - beam_width / 2.0,
    ]

    # Проверка, что соседние брусья не пересекаются.
    for a, b in zip(beam_centers, beam_centers[1:]):
        if b - a < beam_width - 1e-9:
            raise ValueError(
                "Получено пересечение соседних брусьев. Проверьте размеры, отступы и сечение."
            )

    # Размеры по схеме простановки на чертеже:
    # от внешней грани предыдущего бруса со стороны начала координат
    # до грани следующего бруса, обращённой в сторону первого.
    start_faces = [center - beam_width / 2.0 for center in beam_centers]

    dimension_distances = [
        face_b - face_a
        for face_a, face_b in zip(start_faces, start_faces[1:])
    ]

    # Чистый физический просвет оставляем только как справочную величину.
    clear_gaps = [
        b - a - beam_width
        for a, b in zip(beam_centers, beam_centers[1:])
    ]

    return {
        "machine_size": machine_size,
        "raw_pallet_size": raw_pallet_size,
        "pallet_size": pallet_size,
        "delta": delta,
        "adjusted_last_support_to_edge": adjusted_last_support_to_edge,
        "support_centers": support_centers,
        "beam_centers": beam_centers,
        "start_faces": start_faces,
        "dimension_distances": dimension_distances,
        "clear_gaps": clear_gaps,
    }


def input_direction(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    beam_height = read_positive_float("Высота бруса, мм", 70)
    beam_width = read_positive_float("Ширина бруса, мм", 50)

    center_distances = read_distances(
        "Расстояния между центрами соседних опор, мм (через пробел): "
    )
    first_edge_to_support = read_nonnegative_float(
        "От первого габарита оборудования до центра первой опоры, мм"
    )
    last_support_to_edge = read_nonnegative_float(
        "От центра последней опоры до последнего габарита оборудования, мм"
    )
    first_margin = read_nonnegative_float(
        "Отступ поддона со стороны начала, мм", 100
    )
    last_margin = read_nonnegative_float(
        "Отступ поддона со стороны конца, мм", 100
    )

    result = calculate_direction(
        center_distances=center_distances,
        first_edge_to_support=first_edge_to_support,
        last_support_to_edge=last_support_to_edge,
        first_margin=first_margin,
        last_margin=last_margin,
        beam_width=beam_width,
    )

    return {
        "beam_height": beam_height,
        "beam_width": beam_width,
        "center_distances": center_distances,
        "first_edge_to_support": first_edge_to_support,
        "last_support_to_edge": last_support_to_edge,
        "first_margin": first_margin,
        "last_margin": last_margin,
        **result,
    }


# ============================================================
# КОМПАС
# ============================================================

def get_desktop() -> Path:
    desktop = Path.home() / "Desktop"
    return desktop if desktop.exists() else Path.home()


def connect_kompas():
    print("\nПодключение к КОМПАС-3D...")

    constants = gencache.EnsureModule(
        "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}", 0, 1, 0
    ).constants

    constants3d = gencache.EnsureModule(
        "{2CAF168C-7961-4B90-9DA2-701419BEEFE3}", 0, 1, 0
    ).constants

    gencache.EnsureModule(
        "{0422828C-F174-495E-AC5D-D31014DBBE87}", 0, 1, 0
    )

    kompas = Dispatch("KOMPAS.Application.5")
    kompas.Visible = True

    print("OK")
    return kompas, constants, constants3d


def create_beam_m3d(
    kompas,
    constants3d,
    length: float,
    width: float,
    height: float,
    filename: Path,
):
    print(
        f"  Создание {filename.name}: "
        f"{fmt(length)} x {fmt(width)} x {fmt(height)}"
    )

    document = kompas.Document3D

    if not document.Create(False, True):
        raise RuntimeError(f"Не удалось создать деталь {filename.name}")

    part = document.GetPart(constants3d.pTop_Part)
    if part is None:
        raise RuntimeError("Не удалось получить корневую деталь.")

    sketch = part.NewEntity(constants3d.o3d_sketch)
    if sketch is None:
        raise RuntimeError("Не удалось создать объект эскиза.")

    sketch_definition = sketch.GetDefinition()
    plane_xy = part.GetDefaultEntity(constants3d.o3d_planeXOY)

    if plane_xy is None:
        raise RuntimeError("Не удалось получить плоскость XOY.")

    sketch_definition.SetPlane(plane_xy)

    if not sketch.Create():
        raise RuntimeError("Не удалось создать эскиз.")

    sketch_2d = sketch_definition.BeginEdit()
    if sketch_2d is None:
        raise RuntimeError("Не удалось открыть эскиз.")

    sketch_2d.ksLineSeg(0, 0, length, 0, 1)
    sketch_2d.ksLineSeg(length, 0, length, width, 1)
    sketch_2d.ksLineSeg(length, width, 0, width, 1)
    sketch_2d.ksLineSeg(0, width, 0, 0, 1)

    sketch_definition.EndEdit()

    extrusion = part.NewEntity(constants3d.o3d_baseExtrusion)
    if extrusion is None:
        raise RuntimeError("Не удалось создать операцию выдавливания.")

    extrusion_definition = extrusion.GetDefinition()
    extrusion_definition.SetSketch(sketch)

    extrusion_params = extrusion_definition.ExtrusionParam()
    extrusion_params.direction = constants3d.dtNormal
    extrusion_params.depthNormal = height

    if not extrusion.Create():
        raise RuntimeError("Не удалось выполнить выдавливание.")

    if filename.exists():
        filename.unlink()

    if not document.SaveAs(str(filename)):
        raise RuntimeError(f"Не удалось сохранить {filename}")

    print("    OK")
    return document


def insert_component(
    assembly,
    constants3d,
    filename: Path,
    x: float,
    y: float,
    z: float,
    rotate_90: bool = False,
):
    part = assembly.GetPart(constants3d.pNew_Part)

    if part is None:
        raise RuntimeError(f"Не удалось создать компонент для {filename.name}")

    if not assembly.SetPartFromFile(str(filename), part, True):
        raise RuntimeError(f"Не удалось вставить {filename.name}")

    placement = part.GetPlacement()

    if placement is None:
        raise RuntimeError(f"Не удалось получить Placement для {filename.name}")

    if not placement.SetOrigin(x, y, z):
        raise RuntimeError("Не удалось задать координаты компонента.")

    if rotate_90:
        # Локальная X детали -> глобальная Y.
        # Локальная Y детали -> глобальная -X.
        if not placement.SetAxes(
            0.0, 1.0, 0.0,
            -1.0, 0.0, 0.0,
        ):
            raise RuntimeError("Не удалось повернуть компонент.")
    else:
        if not placement.SetAxes(
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
        ):
            raise RuntimeError("Не удалось задать ориентацию компонента.")

    if not part.UpdatePlacement():
        raise RuntimeError("Не удалось обновить положение компонента.")

    return part


def create_assembly(
    kompas,
    constants3d,
    length_data,
    width_data,
    longitudinal_file: Path,
    transverse_file: Path,
    assembly_file: Path,
):
    """
    Система координат сборки для вида сверху:

        (0, 0) = ЛЕВЫЙ ВЕРХНИЙ угол поддона

        X -> вправо  (длина)
        Y -> вниз    (ширина)

    Продольные брусья идут вдоль X.
    Поперечные — вдоль Y.

    В API КОМПАС ориентация поперечного компонента задаётся поворотом
    локальной X вдоль глобальной Y. Из-за локальной ширины в -X его
    origin по X ставится на правую грань бруса.
    """
    print("\nСоздание сборки...")

    assembly = kompas.Document3D

    if not assembly.Create(False, False):
        raise RuntimeError("Не удалось создать сборку.")

    # Нижний слой: продольные брусья.
    print(f"  Продольные брусья: {len(width_data['beam_centers'])} шт.")

    for index, center_y in enumerate(width_data["beam_centers"], start=1):
        y = center_y - width_data["beam_width"] / 2.0

        print(f"    [{index}] Y центр = {fmt(center_y)}")

        insert_component(
            assembly=assembly,
            constants3d=constants3d,
            filename=longitudinal_file,
            x=0.0,
            y=y,
            z=0.0,
            rotate_90=False,
        )

    # Верхний слой: поперечные брусья.
    print(f"  Поперечные брусья: {len(length_data['beam_centers'])} шт.")

    upper_z = width_data["beam_height"]

    for index, center_x in enumerate(length_data["beam_centers"], start=1):
        # При rotate_90 локальная ширина детали направлена в -X,
        # поэтому origin ставим на правую грань.
        x = center_x + length_data["beam_width"] / 2.0

        print(f"    [{index}] X центр = {fmt(center_x)}")

        insert_component(
            assembly=assembly,
            constants3d=constants3d,
            filename=transverse_file,
            x=x,
            y=0.0,
            z=upper_z,
            rotate_90=True,
        )

    print("  Перестроение сборки...")
    assembly.RebuildDocument()

    if assembly_file.exists():
        assembly_file.unlink()

    print("  Сохранение A3D...")

    if not assembly.SaveAs(str(assembly_file)):
        raise RuntimeError(f"Не удалось сохранить {assembly_file}")

    try:
        assembly.ZoomPrevNextOrAll(0)
    except Exception:
        pass

    print("    OK")
    return assembly


# ============================================================
# ОТЧЁТ
# ============================================================

def print_direction_result(name: str, data):
    print("\n" + name)
    print("-" * 60)
    print(f"Размер оборудования:              {fmt(data['machine_size'])} мм")
    print(f"Поддон до округления:             {fmt(data['raw_pallet_size'])} мм")
    print(f"Поддон после округления:          {fmt(data['pallet_size'])} мм")
    print(f"Изменение при округлении:         {fmt(data['delta'])} мм")

    print("\nОТСТУПЫ / ИСХОДНЫЕ РАЗМЕРЫ")
    print(f"  Край поддона -> габарит оборудования (начало): {fmt(data['first_margin'])} мм")
    print(f"  Габарит -> центр первой опоры:                  {fmt(data['first_edge_to_support'])} мм")
    print("  Между центрами опор:                            "
          + " | ".join(fmt(x) for x in data["center_distances"]) + " мм")
    print(f"  Центр последней опоры -> габарит (исходно):     {fmt(data['last_support_to_edge'])} мм")
    print(f"  Центр последней опоры -> габарит (после округл.): {fmt(data['adjusted_last_support_to_edge'])} мм")
    print(f"  Габарит оборудования -> край поддона (конец):   {fmt(data['last_margin'])} мм")

    print("\nБРУСЬЯ")
    print(f"  Количество: {len(data['beam_centers'])}")
    print("  Центры от начала поддона: "
          + " | ".join(fmt(x) for x in data["beam_centers"]) + " мм")
    print("  Внешние грани от начала:   "
          + " | ".join(fmt(x) for x in data["start_faces"]) + " мм")

    print("\nРАЗМЕРЫ МЕЖДУ БРУСЬЯМИ")
    print("  Схема: внешняя грань предыдущего -> обращённая к нему грань следующего")
    for i, distance in enumerate(data["dimension_distances"], start=1):
        print(f"  Брус {i} -> брус {i + 1}: {fmt(distance)} мм")

    print("  Цепочка: "
          + " | ".join(fmt(x) for x in data["dimension_distances"]) + " мм")

    print("\n  Чистые просветы (справочно): "
          + " | ".join(fmt(x) for x in data["clear_gaps"]) + " мм")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("       KOMPAS-3D v21 — ГЕНЕРАТОР ПОДДОНА")
    print("=" * 60)
    print()
    print("Сечение вводится как ВЫСОТА и ШИРИНА бруса.")
    print("Все размеры — в миллиметрах.")
    print("Начало поддона фиксировано в левом верхнем углу.")
    print("Округление габарита изменяет только последний конец.")

    try:
        # По длине определяем X-позиции поперечных брусьев.
        length_data = input_direction(
            "НАПРАВЛЕНИЕ 1 — ДЛИНА ПОДДОНА (X)"
        )

        # По ширине определяем Y-позиции продольных брусьев.
        width_data = input_direction(
            "НАПРАВЛЕНИЕ 2 — ШИРИНА ПОДДОНА (Y)"
        )

        print("\n" + "=" * 60)
        print("РЕЗУЛЬТАТ РАСЧЁТА")
        print("=" * 60)

        print_direction_result("ДЛИНА", length_data)
        print_direction_result("ШИРИНА", width_data)

        pallet_length = length_data["pallet_size"]
        pallet_width = width_data["pallet_size"]
        pallet_height = (
            width_data["beam_height"] + length_data["beam_height"]
        )

        print("\nИТОГОВЫЙ ГАБАРИТ")
        print("-" * 60)
        print(
            f"{fmt(pallet_length)} x "
            f"{fmt(pallet_width)} x "
            f"{fmt(pallet_height)} мм"
        )

        print("\nНажмите Enter, чтобы создать M3D/A3D.")
        input("Для отмены закройте окно или нажмите Ctrl+C...")

        desktop = get_desktop()
        output_dir = desktop / "KOMPAS_Pallet"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Продольный брус идёт на полную длину X.
        longitudinal_file = output_dir / (
            f"Beam_L_{fmt(pallet_length)}x"
            f"{fmt(width_data['beam_width'])}x"
            f"{fmt(width_data['beam_height'])}.m3d"
        )

        # Поперечный брус идёт на полную ширину Y.
        transverse_file = output_dir / (
            f"Beam_W_{fmt(pallet_width)}x"
            f"{fmt(length_data['beam_width'])}x"
            f"{fmt(length_data['beam_height'])}.m3d"
        )

        assembly_file = output_dir / (
            f"Pallet_{fmt(pallet_length)}x{fmt(pallet_width)}.a3d"
        )

        pythoncom.CoInitialize()

        try:
            kompas, constants, constants3d = connect_kompas()

            print("\nСоздание деталей:")

            create_beam_m3d(
                kompas=kompas,
                constants3d=constants3d,
                length=pallet_length,
                width=width_data["beam_width"],
                height=width_data["beam_height"],
                filename=longitudinal_file,
            )

            create_beam_m3d(
                kompas=kompas,
                constants3d=constants3d,
                length=pallet_width,
                width=length_data["beam_width"],
                height=length_data["beam_height"],
                filename=transverse_file,
            )

            create_assembly(
                kompas=kompas,
                constants3d=constants3d,
                length_data=length_data,
                width_data=width_data,
                longitudinal_file=longitudinal_file,
                transverse_file=transverse_file,
                assembly_file=assembly_file,
            )

            print("\n" + "=" * 60)
            print("ГОТОВО")
            print("=" * 60)
            print(f"\nПапка:\n{output_dir}")
            print("\nСозданы:")
            print(f"  {longitudinal_file.name}")
            print(f"  {transverse_file.name}")
            print(f"  {assembly_file.name}")
            print(
                "\nГабарит сборки: "
                f"{fmt(pallet_length)} x "
                f"{fmt(pallet_width)} x "
                f"{fmt(pallet_height)} мм"
            )

        finally:
            pythoncom.CoUninitialize()

    except KeyboardInterrupt:
        print("\n\nОтменено пользователем.")
    except Exception as exc:
        print("\n" + "=" * 60)
        print("ОШИБКА")
        print("=" * 60)
        print(f"\n{type(exc).__name__}: {exc}")

    input("\nНажмите Enter для выхода...")


if __name__ == "__main__":
    main()
