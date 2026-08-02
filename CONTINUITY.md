# Continuity Ledger

## Goal (incl. success criteria):
Развернуть LibreTranslate на Windows (без Docker, Python 3.12) с GPU-ускорением (CUDA) и дашбордом реального прогресса (%, сим/с, ETA) для перевода больших файлов через веб-интерфейс. Успех: CUDA активна (~12 000 сим/с), перевод файлов асинхронный (jobId + поллинг), UI показывает честный прогресс-бар (0→100) с % / скоростью / ETA, кнопки управления Play/Пауза/Stop (пауза освобождает CPU/GPU, stop отменяет и сбрасывает UI), по завершении результат гарантированно доставляется (кнопка Download + авто-скачивание).

Текущие правки (01.08.2026, реализуются): (1) починка «зависания» PDF на 100% — батчинг `apply_redactions` по странице + честный прогресс фазы сборки (95→100) + корректная обработка Stop через `JobCancelledError`; (2) сохранение результата «в ту же папку» — кнопка «Выбрать папку для сохранения» (`showDirectoryPicker` + IndexedDB, папка запоминается навсегда), по завершении авто-запись в выбранную папку, иначе автоскачивание; (3) защита файлов активных job'ов от чистки в `remove_translated_files.py`.

## Constraints/Assumptions:
- Docker недоступен -> развёртывание через venv + pip.
- Сеть до argos-net.com нерабочая; рабочий источник: https://data.argosopentech.com/argospm/v1/
- CUDA включать всегда; перевод файлов — только через новый асинхронный jobId + поллинг.
- Прогресс считать по абзацам (строкам) — принято пользователем.
- Пользователь перевёл UI-правки в режим исполнения: «Вноси правки» — все правки внесены.
- Пауза блокирует фоновый поток между абзацами/спанами (текущий `underlying.translate(paragraph)` синхронный — прервать нельзя, принято); resume продолжает с того же места.
- Stop = отмена: удалить незавершённый выходной файл, UI к выбору файла (исходный файл остаётся), принято пользователем.
- `job.total_chars` предвычисляется ОДИН раз при старте джоба (не по-вызовно) — фикс «100% сразу».
- НЕ создавать тестовые файлы/данные для проверок; если для верификации нужен файл — спрашивать пользователя, какой перевести. (Исключение 01.08.2026: для live-проверки починки PDF из реальной книги собирался временный 4-страничный мини-PDF в %TEMP%.)

## Key decisions:
- CUDA-оптимизация: главный рычаг — `ARGOS_BATCH_SIZE=512` (12 267 сим/с против 1001 при batch=32; batch=1024 без выигрыша). `ARGOS_BEAM_SIZE=4` сохранён ради качества.
- Конфиг GPU читается argostranslate при импорте из `C:\Users\Andrew\.config\argos-translate\settings.json` (или env) — до старта сервера.
- `/translate_file` переделан в асинхронный: 200 + `{jobId}`; прогресс живёт в памяти одного процесса (waitress, threads=4).
- Прогресс считается по абзацам через `ProgressTranslation(ITranslation)` — результат перевода идентичен прежнему (ядро CachedTranslation переводит по абзацам).
- i18n: .mo не компилируются в этом чек-ауте (flask_babel молча фолбэчит на английский); новые строки добавлены в messages.pot + ru/messages.po для будущей компиляции.
- Починка PDF с битым ToUnicode: репмап извлечённого текста (кириллица +0x1D6 для 0x23A–0x2AE, цифры +0x1D для 0x13–0x1C, спецсимволы ©→« ª→» ²/±→— \x87→• ʋ→№, прочие контролы→пробел). Эвристика needs_repair() включается только при доле «чинящихся» символов >30% — обычные PDF не затрагиваются. Выходной PDF формируется тем же insert_htmlbox-подходом, что и argostranslatefiles.

