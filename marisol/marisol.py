from concurrent import futures
from enum import Enum
from PyPDF2 import PdfFileReader, PdfFileWriter
from reportlab.pdfgen import canvas
from reportlab.lib import pagesizes
from pathlib import Path

import copy
import io
import os
import multiprocessing


class Area(Enum):
    TOP_LEFT = 0
    TOP_RIGHT = 1
    BOTTOM_LEFT = 2
    BOTTOM_RIGHT = 3


class RedactionStyle(Enum):
    SOLID = ((0, 0, 0), (0, 0, 0), (1, 1, 1))
    OUTLINE = ((0, 0, 0), (1, 1, 1), (0, 0, 0))

    def __init__(self, stroke, fill, text):
        self.stroke = stroke
        self.fill = fill
        self.text = text


class Marisol(object):

    def __init__(self, prefix, fill, start, area=Area.BOTTOM_RIGHT, x=300, y=30, rotation=0, manual=True,
                 output_dir: str='.'):
        """
        Marisol Base Class - A collection of documents to be bates numbered.

        Args:
            prefix (str): Bates number prefix
            fill (int): Length for zero-filling
            start (int): Starting bates number
            area (Area): Area in which to place the bates number.
            x (int): Horizontal position of text. Text moves to the right as x increases.
            y (int): Vertical position of text. Text moves up as y increases.
            rotation (int): angle of rotation of text.
            manual (bool): whether to manually position text.
            output_dir (str): location to save the stamped documents.
        """
        self.prefix = prefix
        self.fill = fill
        self.start = start
        self.area = area
        self.x = x
        self.y = y
        self.rotation = rotation
        self.manual = manual
        self.output_dir = output_dir

        self.index = 0
        self.number = 0

        self.documents = []
        self.overwrite = False

    def __getitem__(self, key):
        return self.documents[key]

    def __len__(self):
        return len(self.documents)

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self):
            raise StopIteration
        self.index += 1
        return self.documents[self.index-1]

    def _save_document(self, document):
        """
        Internal method called by thread pool executor.

        Args:
            document (Document):  The document to save.

        Returns:
            (str, bool): The file name saved to and success or failure.
        """
        save_path = str(Path(self.output_dir) / document.savename)
        try:
            filename = document.save(filename=save_path, overwrite=self.overwrite)
        except FileExistsError:
            return "EXISTS", False
        else:
            return filename, True

    def append(self, file):
        """
        Add a document to the collection.

        Args:
            file (str or file-like object): PDF file or file name to add.

        Returns:
            marisol.Marisol: The current Marisol instance.
        """
        d = Document(file, self.prefix, self.fill, self.start+self.number, self.area,
                     self.x, self.y, self.rotation, self.manual)
        self.number += len(d)
        self.documents.append(d)
        return self

    def save(self, overwrite=False, threads=multiprocessing.cpu_count()*6):
        """Save all documents using a thread pool executor

        Args:
            overwrite (bool, optional): Switch to allow overwriting of existing files.
            threads (int, optional): The number of threads to use when processing.  Defaults to the number of cores
                times six.

        Returns:
            list: each file name and true or false indicating success or failure
        """
        self.overwrite = overwrite
        with futures.ThreadPoolExecutor(threads) as executor:
            results = executor.map(self._save_document, self)
        return list(results)


