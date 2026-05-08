# arb-intel — установка на Pop!_OS (детально, с нуля)

Pop!_OS отлично подходит — это Ubuntu-based дистрибутив, всё работает нативно,
без WSL и танцев с docker desktop. Этот гайд покрывает чистую установку
с нуля до запущенной системы и приходящих в Telegram алёртов.

> **Терминал**: открывается `Ctrl+Alt+T` или из меню → **Terminal**.
> Все команды ниже — для терминала, копируй построчно.

> **Пароль**: при `sudo` пароль вводится **невидимо** (без звёздочек). Это норма.

---

# Часть 1. Установка инфраструктуры (один раз)

## Шаг 1. Обнови систему

```bash
sudo apt update && sudo apt upgrade -y
```

## Шаг 2. Поставь базовые инструменты

```bash
sudo apt install -y git curl build-essential ca-certificates gnupg lsb-release
```

Проверь:
```bash
git --version
```
Должен показать что-то вроде `git version 2.x.x`.

## Шаг 3. Поставь Docker (нативно, без Docker Desktop)

Pop!_OS — Ubuntu-based, поэтому официальный репо Docker для Ubuntu работает напрямую.

### 3.1. Удали возможные старые версии docker:
```bash
sudo apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null
```
(если их не было, ничего не произойдёт — это нормально)

### 3.2. Добавь GPG-ключ Docker:
```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

### 3.3. Добавь репо Docker:
Pop!_OS базируется на Ubuntu, но `lsb_release -cs` возвращает `pop` — это
не подходит для Docker репо. Поэтому подставляем напрямую кодовое имя
Ubuntu, на котором базируется твой Pop!_OS. Проверь:
```bash
cat /etc/os-release | grep UBUNTU_CODENAME
```
Увидишь например `UBUNTU_CODENAME=jammy` (для Pop 22.04) или `noble` (для 24.04).

Подставь этот codename в команду:
```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```
> Если у тебя `noble` — замени `jammy` на `noble` в команде выше.

### 3.4. Поставь docker engine + compose:
```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 3.5. Дай своему юзеру право запускать docker без sudo:
```bash
sudo usermod -aG docker $USER
```
**Перелогинься** (или перезагрузись) — без этого `docker` будет требовать sudo.

После релогина проверь:
```bash
docker --version
docker compose version
docker run hello-world
```
Последняя команда должна напечатать **"Hello from Docker!"**.

## Шаг 4. Поставь uv (быстрый Python-менеджер)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Подгрузи новые переменные:
```bash
source ~/.bashrc
```
(если у тебя zsh — `source ~/.zshrc`)

Проверь:
```bash
uv --version
```
Должен напечатать `uv 0.x.x`. Если `uv: command not found` — закрой терминал, открой заново.

## Шаг 5. (опционально) Поставь Python 3.12 системно

uv сам скачает Python нужной версии при необходимости, но если хочешь
системный — поставь:
```bash
sudo apt install -y python3.12 python3.12-venv
```
(если в репо нет — uv всё равно сам справится, можешь пропустить шаг)

---

# Часть 2. Получение проекта и секретов

## Шаг 6. Склонируй репо

```bash
cd ~
git clone https://github.com/debchansijjj/arb-intel.git
cd arb-intel
git checkout devin/1778277433-arb-intel-bootstrap
```

Проверь:
```bash
ls
```
Должно быть видно `src/`, `tests/`, `alembic/`, `docker-compose.yml`,
`pyproject.toml`, `.env.example`.

## Шаг 7. Поставь зависимости проекта

```bash
uv sync --all-extras
```

Эта команда сама создаст `.venv/` и поставит все нужные библиотеки
(FastAPI, asyncpg, web3, aiogram и т.д.). Длится 1-3 минуты.

Проверь, что тесты проходят:
```bash
.venv/bin/pytest tests/
```
Должно быть `26 passed`.

И lint:
```bash
.venv/bin/ruff check src tests
```
Должно быть `All checks passed!`.

## Шаг 8. Сделай default branch на GitHub (один раз)

