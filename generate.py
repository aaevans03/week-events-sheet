#!/usr/bin/env python3
"""
Render a weekly-events Slack announcement image from a CSV file.

USAGE:
``python generate.py --csv csv/YYYYMMDD-events.csv -o output/YYYYMMDD-events.png``
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# The sheet is a fixed-width column that grows downward to fit its events. At
# minimum it is a 4:3 portrait photo, the shape Slack previews without cropping.
CANVAS_WIDTH = 1200
MIN_CANVAS_HEIGHT = CANVAS_WIDTH * 4 // 3
TOP_MARGIN = 85
BOTTOM_MARGIN = 48
BACKGROUND = "#F8F8F6"
INK = "#111111"
LIGHT_INK = "#555555"
RULE = "#B9B9B7"
EVENT_RULE = "#D9D9D7"
LEFT = 86
RIGHT = CANVAS_WIDTH - LEFT

# Fonts in git-ignored directory
FONT_DIR = Path(__file__).parent / "fonts"
REGULAR_FONT = FONT_DIR / "IBMPlexSans-Regular.ttf"
BOLD_FONT = FONT_DIR / "IBMPlexSans-SemiBold.ttf"
BLACK_FONT = FONT_DIR / "IBMPlexSans-Bold.ttf"
REQUIRED_COLUMNS = {"title", "day", "location"}


@dataclass(frozen=True)
class Event:
    title: str
    day: str
    time: str
    location: str
    description: str = ""


def read_events(path: Path) -> list[Event]:
    """Read and validate a CSV while preserving the row order."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as csv_file:
            header = csv_file.readline()
            delimiter = "|" if "|" in header else ","
            csv_file.seek(0)
            reader = csv.DictReader(csv_file, delimiter=delimiter)
            headers = set(reader.fieldnames or [])
            missing = REQUIRED_COLUMNS - headers
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(f"CSV is missing required column(s): {names}")

            events = []
            for row_number, row in enumerate(reader, start=2):
                event = Event(
                    title=(row["title"] or "").strip(),
                    day=(row["day"] or "").strip(),
                    time=(row.get("time") or "").strip(),
                    location=(row["location"] or "").strip(),
                    description=(row.get("description") or "").strip(),
                )
                if not all((event.title, event.day, event.location)):
                    raise ValueError(
                        f"Row {row_number} needs a title, day, and location. Time is also preferred"
                    )
                events.append(event)
    except FileNotFoundError as error:
        raise ValueError(f"CSV file not found: {path}") from error

    if not events:
        raise ValueError("CSV has no event rows.")
    return events


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise RuntimeError(
            f"Required font file is missing: {path.name}. "
            "Restore the files in the fonts directory."
        )
    return ImageFont.truetype(path, size)


def text_width(
    draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.FreeTypeFont
) -> int:
    return int(draw.textbbox((0, 0), text, font=text_font)[2])


def fitted_font(
    draw: ImageDraw.ImageDraw, text: str, font_path: Path, max_size: int, max_width: int
) -> ImageFont.FreeTypeFont:
    """Shrink one line of text only when it would overlap its neighbouring column."""
    for size in range(max_size, 19, -1):
        candidate = font(font_path, size)
        if text_width(draw, text, candidate) <= max_width:
            return candidate
    return font(font_path, 20)


def spacing_for_font(
    text_font: ImageFont.FreeTypeFont, reference_size: int, reference_spacing: int
) -> int:
    """Scale spacing proportionally from a known-good font size and spacing."""
    return round(reference_spacing * text_font.size / reference_size)


def draw_rule(draw: ImageDraw.ImageDraw, y: int) -> None:
    draw.line((LEFT - 18, y, RIGHT + 18, y), fill=RULE, width=2)

# TODO: make title more stylized
def draw_title(draw: ImageDraw.ImageDraw, heading: str, y: int) -> int:
    max_font_size = 90
    heading_font = fitted_font(draw, heading, BLACK_FONT, max_font_size, RIGHT - LEFT)
    width = text_width(draw, heading, heading_font)
    draw.text(((CANVAS_WIDTH - width) / 2, y), heading, font=heading_font, fill=INK)
    return y + spacing_for_font(heading_font, max_font_size, 155)


def draw_section_heading(draw: ImageDraw.ImageDraw, heading: str, y: int) -> int:
    draw_rule(draw, y)
    heading_font = font(BLACK_FONT, 41)
    width = text_width(draw, heading, heading_font)
    draw.text(((CANVAS_WIDTH - width) / 2, y + 29), heading, font=heading_font, fill=INK)
    return y + 112

