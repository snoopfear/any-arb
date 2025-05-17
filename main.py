import os
import random
import time
import requests
from web3 import Web3

# ------------------- SETTINGS ----------------------
ENABLED_CHAINS = ['opst', 'bast', 'unit', 'arbt']  # Включены для баланса и маршрутов

ALLOWED_ROUTES = {
    "opst": ["arbt", "bast", "unit"],
    "bast": ["arbt"],
    "unit": ["opst"]
    # "arbt" не должен быть источником
}

THRESHOLD_ETH = 10
MIN_BALANCE_TO_SEND = 25
DELAY_RANGE = (5, 10)  # Задержка между итерациями в секундах (от 15 до 30)

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
    'arbt': f'https://arb-sepolia.g.alchemy.com/v2/{APIKEY}',  # Только для баланса и в ALLOWED_ROUTES
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
print(f'Sender address: {SENDER_ADDRESS}')

# ------------------- ENCODING HELPERS ----------------------
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

def send_remote_order_tx(w3: Web3, from_chain: str, to_chain: str) -> bool:
    try:
        to_address = TO_ADDRESSES[from_chain]  # У всех вызовов один контракт
        sender = SENDER_ADDRESS

        balance_wei = w3.eth.get_balance(sender)
        balance_eth = w3.from_wei(balance_wei, 'ether')
        print(f"💰 [{from_chain.upper()}] Current balance: {balance_eth:.4f} ETH")
        if balance_eth < MIN_BALANCE_TO_SEND:
            print(f"⚠️  [{from_chain.upper()}] Balance too low (< {MIN_BALANCE_TO_SEND} ETH). Skipping.")
            return False

        estimated_amount = fetch_estimated_amount_wei(from_chain, to_chain)
        calldata = build_submit_remote_order_data(sender, estimated_amount, 10**18, chain_id_hex=to_chain.encode().hex())

        nonce = w3.eth.get_transaction_count(sender)
        gas_limit = 150000

        fee_history = w3.eth.fee_history(1, 'latest', [50])
        base_fee = fee_history['baseFeePerGas'][-1]
        priority_fee = w3.to_wei(1, 'gwei')
        max_fee_per_gas = base_fee + priority_fee * 2

        tx = {
            'from': sender,
            'to': to_address,
            'value': w3.to_wei(1, 'ether'),
            'gas': gas_limit,
            'maxFeePerGas': max_fee_per_gas,
            'maxPriorityFeePerGas': priority_fee,
            'type': 2,
            'data': calldata,
            'chainId': w3.eth.chain_id,
            'nonce': nonce
        }

        try:
            w3.eth.call(tx, 'latest')
        except Exception as call_error:
            print(f"🚫 [{from_chain.upper()} → {to_chain.upper()}] Call would revert: {call_error}")
            return False

        signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        print(f"✅ [{from_chain.upper()} → {to_chain.upper()}] TX sent: {w3.to_hex(tx_hash)}")
        return True

    except Exception as e:
        print(f"❌ [{from_chain.upper()}] TX failed: {e}")
        return False

def get_low_balance_chains(threshold=THRESHOLD_ETH):
    low_chains = []
    for chain, w3 in WEB3_INSTANCES.items():
        if chain not in ENABLED_CHAINS:
            continue
        bal = w3.eth.get_balance(SENDER_ADDRESS)
        eth_bal = w3.from_wei(bal, 'ether')
        if eth_bal <= threshold:
            low_chains.append(chain)
    return low_chains

# ------------------- MAIN LOOP ----------------------

while True:
    low_priority_chains = get_low_balance_chains()
    all_sources = [c for c in ALLOWED_ROUTES.keys() if c in ENABLED_CHAINS]

    if low_priority_chains:
        for target in low_priority_chains:
            for source in all_sources:
                if target in ALLOWED_ROUTES.get(source, []) and source != 'arbt':
                    w3 = WEB3_INSTANCES[source]
                    success = send_remote_order_tx(w3, source, target)
                    if success:
                        break
            else:
                continue
            break
    else:
        source = random.choice(all_sources)
        possible_targets = [t for t in ALLOWED_ROUTES[source] if t in ENABLED_CHAINS]
        if possible_targets:
            target = random.choice(possible_targets)
            w3 = WEB3_INSTANCES[source]
            send_remote_order_tx(w3, source, target)

    time.sleep(random.randint(*DELAY_RANGE))
