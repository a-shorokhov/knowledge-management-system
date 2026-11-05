from enum import Enum

from fastapi import HTTPException


class ErrorCode(str, Enum):
    INVALID_LAUNCH_DATES = "INVALID_LAUNCH_DATES"
    USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
    EMAIL_ALREADY_EXISTS = "EMAIL_ALREADY_EXISTS"
    INCORRECT_CREDENTIALS = "INCORRECT_CREDENTIALS"
    INVALID_TOKEN = "INVALID_TOKEN"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    ACCOUNT_ACCESS_DENIED = "ACCOUNT_ACCESS_DENIED"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_HAS_CONTENT = "USER_HAS_CONTENT"
    MODULE_NOT_FOUND = "MODULE_NOT_FOUND"
    LAUNCH_NOT_FOUND = "LAUNCH_NOT_FOUND"
    SECTION_NOT_FOUND = "SECTION_NOT_FOUND"
    SECTION_NOT_FOUND_IN_LAUNCH = "SECTION_NOT_FOUND_IN_LAUNCH"
    SECTION_NOT_FOUND_IN_TARGET_LAUNCH = "SECTION_NOT_FOUND_IN_TARGET_LAUNCH"
    MATERIAL_NOT_FOUND = "MATERIAL_NOT_FOUND"
    MATERIAL_NOT_FOUND_IN_LAUNCH = "MATERIAL_NOT_FOUND_IN_LAUNCH"
    MATERIAL_SECTION_MISMATCH = "MATERIAL_SECTION_MISMATCH"
    NOTE_NOT_FOUND = "NOTE_NOT_FOUND"
    RELATED_DATA_CHANGED = "RELATED_DATA_CHANGED"
    CONTENT_DELETION_FAILED = "CONTENT_DELETION_FAILED"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    INVALID_FILENAME = "INVALID_FILENAME"
    FILE_EXTENSION_MISMATCH = "FILE_EXTENSION_MISMATCH"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    EMPTY_FILE = "EMPTY_FILE"
    INVALID_FILE_CONTENT = "INVALID_FILE_CONTENT"
    FILENAME_TOO_LONG = "FILENAME_TOO_LONG"
    FILE_UPLOAD_FAILED = "FILE_UPLOAD_FAILED"
    MATERIAL_SAVE_FAILED = "MATERIAL_SAVE_FAILED"
    MATERIAL_FILE_REPLACEMENT_FAILED = "MATERIAL_FILE_REPLACEMENT_FAILED"
    MATERIAL_SECTION_HAS_NOTES = "MATERIAL_SECTION_HAS_NOTES"
    CROSS_MODULE_COPY = "CROSS_MODULE_COPY"
    SAME_LAUNCH_COPY = "SAME_LAUNCH_COPY"
    FILE_UNAVAILABLE_FOR_COPY = "FILE_UNAVAILABLE_FOR_COPY"
    MATERIAL_DELETION_FAILED = "MATERIAL_DELETION_FAILED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_DELETION_PENDING = "FILE_DELETION_PENDING"
    FILE_STORAGE_NOT_CONFIGURED = "FILE_STORAGE_NOT_CONFIGURED"
    STORED_OBJECT_NOT_FOUND = "STORED_OBJECT_NOT_FOUND"
    DOWNLOAD_URL_FAILED = "DOWNLOAD_URL_FAILED"
    UNUSED_FILE_DELETION_FAILED = "UNUSED_FILE_DELETION_FAILED"
    FILE_IN_USE = "FILE_IN_USE"
    FILE_DELETION_START_FAILED = "FILE_DELETION_START_FAILED"
    STORAGE_DELETION_PENDING = "STORAGE_DELETION_PENDING"
    FILE_DELETION_CONFLICT = "FILE_DELETION_CONFLICT"
    FILE_RECORD_DELETION_PENDING = "FILE_RECORD_DELETION_PENDING"
    FILE_CLEANUP_FAILED = "FILE_CLEANUP_FAILED"
    REPLACED_FILE_CLEANUP_FAILED = "REPLACED_FILE_CLEANUP_FAILED"
    DELETED_MATERIAL_CLEANUP_FAILED = "DELETED_MATERIAL_CLEANUP_FAILED"


class AppException(HTTPException):
    def __init__(self, status_code: int, error_code: ErrorCode,
                 message: str, field: str | None = None,
                 details: dict | None = None, headers: dict | None = None):
        super().__init__(
            status_code=status_code,
            headers=headers,
            detail={
                "ErrorCode": error_code.value,
                "ErrorMessage": message,
                "ErrorField": field,
                "ErrorContext": details,
            },
        )


