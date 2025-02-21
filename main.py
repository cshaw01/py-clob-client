from flask import Flask, render_template, jsonify, request
import os
import json
from py_clob_client.constants import POLYGON
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, BalanceAllowanceParams, AssetType, OpenOrderParams
from py_clob_client.order_builder.constants import BUY, SELL
from dotenv import load_dotenv
import requests
import traceback
import psycopg2
from psycopg2.extras import execute_values

app = Flask(__name__)

load_dotenv()   

host = "https://clob.polymarket.com"
key = os.getenv("PK")
chain_id = POLYGON

# Create CLOB client and get/set API credentials
client = ClobClient(host, key=key, chain_id=chain_id)
client.set_api_creds(client.create_or_derive_api_creds())

def find_market_by_keyword(client, keywords):
    # Convert single string to list if needed
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k.lower() for k in keywords]  # Lowercase all keywords
    
    next_cursor = ""
    found_markets = []
    
    while True:
        response = client.get_markets(next_cursor)
        
        for market in response['data']:
            # Combine question and description for searching
            search_text = (market['question'].lower() + " " + 
                         market['description'].lower())
            
            # Check if all keywords exist in either question or description
            if all(keyword in search_text for keyword in keywords):
                found_markets.append({
                    'question': market['question'],
                    'condition_id': market['condition_id'],
                    'description': market['description'],
                    'tokens': market['tokens'],
                    'end_date': market['end_date_iso'],
                    'active': market['active'],
                    'closed': market['closed']
                })
        
        next_cursor = response.get('next_cursor')
        if next_cursor == "LTE=" or not next_cursor:
            break
            
    return found_markets

# resp = client.get_market(condition_id = "0x07904ab2c92f575593f7bdeeba7b8c5549f6ce88452c5d19ac9ca4f6df463356")
# print(json.dumps(resp, indent=4))
# Search for markets
# markets = find_market_by_keyword(client, ["youtube", "views"])

# # Print found markets in a readable format
# for market in markets:
#     print("\nMarket found:")
#     print(f"Question: {market['question']}")
#     print(f"Condition ID: {market['condition_id']}")
#     print(f"Description: {market['description']}")
#     # print(f"End Date: {market['end_date']}")
#     # print(f"Active: {market['active']}")
#     # print(f"Closed: {market['closed']}")
#     # print("Tokens:")
#     # for token in market['tokens']:
#     #     print(f"  - {token['outcome']}: {token['token_id']}")
#     print("-------------------")



# resp = client.create_and_post_order(OrderArgs(
#     price=0.01,
#     size=100.0,
#     side=BUY,
#     token_id="89139742281240115366822876841990931233470835661673990707817044229178025656408"
# ))

def get_order_book_summary(token_id):
    try:
        print(f"Fetching order book for token_id: {token_id}")
        book = client.get_order_book(token_id)
        
        if not book or not book.bids or not book.asks:
            return {'bids': [], 'asks': []}
        
        # Convert all orders to list of dicts with price as float for sorting
        all_bids = [{'price': float(bid.price), 'size': bid.size} for bid in book.bids]
        all_asks = [{'price': float(ask.price), 'size': ask.size} for ask in book.asks]
        
        # Sort bids descending (highest first) and asks ascending (lowest first)
        all_bids.sort(key=lambda x: x['price'], reverse=True)
        all_asks.sort(key=lambda x: x['price'])
        
        # Get 5 best bids and asks (closest to the spread)
        bids = all_bids[:5]
        asks = all_asks[:5]
        
        # Convert prices to cents format
        summary = {
            'bids': [{'price': f"{bid['price']*100:.1f}", 'size': bid['size']} for bid in bids],
            'asks': [{'price': f"{ask['price']*100:.1f}", 'size': ask['size']} for ask in asks]
        }
        
        print(f"Processed order book summary: {json.dumps(summary, indent=2)}")
        return summary
    except Exception as e:
        print(f"Error getting order book for token_id {token_id}: {str(e)}")
        print(f"Error type: {type(e)}")
        print(f"Error traceback: {traceback.format_exc()}")
        return {'bids': [], 'asks': []}