class Document(object):

    def __init__(self, file, prefix, fill, start, area, x=300, y=30, rotation=0, manual=True):
        """
        Represents a document to be numbered.

        Args:
            file (): PDF file associated with this document.
            prefix (str): Bates number prefix.
            fill (int): Length to zero-pad number to.
            start (int): Number to start with.
            area (Area): Area on the document where the number should be drawn
            x (int): Horizontal position of text. Text moves right as x increases
            y (int): Vertical position of text. Text moves up as y increases
            rotation (int): angle of rotation of text.
            manual (bool): whether to manually position the text
        """
        self.savename = os.path.splitext(os.path.basename(file))[0]
        
        try:
            self.file = io.BytesIO(file.read())
        except AttributeError:
            with open(file, "rb") as file:
                self.file = io.BytesIO(file.read())
        
        self.reader = PdfFileReader(self.file)
        self.prefix = prefix
        self.fill = fill
        self.start = copy.copy(start)
        self.area = area
        self.x = x
        self.y = y
        self.rotation = rotation
        self.manual = manual

        self.overlays = {x: None for x in Area}
        self.overlays[area] = BatesOverlay(None, self.area, x=self.x, y=self.y, rotation=self.rotation, manual=self.manual)

        self.index = 0

        self.pages = []
        for num, page in enumerate(self.reader.pages):
            p = Page(self, page, self.prefix, self.fill, self.start + num)
            self.pages.append(p)

    def __getitem__(self, k):
        return self.pages[k]

    def __len__(self):
        return self.reader.numPages

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self):
            raise StopIteration
        self.index += 1
        return self.pages[self.index-1]

    def __str__(self):
        return "{begin} - {end}".format(begin=self.begin, end=self.end)

    @property
    def begin(self):
        """
        Beginning bates number for this document.

        Returns:
            str: Bates number of the first page of the document.
        """
        num = str(self.start)
        num = num.zfill(self.fill)
        return "{prefix}{num}".format(prefix=self.prefix, num=num)

    @property
    def end(self):
        """
        Ending bates number for the document

        Returns:
            str: Bates number of the last page of the document.
        """
        num = str(self.start+len(self)-1)
        num = num.zfill(self.fill)
        return "{prefix}{num}".format(prefix=self.prefix, num=num)

    def save(self, filename=None, overwrite=False):
        """
        Applies the bates numbers and saves to file.

        Args:
            filename (str): Path where the PDF should be saved.
            overwrite (bool): Switch to allow overwriting of existing files.

        Returns:
            str: Path where the file was saved.

        Raises:
            FileExistsError: When the file already exists and overwrite is not enabled.
        """
        if filename is None: 
            filename = "{begin}.pdf".format(begin=self.begin)
        else:
            filename += f"_{str(self.start).zfill(self.fill)}.pdf"

        if os.path.exists(filename) and not overwrite:
            raise FileExistsError("PDF file {} already exists and overwrite is disabled.".format(filename))

        with open(filename, "wb") as out_file:
            writer = PdfFileWriter()
            for page in self:
                page.apply()
                writer.addPage(page.page)
            writer.write(out_file)
        return filename

    def add_overlay(self, overlay):
        """
        Add an overlay to the page in addition to the bates stamp.

        Args:
            overlay (Marisol.GenericTextOverlay):  Overlay to apply

        Raises:
            ValueError:  When area is already reserved for Bates Stamp
        """
        area = overlay.area
        if isinstance(self.overlays[area], BatesOverlay):
            raise ValueError("Area {} is already reserved for bates stamp.".format(area))
        else:
            self.overlays[area] = overlay
        return self


class Page(object):

    def __init__(self, document, page, prefix, fill, start):
        """
        Represents a page within a document that will be bates numbered.

        Args:
            document (Marisol.Document):  Parent document
            page (PyPdf2.pdf.PageObject): PDF page associated with this page
            prefix (str): Bates number prefix.
            fill (int): Length to zero-pad number to.
            start (int): Number to start with.
        """
        self.document = document
        self.page = page
        self.prefix = prefix
        self.fill = fill
        self.start = start

        self.height = float(self.page.mediaBox.upperRight[1])
        self.width = float(self.page.mediaBox.lowerRight[0])

        self.canvas_file = io.BytesIO()
        self.canvas = canvas.Canvas(self.canvas_file, pagesize=(self.width, self.height))

        self.redactions = []

    def __str__(self):
        return self.number

    def add_redaction(self, redaction):
        """
        Add a redaction to the page.

        Args:
            redaction (Marisol.Redaction):  Redaction to add to the page.
        """
        position = redaction.position
        size = redaction.size
        if position[0]+size[0] > self.width or position[1]+size[1] > self.height:
            raise OutsideBoundariesError("Redaction with position {} and \
            size {} is outside of page ({},{})".format(position, size, self.width, self.height))
        self.redactions.append(redaction)
        return self

    def apply(self):
        """
        Applies all requested overlays to the page

        Returns:
            bool
        """
        for overlay in self.document.overlays.values():
            if isinstance(overlay, BatesOverlay):
                overlay.text = self.number
                overlay.apply(self.canvas)
            elif isinstance(overlay, GenericTextOverlay):
                overlay.apply(self.canvas)

        for redaction in self.redactions:
            redaction.apply(self.canvas)

        self.canvas.showPage()
        self.canvas.save()

        self.canvas_file.seek(0)
        reader = PdfFileReader(self.canvas_file)
        overlay_page = reader.getPage(0)
        self.page.mergePage(overlay_page)
        return True

    @property
    def number(self):
        """
        The bates number for the page.

        Returns:
            str: Bates number.
        """
        num = str(self.start)
        num = num.zfill(self.fill)
        return "{prefix}{num}".format(prefix=self.prefix, num=num)


