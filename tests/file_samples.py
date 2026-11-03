import base64
import io
import struct
import zlib
from zipfile import ZIP_DEFLATED, ZipFile


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


PNG_DATA = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">2I5B", 1, 1, 8, 2, 0, 0, 0)) + png_chunk(b"IDAT", zlib.compress(b"\0\xff\xff\xff")) + png_chunk(b"IEND", b"")
JPEG_DATA = base64.b64decode("/9j/4AAQSkZJRgABAQAASABIAAD/4QBMRXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAA6ABAAMAAAABAAEAAKACAAQAAAABAAAAAaADAAQAAAABAAAAAQAAAAD/7QA4UGhvdG9zaG9wIDMuMAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmACZjs+EJ+/8AAEQgAAQABAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMAAgICAgICAwICAwUDAwMFBgUFBQUGCAYGBgYGCAoICAgICAgKCgoKCgoKCgwMDAwMDA4ODg4ODw8PDw8PDw8PD//bAEMBAgICBAQEBwQEBxALCQsQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEP/dAAQAAf/aAAwDAQACEQMRAD8A/fyiiigD/9k=")
PDF_DATA = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
OFFICE_PARTS = {
    "docx": ("word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml", "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "document"),
    "xlsx": ("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml", "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "workbook"),
    "pptx": ("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml", "http://schemas.openxmlformats.org/presentationml/2006/main", "presentation"),
}


def office_sample(extension):
    part, content_type, namespace, tag = OFFICE_PARTS[extension]
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/{part}" ContentType="{content_type}"/></Types>')
        archive.writestr("_rels/.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="{part}"/></Relationships>')
        archive.writestr(part, f'<{tag} xmlns="{namespace}"/>')
    return buffer.getvalue()


SAMPLES = {
    "image/png": ("test.png", PNG_DATA),
    "image/jpeg": ("test.jpg", JPEG_DATA),
    "application/pdf": ("test.pdf", PDF_DATA),
    "text/plain": ("test.txt", "Пример текста".encode()),
    "text/csv": ("test.csv", b"name,value\nitem,1\n"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("test.docx", office_sample("docx")),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("test.xlsx", office_sample("xlsx")),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ("test.pptx", office_sample("pptx")),
}
