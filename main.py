import os
import random
import time
import requests
from datetime import datetime, timedelta
from web3 import Web3
import json

# ------------------- CONFIG ----------------------

CONFIG = {
    "ENABLED_CHAINS": ['opst', 'bast', 'unit', 'arbt'],
    "ALLOWED_ROUTES": {
        "opst": ["arbt", "bast", "unit"],
        "bast": ["arbt", "opst", "unit"],
        "unit": ["arbt", "opst", "bast"]
    },
    "THRESHOLD_ETH": 20,
    "MIN_BALANCE_TO_SEND": 25,
    "DELAY_RANGE": (5, 10),
    "SUCCESS_DELAY_MULTIPLIER": 1,
    "FAILURE_DELAY_MULTIPLIER": 0.1,
    "BALANCE_CHECK_EVERY_SUCCESS_TX": 10,

    # Новый блок настроек запроса к t2rn
    "ESTIMATE_REFRESH_INTERVAL_RANGE_SEC": (180, 300),  # (3, 5) минут
    "ESTIMATE_FLUCTUATION_PERCENT_RANGE": (0.0000011, 0.0000015),  # ±0.01%–0.011%

    # --- Паузы ---
    "PAUSE_FILE": "pauses_schedule.txt",
    "BIG_PAUSE_MIN_HOURS": 5,
    "BIG_PAUSE_MAX_HOURS": 7,
    "BIG_PAUSE_MIN_GAP_HOURS": (22, 26),
    "SMALL_PAUSE_COUNT_RANGE": (1, 3),
    "SMALL_PAUSE_MIN_GAP_HOURS": 3,
    "MIN_GAP_BETWEEN_PAUSES_HOURS": 3,
    "DAY_START_HOUR": 0,  # начало суток для генерации пауз
}

HIGH_BALANCE_THRESHOLD = 100
HIGH_BALANCE_WEIGHT = 0.7

# ------------------- ENV SETUP ----------------------

PRIVATE_KEY = os.getenv('PRIVATE_KEY_LOCAL')
APIKEY = os.getenv('APIKEY')

if not PRIVATE_KEY:
    raise Exception('PRIVATE_KEY_LOCAL is missing in environment!')
if not APIKEY:
    raise Exception('APIKEY is missing in environment!')

RPCS = {
    'opst': f'https://opt-sepolia.g.alchemy.com/v2/{APIKEY}',
    'bast': f'https://base-sepolia.g.alchemy.com/v2/{APIKEY}',
    'unit': f'https://unichain-sepolia.g.alchemy.com/v2/{APIKEY}',
    'arbt': f'https://arb-sepolia.g.alchemy.com/v2/{APIKEY}',
}

TO_ADDRESSES = {
    'opst': '0xb6Def636914Ae60173d9007E732684a9eEDEF26E',
    'bast': '0xCEE0372632a37Ba4d0499D1E2116eCff3A17d3C3',
    'unit': '0x1cEAb5967E5f078Fa0FEC3DFfD0394Af1fEeBCC9',
}

WEB3_INSTANCES = {name: Web3(Web3.HTTPProvider(url)) for name, url in RPCS.items()}
w3_example = next(iter(WEB3_INSTANCES.values()))
SENDER_ADDRESS = w3_example.eth.account.from_key(PRIVATE_KEY).address
print(f'👤 Sender address: {SENDER_ADDRESS}')

# ------------------- CACHED ESTIMATES ----------------------

_estimate_cache = {}
_estimate_timestamps = {}
_estimate_refresh_intervals = {}

def fetch_estimated_amount_wei(from_chain: str, to_chain: str) -> int:
    key = f"{from_chain}→{to_chain}"
    now = time.time()
    last_time = _estimate_timestamps.get(key, 0)
    interval = _estimate_refresh_intervals.get(key, random.uniform(*CONFIG["ESTIMATE_REFRESH_INTERVAL_RANGE_SEC"]))

    if now - last_time >= interval or key not in _estimate_cache:
        try:
            print(f"🌐 Обновление estimate {key} из API")
            url = "https://api.t2rn.io/estimate"
            payload = {
                "amountWei": "1000000000000000000",
                "executorTipUSD": 5,
                "fromAsset": "eth",
                "fromChain": from_chain,
                "overpayOptionPercentage": 0,
                "spreadOptionPercentage": 1,
                "toAsset": "eth",
                "toChain": to_chain
            }
            headers = {"accept": "*/*", "content-type": "application/json"}
            response = requests.post(url, headers=headers, json=payload, timeout=5)
            response.raise_for_status()
            hex_value = response.json()["estimatedReceivedAmountWei"]["hex"]
            value = int(hex_value, 16)
            _estimate_cache[key] = value
            _estimate_timestamps[key] = now
            _estimate_refresh_intervals[key] = random.uniform(*CONFIG["ESTIMATE_REFRESH_INTERVAL_RANGE_SEC"])
        except Exception as e:
            print(f"⚠️ Ошибка при получении estimate: {e}")
            if key not in _estimate_cache:
                raise e  # Если данных нет, прерываем
            value = _estimate_cache[key]
    else:
        value = _estimate_cache[key]
        fluct_range = CONFIG["ESTIMATE_FLUCTUATION_PERCENT_RANGE"]
        fluct = random.uniform(*fluct_range)
        fluct *= -1 if random.random() < 0.5 else 1
        value = int(value * (1 + fluct))
        print(f"♻️ Используется estimate из кэша с флуктуацией {fluct*100:.5f}%")

    return value

