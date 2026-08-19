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

        for sheet, page in zip(sheets, pages):
            self.convert(
                sheet,
                characters_dir,
                config,
                cols=page["cols"],
                rows=page["rows"],
                characters=page["chars"],
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
        # Read the image and convert to grayscale
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
        contours, h = cv2.findContours(
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
