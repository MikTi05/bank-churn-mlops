# Отчёт по домашнему заданию №1

## 1. Краткое описание

Проект реализует обязательную часть: воспроизводимое обучение
модели оттока банковских клиентов, joblib-артефакт с паспортом, FastAPI,
PostgreSQL-логирование, тесты, Docker Compose и Kubernetes в локальном
kind-кластере. Дополнительные задания со звёздочками не выполнялись.

## 2. Соответствие обязательной части

| Пункт | Состояние | Подтверждение |
|---|---|---|
| 1. Артефакт с паспортом | ВЫПОЛНЕНО | `artifacts/model.joblib`: ровно `pipeline` и `metadata`; Pipeline содержит `preprocessor` и `classifier`; присутствуют оба ноутбука. |
| 2. Проект на uv | ВЫПОЛНЕНО | src-layout, `pyproject.toml`, `.python-version`, `uv.lock`; `uv sync` и импорт пакета успешны. |
| 3. FastAPI | ВЫПОЛНЕНО | `/health`, `/ready`, `/v1/predict`, `/docs`; lifespan-загрузка; Pydantic-валидация; response contract. |
| 4. PostgreSQL | ВЫПОЛНЕНО | Таблица `predictions` хранит request_id, ts, version, jsonb features, score, latency и status code; без `DATABASE_URL` используется no-op. |
| 5. Тесты | ВЫПОЛНЕНО | 7 обычных тестов проходят, 2 integration-теста проходят отдельно с PostgreSQL. |
| 6. Docker и Compose | ВЫПОЛНЕНО | Образ собирается через uv с `--frozen --no-dev`; API и PostgreSQL healthy; строки 200/422 записываются. |
| 7. Kubernetes | ВЫПОЛНЕНО | Deployment `2/2`, два Pod `1/1 Running`, три probe, resources, ClusterIP Service; predict через port-forward успешен. |
| 8. README | ТРЕБУЕТ ФИНАЛЬНОЙ ПРОВЕРКИ ПОСЛЕ КОММИТА | Ровно три команды созданы и успешно выполнены в текущем проекте. Чистый `git clone` пока невозможен: файлы ещё не добавлены в Git и коммит не создан. |

## 3. Результаты тестов

Финальный обычный запуск:

```text
collected 9 items
7 passed, 2 skipped, 2 warnings in 0.63s
```

Два integration-теста пропускаются без `DATABASE_URL`, что позволяет запускать
обычную проверку без PostgreSQL. При подключении к работающей Compose-базе:

```text
tests/test_integration.py::test_successful_prediction_is_logged PASSED
tests/test_integration.py::test_validation_error_is_logged PASSED
2 passed, 7 deselected, 2 warnings in 0.66s
```

Предупреждения: `StarletteDeprecationWarning` о текущей связке TestClient/httpx
и `DeprecationWarning` для alias `anyio.abc.BlockingPortal`. Они находятся во
внешних зависимостях и не влияют на результат тестов.

## 4. Docker Compose и PostgreSQL

Вторая команда README успешно пересобрала образ и дождалась состояний `Healthy`
для PostgreSQL и API. `/health`, `/ready` и `/docs` возвращают HTTP 200.

Финальный агрегированный SELECT:

```text
 status_code | rows | rows_with_score
-------------+------+-----------------
         200 |    4 |               4
         422 |    3 |               0
```

Для 422 поле `score` остаётся `NULL`, стандартный ответ FastAPI не изменяется.
Данные сохраняются в named volume `bank-churn-mlops_pgdata`.

## 5. Kubernetes

Живой kind-кластер `bank-churn-mlops` проверен без удаления или пересоздания:

```text
NAME                 READY   UP-TO-DATE   AVAILABLE
bank-churn-service   2/2     2            2

NAME                                  READY   STATUS    RESTARTS
bank-churn-service-5978877bf5-mpddv   1/1     Running   0
bank-churn-service-5978877bf5-zqxxs   1/1     Running   0
```

Через port-forward получены реальные ответы:

```json
{"status":"ok","model_version":"1.0.0"}
{"score":0.12278395016062318,"churn":false,"model_version":"1.0.0","request_id":"c621ab41-d878-47e7-9578-98f771adf2ea","latency_ms":15.6}
```

