import os
import random
import time
import requests
from web3 import Web3

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
    # Убираем баланс по времени
    # "BALANCE_CHECK_INTERVAL_SEC": 300  # 5 минут
    "BALANCE_CHECK_EVERY_SUCCESS_TX": 10,  # Проверять баланс каждые 10 успешных транзакций
}

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
    'arbt': '0x22B65d0B9b59af4D3Ed59F18b9Ad53f5F4908B54',
}

WEB3_INSTANCES = {name: Web3(Web3.HTTPProvider(url)) for name, url in RPCS.items()}
w3_example = next(iter(WEB3_INSTANCES.values()))
SENDER_ADDRESS = w3_example.eth.account.from_key(PRIVATE_KEY).address
print(f'👤 Sender address: {SENDER_ADDRESS}')

# ------------------- HELPERS ----------------------

def encode_uint256(n: int) -> str:
    return hex(n)[2:].zfill(64)

def encode_address(addr: str) -> str:
    return addr.lower().replace("0x", "").zfill(64)

def encode_bytes32(s: str) -> str:
    return s.lower().replace("0x", "").ljust(64, "0")

def fetch_estimated_amount_wei(from_chain: str, to_chain: str) -> int:
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
    return int(hex_value, 16)

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
    # Извлекаем только первую часть с кодом ошибки
    msg = str(err)
    if "execution reverted:" in msg:
        # Пример: "('execution reverted: RO#7', '0x08c3...')"
        # Возьмём только 'execution reverted: RO#7'
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

        # 🔽 ЛОГ DATA
        #print(f"📦 [{from_chain.upper()} → {to_chain.upper()}] Calldata: {calldata}")

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
            gas_limit = int(estimated_gas * 1.2)
        except Exception as estimate_error:
            print(f"⚠️ Оценка газа не удалась. Использую gas_limit = 105000.")
            gas_limit = 105_000

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

# ------------------- MAIN LOOP ----------------------

success_tx_count = 0
low_priority_chains = []

def check_balances():
    global low_priority_chains
    print("\n🔍 Проверка балансов...")
    low_priority_chains.clear()

    for chain, w3 in WEB3_INSTANCES.items():
        if chain not in CONFIG["ENABLED_CHAINS"]:
            continue
        balance = w3.eth.get_balance(SENDER_ADDRESS)
        eth_balance = w3.from_wei(balance, 'ether')
        print(f"   - {chain.upper()}: {eth_balance:.4f} ETH")
        if eth_balance <= CONFIG["THRESHOLD_ETH"]:
            low_priority_chains.append(chain)

    if low_priority_chains:
        print(f"⚠️ Приоритет: {', '.join(c.upper() for c in low_priority_chains)}")
    else:
        print("✅ Все балансы в норме.")

check_balances()

while True:
    # Проверка баланса по успешным транзакциям
    if success_tx_count > 0 and success_tx_count % CONFIG["BALANCE_CHECK_EVERY_SUCCESS_TX"] == 0:
        check_balances()

    all_sources = [c for c in CONFIG["ALLOWED_ROUTES"].keys() if c in CONFIG["ENABLED_CHAINS"]]
    success = False

    if low_priority_chains:
        for target in low_priority_chains:
            for source in all_sources:
                if target in CONFIG["ALLOWED_ROUTES"].get(source, []) and source != 'arbt':
                    w3 = WEB3_INSTANCES[source]
                    success = send_remote_order_tx(w3, source, target)
                    if success:
                        break
            if success:
                break
    else:
        source = random.choice(all_sources)
        targets = [t for t in CONFIG["ALLOWED_ROUTES"][source] if t in CONFIG["ENABLED_CHAINS"]]
        if targets:
            target = random.choice(targets)
            w3 = WEB3_INSTANCES[source]
            success = send_remote_order_tx(w3, source, target)

    if success:
        success_tx_count += 1

    base_delay = random.randint(*CONFIG["DELAY_RANGE"])
    delay = int(base_delay * CONFIG["SUCCESS_DELAY_MULTIPLIER"] if success else base_delay * CONFIG["FAILURE_DELAY_MULTIPLIER"])
    delay = max(1, delay)

    print(f"⏳ Следующая попытка через {delay} сек...\n")
    time.sleep(delay)