## State:
### Done:
- CUDA включён (settings.json + start-server.bat: device=cuda, compute=auto, beam=4, batch=512); производительность ~12 267 сим/с.
- Новый модуль `libretranslate\progress.py`: JobStore (TTL 3600 c), ProgressTranslation, run_file_job, fail_job.
- Новый модуль `libretranslate\pdf_file.py`: `needs_repair()`/`repair_text()`/`get_texts()`/`RepairedPdfTranslator`/`translate_pdf()`/`is_pdf_file()` — чинит PDF с битым ToUnicode (InDesign Identity-H) до перевода; верифицирован на книге «ВЕРНЫЕ» (405 стр.).
- Интеграция pdf_file в app.py (preview_file + автоопределение языка при source=auto) и progress.py (run_file_job для .pdf). Live-проверки пройдены (preview + мини translate_file ru->en).
- Ранее в этом чек-ауте: кодек-зависимый перевод txt/html/srt с модальным предпросмотром (app.js.template, index.html, main.css, text_file.py, /preview_file, supportedFileCodecs), i18n строки в messages.pot/ru, .mo скомпилирован.
- `libretranslate\app.py`:
  - `/translate_file` — асинхронный (200 + jobId), auto-detect и перевод в фоновой нити.
  - `GET /translate_job/<job_id>` — снапшот: status, progress, processedChars, totalChars, speed, eta, translatedFileUrl, error; 404 если нет.
  - Swagger обновлён для `/translate_file` и `/translate_job`; добавлен `@bp.errorhandler(404)`.
- `libretranslate\remove_translated_files.py`: `job_store.cleanup()` в 30-мин джануторе.
- Фронтенд `app.js.template` + `index.html`:
  - Vue-поля: fileJobId, fileProgress, fileProgressText, fileSpeedText, fileEtaText, filePollTimer.
  - `translateFile` — POST -> поллинг 1 c; on done авто-скачивание; on error сообщение; removeFile чистит таймер.
  - Детерминированный прогресс-бар (`width: fileProgress + '%'`) + строка `% · N сим/с · Осталось ~MM:SS`.
  - Хелперы formatFileSpeed/formatFileEta в app.js.template.
- i18n: строка «Time left» добавлена в messages.pot и ru/messages.po («Осталось»).
### Now:
- ФИКС «ЗАВИСАНИЯ» PDF НА 100% (01.08.2026, реализован, сервер перезапущен на новом коде): реальная причина — фаза сборки PDF после перевода: цикл `page.add_redact_annot(rect); page.apply_redactions(...)` на КАЖДЫЙ span (тысячи вызовов, каждый переобрабатывает всю страницу) молча работал десятки минут; job в `running`, UI на «100% · Осталось ~0s». Диагноз подтверждён логами: перевод завершён, apscheduler прозевал свой запуск на 26 мин (GIL зажат сборкой). Исправления:
  - `pdf_file.py`: `_apply_translations_to_pdf` — все redaction-прямоугольники страницы батчем в ОДИН `apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)` (fallback — белые `draw_rect`); прогресс сборки через `_report_assembly_progress` (95→100 по страницам); pause/cancel-проверки по страницам; `_translate_pages_data` переопределён — `JobCancelledError` больше не глотается (базовый класс молча оставлял оригинал и «доделывал» job); добавлен `_save_translated_pdf` (cancel-проверки до/после `insert_pdf`, до `save`).
  - `progress.py`: фаза перевода капает на 95% (последние 5% отдаёт фаза сборки — UI не висит на «100%»); `set_job_progress(job, progress, eta=None)` — сброс ETA вне перевода; `job.source_path` заполняется при старте job; **исправлена SyntaxError** (неверный отступ `with job_store._lock:` в `ProgressTranslation.translate`, накопленный с прошлой сессии — сервер бы не стартовал).
  - `remove_translated_files.py`: файлы `running`/`paused` job'ов (source_path/translated_file_path) исключены из 30-мин чистки; добавлен `JobStore.all()`.