class UserAlreadyExistsException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.USER_ALREADY_EXISTS,
            message="Пользователь уже существует",
            field="username",
        )


class EmailAlreadyExistsException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.EMAIL_ALREADY_EXISTS,
            message="Email уже используется",
            field="email",
        )


class IncorrectCredentialsException(AppException):
    def __init__(self):
        super().__init__(
            status_code=401,
            error_code=ErrorCode.INCORRECT_CREDENTIALS,
            message="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )


class InvalidTokenException(AppException):
    def __init__(self):
        super().__init__(
            status_code=401,
            error_code=ErrorCode.INVALID_TOKEN,
            message="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )


class AuthenticationRequiredException(AppException):
    def __init__(self):
        super().__init__(
            status_code=401,
            error_code=ErrorCode.AUTHENTICATION_REQUIRED,
            message="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )


class AccountAccessDeniedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=403,
            error_code=ErrorCode.ACCOUNT_ACCESS_DENIED,
            message="Нет доступа к чужому аккаунту",
        )


class UserNotFoundException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.USER_NOT_FOUND,
            message="Пользователь не найден",
        )


class UserHasContentException(AppException):
    def __init__(self):
        super().__init__(
            status_code=409,
            error_code=ErrorCode.USER_HAS_CONTENT,
            message="Сначала удалите модули и файлы пользователя",
        )


class ModuleNotFoundException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.MODULE_NOT_FOUND,
            message="Модуль не найден",
        )


class LaunchNotFoundException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.LAUNCH_NOT_FOUND,
            message="Запуск не найден",
        )


class SectionNotFoundException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.SECTION_NOT_FOUND,
            message="Раздел не найден",
        )


class SectionNotFoundInLaunchException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.SECTION_NOT_FOUND_IN_LAUNCH,
            message="Раздел не найден в этом запуске",
            field="section_id",
        )


class SectionNotFoundInTargetLaunchException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.SECTION_NOT_FOUND_IN_TARGET_LAUNCH,
            message="Раздел не найден в целевом запуске",
            field="section_id",
        )


class MaterialNotFoundException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.MATERIAL_NOT_FOUND,
            message="Материал не найден",
        )


class MaterialNotFoundInLaunchException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.MATERIAL_NOT_FOUND_IN_LAUNCH,
            message="Материал не найден в этом запуске",
            field="material_id",
        )


class MaterialSectionMismatchException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.MATERIAL_SECTION_MISMATCH,
            message="Материал не находится в указанном разделе",
            field="section_id",
        )


class NoteNotFoundException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.NOTE_NOT_FOUND,
            message="Заметка не найдена",
        )


class RelatedDataChangedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=409,
            error_code=ErrorCode.RELATED_DATA_CHANGED,
            message="Связанные данные изменились, повторите запрос",
        )


class ContentDeletionFailedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.CONTENT_DELETION_FAILED,
            message="Не удалось удалить содержимое из базы данных",
        )


class UnsupportedFileTypeException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            message="Неподдерживаемый тип файла. Разрешены: png, jpg, jpeg, txt, docx, xlsx, pdf, pptx, csv",
            field="file",
        )


class InvalidFilenameException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.INVALID_FILENAME,
            message="Некорректное имя файла",
            field="file",
        )


class FileExtensionMismatchException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.FILE_EXTENSION_MISMATCH,
            message="Расширение файла не соответствует заявленному типу",
            field="file",
        )


class FileTooLargeException(AppException):
    def __init__(self):
        super().__init__(
            status_code=413,
            error_code=ErrorCode.FILE_TOO_LARGE,
            message="Размер файла превышает 5 МиБ",
            field="file",
        )


class EmptyFileException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.EMPTY_FILE,
            message="Нельзя загрузить пустой файл",
            field="file",
        )


class InvalidFileContentException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.INVALID_FILE_CONTENT,
            message="Содержимое файла не соответствует заявленному формату или файл повреждён",
            field="file",
        )


class FilenameTooLongException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.FILENAME_TOO_LONG,
            message="Слишком длинное имя файла",
            field="file",
        )


class FileUploadFailedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.FILE_UPLOAD_FAILED,
            message="Не удалось загрузить файл в хранилище",
        )


class MaterialSaveFailedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.MATERIAL_SAVE_FAILED,
            message="Не удалось сохранить материал в базе данных",
        )


class MaterialFileReplacementFailedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.MATERIAL_FILE_REPLACEMENT_FAILED,
            message="Не удалось заменить файл в базе данных",
        )