Чтобы при `git clone` сразу получать код, а не пустой репо:

1. Открой в браузере: https://github.com/debchansijjj/arb-intel/settings/branches
2. В блоке **Default branch** нажми кнопку с двумя стрелочками (switch ↔).
3. В выпадающем списке выбери `devin/1778277433-arb-intel-bootstrap`.
4. Нажми **Update**.
5. Подтверди **I understand, update the default branch**.

## Шаг 9. Создай Telegram-бота

### 9.1. Получи bot token
1. В Telegram открой контакт **@BotFather**: https://t.me/BotFather
2. Нажми **START**.
3. Отправь: `/newbot`
4. Введи **имя бота** (отображаемое), например: `My Arb Intel`
5. Введи **username бота** — должен заканчиваться на `bot`. Например:
   `myarbintel_47291bot`
6. BotFather пришлёт сообщение с токеном вида:
   ```
   123456789:ABCdefGhIJKlmNoPQRsTUvwxyz_abc123xyz
   ```
   **Скопируй его целиком** (со всеми двоеточиями). Это `BOT_TOKEN`.

### 9.2. Узнай свой chat_id
1. В Telegram открой свеже-созданного бота (по ссылке `t.me/<username>bot`).
2. Нажми **START** (важно).
3. Напиши боту любое сообщение, например `hi`.
4. Открой в браузере (подставь свой токен):
   ```
   https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
   ```
5. В JSON-ответе найди:
   ```json
   "chat": {
     "id": 12345678,
     ...
   }
   ```
   Число `12345678` (у тебя своё) — это твой `chat_id`. Сохрани.

### 9.3. (опционально) Если хочешь слать в группу
1. Создай группу в TG.
2. Добавь бота в группу.
3. Сделай бота **админом**.
4. Напиши любое сообщение в группе.
5. Снова открой `getUpdates` URL — там будет `chat_id` группы (с минусом,
   например `-1001234567890`).

## Шаг 10. (опционально, рекомендую) Helius для Solana

Бесплатно, без карты:
1. https://www.helius.dev/ → **Sign Up** → войди через Google/GitHub.
2. В Dashboard скопируй **Default API Key**.
3. WSS endpoint: `wss://mainnet.helius-rpc.com/?api-key=<твой_ключ>`

Если Solana не нужна — пропусти.

## Шаг 11. (опционально) Alchemy для EVM

Публичные RPC (publicnode) уже работают, но имеют rate-limit. Для серьёзной
нагрузки:
1. https://www.alchemy.com/ → **Sign up** (бесплатно)
2. **Create app** для каждой нужной сети (Base, Arbitrum, Ethereum, BSC).
3. На странице app копируй **WSS URL**.

---

# Часть 3. Настройка и запуск

## Шаг 12. Создай файл `.env`

```bash
cd ~/arb-intel
cp .env.example .env
nano .env
```

Управление в `nano`:
- стрелки — двигаться
- `Ctrl+W` — поиск (введи строку, Enter)
- `Ctrl+O` → `Enter` — сохранить
- `Ctrl+X` — выйти

Найди и поменяй:

### A) База и Redis — **ничего не трогай**:
```env
ARB_INTEL_DB__DSN=postgresql+asyncpg://arb:arb@localhost:5432/arb_intel
ARB_INTEL_REDIS__URL=redis://localhost:6379/0
```

### B) Какие сети мониторить
Если только Base + Arbitrum (рекомендую начать с этого):
```env
ARB_INTEL_CHAINS__ENABLED=["base","arbitrum"]
```

Если все:
```env
ARB_INTEL_CHAINS__ENABLED=["solana","base","arbitrum","bsc","ethereum"]
```

### C) RPC URL'ы
Оставь как в `.env.example` (publicnode), либо замени на Alchemy:
```env
ARB_INTEL_EVM__BASE__WSS=wss://base-mainnet.g.alchemy.com/v2/<твой_alchemy_key>
ARB_INTEL_EVM__BASE__HTTPS=https://base-mainnet.g.alchemy.com/v2/<твой_alchemy_key>
```