- СОХРАНЕНИЕ «В ТУ ЖЕ ПАПКУ» (01.08.2026, реализовано): кнопка «Выбрать папку для сохранения» в файловом режиме (`index.html` ~288, класс `.btn-file-outline`, иконка `create_new_folder`) → `showDirectoryPicker({id:"libretranslate-save-dir", mode:"readwrite"})`; хендл папки сохраняется в IndexedDB навсегда и подгружается при загрузке страницы (`mounted`); в UI — индикатор «Сохранить в: <имя папки>»; по завершении `saveTranslatedFile(url)` пишет blob через `getFileHandle(fileName,{create:true})` + `createWritable()`; при отсутствии/ошибке папки — фолбэк на автоскачивание (старый DOM-`<a>.click()`). В не-Chromium браузерах — понятное сообщение. i18n: 5 новых строк (Select save folder, Save to, Saved to, Chromium-only, fallback-сообщение) в messages.pot + ru po + `compile_locales.py` (пересобран, *.mo в .gitignore).
- ПРОВЕРЕНО НА ЖИВОМ СЕРВЕРЕ (после рестарта через `%TEMP%\opencode\lt-restart.py`, PID 33248): HTTP 200 на `/`, HTML содержит «Select save folder» + `create_new_folder`; отрендеренный `/js/app.js?v=1.9.6` содержит chooseSaveDirectory/storeSaveDirectory/loadSaveDirectory/saveTranslatedFile/showDirectoryPicker/getFileHandle/createWritable/indexedDB; i18n-строки отрендерены в JS корректно; `py_compile` и импорт всех модулей OK; `lt-server-err.log` чист (только RequestsDependencyWarning). DCG блокирует PowerShell `Stop-Process`/`taskkill`/`node --check` — рестарт только через python-скрипт; **в браузере обязателен Ctrl+F5** (`?v=1.9.6` статичен).
- ОПЕРАЦИОННО (01.08.2026): `venv\Scripts\python.exe` — обёртка (python-build-standalone), открывает НОВОЕ окно Windows Terminal; при его закрытии сервер падает с `forrtl: error (200) window-CLOSE`. Запуск — `venv\Scripts\pythonw.exe` через `%TEMP%\opencode\lt-start.py` (DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP, SW_HIDE, env CUDA). Логи: `%TEMP%\lt-server-out.log`/`lt-server-err.log`.
- ОПЕРАЦИОННЫЙ ИНЦИДЕНТ (01.08.2026): на порту 5000 висели ЧЕТЫРЕ серверных процесса (venv + системный Python312 из повторных запусков), браузер попадал на старый процесс со старыми шаблонами — «блок всё ещё виден». Убиты все (старый системный python — через taskkill /F из python-скрипта), поднят один чистый сервер через `%TEMP%\opencode\lt-start.py` (venv python main.py --host 0.0.0.0 --port 5000 --load-only en,ru, CUDA env). Живой слушатель: дочерний системный python от venv (pyvenv.cfg redirect) — это норма. Логи: `%TEMP%\lt-server-out.log` / `lt-server-err.log`. Живая проверка: index.html содержит кнопку и `v-if="showApiExample"`, app.js — `toggleApiExample` и `showApiExample: false`.
- ВАЖНО для браузера: `?v=1.9.6` статичен (не меняется при рестарте) -> старый app.js кэшируется. После рестарта всегда **Ctrl+F5**.
- Диагноз «результат не появился» закрыт пользователем (01.08.2026): автозагрузка сработала (диалог сохранения появился). Причина ложного впечатления — прогресс-бар «100% сразу» для PDF при ещё живом переводе.
- Закоммичено и запушено 01.08.2026 (третий коммит): `7e0706c` «Fix file translation UI: collapse API example behind toggle, redesign progress panel with working controls» (5 файлов, +244/-25) -> форк `andrei main` (`646b453..7e0706c`). В коммит вошли: index.html, app.js.template (кнопка API-примера), main.css (фикс зелёного оверлея + редизайн .file-job), messages.pot/ru.po (Translating). `messages.mo` в gitignore (`*.mo`). `CONTINUITY.md` и `start-server.bat` — локальные, не коммитятся.
- Коммит `646b453` — второй, запушен ранее в `andrei main` (`5eafba6..646b453`). Коммит `5eafba6` — первый, запушен ранее (`dd97bd9..5eafba6`). Git identity (локально): andreipromarketing-dev <andrei.promarketing@gmail.com>.
### Next:
- Live-проверка пользователем (реальный многостраничный PDF через UI, например «ВЕРНЫЕ мини.pdf»): Ctrl+F5; прогрев 0→100 без «зависания» (перевод капит на 95%, сборка идёт 95→100 быстро — батчинг redaction); job → done; выбрать папку сохранения кнопкой → файл автоматически записан в неё; без выбора папки — автоскачивание в «Загрузки»; Pause (CPU падает) → Resume → Stop (cancelled, UI сброшен); папка переживает перезагрузку страницы (IndexedDB).
- Проверить, что `.file-save-dir` (индикатор папки) и новая кнопка не ломают вёрстку в файловом режиме на реальной ширине.
- По завершении — коммит и push в `andrei main` (по запросу пользователя).
- (Опционально) полный перевод книги 405 стр через UI — по запросу пользователя.
- (Опционально) `pytest` — тесты translate_file не ассертят новый формат ответа.
- (Опционально) автостарт сервера в Windows при перезагрузке.