# TODO: The baselines are still a bit wonky
def draw_sunday_events(draw: ImageDraw.ImageDraw, events: list[Event], y: int) -> int:
    for index, event in enumerate(events):
        details = (
            f"{event.time}  •  {event.location}"
            if event.time
            else event.location
        )
        detail_font = fitted_font(draw, details, REGULAR_FONT, 38, 480)
        detail_width = text_width(draw, details, detail_font)
        title_max_width = RIGHT - LEFT - detail_width - 38
        title_font = fitted_font(draw, event.title, BOLD_FONT, 52, title_max_width)

        # TODO: AM and PM are smaller font for stylizing
        draw.text((LEFT, y), event.title, font=title_font, fill=INK)
        draw.text((RIGHT - detail_width, y + 7), details, font=detail_font, fill=LIGHT_INK)

        # TODO: refactor so description text is a shared helper
        event_height = 115
        if event.description:
            description_font = fitted_font(
                draw, event.description, REGULAR_FONT, 34, RIGHT - LEFT
            )
            draw.text(
                (LEFT, y + 65), event.description, font=description_font, fill=LIGHT_INK
            )
            event_height = 165

        y += event_height
        if index != len(events) - 1:
            draw.line((LEFT, y - 22, RIGHT, y - 22), fill=EVENT_RULE, width=2)
    return y


def draw_weekday_events(draw: ImageDraw.ImageDraw, events: list[Event], y: int) -> int:
    for index, event in enumerate(events):
        title_font = fitted_font(draw, event.title, BOLD_FONT, 48, RIGHT - LEFT)
        draw.text((LEFT, y), event.title, font=title_font, fill=INK)

        # TODO: AM and PM are smaller font for stylizing
        detail = (
            f"{event.day}, {event.time}  •  {event.location}"
            if event.time
            else f"{event.day}  •  {event.location}"
        )
        detail_font = fitted_font(draw, detail, REGULAR_FONT, 38, RIGHT - LEFT)
        draw.text((LEFT, y + 70), detail, font=detail_font, fill=LIGHT_INK)

        event_height = 155
        if event.description:
            description_font = fitted_font(
                draw, event.description, REGULAR_FONT, 38, RIGHT - LEFT
            )
            draw.text(
                (LEFT, y + 119), event.description, font=description_font, fill=LIGHT_INK
            )
            event_height = 205

        y += event_height
        if index != len(events) - 1:
            draw.line((LEFT + 5, y - 8, LEFT + 555, y - 8), fill=EVENT_RULE, width=2)
            y += 15
    return y


def draw_sheet(
    draw: ImageDraw.ImageDraw,
    heading: str,
    sunday_events: list[Event],
    weekday_events: list[Event],
) -> int:
    """Draw the whole sheet and return the y just below the last event."""
    y = draw_title(draw, heading, TOP_MARGIN)
    y = draw_section_heading(draw, "SUNDAY", y)
    y = draw_sunday_events(draw, sunday_events, y)
    y = draw_section_heading(draw, "DURING THE WEEK", y)

    # TODO: Note at bottom, about adding events
    return draw_weekday_events(draw, weekday_events, y)


def canvas_height(
    heading: str, sunday_events: list[Event], weekday_events: list[Event]
) -> int:
    """Measure the sheet by drawing it onto a throwaway one-pixel-tall canvas.

    Pillow clips anything drawn past the edge, so the scratch draw costs nothing
    but still reports the real bottom. Measuring by drawing keeps the height from
    drifting out of step with the layout the way a separate calculation would.
    """
    scratch = ImageDraw.Draw(Image.new("RGB", (CANVAS_WIDTH, 1)))
    content_bottom = draw_sheet(scratch, heading, sunday_events, weekday_events)
    return max(MIN_CANVAS_HEIGHT, content_bottom + BOTTOM_MARGIN)


def render(events: list[Event], heading: str) -> Image.Image:
    sunday_events = [event for event in events if event.day.casefold() == "sunday"]
    weekday_events = [event for event in events if event.day.casefold() != "sunday"]

    if not weekday_events or not sunday_events:
        raise ValueError("Include at least one Sunday event and one non-Sunday event.")

    height = canvas_height(heading, sunday_events, weekday_events)
    image = Image.new("RGB", (CANVAS_WIDTH, height), BACKGROUND)
    draw_sheet(ImageDraw.Draw(image), heading, sunday_events, weekday_events)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a Slack-ready weekly events PNG from a CSV file."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("template.csv"),
        help="CSV with title, day, and location columns; time and description are optional",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        # TODO: Output file is based on the CSV template file name
        default=Path("output/weekly-events.png"),
        help="Output PNG path (default: output/weekly-events.png)",
    )
    args = parser.parse_args()

    try:
        match = re.search(r"(?<!\d)(\d{8})(?!\d)", args.csv.stem)
        if not match:
            raise ValueError(
                "CSV filename must include a week date in YYYYMMDD format."
            )
        week_date = datetime.strptime(match.group(1), "%Y%m%d")
        image = render(read_events(args.csv), f"Week of {week_date:%m/%d}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.output, format="PNG", optimize=True)
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Created {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
