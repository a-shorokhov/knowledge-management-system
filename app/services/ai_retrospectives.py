import json
import re

from sqlalchemy.exc import SQLAlchemyError

from adapters.ai.yandex import AIError
from core.exceptions import LaunchNotFoundException
from services.rag import SYSTEM_RULES


HEADINGS = ('Подтверждённые наблюдения', 'Ограничения данных', 'Повторяющиеся проблемы', 'Рекомендации')
RETROSPECTIVE_RULES = SYSTEM_RULES + (
    ' Подготовь ретроспективу проведения учебного модуля. analyzed — анализируемый запуск, '
    'comparison — другой запуск для сравнения; не смешивай их годы и результаты. '
    'Форма описывает планы; заметки и ручная рефлексия — сообщения преподавателя. '
    'Наличие предложения или файла не доказывает проведение мероприятия. '
    'Не делай вывод об эффективности по несопоставимым числам обращений и студентов. '
    'В материалах переданы только Top-5 фрагментов каждого запуска: это выборка, '
    'не полная статистика по всем файлам. Укажи этот предел, если фрагменты используются. '
    'Статусы pending, processing, failed означают, что содержимое соответствующих файлов не учтено. '
    'При пустых формах или недостатке данных явно укажи ограничения; не выдумывай события. '
    'Пиши рекомендации как предложения. Используй отдельные ссылки [S1] [S2], без объединения в скобках. '
    'Ответ оформи Markdown строго с четырьмя заголовками второго уровня в указанном порядке:\n' +
    '\n'.join('## ' + heading for heading in HEADINGS)
)
SEARCH_QUESTION = 'Итоги проведения: цели и результаты обучения, трудности студентов, обратная связь, повторяющиеся проблемы, внесённые изменения и предложения по улучшению.'


class AIRetrospectiveService:
    def __init__(self, repository, rag, ai):
        self.repository = repository
        self.rag = rag
        self.ai = ai

    def generate(self, user_id, launch_id, compared_to_launch_id):
        if compared_to_launch_id == launch_id:
            raise AIError('RETROSPECTIVE_SAME_LAUNCH', 'Нельзя сравнивать запуск с самим собой', 422)
        snapshots = []
        for selected in ([launch_id] if compared_to_launch_id is None else [launch_id, compared_to_launch_id]):
            snapshot = self.repository.get_context(selected, user_id)
            if snapshot is None:
                raise LaunchNotFoundException()
            if snapshots and snapshots[0]['launch']['module_id'] != snapshot['launch']['module_id']:
                raise AIError('RETROSPECTIVE_DIFFERENT_MODULE', 'Сравнивать можно только запуски одного модуля', 422)
            if len(snapshot['notes']) > 200 or len(snapshot['materials']) > 200:
                raise AIError('RETROSPECTIVE_CONTEXT_LIMIT', 'Анализ поддерживает до 200 заметок и 200 материалов на запуск', 413)
            snapshots.append(snapshot)
        self.repository.finish_read()
        sources = []
        payload = {'launches': []}

        def source(kind, data, selected):
            item = {'source_id': f'S{len(sources) + 1}', 'kind': kind, 'launch_id': selected, 'data': data}
            sources.append(item)
            return item

        vector = None
        for index, snapshot in enumerate(snapshots):
            launch = snapshot['launch']
            items = [source('launch', launch, launch['id'])]
            if snapshot['design'] and snapshot['design'].get('data'):
                items.append(source('design', snapshot['design'], launch['id']))
            for note in snapshot['notes']:
                items.append(source('note', note, launch['id']))
            if snapshot['reflection']:
                items.append(source('manual_reflection', snapshot['reflection'], launch['id']))
            payload['launches'].append({'launch_id': launch['id'], 'role': 'analyzed' if index == 0 else 'comparison',
                'sources': items, 'materials': snapshot['materials'], 'file_retrieval': 'cosine Top-5, not exhaustive'})
        if len(json.dumps(payload, ensure_ascii=False, default=str)) > 45000:
            raise AIError('RETROSPECTIVE_CONTEXT_LIMIT', 'Данные запуска превышают допустимый объём для анализа', 413)
        for snapshot, run in zip(snapshots, payload['launches']):
            if any(m['indexing_status'] == 'ready' and not m.get('deletion_pending', False) for m in snapshot['materials']):
                if vector is None:
                    vector = self.ai.embed(SEARCH_QUESTION, query=True)
                rows = self.rag.search(user_id, snapshot['launch']['module_id'], run['launch_id'], vector)
                run['sources'].extend(source('file_chunk', row, run['launch_id']) for row in rows)
        self.repository.finish_read()
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        if len(encoded) > 60000:
            raise AIError('RETROSPECTIVE_CONTEXT_LIMIT', 'Данные запуска превышают допустимый объём для анализа', 413)
        result = self.ai.generate([{'role': 'system', 'content': RETROSPECTIVE_RULES},
                                   {'role': 'user', 'content': encoded}], max_completion_tokens=8192)
        content = result['answer']
        actual_headings = re.findall(r'^##\s+(.+?)\s*$', content, re.MULTILINE)
        citations = set(re.findall(r'\[([^\[\]\n]+)\]', content))
        allowed = {item['source_id'] for item in sources}
        if actual_headings != list(HEADINGS) or not citations or not citations.issubset(allowed):
            raise AIError('RETROSPECTIVE_INVALID_REPORT', 'ИИ вернул отчёт без нужных разделов или корректных источников')
        references = []
        for item in sources:
            if item['source_id'] not in citations:
                continue
            data = item['data']
            label = {'launch': 'Данные запуска', 'design': 'Форма запуска', 'note': 'Заметка преподавателя',
                     'manual_reflection': 'Ручная рефлексия', 'file_chunk': 'Фрагмент материала'}[item['kind']]
            parts = [f'[{item["source_id"]}] {label}', f'launch_id={item["launch_id"]}']
            for key in ('id', 'title', 'year', 'material_id', 'chunk_index', 'page_number', 'slide_number', 'sheet_name', 'cell_range'):
                if data.get(key) is not None:
                    parts.append(f'{key}={json.dumps(data[key], ensure_ascii=False)}')
            references.append('; '.join(parts))
        content += '\n\n### Источники на момент генерации\n' + '\n'.join('- ' + item for item in references)
        try:
            report = self.repository.save_report(user_id, snapshots[0]['launch']['module_id'], launch_id, compared_to_launch_id, content)
        except SQLAlchemyError:
            raise AIError('RETROSPECTIVE_SAVE_FAILED', 'Не удалось сохранить отчёт', 503) from None
        if report is None:
            raise AIError('RETROSPECTIVE_CONTEXT_CHANGED', 'Запуск удалён или доступ изменился во время генерации', 409)
        return report

    def history(self, user_id, launch_id, limit, offset):
        reports = self.repository.get_history(launch_id, user_id, limit, offset)
        if reports is None:
            raise LaunchNotFoundException()
        return reports
