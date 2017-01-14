from concurrent import futures

from PyPDF2 import PdfFileReader, PdfFileWriter
from reportlab.pdfgen import canvas
from reportlab.lib import pagesizes

import copy
import io
import multiprocessing


class Marisol(object):
    """ A collection of documents to be bates numbered. """
    def __init__(self, prefix, fill, start):
        """
        Base Class

        Args:
            prefix (str): Bates number prefix
            fill (int): Length for zero-filling
            start (int): Starting bates number
        """
        self.prefix = prefix
        self.fill = fill
        self.start = start
        self.index = 0
        self.number = 0

        self.documents = []

    def __len__(self):
        return len(self.documents)

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self):
            raise StopIteration
        d = Document(self.documents[self.index],
                     self.prefix,
                     self.fill,
                     self.start+self.number)
        self.index += 1
        self.number += len(d)
        return d

    def _save_document(self, document):
        """
        Internal method called by thread pool executor.

        Args:
            document (Document):  The document to save.

        Returns:
            (str, bool): The file name saved to and success or failure.
        """
        try:
            filename = document.save()
        except Exception as err:
            return "ERROR", False
        else:
            return filename, True

    def append(self, file):
        """
        Add a document to the collection.

        Args:
            file (str or file-like object):  PDF file or file name to add.

        Returns:
            Marisol
        """
        self.documents.append(file)
        return self

    def save_all(self, threads=multiprocessing.cpu_count()*6):
        """Save all documents using a thread pool executor

        Args:
            threads (int):  The number of threads to use when processing.

        Returns:
            list: each file name and true or false indicating success or failure
        """
        with futures.ThreadPoolExecutor(threads) as executor:
            results = executor.map(self.save_doc, self)
        return list(results)


class Document(object):
    """
    Class representing documents/files.

    :param file:
    :param prefix:
    :param fill:
    :param start:
    :type file:  File or file-like object
    :type prefix: str
    :type fill: int
    :type start: int
    """
    def __init__(self, file, prefix, fill, start):
        try:
            self.file = io.BytesIO(file.read())
        except AttributeError:
            with open(file, "rb") as file:
                self.file = io.BytesIO(file.read())
        self.reader = PdfFileReader(self.file)
        self.prefix = prefix
        self.fill = fill
        self.start = copy.copy(start)
        self.index = 0

    def __len__(self):
        return self.reader.numPages

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self):
            raise StopIteration
        p = Page(self.reader.getPage(self.index),
                 self.prefix,
                 self.fill,
                 self.start+self.index)
        self.index += 1
        return p

    def __str__(self):
        return "{begin} - {end}".format(begin=self.begin, end=self.end)

    @property
    def begin(self):
        """
        Beginning bates number for the document.

        :return: Bates number of first page in document.
        :rtype: str
        """
        num = str(self.start)
        num = num.zfill(self.fill)
        return "{prefix}{num}".format(prefix=self.prefix, num=num)

    @property
    def end(self):
        """Ending bates number for the document"""
        num = str(self.start+len(self)-1)
        num = num.zfill(self.fill)
        return "{prefix}{num}".format(prefix=self.prefix, num=num)

    def save(self, filename=None):
        """
        Applies the bates numbers and saves to file.

        :param filename: Path where the PDF should be saved
        :type filename: str
        :return: Path where file was saved
        :rtype: str
        """
        filename = filename or "{begin}.pdf".format(begin=self.begin)
        with open(filename, "wb") as out_file:
            writer = PdfFileWriter()
            for page in self:
                page.apply()
                writer.addPage(page.page)
            writer.write(out_file)
        return filename


class Page(object):

    def __init__(self, page, prefix, fill, start):
        self.page = page
        self.prefix = prefix
        self.fill = fill
        self.start = start
        self.height = self.page.mediaBox.upperRight[1]
        self.width = self.page.mediaBox.lowerRight[0]

    def __str__(self):
        return self.number

    def apply(self):
        """Applies the bates number overlay to the page"""
        overlay = Overlay(self.size, self.number)
        self.page.mergePage(overlay.page())

    @property
    def number(self):
        """
        The bates number for the page.
        :return: Bates number
        :rtype: str
        """
        num = str(self.start)
        num = num.zfill(self.fill)
        return "{prefix}{num}".format(prefix=self.prefix, num=num)

    @property
    def size(self):
        """
        Takes the dimensions of the original page and returns the name and dimensions of the corresponding reportlab
        pagesize.

        :return: A tuple containing the name of the page size and the dimensions (in a tuple)
        :rtype: (str, tuple)
        """
        dims = (float(self.width), float(self.height))
        for name in dir(pagesizes):
            size = getattr(pagesizes, name)
            if isinstance(size, tuple):
                if dims == size:
                    return name, size
        else:
            return ValueError("Unknown page size.")


class Overlay(object):

    def __init__(self, size, text):
        self.size_name, self.size = size
        self.text = text

        self.output = io.BytesIO()
        self.c = canvas.Canvas(self.output, pagesize=self.size)
        offset_right = 15 # initial offset
        offset_right += len(text)*7  # offset for text length
        self.c.drawString(self.size[0]-offset_right, 15, self.text)
        self.c.showPage()
        self.c.save()

    def page(self):
        """
        The page used to perform the overlay.
        :return: The page
        :rtype: PyPdf2.pdf.PageObject
        """
        self.output.seek(0)
        reader = PdfFileReader(self.output)
        return reader.getPage(0)


