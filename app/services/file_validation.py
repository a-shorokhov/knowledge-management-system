import io
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
from zlib import error as ZlibError


MAX_OFFICE_ENTRIES = 2000
MAX_OFFICE_UNPACKED_SIZE = 50 * 1024 * 1024
MAX_PACKAGE_XML_SIZE = 256 * 1024
CONTENT_TYPES_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_FORMATS = {
    "docx": ("word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml", "wordprocessingml", "document"),
    "xlsx": ("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml", "spreadsheetml", "workbook"),
    "pptx": ("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml", "presentationml", "presentation"),
}


def _contains_dtd(data: bytes):
    return b"<!DOCTYPE" in data.replace(b"\x00", b"").upper()


def _read_package_xml(archive: ZipFile, name: str):
    if archive.getinfo(name).file_size > MAX_PACKAGE_XML_SIZE:
        raise ValueError("Слишком большой служебный XML")
    with archive.open(name) as stream:
        data = stream.read(MAX_PACKAGE_XML_SIZE + 1)
    if len(data) > MAX_PACKAGE_XML_SIZE or _contains_dtd(data):
        raise ValueError("Недопустимый служебный XML")
    return ElementTree.fromstring(data)


def _is_office_file(data: bytes, extension: str):
    if not data.startswith(b"PK\x03\x04"):
        return False
    part, content_type, namespace, root_name = OFFICE_FORMATS[extension]
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > MAX_OFFICE_ENTRIES or len(names) != len(set(names)):
                return False
            if sum(entry.file_size for entry in entries) > MAX_OFFICE_UNPACKED_SIZE:
                return False
            if any(entry.flag_bits & 1 or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED} for entry in entries):
                return False
            if not {"[Content_Types].xml", "_rels/.rels", part}.issubset(names):
                return False

            types = _read_package_xml(archive, "[Content_Types].xml")
            if types.tag != f"{{{CONTENT_TYPES_NAMESPACE}}}Types":
                return False
            if not any(item.get("PartName") == f"/{part}" and item.get("ContentType") == content_type for item in types.findall(f"{{{CONTENT_TYPES_NAMESPACE}}}Override")):
                return False

            relationships = _read_package_xml(archive, "_rels/.rels")
            if relationships.tag != f"{{{RELATIONSHIPS_NAMESPACE}}}Relationships":
                return False
            if not any(item.get("Target", "").lstrip("/") == part and item.get("Type", "").endswith("/officeDocument") and item.get("TargetMode") != "External" for item in relationships.findall(f"{{{RELATIONSHIPS_NAMESPACE}}}Relationship")):
                return False

            with archive.open(part) as stream:
                prefix = stream.read(8192)
            if _contains_dtd(prefix):
                return False
            parser = ElementTree.XMLPullParser(events=("start",))
            parser.feed(prefix)
            first = next(parser.read_events(), None)
            allowed_roots = {
                f"{{http://schemas.openxmlformats.org/{namespace}/2006/main}}{root_name}",
                f"{{http://purl.oclc.org/ooxml/{namespace}/main}}{root_name}",
            }
            return first is not None and first[1].tag in allowed_roots
    except (BadZipFile, LookupError, ValueError, RuntimeError, NotImplementedError, OSError, ElementTree.ParseError, ZlibError):
        return False


def is_valid_file_content(data: bytes, extension: str):
    if extension == "png":
        return len(data) >= 45 and data.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") and data.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    if extension == "jpg":
        return len(data) >= 5 and data.startswith(b"\xff\xd8\xff") and data.rstrip().endswith(b"\xff\xd9")
    if extension == "pdf":
        return re.match(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r|\n)", data) is not None and b"%%EOF" in data[-1024:]
    if extension in OFFICE_FORMATS:
        return _is_office_file(data, extension)
    if extension in {"txt", "csv"}:
        try:
            encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            text = data.decode(encoding)
        except UnicodeDecodeError:
            return False
        return bool(text) and all(character in "\t\n\r" or ord(character) >= 32 and not 127 <= ord(character) <= 159 for character in text)
    return False
