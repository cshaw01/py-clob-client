import os
from datetime import datetime, timedelta
from py_clob_client.constants import POLYGON
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import TradeParams
from dotenv import load_dotenv
load_dotenv()

def setup_client():
    # Basic required configuration
    host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
    # Ensure host doesn't end with a trailing slash
    host = host.rstrip('/')
    private_key = os.getenv("PK")
    
    if not private_key:
        raise ValueError("Please set PK environment variable")

    # Initialize client
    client = ClobClient(host, key=private_key, chain_id=POLYGON)

    # Check if API credentials already exist
    if not all([os.getenv("CLOB_API_KEY"), os.getenv("CLOB_SECRET"), os.getenv("CLOB_PASS_PHRASE")]):
        try:
            print("Generating API credentials...")
            creds = client.create_api_key()
            print("Save these credentials in your .env file:")
            print(f"CLOB_API_KEY={creds['apiKey']}")
            print(f"CLOB_SECRET={creds['secret']}")
            print(f"CLOB_PASS_PHRASE={creds['passphrase']}")
        except Exception as e:
            print(f"Failed to generate API credentials: {str(e)}")
            print("Please ensure your CLOB_API_URL and PK are correct")
            raise

    return client

def get_user_positions(client):
    # Get trades from the last 30 days
    start_date = datetime.now() - timedelta(days=30)
    
    # Fetch trade history
    trades = client.get_trades(
        params=TradeParams(
            start_date=start_date.isoformat(),
        )
    )
    
    # Group trades by market
    positions = {}
    for trade in trades:
        market_id = trade['token_id']
        
        if market_id not in positions:
            # Get market details
            market = client.get_market(market_id)
            positions[market_id] = {
                'name': market.get('name', 'Unknown Market'),
                'size': 0,
                'trades': []
            }
        
        # Add or subtract from position size based on side
        size_change = float(trade['size'])
        if trade['side'] == 'SELL':
            size_change = -size_change
            
        positions[market_id]['size'] += size_change
        positions[market_id]['trades'].append(trade)

    return positions

def main():
    client = setup_client()
    positions = get_user_positions(client)
    
    # Print positions
    print("\nYour Current Positions:")
    print("-" * 50)
    for market_id, data in positions.items():
        if data['size'] != 0:  # Only show active positions
            print(f"Market: {data['name']}")
            print(f"Position Size: {data['size']}")
            print(f"Number of Trades: {len(data['trades'])}")
            print("-" * 50)

if __name__ == "__main__":
    main() 