import os
import random
import time
from web3 import Web3
from web3.exceptions import Web3RPCError

# Загрузка приватного ключа и APIKEY из переменных окружения
PRIVATE_KEY = os.getenv('PRIVATE_KEY_LOCAL')
APIKEY = os.getenv('APIKEY')

if not PRIVATE_KEY:
    raise Exception('Ошибка: PRIVATE_KEY_LOCAL не найден в окружении!')

if not APIKEY:
    raise Exception('Ошибка: APIKEY не найден в окружении!')

# RPC по сетям
RPCS = {
    'opt': f'https://opt-sepolia.g.alchemy.com/v2/{APIKEY}',
    'base': f'https://base-sepolia.g.alchemy.com/v2/{APIKEY}',
    'uni': f'https://unichain-sepolia.g.alchemy.com/v2/{APIKEY}',
}

# Целевые адреса для каждой сети
TO_ADDRESSES = {
    'opt': '0xb6Def636914Ae60173d9007E732684a9eEDEF26E',
    'base': '0xCEE0372632a37Ba4d0499D1E2116eCff3A17d3C3',
    'uni': '0x1cEAb5967E5f078Fa0FEC3DFfD0394Af1fEeBCC9',
}

BASE_VALUE = 0x0de089c08f7071dc


def get_random_value():
    random_percent = random.uniform(0.0001, 0.0002)
    new_value = int(BASE_VALUE - (BASE_VALUE * random_percent)) & 0xFFFFFFFFFFFFFFFF
    return hex(new_value)[2:]


def get_tx_data():
    random_value = get_random_value()
    template = (
        '0x56591d5961726274000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000189b27215bC6c8d842A4D320fcb232ce8A076013'
        '0000000000000000000000000000000000000000000000000{value}000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000de0b6b3a7640000'
    )
    return {chain: template.format(value=random_value) for chain in RPCS.keys()}


WEB3_INSTANCES = {name: Web3(Web3.HTTPProvider(url)) for name, url in RPCS.items()}
w3_example = next(iter(WEB3_INSTANCES.values()))
SENDER_ADDRESS = w3_example.eth.account.from_key(PRIVATE_KEY).address

print(f'✅ Адрес отправителя: {SENDER_ADDRESS}')


def get_network_fees(w3: Web3):
    fee_history = w3.eth.fee_history(1, 'latest', [50])
    base_fee = fee_history['baseFeePerGas'][-1]
    priority_fee_suggested = fee_history['reward'][-1][0]

    return int(base_fee), int(priority_fee_suggested)


def send_priority_tx(w3: Web3, chain: str):
    data = get_tx_data()[chain]
    to_address = TO_ADDRESSES[chain]

    for attempt in range(3):
        try:
            balance = w3.eth.get_balance(SENDER_ADDRESS)
            eth_balance = w3.from_wei(balance, 'ether')
            if eth_balance <= 25:
                print(f"❌ Баланс в {chain.upper()} меньше или равен 25 ETH: {eth_balance:.4f} ETH")
                return False

            nonce = w3.eth.get_transaction_count(SENDER_ADDRESS, 'pending')
            base_fee, suggested_priority_fee = get_network_fees(w3)

            priority_fee = int(suggested_priority_fee * 2.5) + w3.to_wei(0.2, 'gwei')  # 🚀 +150-200%
            priority_fee = int(priority_fee * (1 + 0.2 * attempt))  # +20% за каждую повторную попытку

            max_fee_per_gas = base_fee * 2 + priority_fee

            estimated_gas = w3.eth.estimate_gas({
                'from': SENDER_ADDRESS,
                'to': to_address,
                'value': w3.to_wei(1, 'ether'),
                'data': data
            })
            gas_limit = int(estimated_gas * 1.2)

            tx = {
                'chainId': w3.eth.chain_id,
                'nonce': nonce,
                'to': to_address,
                'value': w3.to_wei(1, 'ether'),
                'gas': gas_limit,
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': priority_fee,
                'type': 2,
                'data': data
            }

            signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            print(f"✅ [{chain.upper()}] Приоритетная транзакция отправлена: {w3.to_hex(tx_hash)}")
            return True

        except Web3RPCError as e:
            error_message = str(e)
            print(f'⚠️ [{chain.upper()}] Ошибка при отправке транзакции: {error_message}')
            if 'underpriced' in error_message or 'nonce too low' in error_message:
                continue
            else:
                break

        except Exception as e:
            print(f'❌ [{chain.upper()}] Неизвестная ошибка: {str(e)}')
            continue

    print('❌ Не удалось отправить приоритетную транзакцию после 3 попыток.')
    return False


# Основной цикл
while True:
    chain = random.choice(list(RPCS.keys()))
    w3 = WEB3_INSTANCES[chain]

    success = send_priority_tx(w3, chain)

    if not success:
        all_low = True
        for c, w in WEB3_INSTANCES.items():
            bal = w.eth.get_balance(SENDER_ADDRESS)
            if w.from_wei(bal, 'ether') > 1:
                all_low = False
                break

        if all_low:
            print("❌ Во всех сетях баланс ниже 25 ETH. Завершение.")
            break

    sleep_time = random.randint(1, 5)
    print(f"⏳ Ждем {sleep_time} секунд до следующей транзакции...")
    time.sleep(sleep_time)