Для Solana с Helius:
```env
ARB_INTEL_SOLANA__RPC_WSS=wss://mainnet.helius-rpc.com/?api-key=<твой_helius_key>
ARB_INTEL_SOLANA__RPC_HTTPS=https://mainnet.helius-rpc.com/?api-key=<твой_helius_key>
ARB_INTEL_SOLANA__HELIUS_API_KEY=<твой_helius_key>
```

### D) Telegram (вставь из шага 9)
```env
ARB_INTEL_TELEGRAM__BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUvwxyz_abc123xyz
ARB_INTEL_TELEGRAM__CHAT_IDS=[12345678]
```
> **Заметь**: `BOT_TOKEN` — без кавычек. `CHAT_IDS` — JSON-список в квадратных
> скобках. Несколько чатов: `[12345678, 87654321]`.

### E) Пороги алёртов (понижаем сразу, чтоб точно увидеть)
```env
ARB_INTEL_TELEGRAM__MIN_NET_PROFIT_USD=2.0
ARB_INTEL_TELEGRAM__MIN_CONFIDENCE=0.5
ARB_INTEL_TELEGRAM__COOLDOWN_S=60
```

Сохрани (`Ctrl+O`, `Enter`) и выйди (`Ctrl+X`).

Быстрая проверка что значения правильные:
```bash
grep -E "BOT_TOKEN|CHAT_IDS|CHAINS__ENABLED" .env
```

## Шаг 13. Запусти Postgres + Redis

```bash
docker compose up -d postgres redis
```

Подожди 5-10 секунд:
```bash
docker compose ps
```

Должны быть оба `(healthy)`:
```
NAME                   STATUS                            PORTS
arb-intel-postgres-1   Up 10 seconds (healthy)           0.0.0.0:5432->5432/tcp
arb-intel-redis-1      Up 10 seconds (healthy)           0.0.0.0:6379->6379/tcp
```

> Если `(unhealthy)` или `(starting)` дольше 30 сек — посмотри логи:
> `docker compose logs postgres` или `docker compose logs redis`.

## Шаг 14. Создай таблицы в БД

```bash
.venv/bin/alembic upgrade head
```

Должна напечатать одну строку:
```
INFO  [alembic.runtime.migration] Running upgrade  -> bde2610710e8, initial schema
```

Проверка таблиц:
```bash
docker exec arb-intel-postgres-1 psql -U arb -d arb_intel -c "\dt"
```
Должен вывести список из 11 таблиц (10 моделей + alembic_version).

## Шаг 15. Запусти всё

```bash
.venv/bin/arb-intel
```

В терминале посыпятся JSON-логи:
```
{"event":"api.start","host":"0.0.0.0","port":8080,"level":"info"}
{"event":"discovery.bootstrap.start","level":"info"}
{"event":"evm.tracker.subscribe","chain":"base","level":"info"}
```

**Не закрывай этот терминал** — пока он открыт, система работает.
Остановить: `Ctrl+C`.

## Шаг 16. Проверь что работает

Открой **второй терминал** (`Ctrl+Alt+T` или новая вкладка):

```bash
# Health
curl http://localhost:8080/health
# → {"ok":true,"env":"dev"}

# Сколько пулов трекер нашёл (через 1-2 минуты должно расти)
curl http://localhost:8080/pools-count/base
curl http://localhost:8080/pools-count/arbitrum

# Найденные арбитражи (через несколько минут появятся)
curl http://localhost:8080/opportunities/recent | head -c 1500

# Прометей-метрики
curl http://localhost:8080/metrics | grep '^arb_'
```

## Шаг 17. Проверь Telegram

В чате с ботом должны прийти алёрты вида:
```
🔥 ARB | base / arbitrum
buy:  USDC/WETH @ Aerodrome
sell: USDC/WETH @ Uniswap V3
spread: 38 bps   net: $14.20
liq: $850k       conf: 0.78
```

Если **5 минут — тишина**:
```bash
# В другом терминале:
curl http://localhost:8080/opportunities/recent | head -c 500
```
- Если пусто — алёрт-движок ещё не нашёл арбитража, подожди ещё 5 минут
  (на slow-сетях типа BSC/ETH может занять до 15 минут до первого хита).