Третья команда README проверена как с уже существующим tunnel, так и с новым
временным port-forward. Созданный скриптом процесс корректно завершился после
проверки.

## 6. Скриншоты

### Pytest

![Успешный pytest](screenshots/01-pytest.png)

### PostgreSQL

![SELECT из predictions](screenshots/02-postgres.png)

### Kubernetes и port-forward

![Две реплики и predict](screenshots/03-kubernetes.png)

### k9s

![Два Pod в k9s](screenshots/04-k9s.png)

Все четыре PNG открыты и визуально проверены. Скриншоты не изменялись.

## 7. Воспроизводимость и подготовка к публикации

В проекте присутствуют исходный код, lock-файл, Python version, CSV, модель,
ноутбуки, Docker/Compose, Kubernetes, tests, screenshots, README, REPORT и
kind-скрипт. CSV и joblib намеренно не исключены из Git.

README содержит ровно три bash-команды. Все три выполнены в текущем проекте.
При этом полноценная проверка через новый `git clone` не выполнялась: Git пока
не содержит отслеживаемых файлов и пользователь запретил создавать коммиты.

Игнорируются `.env`, `.venv/`, `_seminar_reference/`, `.git/` как служебный
каталог, Python/pytest caches и `.DS_Store`. Реальный `.env` совпадает с
документированным локальным учебным примером и не будет опубликован.

## 8. Журнал проблем

### Проблема 1. Ошибка доступа к кешу uv

При первой попытке установки зависимостей Codex получил ошибку:

```
Failed to initialize cache at /Users/mikti/.cache/uv
Operation not permitted
```

Причина: ограничения доступа к стандартной директории кеша в среде выполнения Codex.

Решение: для запуска uv использована временная директория `/tmp/bank-churn-uv-cache`. После изменения пути кеша установка зависимостей продолжилась.

### Проблема 2. Ошибка сетевого доступа к PyPI

При установке зависимостей в среде Codex возникла ошибка:

```
Failed to fetch: https://pypi.org/simple/pydantic-settings/
dns error
```

Причина: ограничения сетевого доступа в среде выполнения Codex.

Решение: после разрешения сетевого доступа зависимости были успешно установлены, а файл `uv.lock` обновлён.

### Проблема 3. Предупреждения при тестировании

При выполнении тестов получены `StarletteDeprecationWarning` о текущей связке
`TestClient`/`httpx` и `DeprecationWarning` для alias
`anyio.abc.BlockingPortal`.

Причина: предупреждения формируются внешними зависимостями тестового окружения,
а не кодом сервиса. Они не меняют контракт API и не препятствуют выполнению
проверок.

Результат: обычный запуск завершился как `7 passed, 2 skipped, 2 warnings`, а
отдельный запуск с PostgreSQL — `2 passed, 7 deselected, 2 warnings`.

### Проблема 4. Конфликт локального порта PostgreSQL

При первом запуске Docker Compose контейнер PostgreSQL не смог опубликовать
стандартный порт на хосте:

```
Error response from daemon: ports are not available: exposing port TCP
127.0.0.1:5432 -> 127.0.0.1:0: listen tcp4 127.0.0.1:5432:
bind: address already in use
```

Причина: порт `127.0.0.1:5432` уже занят локальным процессом. Запущенных
чужих Docker-контейнеров с этим портом обнаружено не было. Останавливать или
удалять чужие процессы не стали.

Решение: host-порт учебной базы изменён на `55432` через переменную
`POSTGRES_PORT` в локальном `.env` и документирован в `.env.example`. Внутри
Compose адрес базы не изменился: API подключается к `db:5432`.

Результат повторной проверки: контейнер `db` перешёл в состояние `healthy` на
`127.0.0.1:55432`, после чего контейнер `api` успешно запустился.

### Проблема 5. Конфликт Compose-переменных с Pydantic Settings

После создания общего `.env` обычный запуск тестов остановился при импорте
приложения:

```
pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings
postgres_password
  Extra inputs are not permitted [type=extra_forbidden]
postgres_port
  Extra inputs are not permitted [type=extra_forbidden]
```

