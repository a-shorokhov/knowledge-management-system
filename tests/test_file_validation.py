import io
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from services.file_validation import is_valid_file_content
from file_samples import OFFICE_PARTS, PNG_DATA, JPEG_DATA, PDF_DATA, office_sample


def modified_office(extension, changes):
    result = io.BytesIO()
    with ZipFile(io.BytesIO(office_sample(extension))) as original, ZipFile(result, 'w', ZIP_DEFLATED) as updated:
        for name in original.namelist():
            data = changes.get(name, original.read(name))
            if data is not None:
                updated.writestr(name, data)
    return result.getvalue()


class FileValidationTests(unittest.TestCase):
    def test_supported_signatures(self):
        for extension, data in [('png', PNG_DATA), ('jpg', JPEG_DATA), ('pdf', PDF_DATA)]:
            with self.subTest(extension=extension):
                self.assertTrue(is_valid_file_content(data, extension))

    def test_executable_signatures_rejected_for_every_allowed_format(self):
        for binary in [b'MZ\x90\x00' + b'\x00'*128, b'\x7fELF\x00\x00', b'\xcf\xfa\xed\xfe\x00']:
            for extension in ['png', 'jpg', 'pdf', 'docx', 'xlsx', 'pptx', 'txt', 'csv']:
                with self.subTest(extension=extension):
                    self.assertFalse(is_valid_file_content(binary, extension))

    def test_truncated_signatures_and_wrong_format(self):
        for data, extension in [(PNG_DATA[:8], 'png'), (JPEG_DATA[:3], 'jpg'), (b'%PDF-1.7\nmissing end marker', 'pdf'), (b'%PDF-nonsense\n%%EOF', 'pdf'), (PNG_DATA, 'pdf'), (PDF_DATA, 'png')]:
            self.assertFalse(is_valid_file_content(data, extension))

    def test_office_packages_and_wrong_office_type(self):
        for extension in ['docx', 'xlsx', 'pptx']:
            self.assertTrue(is_valid_file_content(office_sample(extension), extension))
        self.assertFalse(is_valid_file_content(office_sample('docx'), 'xlsx'))
        self.assertFalse(is_valid_file_content(office_sample('xlsx'), 'pptx'))

    def test_ordinary_zip_is_not_office_document(self):
        result = io.BytesIO()
        with ZipFile(result, 'w') as archive:
            archive.writestr('hello.txt', 'hello')
        for extension in ['docx', 'xlsx', 'pptx']:
            self.assertFalse(is_valid_file_content(result.getvalue(), extension))

    def test_invalid_manifest_and_main_xml_rejected(self):
        part = OFFICE_PARTS['docx'][0]
        for changes in [
            {'[Content_Types].xml': None},
            {'[Content_Types].xml': b'not XML'},
            {'[Content_Types].xml': b'<?xml version="1.0" encoding="unknown-encoding"?><Types/>'},
            {'_rels/.rels': b'not XML'},
            {part: b'MZ\x00not a Word XML'},
            {part: b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>'},
        ]:
            self.assertFalse(is_valid_file_content(modified_office('docx', changes), 'docx'))

    def test_office_dtd_and_oversized_manifest_rejected(self):
        for data in [b'<!DOCTYPE Types [<!ENTITY x "test">]><Types/>', b'<?xml version="1.0"?>' + b' '* (256*1024)]:
            self.assertFalse(is_valid_file_content(modified_office('docx', {'[Content_Types].xml': data}), 'docx'))

    def test_office_archive_limits(self):
        data=office_sample('docx')
        with patch('services.file_validation.MAX_OFFICE_ENTRIES', 2):
            self.assertFalse(is_valid_file_content(data, 'docx'))
        with patch('services.file_validation.MAX_OFFICE_UNPACKED_SIZE', 1):
            self.assertFalse(is_valid_file_content(data, 'docx'))

    def test_text_encodings_and_binary_control_characters(self):
        text='Тестовый текст\nВторая строка\tзначение'
        for encoding in ['utf-8', 'utf-8-sig', 'utf-16']:
            self.assertTrue(is_valid_file_content(text.encode(encoding), 'txt'))
        self.assertTrue(is_valid_file_content(b'name;value\nitem;1\n', 'csv'))
        self.assertFalse(is_valid_file_content(b'a\x00b', 'txt'))
        self.assertFalse(is_valid_file_content(b'\x80\x81\xff', 'csv'))
        self.assertFalse(is_valid_file_content(b'', 'txt'))


if __name__ == '__main__':
    unittest.main()