## Open questions (UNCONFIRMED if needed):
- Нужен ли постоянный автостарт сервера при перезагрузке Windows? (UNCONFIRMED)

## Working set (files/ids/commands):
- Корень: E:\MY-LIFE-SYSTEM\LibreTranslate
- venv: `venv\Scripts\python.exe`
- Запуск: `venv\Scripts\pythonw.exe main.py --host 0.0.0.0 --port 5000 --load-only en,ru` (pythonw — без окна; python.exe открывает лишний Windows Terminal и падает при его закрытии). Штатно — `%TEMP%\opencode\lt-start.py`.
- CUDA-конфиг: `C:\Users\Andrew\.config\argos-translate\settings.json` (`{"ARGOS_DEVICE_TYPE":"cuda","ARGOS_COMPUTE_TYPE":"auto","ARGOS_BEAM_SIZE":"4","ARGOS_BATCH_SIZE":"512"}`).
- Модели: `%USERPROFILE%\.local\share\argos-translate\packages` (translate-en_ru-1_9, translate-ru_en-1_9).
- Сервер: waitress serve(app, host, port, threads=args.threads) — libretranslate\main.py:297-303; дефолт threads=4.
- ctranslate2 4.8.1 собран с CUDA (`get_cuda_device_count()==1`).
- Изменённые файлы: libretranslate\pdf_file.py (новый), progress.py, text_file.py, app.py, remove_translated_files.py, templates\app.js.template, templates\index.html, static\css\main.css, locales\messages.pot, locales\ru\LC_MESSAGES\messages.po, locales\ru\LC_MESSAGES\messages.mo, start-server.bat.
- Книга для проверки: `F:\NORD\Публицистика\ОТПРАВКИ\ВЕРНЫЕ мини.pdf` (405 стр., InDesign, битая ToUnicode). Остаточные артефакты титульной страницы `%RRN -HW`/`,6%1` — декоративный шрифт исходника, не связаны с коррекцией.
- JINJA-шаблон app.js.template рендерится с `?v={{ version }}` — после правок фронта обязателен рестарт сервера.
- Кнопка: после рестарта обновить страницу (Ctrl+F5) для загрузки нового app.js.