Причина: `.env` содержит переменные `POSTGRES_PASSWORD` и `POSTGRES_PORT` для
Docker Compose, которых нет среди полей настроек FastAPI. Pydantic Settings v2
по умолчанию запрещает лишние значения из dotenv-файла.

Решение: в `Settings.model_config` добавлено `extra="ignore"`. Приложение
по-прежнему читает `DATABASE_URL`, `MODEL_PATH` и `LOG_LEVEL`, а
Compose-специфичные переменные безопасно игнорируются.

Результат повторной проверки: обычный набор завершился с результатом
`7 passed, 2 skipped`, а реальные PostgreSQL integration-тесты — `2 passed`.

### Проблема 6. Ограничение доступа к Docker socket из sandbox

Первая проверка Docker daemon из ограниченной среды завершилась ошибкой:

```
permission denied while trying to connect to the docker API at
unix:///Users/mikti/.docker/run/docker.sock
```

Причина: процесс проверки не имел доступа к локальному Docker socket.

Решение: после явного разрешения доступа была повторена только необходимая
Docker-команда. Daemon ответил версией `29.8.0`; сборка и запуск Compose затем
выполнились успешно. Глобальная конфигурация Docker не изменялась.

### Проблема 7. kubectl dry-run без Kubernetes-контекста

Попытка выполнить клиентскую проверку созданных манифестов командой
`kubectl create --dry-run=client` завершилась ошибкой discovery:

```
unable to recognize "k8s/deployment.yaml": Get
"http://localhost:8080/api?timeout=32s": dial tcp [::1]:8080:
connect: operation not permitted
unable to recognize "k8s/service.yaml": Get
"http://localhost:8080/api?timeout=32s": dial tcp [::1]:8080:
connect: operation not permitted
error: current-context is not set
```

Причина: в момент первой проверки kind-кластер ещё не был создан и текущий
kube-context отсутствовал. Даже с `--dry-run=client` kubectl этой версии
выполнял API discovery для объектов из файла.

Первичное решение: YAML разобран локальным YAML-парсером; структурно проверены
apiVersion/kind, labels/selectors, две реплики, образ, порты, три probe,
ресурсы и отсутствие ссылок на DATABASE_URL, Secret и ConfigMap.

Окончательный результат: после появления кластера `bank-churn-mlops` выполнена
серверная проверка. Deployment достиг `2/2`, оба Pod — `1/1 Running`, Service
применён, а `/health` и `/v1/predict` успешно проверены через port-forward.
Команда `bash scripts/check-kind.sh` воспроизводит эту проверку и корректно
завершает созданный ею временный port-forward.

### Проблема 8. Ограничение кеша Homebrew при проверке k9s

При первой проверке команда `brew info k9s` подтвердила наличие формулы
`k9s 0.51.0` и то, что инструмент не установлен, но затем Homebrew попытался
обновить свой кеш и
вывел:

```
Error: Operation not permitted @ dir_s_mkdir -
/Users/mikti/Library/Caches/Homebrew/api/formula
```

Причина: sandbox не разрешал запись в пользовательский кеш Homebrew. Codex не
устанавливал инструмент самостоятельно. Позднее пользователь установил k9s из
обычного терминала.

Окончательный результат: `/opt/homebrew/bin/k9s` сообщает версию `0.51.0`, а
на финальном скриншоте в контексте `kind-bank-churn-mlops` видны два Pod со
статусом `1/1 Running`.

### Проблема 9. Недоступность стандартных PDF-утилит

Для аудита исходного задания сначала были проверены стандартные инструменты
Poppler. Команды `pdfinfo`, `pdftotext` и `pdftoppm` отсутствовали. Попытка
использовать системный Swift также завершилась ошибкой из-за несовместимости
кеша компилятора и SDK.

Решение: во временном окружении uv с кешем в `/tmp` использованы `pypdf` и
`PyMuPDF`. Из исходного PDF извлечён текст всех трёх страниц, затем каждая
страница отрендерена и визуально проверена. Временные изображения удалены,
зависимости проекта и исходный PDF не изменялись.
