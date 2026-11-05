import csv
import io
from pathlib import Path

from adapters.ai.yandex import AIError
from services.file_validation import is_valid_file_content


MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 500_000
MAX_CHUNKS = 600


def extract_chunks(data: bytes, filename: str):
    extension = Path(filename).suffix.lower().lstrip('.')
    if extension not in {'txt', 'csv', 'pdf', 'docx', 'pptx', 'xlsx'}:
        raise AIError('INDEX_UNSUPPORTED_FORMAT', 'Формат требует OCR или не поддерживается', 422)
    if not data or len(data) > MAX_BYTES or not is_valid_file_content(data, extension):
        raise AIError('INDEX_INVALID_FILE', 'Файл повреждён или превышает лимит', 422)
    chunks = []
    total = 0

    def append(text, **location):
        nonlocal total
        text = text.strip()
        if not text:
            return
        total += len(text)
        if total > MAX_TEXT:
            raise AIError('INDEX_TEXT_LIMIT', 'Слишком большой объём извлечённого текста', 422)
        for start in range(0, len(text), 880):
            content = text[start:start + 1000]
            chunks.append({'chunk_index': len(chunks), 'content': content, **location})
            if len(chunks) > MAX_CHUNKS:
                raise AIError('INDEX_CHUNK_LIMIT', 'Слишком много фрагментов', 422)
            if start + 1000 >= len(text):
                break

    try:
        if extension in {'txt', 'csv'}:
            encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
            text = data.decode(encoding)
            if extension == 'txt':
                append(text)
            else:
                for number, row in enumerate(csv.reader(io.StringIO(text)), 1):
                    append(f'Строка {number}: ' + ' | '.join(row))
        elif extension == 'pdf':
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted or len(reader.pages) > 300:
                raise AIError('INDEX_PDF_UNSUPPORTED', 'PDF зашифрован или содержит более 300 страниц', 422)
            for number, page in enumerate(reader.pages, 1):
                append(page.extract_text() or '', page_number=number)
        elif extension == 'docx':
            from docx import Document
            document = Document(io.BytesIO(data))
            for block in document.iter_inner_content():
                if hasattr(block, 'text'):
                    append(block.text)
                else:
                    for row in block.rows:
                        append(' | '.join(cell.text for cell in row.cells))
        elif extension == 'pptx':
            from pptx import Presentation
            for number, slide in enumerate(Presentation(io.BytesIO(data)).slides, 1):
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        append(shape.text, slide_number=number)
                    elif shape.has_table:
                        for row in shape.table.rows:
                            append(' | '.join(cell.text for cell in row.cells), slide_number=number)
        else:
            from openpyxl import load_workbook
            from openpyxl.utils import get_column_letter
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
            try:
                for sheet in book:
                    if sheet.max_row and sheet.max_row > 10000 or sheet.max_column and sheet.max_column > 200:
                        raise AIError('INDEX_SHEET_LIMIT', 'Лист превышает лимит 10000 строк или 200 столбцов', 422)
                    for number, row in enumerate(sheet.iter_rows(max_row=10001, max_col=min(sheet.max_column or 200, 200), values_only=True), 1):
                        if number > 10000:
                            raise AIError('INDEX_SHEET_LIMIT', 'Лист превышает лимит строк', 422)
                        cells = [(i, str(value)) for i, value in enumerate(row, 1) if value is not None]
                        if cells:
                            first, last = cells[0][0], cells[-1][0]
                            append(' | '.join(f'{get_column_letter(i)}{number}: {value}' for i, value in cells),
                                   sheet_name=sheet.title, cell_range=f'{get_column_letter(first)}{number}:{get_column_letter(last)}{number}')
            finally:
                book.close()
    except AIError:
        raise
    except Exception:
        raise AIError('INDEX_EXTRACTION_FAILED', 'Не удалось извлечь текст из файла', 422) from None
    if not chunks:
        raise AIError('INDEX_NO_TEXT', 'Текст не найден, работа со сканами и изображениями сейчас недоступна', 422)
    return chunks