# ------------------- HELPERS ----------------------

def encode_uint256(n: int) -> str:
    return hex(n)[2:].zfill(64)

def encode_address(addr: str) -> str:
    return addr.lower().replace("0x", "").zfill(64)

def encode_bytes32(s: str) -> str:
    return s.lower().replace("0x", "").ljust(64, "0")

def build_submit_remote_order_data(sender: str, amount_wei: int, max_reward_wei: int, chain_id_hex: str) -> str:
    selector = "56591d59"
    return (
        "0x" + selector +
        encode_bytes32(chain_id_hex) +
        encode_uint256(0) +
        encode_address(sender) +
        encode_uint256(amount_wei) +
        "0" * 64 +
        encode_uint256(0) +
        encode_uint256(max_reward_wei)
    )

def parse_simulation_error(err: Exception) -> str:
    msg = str(err)
    if "execution reverted:" in msg:
        start = msg.find("execution reverted:")
        end = msg.find("',", start)
        if end == -1:
            end = len(msg)
        return msg[start:end].strip("'\" ")
    return msg

def send_remote_order_tx(w3: Web3, from_chain: str, to_chain: str) -> bool:
    try:
        to_address = TO_ADDRESSES[from_chain]
        sender = SENDER_ADDRESS

        balance_wei = w3.eth.get_balance(sender)
        balance_eth = w3.from_wei(balance_wei, 'ether')
        print(f"💰 [{from_chain.upper()}] Баланс: {balance_eth:.4f} ETH")
        if balance_eth < CONFIG["MIN_BALANCE_TO_SEND"]:
            print(f"⚠️  Недостаточный баланс (< {CONFIG['MIN_BALANCE_TO_SEND']} ETH). Пропуск.")
            return False

        estimated_amount = fetch_estimated_amount_wei(from_chain, to_chain)
        calldata = build_submit_remote_order_data(sender, estimated_amount, 10**18, chain_id_hex=to_chain.encode().hex())

        nonce = w3.eth.get_transaction_count(sender)

        fee_history = w3.eth.fee_history(1, 'latest', [50])
        base_fee = fee_history['baseFeePerGas'][-1]
        priority_fee = w3.to_wei(1, 'gwei')
        max_fee_per_gas = base_fee + priority_fee * 2

        tx_common = {
            'from': sender,
            'to': to_address,
            'value': w3.to_wei(1, 'ether'),
            'data': calldata,
        }

        try:
            estimated_gas = w3.eth.estimate_gas(tx_common)
            gas_limit = int(estimated_gas * 1.1)
        except Exception:
            print(f"⚠️ Оценка газа не удалась. Использую gas_limit = 110000.")
            gas_limit = 110_000

        tx = {
            **tx_common,
            'gas': gas_limit,
            'maxFeePerGas': max_fee_per_gas,
            'maxPriorityFeePerGas': priority_fee,
            'type': 2,
            'chainId': w3.eth.chain_id,
            'nonce': nonce
        }

        try:
            w3.eth.call(tx, 'latest')
        except Exception as call_error:
            parsed_err = parse_simulation_error(call_error)
            print(f"🚫 [{from_chain.upper()} → {to_chain.upper()}] Транзакция отклонена при симуляции: ({parsed_err})")
            return False

        signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        print(f"✅ [{from_chain.upper()} → {to_chain.upper()}] TX отправлена: {w3.to_hex(tx_hash)}")
        return True

    except Exception as e:
        print(f"❌ [{from_chain.upper()}] Ошибка при отправке TX: {e}")
        return False

# ------------------- BALANCE CHECKS ----------------------

def get_low_balance_chains():
    low_balance = []
    for chain, w3 in WEB3_INSTANCES.items():
        if chain not in CONFIG["ENABLED_CHAINS"]:
            continue
        bal = w3.eth.get_balance(SENDER_ADDRESS)
        eth_bal = w3.from_wei(bal, 'ether')
        if eth_bal < CONFIG["THRESHOLD_ETH"]:
            low_balance.append(chain)
    return low_balance