def update_bot_table(markets_data):
    try:
        # Connect to PostgreSQL
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        cur = conn.cursor()
        
        # Prepare data for insertion/update
        for market in markets_data:
            # Check if market already exists
            cur.execute("""
                SELECT market_id FROM bot WHERE market_id = %s
            """, (market['condition_id'],))
            
            exists = cur.fetchone()
            
            if exists:
                # Update existing record
                cur.execute("""
                    UPDATE bot 
                    SET yes_id = %s,
                        no_id = %s,
                        market_name = %s,
                        updated = CURRENT_TIMESTAMP
                    WHERE market_id = %s
                """, (
                    str(market['yes_token']),
                    str(market['no_token']),
                    market['question'],
                    market['condition_id']
                ))
            else:
                # Insert new record
                cur.execute("""
                    INSERT INTO bot (
                        market_id, yes_id, no_id, market_name,
                        buy_yes, buy_no, max_yes, max_no
                    ) VALUES (%s, %s, %s, %s, 0, 0, 0, 0)
                """, (
                    market['condition_id'],
                    str(market['yes_token']),
                    str(market['no_token']),
                    market['question']
                ))
        
        conn.commit()
        print(f"Successfully updated bot table with {len(markets_data)} markets")
        
    except Exception as e:
        print(f"Error updating bot table: {str(e)}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

@app.route('/')
def index():
    try:
        # Get collateral balance
        collateral = client.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        print(f"Collateral balance: {collateral}")
        
        # Use Gamma API to get event by slug with specific filters
        gamma_endpoint = "https://gamma-api.polymarket.com"
        event_slug = "the-monkey-opening-weekend-box-office"
        
        # Build query with multiple parameters
        params = {
            'slug': event_slug,  
            'active': True,
            'archived': False,
            'limit': 100
        }
        
        # Make request to Gamma API for events
        response = requests.get(f"{gamma_endpoint}/events", params=params)
        response.raise_for_status()
        event_data = response.json()
        
        # Save response to file for debugging
        with open('test.json', 'w') as f:
            json.dump({
                'url': response.url,
                'status_code': response.status_code,
                'response': event_data
            }, f, indent=4)
        
        # Check if we got any events
        if not event_data or not isinstance(event_data, list) or len(event_data) == 0:
            return render_template('index.html', 
                                error="No events found", 
                                collateral=collateral)
        
        # Get the first event
        event = event_data[0]
        markets_data = []
        
        # The markets are directly in the event object
        if 'markets' in event:
            for market in event['markets']:
                print(f"\nProcessing market: {market['question']}")
                token_ids = json.loads(market['clobTokenIds'])
                print(f"Token IDs: YES={token_ids[0]}, NO={token_ids[1]}")
                
                # Get positions from trade history
                try:
                    trades = client.get_trades()  # Get all trades for the user
                    print(f"\nAll trades: {json.dumps(trades, indent=2)}")
                    
                    yes_position = 0
                    no_position = 0
                    
                    for trade in trades:
                        print(f"\nProcessing trade: {json.dumps(trade, indent=2)}")
                        
                        # Check if this trade is for our current market
                        if str(trade.get('token_id')) == str(token_ids[0]):  # YES token
                            print(f"Found YES token trade")
                            if trade.get('side') == 'BUY':
                                yes_position += float(trade.get('size', 0))
                            else:
                                yes_position -= float(trade.get('size', 0))
                            print(f"Updated YES position: {yes_position}")
                            
                        elif str(trade.get('token_id')) == str(token_ids[1]):  # NO token
                            print(f"Found NO token trade")
                            if trade.get('side') == 'BUY':
                                no_position += float(trade.get('size', 0))
                            else:
                                no_position -= float(trade.get('size', 0))
                            print(f"Updated NO position: {no_position}")
                    
                    print(f"\nFinal positions for market {market['question']}:")
                    print(f"YES position: {yes_position}")
                    print(f"NO position: {no_position}")
                    
                except Exception as e:
                    print(f"Error getting positions: {str(e)}")
                    print(f"Error details: {traceback.format_exc()}")
                    yes_position = 0
                    no_position = 0
                
                try:
                    yes_price = client.get_price(token_ids[0], "SELL")
                    yes_price_value = yes_price.get('price', 'N/A')
                    print(f"YES price: {yes_price_value}")
                except Exception as e:
                    print(f"Error getting YES price: {str(e)}")
                    yes_price_value = 'No orderbook'
                    
                try:
                    no_price = client.get_price(token_ids[1], "SELL")
                    no_price_value = no_price.get('price', 'N/A')
                    print(f"NO price: {no_price_value}")
                except Exception as e:
                    print(f"Error getting NO price: {str(e)}")
                    no_price_value = 'No orderbook'
                
                # Get order books for both YES and NO tokens
                print("\nFetching YES token order book...")
                yes_book = get_order_book_summary(token_ids[0])
                print("\nFetching NO token order book...")
                no_book = get_order_book_summary(token_ids[1])
                
                market_info = {
                    'question': market['question'],
                    'condition_id': market['conditionId'],
                    'yes_token': token_ids[0],
                    'no_token': token_ids[1],
                    'yes_price': yes_price_value,
                    'no_price': no_price_value,
                    'volume': market.get('volume', '0'),
                    'accepting_orders': market.get('acceptingOrders', False),
                    'yes_order_book': yes_book,
                    'no_order_book': no_book,
                    'yes_position': yes_position,
                    'no_position': no_position
                }
                # print(f"\nMarket inf vo: {json.dumps(market_info, indent=2)}")
                markets_data.append(market_info)
                
            print(f"\nTotal markets processed: {len(markets_data)}")
            
            return render_template('index.html', 
                                event_title=event.get('title', 'Unknown Event'),
                                event_description=event.get('description', ''),
                                markets=markets_data, 
                                collateral=collateral)
        else:
            return render_template('index.html', 
                                error="No markets found for event", 
                                collateral=collateral)
                                
    except requests.exceptions.RequestException as e:
        print(f"API Request Error: {str(e)}")
        return render_template('index.html', 
                             error=f"API Error: {str(e)}", 
                             collateral=collateral)
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return render_template('index.html', 
                             error=f"Unexpected error: {str(e)}", 
                             collateral=collateral)

@app.route('/execute_trade', methods=['POST'])
def execute_trade():
    try:
        data = request.json
        
        # Create order arguments
        order_args = OrderArgs(
            price=float(data['price']),
            size=float(data['size']),
            side=BUY if data['side'] == 'BUY' else SELL,
            token_id=data['token_id']
        )
        
        # Execute the trade
        resp = client.create_and_post_order(order_args)
        
        return jsonify({'success': True, 'response': resp})
    except Exception as e:
        print(f"Error executing trade: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)