class GenericTextOverlay(object):

    def __init__(self, text, area, x=300, y=30, rotation=0, manual=True):
        self.text = text
        self.area = area
        self.x = x
        self.y = y
        self.rotation = rotation
        self.manual = manual

    def apply(self, c):
        """
        Applies the bates number to a canvas.

        Args:
             c (canvas.Canvas): canvas to apply the overlay to
        """
        position_left, position_bottom = self.position(c, self.x, self.y, manual=self.manual)
        c.saveState()
        c.translate(position_left, position_bottom)
        c.rotate(self.rotation)
        c.drawCentredString(0, 0, self.text)
        c.restoreState()

    def position(self, c, x, y, h=15, manual=True):
        """
        Get the appropriate position on the page for the current text given an area.

        Args:
            c (canvas.Canvas): Page to get the positioning for
            x (int): Horizontal position of text. Text moves right as x increases
            y (int): Vertical position of text. Text moves up as y increases
            h (int): units from bottom or top of page. Default is 15

        Returns:
            tuple: the position
        """
        if manual:
            return x, y #(300, 30) is roughly center 
        else:
            if self.area in [Area.BOTTOM_LEFT, Area.BOTTOM_RIGHT]:  # top
                from_bottom = c._pagesize[1] - h  # 15 up from bottom of page
            elif self.area in [Area.TOP_LEFT, Area.TOP_RIGHT]:  # bottom
                from_bottom = h  # 15 down from top of page

            if self.area in [Area.TOP_LEFT, Area.BOTTOM_LEFT]:  # left
                from_left = h
            elif self.area in [Area.TOP_RIGHT, Area.BOTTOM_RIGHT]:  # right
                offset = h  # initial offset
                offset += c.stringWidth(self.text)  # offset for text length
                from_left = c._pagesize[0]-offset
            return 30, c._pagesize[0] - c.stringWidth(self.text) 
        

class BatesOverlay(GenericTextOverlay):
    pass


class StaticOverlay(GenericTextOverlay):
    pass


class Redaction(object):

    def __init__(self, position, size, text=None, style=RedactionStyle.SOLID):
        """

        Args:
            position (tuple): from-left and from-bottom position to draw redaction at in points
            size (tuple): width and height of the redaction in points.
            text (str):
            style (Marisol.RedactionStyle):
        """
        self.position = position
        self.size = size

        # center of the drawn redaction (from-left, from-bottom)
        self.center = (self.position[0]+self.size[0]/2,
                       (self.position[1]+self.size[1]/2)-5.0)

        self.text = text
        self.style = style

    def apply(self, c):
        """
        Apply the redaction to a canvas.

        Args:
            c (Canvas): canvas to apply the redaction to.
        """
        page_width = c._pagesize[0]
        page_height = c._pagesize[1]

        c.setFont("Helvetica", 10)

        c.setStrokeColorRGB(*self.style.stroke)
        c.setFillColorRGB(*self.style.fill)

        c.rect(*self.position+self.size, fill=1)

        if self.text is not None:
            c.setStrokeColorRGB(*self.style.text)
            c.setFillColorRGB(*self.style.text)
            c.drawCentredString(self.center[0], self.center[1], self.text)


class OutsideBoundariesError(ValueError):
    """Raised when an item is drawn outside the page boundaries."""
    pass