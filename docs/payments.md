# Прямые платежи за память

Memory Market принимает оплату напрямую на публичный EVM-адрес оператора. Сервис не создаёт депозитных адресов, не хранит приватный ключ и не может вывести средства: он только читает Base, проверяет перевод canonical Circle USDC и атомарно выдаёт доступ к купленной Memory Unit.

## Быстрый запуск

Укажите в `.env` публичный адрес получения средств:

```dotenv
PAYMENT_RECIPIENT=0xYour40HexCharacterBaseAddress
```

Затем перезапустите Memory Market:

```bash
docker compose up -d --build memory-market hub
```

Проверка конфигурации:

```bash
curl -s http://127.0.0.1:8810/v1/billing/rail
curl -s http://127.0.0.1:8810/healthz
```

`enabled` должен быть `true`, а `pay_to` — совпадать с заданным адресом. В `.env` нужен только публичный адрес. Seed phrase и private key сервису не нужны и не должны попадать ни в `.env`, ни в Docker secrets.

## Как проходит покупка

1. Издатель создаёт Memory Unit с `visibility: "paid"` и `price_usdc`.
2. Покупатель указывает свой `Actor ID` и создаёт платёжный order.
3. Market фиксирует текущий блок Base и выдаёт уникальную точную сумму USDC. Например, при цене `2.50` счёт может быть `2.500037` USDC.
4. Покупатель переводит именно эту сумму canonical USDC в сети Base на `PAYMENT_RECIPIENT`. В ответе есть EIP-681 URI для совместимого кошелька.
5. Фоновый scanner или ручной endpoint проверки находит ERC-20 `Transfer` и проверяет токен, получателя, сумму, высоту блока, статус транзакции, глубину подтверждений и уникальность tx hash.
6. Захват транзакции и выдача access grant происходят в одной PostgreSQL-транзакции. После этого чтение разрешено только тому же криптографически подтверждённому actor.
7. Успешная покупка отправляется в Provenance Ledger как событие `shared`; временная недоступность ledger не отменяет уже подтверждённую оплату.

Последние шесть знаков суммы — invoice identifier, а не отдельная комиссия: эта микросумма входит в фактический перевод на кошелёк. Округлённый или частичный перевод не будет зачтён автоматически.

## API

Создать order:

```bash
curl -sS http://127.0.0.1:8810/v1/billing/orders \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer $MEMORY_MARKET_API_KEY' \
  -H 'X-Actor-ID: did:actor:<sha256-public-key>' \
  -H 'X-Actor-Public-Key: <base64url-public-key>' \
  -H 'X-Actor-Signature: <base64url-signature-over-actor-id>' \
  -d '{"memory_id":"mem_example","grantee_id":"did:actor:<sha256-public-key>"}'
```

Важные поля ответа:

- `amount_usdc` — точная отображаемая сумма;
- `amount_raw` — та же сумма в 6-decimal raw units для ERC-20;
- `pay_to` — адрес оператора;
- `token_address` — разрешённый контракт USDC;
- `eip681` — wallet deep link;
- `expires_at` и `required_confirmations` — условия финализации.

Узнать состояние order:

```bash
curl -sS http://127.0.0.1:8810/v1/billing/orders/pay_ORDER_ID \
  -H 'Authorization: Bearer $MEMORY_MARKET_API_KEY' \
  -H 'X-Actor-ID: did:actor:<sha256-public-key>' \
  -H 'X-Actor-Public-Key: <base64url-public-key>' \
  -H 'X-Actor-Signature: <base64url-signature-over-actor-id>'
```

Попросить немедленно проверить известную транзакцию:

```bash
curl -sS http://127.0.0.1:8810/v1/billing/orders/pay_ORDER_ID/confirm \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer $MEMORY_MARKET_API_KEY' \
  -H 'X-Actor-ID: did:actor:<sha256-public-key>' \
  -H 'X-Actor-Public-Key: <base64url-public-key>' \
  -H 'X-Actor-Signature: <base64url-signature-over-actor-id>' \
  -d '{"tx_hash":"0xTRANSACTION_HASH"}'
```

После `state: "confirmed"`:

```bash
curl -sS http://127.0.0.1:8810/v1/memories/mem_example \
  -H 'Authorization: Bearer $MEMORY_MARKET_API_KEY' \
  -H 'X-Actor-ID: did:actor:<sha256-public-key>' \
  -H 'X-Actor-Public-Key: <base64url-public-key>' \
  -H 'X-Actor-Signature: <base64url-signature-over-actor-id>'
```

