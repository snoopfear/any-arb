import os
import random
import time
import requests
from web3 import Web3
from web3.exceptions import Web3RPCError
from decimal import Decimal

# Загрузка переменных окружения
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
}

TO_ADDRESSES = {
    'opst': '0xb6Def636914Ae60173d9007E732684a9eEDEF26E',
    'bast': '0xCEE0372632a37Ba4d0499D1E2116eCff3A17d3C3',
    'unit': '0x1cEAb5967E5f078Fa0FEC3DFfD0394Af1fEeBCC9',
}

WEB3_INSTANCES = {name: Web3(Web3.HTTPProvider(url)) for name, url in RPCS.items()}
w3_example = next(iter(WEB3_INSTANCES.values()))
SENDER_ADDRESS = w3_example.eth.account.from_key(PRIVATE_KEY).address
print(f'Sender address: {SENDER_ADDRESS}')


# ------------------- encoding helpers ----------------------
def encode_uint256(n: int) -> str:
    return hex(n)[2:].zfill(64)

def encode_address(addr: str) -> str:
    return addr.lower().replace("0x", "").zfill(64)

def encode_bytes32(s: str) -> str:
    return s.lower().replace("0x", "").ljust(64, "0")


def fetch_estimated_amount_wei(chain: str) -> int:
    url = "https://api.t2rn.io/estimate"
    payload = {
        "amountWei": "1000000000000000000",
        "executorTipUSD": 5,
        "fromAsset": "eth",
        "fromChain": chain,
        "overpayOptionPercentage": 0,
        "spreadOptionPercentage": 1,
        "toAsset": "eth",
        "toChain": "arbt"
    }
    headers = {
        "accept": "*/*",
        "content-type": "application/json"
    }

    response = requests.post(url, headers=headers, json=payload, timeout=5)
    response.raise_for_status()
    hex_value = response.json()["estimatedReceivedAmountWei"]["hex"]
    return int(hex_value, 16)


def build_submit_remote_order_data(sender: str, amount_wei: int, max_reward_wei: int, chain_id_hex: str = "0x61726274") -> str:
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

def send_remote_order_tx(w3: Web3, chain: str) -> bool:
    try:
        to_address = TO_ADDRESSES[chain]
        sender = SENDER_ADDRESS

        # 1. Get estimated amount from API
        estimated_amount = fetch_estimated_amount_wei(chain)

        # 2. Build calldata
        calldata = build_submit_remote_order_data(sender, estimated_amount, 10**18)

        # 3. Transaction setup
        nonce = w3.eth.get_transaction_count(sender)
        gas_price = w3.to_wei(1, 'gwei')
        gas_limit = 105000

        tx = {
            'chainId': w3.eth.chain_id,
            'nonce': nonce,
            'to': to_address,
            'value': w3.to_wei(1, 'ether'),
            'gas': gas_limit,
            'gasPrice': gas_price,
            'data': calldata
        }

        signed_tx = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        print(f"✅ [{chain.upper()}] TX sent: {w3.to_hex(tx_hash)}")
        return True

    except Exception as e:
        print(f"❌ [{chain.upper()}] TX failed: {e}")
        return False

# ------------------- main loop ----------------------

while True:
    chain = random.choice(list(RPCS.keys()))
    w3 = WEB3_INSTANCES[chain]

    success = send_remote_order_tx(w3, chain)

    if not success:
        all_low = True
        for c, w in WEB3_INSTANCES.items():
            bal = w.eth.get_balance(SENDER_ADDRESS)
            if w.from_wei(bal, 'ether') > 1:
                all_low = False
                break

        if all_low:
            print("❌ All balances low. Exiting.")
            break

    sleep_time = random.randint(1, 5)
    print(f"⏳ Sleeping {sleep_time} sec...")
    time.sleep(sleep_time)

