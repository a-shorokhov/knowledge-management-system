# KMS — Knowledge Management System

**KMS** — backend-система управления знаниями для преподавателей: образовательные модули, их повторные запуски, материалы, заметки и рефлексии. Проект помогает сохранять учебные наработки между семестрами и повторно использовать их без дублирования файлов.

API построен на **FastAPI**, данные хранятся в **PostgreSQL**, файлы — в **S3-совместимом объектном хранилище**. В ветке `ai-rag` дополнительно реализованы компоненты индексации документов, поиска по фрагментам и генерации ответов/ретроспектив через **Yandex AI Studio**.

> **Статус:** учебный MVP. ИИ-возможности относятся к ветке [`ai-rag`](https://github.com/a-shorokhov/knowledge-management-system/tree/ai-rag) (PR #14) до её слияния в `main`. Наличие исходного кода и тестов не заменяет проверку фактического развёртывания с настроенными PostgreSQL, S3 и Yandex AI Studio.

## Возможности

- **Пользователи:** регистрация, вход, JWT-аутентификация, операции с профилем.
- **Модули:** создание, просмотр, изменение и удаление собственных образовательных модулей.
- **Запуски модулей:** учебный год, семестр, статус, даты, количество участников, описание изменений; копирование предыдущего запуска.
- **Проектирование запуска:** структурированная форма (JSONB) с возможностью сохранения черновика.
- **Разделы и материалы:** организация материалов по разделам, порядок отображения, загрузка, скачивание, замена и копирование.
- **S3-хранилище:** отдельно учитываются физические файлы (`stored_files`) и их использование в материалах (`materials`). Копии материалов могут ссылаться на один и тот же файл. Предусмотрена очистка неиспользуемых файлов и журнал отложенной очистки.
- **Заметки:** свободный текст, структурированные поля, приоритеты и статусы.
- **Ручная рефлексия:** результаты проведения запуска, проблемы и решения для следующих итераций.
- **ИИ-функции в `ai-rag`:** фоновая индексация документов, поиск релевантных фрагментов, ответы с указанием источников, генерация и сохранение ИИ-ретроспектив, в том числе сравнение запусков одного модуля.

## Технологии

| Компонент | Технология |
|---|---|
| HTTP API и Swagger/OpenAPI | Python, FastAPI, Pydantic |
| Работа с БД | SQLAlchemy, PostgreSQL 18, Alembic |
| Поиск по векторам | pgvector |
| Хранение файлов | S3 API (например, Yandex Object Storage) |
| Аутентификация | JWT, Argon2 для паролей |
| ИИ | Yandex AI Studio: DeepSeek V4.1 Flash, Text Embeddings v2 |
| Фоновая обработка | Отдельный Python worker |
| Инфраструктура | Docker, Docker Compose |
| Проверки | unittest, GitHub Actions |

## Архитектура

```text
Swagger / другой HTTP-клиент
              |
              v
      FastAPI + Pydantic
              |
        Depends / JWT
              |
              v
           Services
              |
              v
         Repositories
              |
              v
     SQLAlchemy / PostgreSQL

Материалы ----> S3-совместимое хранилище

AI worker ---> извлечение текста ---> embeddings ---> pgvector
RAG API -----> поиск с проверкой доступа ---> Yandex AI Studio
```

Слои разделяют обязанности: **API** принимает и валидирует запросы, **Service** управляет сценариями и бизнес-правилами, **Repository** выполняет операции с данными. Доступ к модулям и их содержимому ограничен владельцем: одного действительного JWT недостаточно для чтения чужих объектов.

Основные сущности: `users`, `modules`, `launches`, `run_sections`, `materials`, `stored_files`, `notes`, `launch_designs`, `launch_reflections`, `document_chunks`, `ai_retrospectives`.

> В коде физическая таблица запусков называется `launches` (не `module_runs`). Для связи с запуском используется `launch_id`. Для описания фактической БД ориентируйтесь на миграции Alembic, а не на устаревшие версии ERD.

## Быстрый запуск через Docker Compose

### 1. Подготовить конфигурацию

```bash
git clone https://github.com/a-shorokhov/knowledge-management-system.git
cd knowledge-management-system
git switch ai-rag
cp .env.example .env
```

Откройте `.env` и заполните минимум:

```dotenv
DB_USER=kms
DB_PASSWORD=replace_with_strong_password
DB_NAME=kms
SECRET_KEY=replace_with_long_random_secret_at_least_32_chars

S3_ENDPOINT=https://storage.yandexcloud.net
S3_ACCESS_KEY=your_s3_access_key
S3_SECRET_KEY=your_s3_secret_key
S3_BUCKET=your_bucket_name
S3_REGION=ru-central1

API_PORT=8000
CORS_ORIGINS=[]
```

`SECRET_KEY` можно сгенерировать командой:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Не добавляйте настоящий `.env`, API-ключи, пароли и токены в Git.** `.env.example` содержит только образцы переменных.

### 2. Включить ИИ при необходимости

В `.env`:

```dotenv
AI_ENABLED=true
YANDEX_AI_FOLDER_ID=your_folder_id
YANDEX_AI_API_KEY=your_yandex_ai_studio_api_key
AI_LLM_MODEL=deepseek-v4.1-flash
AI_EMBED_DOC_MODEL=text-embeddings-v2-doc/latest
AI_EMBED_QUERY_MODEL=text-embeddings-v2-query/latest
AI_EMBED_DIM=256
AI_TOP_K=5
AI_REQUEST_TIMEOUT_SECONDS=120
```

Для Yandex AI Studio используется **отдельный ключ**, не S3-ключ. При `AI_ENABLED=false` основная часть KMS может работать без вызовов ИИ-провайдера; ИИ-запросы требуют корректной конфигурации.

### 3. Запустить

```bash
docker compose up -d --build
```

API при запуске применяет миграции Alembic. Compose поднимает `api`, PostgreSQL с pgvector и `worker` для фоновой индексации.

- **Swagger UI:** <http://localhost:8000/docs>
- **OpenAPI JSON:** <http://localhost:8000/openapi.json>
- **ReDoc:** <http://localhost:8000/redoc>

Если переопределён `API_PORT`, используйте соответствующий порт. По умолчанию API доступен только на `127.0.0.1` хоста; для удалённого стенда требуется отдельная настройка доступа и сети.

Проверить состояние контейнеров и логи:

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker
```

Остановить контейнеры, **сохранив данные в томах**:

```bash
docker compose down
```

Не используйте `docker compose down -v`, если требуется сохранить базу данных.

## Работа через Swagger

1. Откройте `/docs`.
2. Выполните `POST /auth/register`, затем `POST /auth/login`.
3. Авторизуйтесь через **Authorize** с полученным Bearer JWT.
4. Создайте модуль через `POST /modules` и проверьте его через `GET /modules`.
5. Создайте запуск через `POST /modules/{module_id}/launches`.
6. Добавьте раздел, материал (загрузка через `multipart/form-data`) или заметку.
7. Проверьте копирование запуска и повторное использование файла.
8. При настроенной ИИ-интеграции дождитесь индексации документа и попробуйте `POST /ai/ask`.

Данные запроса для `POST /modules`:

```json
{
  "title": "Основы Python",
  "description": "Введение в программирование"
}
```

`owner_id` вводить не нужно: backend получает владельца из проверенного JWT. Лишние поля отклоняются Pydantic.

### Основные группы API

| Группа | Примеры маршрутов |
|---|---|
| Авторизация | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Модули | `POST /modules`, `GET /modules`, `PATCH /modules/{module_id}` |
| Запуски | `POST /modules/{module_id}/launches`, `POST /launches/{launch_id}/copy`, `GET /launches/{launch_id}/previous-context` |
| Разделы | `/launches/{launch_id}/sections`, `/sections/{section_id}` |
| Материалы | `/launches/{launch_id}/materials`, `/materials/{material_id}`, `/materials/{material_id}/download` |
| Заметки | `/launches/{launch_id}/notes`, `/notes/{note_id}` |
| Формы запусков | `GET /launch-design/template`, `GET/PUT /launches/{launch_id}/design` |
| Ручные рефлексии | `GET/PUT /launches/{launch_id}/reflection` |
| Файлы | `/stored-files`, `/stored-files/{file_id}`, `POST /stored-files/{file_id}/reindex` |
| ИИ (ветка `ai-rag`) | `POST /ai/ask`, `POST/GET /launches/{launch_id}/ai-retrospectives` |

Полные тела запросов, параметры и коды ответов смотрите в автоматически формируемом Swagger UI.

## Как работают ИИ-возможности

1. **Индексация.** Фоновый worker читает файл из S3, извлекает текст, делит его на фрагменты, получает embeddings и сохраняет их в `document_chunks`.
2. **Поиск.** `POST /ai/ask` принимает вопрос в рамках модуля или запуска, проверяет доступ пользователя и выбирает до пяти наиболее близких доступных фрагментов (Top-5).
3. **Генерация ответа.** DeepSeek формирует ответ по найденным источникам. В ответе возвращаются использованные ссылки-идентификаторы источников.
4. **Ретроспектива.** Анализируются данные запуска, заметки, ручная рефлексия и доступные фрагменты материалов. Сформированный отчёт сохраняется отдельной записью; возможно сравнение двух запусков одного модуля.

Поддерживаемые форматы для извлечения текста: **TXT, CSV, PDF, DOCX, PPTX, XLSX**. Изображения и сканированные PDF без текстового слоя не распознаются (OCR не предусмотрен).

Текущие ограничения индексации в коде: файл до **5 МиБ**, до **600 фрагментов** и до **500 000 символов** извлечённого текста. Для PDF — до 300 страниц. Доступный контекст RAG намеренно ограничен Top-5.

В [`app/adapters/ai/yandex.py`](app/adapters/ai/yandex.py) параметр `max_completion_tokens` ограничивает **выходные токены генерации**. Отдельный лимит ретроспективы задан в [`app/services/ai_retrospectives.py`](app/services/ai_retrospectives.py). Он не равен общему количеству входных и выходных токенов, а длительные ответы могут упираться в таймаут провайдера.

## Безопасность и обработка ошибок

- Пароли хешируются с помощью **Argon2**; API использует подписанные **JWT**.
- Роутеры определяют пользователя через `get_current_user()`.
- Репозитории проверяют принадлежность модуля владельцу при доступе к его содержимому.
- Pydantic проверяет типы, обязательные и запрещённые поля.
- Для бизнес-ошибок предусмотрены централизованные обработчики и HTTP-статусы, в том числе `401`, `404`, `409` и `422`.
- Файлы передаются через S3; ссылки на скачивание создаются по запросу и не сохраняются в БД как постоянные URL.

## Миграции и тестирование

Схема данных управляется **Alembic** (`alembic/versions/`). В Docker API применяет актуальные миграции при запуске.

Автоматизированные проверки находятся в `tests/` и запускаются в GitHub Actions с PostgreSQL 18 и pgvector. Workflow: [`.github/workflows/tests.yml`](.github/workflows/tests.yml).

Для локального запуска тестов нужны установленные зависимости и отдельно настроенная тестовая PostgreSQL с pgvector. После подготовки тестового окружения:

```bash
PYTHONPATH=app python -m unittest discover -s tests -p 'test_*.py' -v
```

Настройки тестовой БД берутся из переменной `KMS_TEST_DATABASE_URL`. **Не направляйте тесты на рабочую БД:** сценарии миграций и тестирования могут менять или удалять тестовые данные.

## Служебная очистка S3

Для повторной обработки отложенных задач удаления файлов предусмотрена команда:

```bash
docker compose exec api python app/cleanup_files.py --limit 100
```

Сведения о незавершённой очистке записываются в отдельный постоянный том `file_cleanup_data`. Очистка физических файлов должна учитывать, используются ли они другими материалами.

## Структура репозитория

```text
app/
  api/v1/        # HTTP-маршруты FastAPI
  schemas/       # Pydantic-модели запросов и ответов
  services/      # Сценарии и бизнес-логика
  repositories/  # Работа с PostgreSQL через SQLAlchemy
  models/        # ORM-модели таблиц
  adapters/      # S3, Yandex AI Studio и вспомогательные адаптеры
  core/          # Конфигурация, JWT, Depends, обработка ошибок
  main.py        # Приложение FastAPI
  start.py       # Миграции и запуск API
  worker.py      # Фоновая индексация
alembic/         # Миграции БД
tests/          # Автоматизированные проверки
compose.yaml     # Docker Compose
Dockerfile       # Контейнер backend
.env.example     # Шаблон локальной конфигурации
README.md        # Эта документация
```

## Статус проекта

KMS разрабатывается как учебный MVP. Возможности и ограничения конкретной версии определяются текущей веткой и состоянием развёртывания. При подготовке демонстрации рекомендуется проверять не только успешные HTTP-ответы, но и сохранение данных, разграничение доступа и поведение при ошибках.