def choose_source_chain(all_sources):
    high_balance_chains = []
    normal_chains = []
    for c in all_sources:
        bal = WEB3_INSTANCES[c].eth.get_balance(SENDER_ADDRESS)
        eth_bal = WEB3_INSTANCES[c].from_wei(bal, 'ether')
        if eth_bal > HIGH_BALANCE_THRESHOLD:
            high_balance_chains.append(c)
        else:
            normal_chains.append(c)

    if high_balance_chains and random.random() < HIGH_BALANCE_WEIGHT:
        return random.choice(high_balance_chains)
    if normal_chains:
        return random.choice(normal_chains)
    return random.choice(all_sources)

def check_balances():
    print("\n🔍 Проверка балансов...")
    for chain, w3 in WEB3_INSTANCES.items():
        if chain not in CONFIG["ENABLED_CHAINS"]:
            continue
        balance = w3.eth.get_balance(SENDER_ADDRESS)
        eth_balance = w3.from_wei(balance, 'ether')
        print(f"   - {chain.upper()}: {eth_balance:.4f} ETH")

# ------------------- PAUSE LOGIC ----------------------

def read_pauses_schedule():
    if not os.path.exists(CONFIG["PAUSE_FILE"]):
        return None
    try:
        with open(CONFIG["PAUSE_FILE"], "r", encoding="utf-8") as f:
            data = json.load(f)
            # data format: { "date": "YYYY-MM-DD", "pauses": [{"start": timestamp, "duration": seconds}, ...], "last_big_pause": timestamp }
            return data
    except Exception as e:
        print(f"⚠️ Ошибка чтения расписания пауз: {e}")
        return None

def save_pauses_schedule(schedule):
    try:
        with open(CONFIG["PAUSE_FILE"], "w", encoding="utf-8") as f:
            json.dump(schedule, f)
    except Exception as e:
        print(f"⚠️ Ошибка записи расписания пауз: {e}")

def generate_pauses_schedule(last_big_pause_ts=None):
    today_date = datetime.utcnow().date()
    day_start_dt = datetime.combine(today_date, datetime.min.time()) + timedelta(hours=CONFIG["DAY_START_HOUR"])

    # Определяем когда можно делать большую паузу (через 22-26 часов после last_big_pause)
    if last_big_pause_ts:
        earliest_big_pause_start = datetime.utcfromtimestamp(last_big_pause_ts) + timedelta(
            hours=random.uniform(*CONFIG["BIG_PAUSE_MIN_GAP_HOURS"]))
        if earliest_big_pause_start < day_start_dt:
            earliest_big_pause_start = day_start_dt
    else:
        earliest_big_pause_start = day_start_dt

    # Большая пауза в диапазоне 5-7 часов, не раньше earliest_big_pause_start + 22-26 часов
    big_pause_start_window_start = earliest_big_pause_start
    big_pause_start_window_end = day_start_dt + timedelta(days=1)

    # Если сейчас за день слишком поздно для большой паузы, сдвигаем на следующий день
    if big_pause_start_window_start > big_pause_start_window_end:
        # Запланируем большую паузу на следующий день (через ~24 часа)
        big_pause_start_window_start = big_pause_start_window_end
        big_pause_start_window_end = big_pause_start_window_start + timedelta(hours=4)

    big_pause_start = big_pause_start_window_start + timedelta(
        seconds=random.uniform(0, (big_pause_start_window_end - big_pause_start_window_start).total_seconds()))
    big_pause_duration = timedelta(
        hours=random.uniform(CONFIG["BIG_PAUSE_MIN_HOURS"], CONFIG["BIG_PAUSE_MAX_HOURS"]))

    big_pause_end = big_pause_start + big_pause_duration

    pauses = []
    # Добавляем большую паузу
    pauses.append({"start": int(big_pause_start.timestamp()), "duration": int(big_pause_duration.total_seconds()), "type": "big"})

    # Малые паузы (1-3 шт)
    small_count = random.randint(*CONFIG["SMALL_PAUSE_COUNT_RANGE"])
    small_pause_total_period_start = day_start_dt
    small_pause_total_period_end = big_pause_start  # До большой паузы

    # Для простоты разбросаем малые паузы равномерно между началом суток и большой паузой, соблюдая минимальные интервалы
    possible_start = small_pause_total_period_start.timestamp()
    possible_end = small_pause_total_period_end.timestamp()

    small_pauses = []
    last_pause_end = possible_start - CONFIG["MIN_GAP_BETWEEN_PAUSES_HOURS"] * 3600

    for _ in range(small_count):
        # Определяем минимальный старт, чтобы не было меньше 3 часов от предыдущей паузы
        min_start = last_pause_end + CONFIG["MIN_GAP_BETWEEN_PAUSES_HOURS"] * 3600
        max_start = possible_end - (small_count - len(small_pauses)) * (CONFIG["MIN_GAP_BETWEEN_PAUSES_HOURS"] * 3600)

        if min_start > max_start:
            break  # не можем поставить паузу

        start_ts = random.uniform(min_start, max_start)
        duration_sec = random.randint(15*60, 30*60)  # Малые паузы 15-30 минут
        small_pauses.append({"start": int(start_ts), "duration": duration_sec, "type": "small"})
        last_pause_end = start_ts + duration_sec

    pauses.extend(small_pauses)

    # Сортируем по времени
    pauses.sort(key=lambda x: x["start"])

    schedule = {
        "date": today_date.isoformat(),
        "pauses": pauses,
        "last_big_pause": int(big_pause_start.timestamp())
    }
    save_pauses_schedule(schedule)
    print(f"🕒 Сгенерировано расписание пауз на {today_date}: {len(pauses)} пауз (большая - {big_pause_duration})")
    return schedule

