import logging
import math
import time

import httpx


logger = logging.getLogger(__name__)


class AIError(Exception):
    def __init__(self, code, message, status_code=502):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def validate_embedding(values):
    try:
        if not isinstance(values, list) or len(values) != 256 or any(isinstance(x, bool) for x in values):
            raise ValueError
        vector = [float(x) for x in values]
        if not all(math.isfinite(x) for x in vector) or not any(vector):
            raise ValueError
        return vector
    except (TypeError, ValueError, OverflowError):
        raise AIError('AI_INVALID_EMBEDDING', 'ИИ вернул некорректный вектор') from None


class YandexAIAdapter:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=settings.AI_REQUEST_TIMEOUT_SECONDS, follow_redirects=False)

    def close(self):
        self.client.close()

    def _post(self, path, payload):
        key = self.settings.YANDEX_AI_API_KEY.get_secret_value()
        if not self.settings.AI_ENABLED or not key or not self.settings.YANDEX_AI_FOLDER_ID:
            raise AIError('AI_NOT_CONFIGURED', 'Задайте настройки Yandex AI Studio и включите AI_ENABLED', 503)
        for attempt in range(3):
            try:
                response = self.client.post('https://ai.api.cloud.yandex.net/' + path,
                    json=payload, headers={'Authorization': 'Bearer ' + key, 'x-data-logging-enabled': 'false'})
            except httpx.TimeoutException:
                raise AIError('AI_TIMEOUT', 'Превышено время ожидания ИИ', 504) from None
            except httpx.HTTPError:
                raise AIError('AI_UNAVAILABLE', 'Сервис ИИ недоступен', 503) from None
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            if response.status_code != 200:
                code = 'AI_AUTH_FAILED' if response.status_code in (401, 403) else 'AI_RATE_LIMIT' if response.status_code == 429 else 'AI_UPSTREAM_ERROR'
                raise AIError(code, 'Запрос к сервису ИИ не выполнен', 503 if response.status_code == 429 else 502)
            try:
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError
                return result
            except ValueError:
                raise AIError('AI_INVALID_RESPONSE', 'Сервис ИИ вернул некорректный ответ') from None

    def embed(self, text, *, query=False):
        model = self.settings.AI_EMBED_QUERY_MODEL if query else self.settings.AI_EMBED_DOC_MODEL
        result = self._post('foundationModels/v1/textEmbedding', {
            'modelUri': f'emb://{self.settings.YANDEX_AI_FOLDER_ID}/{model}', 'text': text, 'dim': '256'})
        logger.info('ai_embedding tokens=%s', result.get('numTokens'))
        return validate_embedding(result.get('embedding'))

    def generate(self, messages, *, max_completion_tokens=32768):
        result = self._post('v1/chat/completions', {
            'model': f'gpt://{self.settings.YANDEX_AI_FOLDER_ID}/{self.settings.AI_LLM_MODEL}',
            'messages': messages, 'temperature': 0,
            'max_completion_tokens': max_completion_tokens, 'stream': False})
        try:
            choice = result['choices'][0]
            message = choice['message']
            if not isinstance(message, dict):
                raise ValueError
            answer = message.get('content')
            reason = choice.get('finish_reason')
        except (KeyError, IndexError, TypeError, ValueError):
            raise AIError('AI_INVALID_RESPONSE', 'Сервис ИИ вернул ответ неожиданного формата') from None
        raw_usage = result.get('usage')
        usage = {key: value for key, value in raw_usage.items()
                 if key in {'prompt_tokens', 'completion_tokens', 'total_tokens'} and type(value) is int and value >= 0} if isinstance(raw_usage, dict) else {}
        safe_reason = reason if reason in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call') else 'unknown'
        logger.info('ai_generation finish_reason=%s prompt_tokens=%s completion_tokens=%s',
                    safe_reason, usage.get('prompt_tokens'), usage.get('completion_tokens'))
        if reason == 'length':
            raise AIError('AI_OUTPUT_LIMIT', 'Модель исчерпала лимит генерации и не закончила ответ. Отчёт не сохранён.')
        if reason == 'content_filter' or message.get('refusal'):
            raise AIError('AI_CONTENT_FILTER', 'Ответ заблокирован правилами сервиса ИИ')
        if reason != 'stop':
            raise AIError('AI_UNFINISHED_RESPONSE', 'Сервис ИИ не завершил генерацию ответа')
        if not isinstance(answer, str) or not answer.strip():
            raise AIError('AI_EMPTY_RESPONSE', 'Сервис ИИ вернул пустой ответ')
        return {'answer': answer, 'usage': usage, 'finish_reason': reason}