class MaterialSectionHasNotesException(AppException):
    def __init__(self):
        super().__init__(
            status_code=409,
            error_code=ErrorCode.MATERIAL_SECTION_HAS_NOTES,
            message="У материала есть заметки с привязкой к текущему разделу. Сначала отвяжите их от раздела или удалите",
            field="section_id",
        )


class CrossModuleCopyException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.CROSS_MODULE_COPY,
            message="Копирование разрешено только между запусками одного модуля",
            field="launch_id",
        )


class SameLaunchCopyException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400,
            error_code=ErrorCode.SAME_LAUNCH_COPY,
            message="Выберите другой запуск",
            field="launch_id",
        )


class FileUnavailableForCopyException(AppException):
    def __init__(self):
        super().__init__(
            status_code=409,
            error_code=ErrorCode.FILE_UNAVAILABLE_FOR_COPY,
            message="Файл удаляется или уже недоступен для копирования",
        )


class MaterialDeletionFailedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.MATERIAL_DELETION_FAILED,
            message="Не удалось удалить материал из базы данных",
        )


class FileNotFoundException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.FILE_NOT_FOUND,
            message="Файл не найден",
        )


class FileDeletionPendingException(AppException):
    def __init__(self):
        super().__init__(
            status_code=409,
            error_code=ErrorCode.FILE_DELETION_PENDING,
            message="Файл ожидает удаления",
        )


class FileStorageNotConfiguredException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.FILE_STORAGE_NOT_CONFIGURED,
            message="Хранилище этого файла не настроено",
        )


class StoredObjectNotFoundException(AppException):
    def __init__(self):
        super().__init__(
            status_code=404,
            error_code=ErrorCode.STORED_OBJECT_NOT_FOUND,
            message="Файл не найден в хранилище",
        )


class DownloadUrlFailedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.DOWNLOAD_URL_FAILED,
            message="Не удалось получить ссылку на файл",
        )


class UnusedFileDeletionFailedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.UNUSED_FILE_DELETION_FAILED,
            message="Не удалось удалить неиспользуемый файл",
        )


class FileInUseException(AppException):
    def __init__(self):
        super().__init__(
            status_code=409,
            error_code=ErrorCode.FILE_IN_USE,
            message="Файл используется материалами. Сначала удалите их или замените файл",
        )


class FileDeletionStartFailedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.FILE_DELETION_START_FAILED,
            message="Не удалось начать удаление файла. Повторите запрос",
        )


class StorageDeletionPendingException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.STORAGE_DELETION_PENDING,
            message="Файл ожидает удаления из хранилища. Повторите запрос",
        )


class FileDeletionConflictException(AppException):
    def __init__(self):
        super().__init__(
            status_code=409,
            error_code=ErrorCode.FILE_DELETION_CONFLICT,
            message="Не удалось завершить удаление файла. Повторите запрос",
        )


class FileRecordDeletionPendingException(AppException):
    def __init__(self):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.FILE_RECORD_DELETION_PENDING,
            message="Объект удалён из S3, запись помечена как ожидающая удаления. Повторите запрос",
        )


class FileCleanupFailedException(AppException):
    def __init__(self, file_ids: list[int], prefix: str = ""):
        paths = ", ".join(f"DELETE /stored-files/{file_id}" for file_id in file_ids)
        super().__init__(
            status_code=503,
            error_code=ErrorCode.FILE_CLEANUP_FAILED,
            message=prefix + f"Не удалось завершить очистку файлов. Повторите: {paths}",
            details={"file_ids": file_ids},
        )


class ReplacedFileCleanupFailedException(AppException):
    def __init__(self, file_id: int):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.REPLACED_FILE_CLEANUP_FAILED,
            message=f"Файл материала заменён, но старый файл №{file_id} не удалось удалить. Повторите удаление через DELETE /stored-files/{file_id}",
            details={"file_id": file_id},
        )


class DeletedMaterialCleanupFailedException(AppException):
    def __init__(self, file_id: int):
        super().__init__(
            status_code=503,
            error_code=ErrorCode.DELETED_MATERIAL_CLEANUP_FAILED,
            message=f"Материал удалён, но файл №{file_id} не удалось удалить. Повторите удаление через DELETE /stored-files/{file_id}",
            details={"file_id": file_id},
        )


class InvalidLaunchDatesException(AppException):
    def __init__(self):
        super().__init__(
            status_code=422,
            error_code=ErrorCode.INVALID_LAUNCH_DATES,
            message="Дата окончания не может быть раньше даты начала",
            field="ends_on",
        )
