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

# Данные для транзакций
TX_DATA = {
    'opt': '0x56591d5961726274000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000189b27215bC6c8d842A4D320fcb232ce8A0760130000000000000000000000000000000000000000000000000dde4f3abc938436000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000de0b6b3a7640000',
    'base': '0x56591d5961726274000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000189b27215bC6c8d842A4D320fcb232ce8A0760130000000000000000000000000000000000000000000000000de076b510f59707000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000de0b6b3a7640000',
    'uni': '0x56591d5961726274000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000189b27215bC6c8d842A4D320fcb232ce8A0760130000000000000000000000000000000000000000000000000de076b706379126000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000de0b6b3a7640000',
}

# Инициализируем Web3 для всех сетей
WEB3_INSTANCES = {name: Web3(Web3.HTTPProvider(url)) for name, url in RPCS.items()}

# Получаем адрес отправителя
w3_example = next(iter(WEB3_INSTANCES.values()))
SENDER_ADDRESS = w3_example.eth.account.from_key(PRIVATE_KEY).address

print(f'✅ Адрес отправителя: {SENDER_ADDRESS}')

def send_tx(w3: Web3, chain: str):
    data = TX_DATA[chain]
    to_address = TO_ADDRESSES[chain]

    for attempt in range(3):
        try:
            balance = w3.eth.get_balance(SENDER_ADDRESS)
            eth_balance = w3.from_wei(balance, 'ether')
            if eth_balance <= 0.1:
                print(f"❌ Баланс в {chain.upper()} меньше или равен 0.1 ETH: {eth_balance:.4f} ETH")
                return False

            nonce = w3.eth.get_transaction_count(SENDER_ADDRESS, 'pending')

            # Получение gas fee динамически через RPC
            latest_block = w3.eth.get_block('latest')
            base_fee = latest_block.get('baseFeePerGas', w3.to_wei(1, 'gwei'))
            priority_fee = w3.eth.max_priority_fee
            priority_fee += w3.to_wei(random.uniform(0.0001, 0.0003), 'gwei')

            # Estimate gas
            estimated_gas = w3.eth.estimate_gas({
                'from': sender_address,
                'to': to_address,
                'value': w3.to_wei(1, 'ether'),
                'data': data
            })
            
            tx = {
                'chainId': w3.eth.chain_id,
                'nonce': nonce,
                'to': to_address,
                'value': w3.to_wei(1, 'ether'),
                'gas': 1400000,
                'maxFeePerGas': base_fee + priority_fee,
                'maxPriorityFeePerGas': priority_fee,
                'type': 2,
                'data': data
            }

            signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            print(f"✅ [{chain.upper()}] Транзакция отправлена: {w3.to_hex(tx_hash)} → {to_address}")
            return True

        except Web3RPCError as e:
            error_message = str(e)
            if 'nonce too low' in error_message:
                print('⚠️ Nonce too low, пробуем снова...')
                time.sleep(1)
                continue
            elif 'replacement transaction underpriced' in error_message:
                print('⚠️ Replacement transaction underpriced, увеличиваем приоритет...')
                time.sleep(1)
                continue
            else:
                print(f'❌ Неизвестная ошибка: {error_message}')
                break

    print('❌ Не удалось отправить транзакцию после 3 попыток.')
    return False

# Основной цикл
while True:
    chain = random.choice(list(RPCS.keys()))
    w3 = WEB3_INSTANCES[chain]

    success = send_tx(w3, chain)
    if not success:
        # Если баланс кончился, проверяем и по другим сетям
        all_low = True
        for c, w in WEB3_INSTANCES.items():
            bal = w.eth.get_balance(SENDER_ADDRESS)
            if w.from_wei(bal, 'ether') > 0.1:
                all_low = False
                break

        if all_low:
            print("❌ Во всех сетях баланс ниже 0.1 ETH. Завершение.")
            break

    sleep_time = random.randint(1, 5)
    print(f"⏳ Ждем {sleep_time} секунд до следующей транзакции...")
    time.sleep(sleep_time)