- Если непусто, но в TG ничего — проверь BOT_TOKEN и CHAT_IDS, и
  посмотри логи запущенного `arb-intel` на ошибки `Telegram`.

---

# Часть 4. Что часто ломается

| Симптом | Причина | Фикс |
|---|---|---|
| `docker: permission denied` | Не перелогинился после `usermod -aG docker` | Перезагрузись или `newgrp docker` |
| `Cannot connect to the Docker daemon` | Docker не запущен | `sudo systemctl start docker && sudo systemctl enable docker` |
| `port 5432 already in use` | На системе стоит другой Postgres | `sudo systemctl stop postgresql` (если есть), или поменяй порт в `docker-compose.yml` |
| `port 6379 already in use` | Локальный Redis | `sudo systemctl stop redis-server` |
| `uv: command not found` | PATH не обновлён | `source ~/.bashrc` или закрой/открой терминал |
| `SettingsError: error parsing value for field "evm"` | Старый код | `cd ~/arb-intel && git pull` |
| Telegram молчит, `getUpdates` пустой | Не нажал START у бота | Открой бота, нажми START, отправь сообщение |
| `Telegram Unauthorized` в логах | Неверный BOT_TOKEN | Перепроверь у @BotFather (`/mybots` → бот → API Token) |
| `Chat not found` в логах | Неверный chat_id | Снова шаг 9.2 |
| Алёрты не идут | Слишком высокие пороги | `MIN_NET_PROFIT_USD=1.0`, `MIN_CONFIDENCE=0.4` в `.env`, перезапусти |
| WSS отваливается каждые 30 сек | Publicnode rate-limit | Возьми Alchemy free tier (шаг 11) |
| `alembic: command not found` | venv не активен | Используй `.venv/bin/alembic ...` явно |

---

# Часть 5. Шпаргалка ежедневного использования

Запуск (всё уже установлено):
```bash
cd ~/arb-intel
docker compose up -d postgres redis
.venv/bin/arb-intel
```

Остановка:
```bash
# Ctrl+C в терминале с arb-intel
docker compose down            # остановить pg+redis (данные сохранятся)
```

Полный сброс БД:
```bash
docker compose down -v          # удаляет volumes
docker compose up -d postgres redis
.venv/bin/alembic upgrade head
```

Обновить код:
```bash
cd ~/arb-intel
git pull
uv sync --all-extras
.venv/bin/alembic upgrade head
```

Логи:
```bash
docker compose logs -f postgres
docker compose logs -f redis
journalctl -u docker -f         # системные docker логи
```

Запуск воркеров отдельно (для масштабирования):
```bash
# в разных терминалах
.venv/bin/arb-intel-worker discovery
.venv/bin/arb-intel-worker tracker:base
.venv/bin/arb-intel-worker tracker:arbitrum
.venv/bin/arb-intel-worker tracker:solana
.venv/bin/arb-intel-worker scanner
.venv/bin/arb-intel-worker alerts
```

Запуск всего стека через docker:
```bash
docker compose up -d --build    # сначала соберёт образ
```

---

# Часть 6. Автозапуск при старте системы (опционально)

Если хочешь чтобы сервис стартовал сам при включении ноута:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/arb-intel.service <<'EOF'
[Unit]
Description=arb-intel arbitrage detector
After=docker.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=%h/arb-intel
ExecStartPre=/usr/bin/docker compose up -d postgres redis
ExecStart=%h/arb-intel/.venv/bin/arb-intel
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now arb-intel
sudo loginctl enable-linger $USER    # чтобы работал даже когда ты не залогинен
```

Проверить статус:
```bash
systemctl --user status arb-intel
journalctl --user -u arb-intel -f
```

Остановить:
```bash
systemctl --user stop arb-intel
systemctl --user disable arb-intel
```

---

Если на каком-либо шаге упадёт ошибка — скопируй её **целиком** (с номером шага),
я разберу.