def get_current_pause(schedule):
    now_ts = int(time.time())
    for p in schedule["pauses"]:
        start = p["start"]
        end = start + p["duration"]
        if start <= now_ts < end:
            return p
    return None

def should_generate_new_schedule(schedule):
    today_date = datetime.utcnow().date()
    if not schedule:
        return True
    if schedule.get("date") != today_date.isoformat():
        return True
    return False

def wait_for_pause_end(pause):
    pause_end_ts = pause["start"] + pause["duration"]
    now_ts = int(time.time())
    sleep_seconds = pause_end_ts - now_ts
    if sleep_seconds > 0:
        pause_type = pause.get("type", "pause")
        print(f"⏸ {pause_type.capitalize()} пауза активна, спим {sleep_seconds} сек...")
        time.sleep(sleep_seconds)

# ------------------- MAIN LOOP ----------------------

success_tx_count = 0
check_balances()

# Загружаем расписание пауз
schedule = read_pauses_schedule()
if should_generate_new_schedule(schedule):
    last_big_pause = schedule["last_big_pause"] if schedule else None
    schedule = generate_pauses_schedule(last_big_pause_ts=last_big_pause)

while True:
    # Проверяем паузу
    current_pause = get_current_pause(schedule)
    if current_pause:
        # В паузе — спим
        wait_for_pause_end(current_pause)
        # Если это большая пауза — обновляем расписание на следующий день после её окончания
        if current_pause["type"] == "big":
            print("🔄 Большая пауза закончилась, обновляем расписание пауз...")
            schedule = generate_pauses_schedule(last_big_pause_ts=current_pause["start"])
        continue  # После паузы идём к следующему циклу

    if success_tx_count > 0 and success_tx_count % CONFIG["BALANCE_CHECK_EVERY_SUCCESS_TX"] == 0:
        check_balances()

    all_sources = [c for c in CONFIG["ALLOWED_ROUTES"].keys() if c in CONFIG["ENABLED_CHAINS"]]
    low_priority_targets = get_low_balance_chains()

    target_candidates = low_priority_targets if low_priority_targets else list(set(
        t for src in all_sources for t in CONFIG["ALLOWED_ROUTES"][src]
    ) & set(CONFIG["ENABLED_CHAINS"]))

    source = choose_source_chain(all_sources)
    # Продолжаем основной цикл после выбора source-chain:

    allowed_targets_for_source = [t for t in CONFIG["ALLOWED_ROUTES"].get(source, []) if t in CONFIG["ENABLED_CHAINS"]]

    # Фильтруем allowed_targets_for_source так, чтобы они совпадали с target_candidates,
    # либо если target_candidates пусты — берём все разрешённые
    targets = [t for t in allowed_targets_for_source if t in target_candidates]
    if not targets:
        targets = allowed_targets_for_source

    if not targets:
        print("⚠️ Нет доступных target-цепочек для выбранного source. Ждём...")
        time.sleep(60)
        continue

    target = random.choice(targets)

    print(f"\n▶️ Пробуем отправить TX: {source.upper()} → {target.upper()}")

    success = send_remote_order_tx(WEB3_INSTANCES[source], source, target)

    delay_sec = random.uniform(*CONFIG["DELAY_RANGE"])
    if success:
        delay_sec *= CONFIG["SUCCESS_DELAY_MULTIPLIER"]
        success_tx_count += 1
    else:
        delay_sec *= CONFIG["FAILURE_DELAY_MULTIPLIER"]

    print(f"🕑 Ждём {delay_sec:.1f} секунд перед следующим циклом...")
    time.sleep(delay_sec)
