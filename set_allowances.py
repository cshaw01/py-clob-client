from web3 import Web3
from web3.constants import MAX_INT
from web3.middleware import geth_poa_middleware
from dotenv import load_dotenv
import os
import time

def setup_allowances():
    # Load environment variables
    load_dotenv()
    
    # Configuration
    RPC_URL = "https://polygon-rpc.com"
    CHAIN_ID = 137
    
    # Get private key from environment (without 0x prefix)
    private_key = os.getenv("PK")
    if not private_key:
        raise ValueError("Please set POLYMARKET_PRIVATE_KEY in your .env file")
    
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key

    # Initialize Web3
    web3 = Web3(Web3.HTTPProvider(RPC_URL))
    web3.middleware_onion.inject(geth_poa_middleware, layer=0)
    
    # Get account from private key
    account = web3.eth.account.from_key(private_key)
    public_address = account.address
    
    print(f"Setting up allowances for address: {public_address}")
    
    # Check POL/MATIC balance
    balance = web3.eth.get_balance(public_address)
    print(f"Current POL balance: {web3.from_wei(balance, 'ether')} POL")
    
    if balance == 0:
        raise ValueError("No POL found in wallet. Please add POL to cover gas fees.")

    # Contract ABIs
    ERC20_ABI = """[{
        "constant": false,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "payable": false,
        "stateMutability": "nonpayable",
        "type": "function"
    }]"""

    ERC1155_ABI = """[{
        "inputs": [
            {"internalType": "address", "name": "operator", "type": "address"},
            {"internalType": "bool", "name": "approved", "type": "bool"}
        ],
        "name": "setApprovalForAll",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }]"""

    # Contract addresses
    USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
    
    # Spender addresses that need allowances
    SPENDERS = {
        "CTF Exchange": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
        "Neg Risk CTF Exchange": "0xC5d563A36AE78145C45a50134d48A1215220f80a",
        "Neg Risk Adapter": "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
    }

    # Initialize contracts
    usdc_contract = web3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
    ctf_contract = web3.eth.contract(address=CTF_ADDRESS, abi=ERC1155_ABI)

    # Add a function to get the next nonce with retry
    def get_next_nonce(web3, address, retries=3, delay=1):
        for _ in range(retries):
            try:
                return web3.eth.get_transaction_count(address)
            except Exception:
                time.sleep(delay)
        raise Exception("Failed to get nonce after retries")

    # Add a function to send transaction with retry
    def send_transaction(web3, transaction, private_key, retries=3, delay=2):
        signed_tx = web3.eth.account.sign_transaction(transaction, private_key)
        for _ in range(retries):
            try:
                tx_hash = web3.eth.send_raw_transaction(signed_tx.rawTransaction)
                receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
                return receipt
            except Exception as e:
                if "nonce too low" in str(e):
                    time.sleep(delay)
                    continue
                raise e
        raise Exception("Failed to send transaction after retries")

    # Set allowances for each spender
    for spender_name, spender_address in SPENDERS.items():
        print(f"\nSetting allowances for {spender_name}...")
        
        # Set USDC allowance
        try:
            nonce = get_next_nonce(web3, public_address)
            tx = usdc_contract.functions.approve(
                spender_address,
                int(MAX_INT, 0)
            ).build_transaction({
                "chainId": CHAIN_ID,
                "from": public_address,
                "nonce": nonce,
                "gasPrice": web3.eth.gas_price
            })
            
            receipt = send_transaction(web3, tx, private_key)
            print(f"✅ USDC allowance set for {spender_name}")
            # Add delay between transactions
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Failed to set USDC allowance for {spender_name}: {str(e)}")
            continue

        # Set CTF allowance
        try:
            nonce = get_next_nonce(web3, public_address)
            tx = ctf_contract.functions.setApprovalForAll(
                spender_address,
                True
            ).build_transaction({
                "chainId": CHAIN_ID,
                "from": public_address,
                "nonce": nonce,
                "gasPrice": web3.eth.gas_price
            })
            
            receipt = send_transaction(web3, tx, private_key)
            print(f"✅ CTF allowance set for {spender_name}")
            # Add delay between transactions
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Failed to set CTF allowance for {spender_name}: {str(e)}")

if __name__ == "__main__":
    setup_allowances() 