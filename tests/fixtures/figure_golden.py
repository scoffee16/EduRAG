"""Deterministic image-heavy PDF fixture for the VLM figure-parsing evaluation.

The fixture is generated with pymupdf only (no Pillow) so it stays inside the
project's offline test dependencies: a scratch page draws the figure shapes,
the pixmap is exported as PNG, and the PNG is inserted into the real page as a
raster image region.  A fake describer returns fixed Chinese descriptions keyed
by page number, which keeps the retrieval evaluation deterministic and offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pymupdf

from edurage.ingest.figure_describer import FigureDescription, image_sha256

COURSE_CODE = "CS-FIGURE"
DOCUMENT_ID = "doc-figure-golden"
FILENAME = "figure-golden.pdf"
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0

FIGURE_PAGE_NUMBERS: tuple[int, ...] = (1, 3, 5, 7, 9)
TEXT_ONLY_PAGE_NUMBERS: tuple[int, ...] = (2, 4, 6)
LONG_TEXT_PAGE = 8
SMALL_IMAGE_PAGE = 10
TOTAL_PAGES = 10

# ``image_ratio`` is the expected raster area / page area for figure pages.
FIGURE_IMAGE_RATIO_MIN = 0.35

FIGURE_DESCRIPTIONS: dict[int, str] = {
    1: (
        "微程序控制器思维导图\n"
        "根节点：微程序控制器\n"
        "- 控制存储器：存放微指令，下一级节点为微指令寄存器\n"
        "- 微指令寄存器：保存当前正在执行的微指令\n"
        "- 微地址寄存器：保存下一条微指令的地址\n"
        "- 时序控制：产生节拍信号，协调各部件"
    ),
    3: (
        "指令执行流程图\n"
        "开始 -> 取指 -> 译码 -> 执行 -> 写回 -> 结束\n"
        "取指：从存储器读取指令\n"
        "译码：解析操作码\n"
        "执行：运算器完成运算\n"
        "写回：把结果写回寄存器"
    ),
    5: (
        "微指令字段定义表\n"
        "表头：字段名称 | 起始位 | 结束位 | 位数 | 含义\n"
        "控制字段：起始位 0，结束位 7，共 8 位，控制各功能部件\n"
        "条件字段：起始位 8，结束位 10，共 3 位，选择下一条微指令\n"
        "下址字段：起始位 11，结束位 19，共 9 位，给出下址"
    ),
    7: (
        "控制信号时序图\n"
        "横轴：时间，按节拍 T0 到 T3 划分\n"
        "纵轴：控制信号，包括 PCout、MARin、DRout\n"
        "T0 节拍：PCout 有效\n"
        "T1 节拍：MARin 有效\n"
        "T2 节拍：DRout 有效"
    ),
    9: (
        "总线结构思维导图\n"
        "根节点：总线结构\n"
        "- 数据总线：传输数据，宽度决定一次传送的位数\n"
        "- 地址总线：传输地址，宽度决定可访问空间\n"
        "- 控制总线：传输控制信号"
    ),
}

FIGURE_QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "mind-map-controller",
        "question": "微程序控制器思维导图中，控制存储器的下一级节点是什么？",
        "page": 1,
    },
    {
        "id": "flowchart-fetch",
        "question": "指令执行流程图中，取指阶段之后依次经过哪些节点？",
        "page": 3,
    },
    {
        "id": "table-fields",
        "question": "微指令字段定义表的表头有哪些列，控制字段占多少位？",
        "page": 5,
    },
    {
        "id": "timing-axes",
        "question": "控制信号时序图中，横轴和纵轴分别表示什么？",
        "page": 7,
    },
    {
        "id": "bus-mind-map",
        "question": "总线结构思维导图包含哪些根节点和子节点？",
        "page": 9,
    },
)

_TEXT_PAGES: dict[int, str] = {
    2: (
        "Chapter 2 Registers\n"
        "Registers hold operands close to the arithmetic unit. "
        "The program counter stores the address of the next instruction, "
        "while the instruction register keeps the instruction under execution.\n"
        "A register file supports several concurrent reads and one write per cycle."
    ),
    4: (
        "Chapter 4 Register Transfer Language\n"
        "Register transfer language describes data movement between registers. "
        "Each transfer statement names a destination, a source, and optional conditions.\n"
        "Common operations include load, store, move, and exchange."
    ),
    6: (
        "Chapter 6 Interrupt Handling\n"
        "An interrupt suspends the current program and transfers control to a handler. "
        "The processor saves the program counter, masks lower-priority interrupts, "
        "and resumes the interrupted program after the handler returns."
    ),
}

_LONG_TEXT = (
    "Chapter 8 Lab Report Guidance\n"
    "Write a short report that states the goal of the experiment, lists the hardware "
    "and software environment, and describes the observed behaviour step by step. "
    "Include a clear problem statement, a short description of the design, and the "
    "measurements you collected. Discuss the difference between the expected result "
    "and the measured result, and explain the possible reasons for that difference. "
    "Keep the report concise, use complete sentences, and finish with the lessons you "
    "learned. Attach any tables or screenshots you used while collecting data, and "
    "list the commands that reproduce each measurement. Do not include confidential "
    "credentials in the report. Review your report once for spelling, grammar, and "
    "consistent terminology before submitting it to the teaching assistant. Keep the "
    "report concise, use complete sentences, and finish with the lessons you learned. "
    "Attach any tables or screenshots you used while collecting data, and list the "
    "commands that reproduce each measurement. Review your report once for spelling, "
    "grammar, and consistent terminology before submitting it. "
    "This page intentionally contains a longer text block so that the VLM figure "
    "trigger skips it even though a large raster image is present on the page."
)

_SMALL_IMAGE_TEXT = "Chapter 10 Short Note\nA small illustration is included for reference."


def _draw_figure(page: pymupdf.Page, kind: str) -> None:
    """Draw one deterministic figure shape set onto a scratch page."""

    width = page.rect.width
    height = page.rect.height
    margin = 0.06 * min(width, height)
    if kind == "mind-map":
        page.draw_rect(pymupdf.Rect(width * 0.3, margin, width * 0.7, height * 0.18))
        for index in range(1, 4):
            y = height * 0.25 + index * height * 0.16
            page.draw_rect(
                pymupdf.Rect(width * 0.08, y, width * 0.42, y + height * 0.1)
            )
            page.draw_line(
                (width * 0.5, height * 0.18),
                (width * 0.25, y),
                color=(0.2, 0.2, 0.8),
                width=1.5,
            )
    elif kind == "flowchart":
        for index in range(1, 5):
            x = margin + (index - 1) * width * 0.22
            page.draw_rect(
                pymupdf.Rect(x, height * 0.4, x + width * 0.16, height * 0.55)
            )
            if index < 4:
                page.draw_line(
                    (x + width * 0.16, height * 0.475),
                    (x + width * 0.22, height * 0.475),
                    color=(0.1, 0.5, 0.1),
                    width=2,
                )
        page.draw_line(
            (width * 0.5, height * 0.15),
            (width * 0.5, height * 0.4),
            color=(0.1, 0.5, 0.1),
            width=2,
        )
    elif kind == "table":
        columns = 5
        rows = 4
        left = width * 0.08
        top = height * 0.18
        cell_width = (width * 0.84) / columns
        cell_height = (height * 0.5) / rows
        for column in range(columns + 1):
            x = left + column * cell_width
            page.draw_line((x, top), (x, top + rows * cell_height), width=1)
        for row in range(rows + 1):
            y = top + row * cell_height
            page.draw_line((left, y), (left + columns * cell_width, y), width=1)
    elif kind == "axes":
        x0 = width * 0.12
        y0 = height * 0.8
        x1 = width * 0.9
        y1 = height * 0.2
        page.draw_line((x0, y0), (x1, y0), width=2)
        page.draw_line((x0, y0), (x0, y1), width=2)
        for index in range(1, 4):
            x = x0 + index * (x1 - x0) / 4
            page.draw_line((x, y0), (x, y0 - height * 0.55), color=(0.8, 0.2, 0.2), width=1.5)
        page.draw_line((x0, y1), (x1, y1), color=(0.2, 0.2, 0.8), width=2)
    else:
        raise ValueError(f"Unknown fixture figure kind: {kind}")


def _figure_png(kind: str, width: float, height: float, *, scale: float = 2.0) -> bytes:
    """Render a deterministic figure raster as PNG bytes."""

    scratch = pymupdf.open()
    try:
        page = scratch.new_page(width=width, height=height)
        _draw_figure(page, kind)
        matrix = pymupdf.Matrix(scale, scale)
        return page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
    finally:
        scratch.close()


def _insert_figure(page: pymupdf.Page, kind: str, rect: pymupdf.Rect) -> None:
    """Insert one figure raster (aspect ratio matches ``rect``) into a page."""

    png = _figure_png(kind, rect.width, rect.height)
    page.insert_image(rect, stream=png, keep_proportion=False)


def make_figure_pdf(path: Path) -> Path:
    """Write the deterministic ten-page figure PDF and return its path."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        for page_number in range(1, TOTAL_PAGES + 1):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            if page_number in FIGURE_PAGE_NUMBERS:
                kind = ("mind-map", "flowchart", "table", "axes", "mind-map")[
                    FIGURE_PAGE_NUMBERS.index(page_number)
                ]
                _insert_figure(
                    page,
                    kind,
                    pymupdf.Rect(50, 70, 545, 640),
                )
                page.insert_text(
                    (50, 690),
                    f"Figure {page_number}. Caption for the illustrated page.",
                    fontsize=12,
                )
            elif page_number == LONG_TEXT_PAGE:
                _insert_figure(page, "flowchart", pymupdf.Rect(50, 70, 545, 500))
                page.insert_textbox(
                    pymupdf.Rect(50, 520, 545, 820),
                    _LONG_TEXT,
                    fontsize=9,
                )
            elif page_number == SMALL_IMAGE_PAGE:
                _insert_figure(page, "table", pymupdf.Rect(50, 70, 200, 200))
                page.insert_text((50, 240), _SMALL_IMAGE_TEXT, fontsize=12)
            else:
                text = _TEXT_PAGES[page_number]
                heading, _, body = text.partition("\n")
                page.insert_text((72, 90), heading, fontsize=16)
                page.insert_textbox(
                    pymupdf.Rect(72, 130, 523, 780),
                    body,
                    fontsize=12,
                )
        document.save(path)
    finally:
        document.close()
    return path


class FakeFigureDescriber:
    """Deterministic describer keyed by page number; never calls a real VLM."""

    def __init__(
        self,
        descriptions: dict[int, str] | None = None,
        *,
        fail_pages: frozenset[int] = frozenset(),
    ) -> None:
        self.descriptions = dict(descriptions or FIGURE_DESCRIPTIONS)
        self.fail_pages = fail_pages
        self.calls: list[tuple[int, int]] = []

    def describe(self, image: bytes, *, page: int) -> FigureDescription:
        """Return the fixed description for ``page`` and record the call."""

        self.calls.append((page, len(image)))
        if page in self.fail_pages:
            raise RuntimeError(f"fake VLM failure on page {page}")
        text = self.descriptions.get(page, "无法识别")
        return FigureDescription(text=text, image_hash=image_sha256(image))