Тот же flow доступен в консоли: карточка paid-memory открывает checkout, показывает точные реквизиты, копирование значений, wallet deep link и поле ручной проверки tx hash. Пока drawer открыт, состояние обновляется автоматически.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `PAYMENT_RECIPIENT` | пусто | Публичный адрес получения. Пустое значение полностью закрывает checkout. |
| `PAYMENT_CHAIN_ID` | `8453` | Base mainnet. Иное значение отвергается при старте. |
| `PAYMENT_ASSET` | `USDC` | Для direct rail поддерживается только USDC. |
| `PAYMENT_USDC_ADDRESS` | `0x8335…2913` | Canonical Circle USDC на Base. Менять только для контролируемого форка/теста. |
| `PAYMENT_BASE_RPC_URLS` | четыре публичных endpoint | Список JSON-RPC через запятую с автоматическим failover. В production используйте свои authenticated RPC. |
| `PAYMENT_MIN_CONFIRMATIONS` | `5` | Требуемая глубина подтверждений, от 1 до 200. |
| `PAYMENT_ORDER_TTL_MINUTES` | `60` | Срок действия котировки, от 5 минут до суток. |
| `PAYMENT_LATE_GRACE_HOURS` | `24` | Окно, в котором запоздавший on-chain перевод ещё может быть зачтён. |
| `PAYMENT_POLL_SECONDS` | `20` | Интервал фонового scanner, от 5 до 300 секунд. |
| `PAYMENT_LOG_SCAN_BLOCKS` | `40` | Начальный размер диапазона `eth_getLogs`; автоматически уменьшается при RPC range limit. |
| `PAYMENT_EXPLORER_URL` | `https://basescan.org` | Основа ссылок на адрес и транзакцию. |
| `AIFACTORY_CRYPTO_ENABLED` | `0` | Отдельная escrow/x402-система bundled Hub. Для direct settlement не нужна. |
| `TOPUP_ENABLED` | `0` | Пополнение кредитных счетов хаба в USDC ([credits-topup.ru.md](https://github.com/alexar76/aimarket-hub/blob/main/docs/credits-topup.ru.md)); пробрасывается как `AIMARKET_TOPUP_ENABLED`. |
| `TOPUP_PAY_TO` | пусто | Кошелёк, на который приходят пополнения и ничего больше (только адрес). Задан — хаб сам следит за ним и зачисляет поступления: оплату счёта и обычные переводы с привязанных кошельков. Пусто — пополнения идут на `PAYMENT_RECIPIENT`, и каждое нужно предъявить. Пробрасывается как `AIMARKET_TOPUP_PAY_TO`. |
| `PEER_API_KEYS` | пусто | Ключи кредитных счетов этого хаба на чужих хабах (`url=key,…`) для субподряда. Секрет: только `.env`. |

`PAYMENT_RECIPIENT` также передаётся Hub как `AIMARKET_PAYMENT_RECIPIENT` и `AIMARKET_X402_PAY_TO`, поэтому адрес может появляться в его платёжных метаданных. Это не включает приём x402 authorization: такой режим требует отдельно развёрнутых контрактов и settlement verifier.

Поэтому в `/.well-known/ai-market.json` хаба стоит `payment_configured: false`, и это ожидаемо.
Поле описывает только встроенную escrow/x402-систему (`AIFACTORY_CRYPTO_ENABLED`). Как хаб
принимает деньги на самом деле, видно рядом, в `payment_rails`:

- `seller_direct.enabled: true` — покупатель платит на payout-адрес листинга, хаб проверяет
  перевод и деньги не держит;
- `credits.enabled: true` — предоплаченный баланс по `X-API-Key`;
- `channel.enabled: false` — кастодиальные платёжные каналы выключены.

Агент или монитор, который судит о приёме оплаты по одному `payment_configured`, ошибётся:
смотрите `payment_rails`.

## Инварианты безопасности

Платёж подтверждается только если одновременно выполнены все условия:

- сеть — Base mainnet (`chain_id=8453`);
- адрес контракта совпадает с настроенным canonical USDC;
- `Transfer.to` в event log точно равен `PAYMENT_RECIPIENT`;
- `Transfer.value` точно равен `amount_raw` конкретного order;
- транзакция успешна, уже mined и имеет нужную глубину подтверждений;
- блок перевода не старше блока создания order;
- timestamp блока не выходит за TTL плюс late-grace;
- один tx hash может быть связан только с одним order;
- grant и присвоение tx hash коммитятся атомарно.

Присланный клиентом tx hash никогда не считается доказательством сам по себе. При недоступности всех RPC выдача доступа останавливается с `503`; при пустом/невалидном адресе checkout закрыт или приложение не стартует. Сканирование ведётся только по finalized range и продолжает его с сохранённой высоты после рестарта.

## Эксплуатация

- Используйте выделенный receiving wallet и сверяйте первые/последние символы адреса перед rollout.
- Поставьте сервис за TLS, identity-aware gateway и rate limiting. В production `X-Actor-ID` нельзя выбрать произвольно: он привязан к Ed25519 public key, а order read/confirm дополнительно требуют того же actor.
- Мониторьте ошибки scanner, отставание RPC, количество pending/expired order и баланс кошелька.
- Не уменьшайте confirmations без анализа reorg risk.
- Сохраните БД перед миграциями: в ней находятся соответствия order → tx → grant.
- Возвраты и revenue split не автоматизированы. Они требуют отдельной политики и исходящих транзакций вне этого сервиса.
- Не включайте `AIFACTORY_CRYPTO_ENABLED=1`, пока не развёрнуты и не проверены escrow contracts, oracle и settlement verifier bundled Hub.

## Проверка без реальных средств

Юнит-тесты используют детерминированную Fake Base chain и не отправляют транзакции:

```bash
./scripts/check.sh
```

Они проверяют недостаточную финальность, точное совпадение суммы, scanner, выдачу grant и запрет доступа при неверном платеже. Для staging используйте отдельный recipient и контролируемый RPC/fork; не подменяйте production USDC случайным токеном.
