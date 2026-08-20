import os
import json

import cv2

from handwrite.characters import ALL_CHARS, EXISTING_CHARS, PAGES

# ALL_CHARS is re-exported here (rather than defined here) purely so that
# any existing code/tests importing `from handwrite.sheettopng import
# ALL_CHARS` keep working. The single source of truth for character lists
# and page layout now lives in handwrite/characters.py.


class SheetDetectionError(Exception):
    """Raised when a scanned sheet cannot be read or its boxes not found."""


class PageValidationError(SheetDetectionError):
    """Raised when a scan is not the form page it is being processed as.

    A subclass, so callers already handling SheetDetectionError - the CLI
    among them - report this the same way.
    """


# A pixel darker than this is taken to be pen. The "do not write here" cross
# printed in an unused box is a light grey, well above it, so an empty box
# reads as empty even though something is printed in it.
INK_LEVEL = 128

# A box with more than this fraction of dark pixels has been written in.
# Measured on real filled forms: written boxes run from about 0.008 upwards,
# unused ones sit at 0.000.
INK_FRACTION = 0.005


def _read_and_find_boxes(sheet_image, threshold_value):
    """Read a scan and return it with its four-sided contours, largest first."""
    image = cv2.imread(sheet_image)
    if image is None:
        raise SheetDetectionError(
            "Could not read '{}'. Check the path exists and is an image "
            "file OpenCV can open (jpg, png, bmp, tif).".format(sheet_image)
        )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Threshold and filter the image for better contour detection
    _, thresh = cv2.threshold(gray, threshold_value, 255, 1)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    close = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, close_kernel, iterations=2)

    # Search for contours.
    contours, _hierarchy = cv2.findContours(
        close, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    # Filter contours based on number of sides and then reverse sort by area.
    contours = sorted(
        filter(
            lambda cnt: len(
                cv2.approxPolyDP(cnt, 0.01 * cv2.arcLength(cnt, True), True)
            )
            == 4,
            contours,
        ),
        key=cv2.contourArea,
        reverse=True,
    )
    return image, gray, contours


def _count_clusters(values, tolerance):
    """How many distinct positions are in a sorted list of coordinates."""
    if not values:
        return 0
    count = 1
    for previous, current in zip(values, values[1:]):
        if current - previous > tolerance:
            count += 1
    return count


def _boxes_in_reading_order(rectangles, cols, rows):
    """Sort box rectangles the way save_images expects them: rows, then columns."""
    ordered = sorted(rectangles, key=lambda rect: rect[1])
    result = []
    for row in range(rows):
        result.extend(
            sorted(ordered[cols * row : cols * (row + 1)], key=lambda r: r[0])
        )
    return result


def _trailing_empty_boxes(gray, ordered):
    """Count the unwritten boxes at the end of a page.

    This is what tells the pages apart. Page 1 fills every box, page 2 leaves
    seven at the end and page 3 leaves two, so the count identifies the page
    without reading anything printed on it.
    """
    empty = 0
    for x, y, width, height in reversed(ordered):
        inside = gray[
            y + height // 6 : y + 5 * height // 6, x + width // 6 : x + 5 * width // 6
        ]
        if inside.size and (inside < INK_LEVEL).mean() > INK_FRACTION:
            break
        empty += 1
    return empty


class SHEETtoPNG:
    """Converter class to convert input sample sheet(s) to character PNGs."""

    def convert(self, sheet, characters_dir, config, cols=8, rows=10, characters=None):
        """Convert one sheet of sample writing input to a directory structure of PNGs.

        Detect all characters in the sheet as separate contours and convert each to
        a PNG image in a temp/user provided directory.

        Parameters
        ----------
        sheet : str
            Path to the sheet file to be converted.
        characters_dir : str
            Path to directory to save characters in.
        config: str
            Path to config file.
        cols : int, default=8
            Number of columns of expected contours. Defaults to 8 based on the default sample.
        rows : int, default=10
            Number of rows of expected contours. Defaults to 10 based on the default sample.
        characters : list of int, optional
            Unicode ordinal for each box on this sheet, in the exact
            left-to-right, top-to-bottom order the boxes appear on the page.
            Defaults to EXISTING_CHARS (the original 80-character, single
            page form), which preserves the original single-sheet behaviour.
        """
        if characters is None:
            characters = EXISTING_CHARS

        with open(config) as f:
            threshold_value = json.load(f).get("threshold_value", 200)
        if os.path.isdir(sheet):
            raise IsADirectoryError("Sheet parameter should not be a directory.")
        detected = self.detect_characters(sheet, threshold_value, cols=cols, rows=rows)
        self.save_images(detected, characters_dir, characters)

    def convert_pages(self, sheets, characters_dir, config, pages=None):
        """Convert several sheets (one per form page) into one characters directory.

        This is how the extended, multi-page form is processed: each scanned
        page image is run through the same single-sheet `convert()` above,
        using that page's own cols/rows/characters, and all the resulting
        PNGs land in the same `characters_dir` so the rest of the pipeline
        (PNGtoSVG, SVGtoTTF) doesn't need to know multiple pages exist.

        Parameters
        ----------
        sheets : list of str
            Paths to the scanned page images, in the same order as `pages`
            (page 1 first, page 2 second, ...).
        characters_dir : str
            Path to directory to save characters in.
        config : str
            Path to config file.
        pages : list of dict, optional
            Defaults to `handwrite.characters.PAGES`. Each entry needs
            `cols`, `rows` and `chars` keys.
        """
        if pages is None:
            pages = PAGES

        if len(sheets) != len(pages):
            raise ValueError(
                "Expected {} sheet(s) (one per form page), got {}.".format(
                    len(pages), len(sheets)
                )
            )

        # Check every page before extracting anything. A scan in the wrong
        # place or the wrong way up still has the right number of boxes, so
        # without this the pipeline would happily file each character under
        # its neighbour's codepoint and build a font that looks fine and is
        # entirely wrong.
        with open(config) as f:
            threshold_value = json.load(f).get("threshold_value", 200)
        for number, (sheet, page) in enumerate(zip(sheets, pages), start=1):
            self.validate_page(sheet, page, number, len(pages), threshold_value)

        for sheet, page in zip(sheets, pages):
            self.convert(
                sheet,
                characters_dir,
                config,
                cols=page["cols"],
                rows=page["rows"],
                characters=page["chars"],
            )

    def validate_page(self, sheet, page, number, total, threshold_value=200):
        """Check a scan really is the form page it is about to be read as.

        Three things about the printed form give this away without reading a
        single character:

        * the grid is `cols` across and `rows` down, so a sheet turned on its
          side comes out transposed;
        * the title is printed above the grid, so an upside down sheet has
          its ink below instead;
        * each page leaves a different number of boxes crossed out at the
          end - none, seven, two - so counting the unwritten boxes at the
          bottom says which page this is.

        Raises
        ------
        PageValidationError
            With what is wrong and what to do about it.
        """
        cols, rows = page["cols"], page["rows"]
        _image, gray, contours = _read_and_find_boxes(sheet, threshold_value)

        if len(contours) < cols * rows:
            raise PageValidationError(
                "Page {} of {}: found only {} box(es) on '{}', expected {}. "
                "The scan may be cropped, skewed or too light - try "
                "rescanning, and check the pages are in order.".format(
                    number, total, len(contours), sheet, cols * rows
                )
            )

        rectangles = [cv2.boundingRect(contour) for contour in contours[: cols * rows]]
        widths = sorted(rect[2] for rect in rectangles)
        heights = sorted(rect[3] for rect in rectangles)
        box_width = widths[len(widths) // 2]
        box_height = heights[len(heights) // 2]

        across = _count_clusters(
            sorted(x + w // 2 for x, _y, w, _h in rectangles), box_width // 2
        )
        down = _count_clusters(
            sorted(y + h // 2 for _x, y, _w, h in rectangles), box_height // 2
        )
        if (across, down) != (cols, rows):
            raise PageValidationError(
                "Page {} of {} ('{}') has the wrong grid: its boxes form {} by "
                "{}, but page {} is {} by {}. Either the scan is rotated - it "
                "must be upright and in portrait, the same way up as it was "
                "printed - or this is not page {}. The scans are matched to "
                "the form by sorted filename.".format(
                    number, total, sheet, across, down, number, cols, rows, number
                )
            )

        top = min(y for _x, y, _w, _h in rectangles)
        bottom = max(y + h for _x, y, _w, h in rectangles)
        above = int((gray[:top] < INK_LEVEL).sum())
        below = int((gray[bottom:] < INK_LEVEL).sum())
        if below > above:
            raise PageValidationError(
                "Page {} of {} ('{}') looks upside down: the printed heading "
                "should be above the boxes, but the ink is below them. Turn "
                "the page the right way up and scan it again.".format(
                    number, total, sheet
                )
            )

        expected_empty = cols * rows - len(page["chars"])
        empty = _trailing_empty_boxes(
            gray, _boxes_in_reading_order(rectangles, cols, rows)
        )
        if empty != expected_empty:
            raise PageValidationError(
                "Page {} of {} ('{}') does not look like page {}: it ends with "
                "{} unwritten box(es), and page {} should end with {}. Check "
                "the scans are in page order - they are matched by sorted "
                "filename - and that no box was left blank by mistake.".format(
                    number, total, sheet, number, empty, number, expected_empty
                )
            )

    def detect_characters(self, sheet_image, threshold_value, cols=8, rows=10):
        """Detect contours on the input image and filter them to get only characters.

        Uses opencv to threshold the image for better contour detection. After finding all
        contours, they are filtered based on area, cropped and then sorted sequentially based
        on coordinates. Finally returs the cols*rows top candidates for being the character
        containing contours.

        Parameters
        ----------
        sheet_image : str
            Path to the sheet file to be converted.
        threshold_value : int
            Value to adjust thresholding of the image for better contour detection.
        cols : int, default=8
            Number of columns of expected contours. Defaults to 8 based on the default sample.
        rows : int, default=10
            Number of rows of expected contours. Defaults to 10 based on the default sample.

        Returns
        -------
        sorted_characters : list of list
            Final rows*cols contours in form of list of list arranged as:
            sorted_characters[x][y] denotes contour at x, y position in the input grid.

        Raises
        ------
        SheetDetectionError
            If the image cannot be read, or fewer than rows*cols boxes are
            found on it.
        """
        image, gray, contours = _read_and_find_boxes(sheet_image, threshold_value)

        # Every box on the sheet has to have been found, otherwise the
        # position-to-character mapping silently shifts and the font ends up
        # with the right glyphs under the wrong characters.
        if len(contours) < rows * cols:
            raise SheetDetectionError(
                "Found only {} box(es) on '{}', expected {} ({} columns x {} "
                "rows). The scan may be cropped, skewed, or too light - try "
                'rescanning, or adjust "threshold_value" in the config '
                "(currently detecting at {}).".format(
                    len(contours),
                    sheet_image,
                    rows * cols,
                    cols,
                    rows,
                    threshold_value,
                )
            )

        # Calculate the bounding of the first contour and approximate the height
        # and width for final cropping.
        x, y, w, h = cv2.boundingRect(contours[0])
        space_h, space_w = 7 * h // 16, 7 * w // 16

        # Since amongst all the contours, the expected case is that the 4 sided contours
        # containing the characters should have the maximum area, so we loop through the first
        # rows*colums contours and add them to final list after cropping.
        characters = []
        for i in range(rows * cols):
            x, y, w, h = cv2.boundingRect(contours[i])
            cx, cy = x + w // 2, y + h // 2

            roi = image[cy - space_h : cy + space_h, cx - space_w : cx + space_w]
            characters.append([roi, cx, cy])

        # Now we have the characters but since they are all mixed up we need to position them.
        # Sort characters based on 'y' coordinate and group them by number of rows at a time. Then
        # sort each group based on the 'x' coordinate.
        characters.sort(key=lambda x: x[2])
        sorted_characters = []
        for k in range(rows):
            sorted_characters.extend(
                sorted(characters[cols * k : cols * (k + 1)], key=lambda x: x[1])
            )

        return sorted_characters

    def save_images(self, characters, characters_dir, character_ords):
        """Create directory for each character and save as PNG.

        Creates directory and PNG file for each image as following:

            characters_dir/ord(character)/ord(character).png

        Parameters
        ----------
        characters : list of list
            Sorted list of character images (one per detected box on the sheet),
            each inner list representing a row of images.
        characters_dir : str
            Path to directory to save characters in.
        character_ords : list of int
            Unicode ordinal for each box, in the same left-to-right,
            top-to-bottom order as `characters`. If a sheet has more boxes
            than characters (e.g. unused/leftover boxes on the last row of a
            page), the extra boxes are simply ignored: `zip` stops at the
            shorter of the two lists.
        """
        os.makedirs(characters_dir, exist_ok=True)

        # Create directory for each character and save the png for the character.
        # Structure: UserProvidedDir/ord(character)/ord(character).png
        for ordinal, images in zip(character_ords, characters):
            character = os.path.join(characters_dir, str(ordinal))
            if not os.path.exists(character):
                os.mkdir(character)
            cv2.imwrite(
                os.path.join(character, str(ordinal) + ".png"),
                images[0],
            )
