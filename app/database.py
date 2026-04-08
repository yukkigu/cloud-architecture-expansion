# database.py

import os
import psycopg2
import psycopg2.extras
import hashlib
import json




# Establish database connection
def create_connection():
    """ Create a database connection to the PostgreSQL database. """

    # Database parameters
    db_params = {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "dbname": os.getenv("DB_NAME"),
    }

    conn = None
    try:
        # conn = connect(db_file, check_same_thread=False)
        # print(f"Connected to database: {db_file}")
        conn = psycopg2.connect(**db_params)
        conn.autocommit = False
        print("Connected to PostgreSQL database successfully.")
    except Exception as e:
        print(f"Error connecting to database: {e}")
    return conn

# Hash the request body for idempotency key storage
def hash_request_body(request_body: dict) -> str:
    """ Hash the request body to store in idempotency records. """
    # Convert the request body to a JSON string and hash it with sha256
    request_body_str = json.dumps(request_body, sort_keys=True)
    return hashlib.sha256(request_body_str.encode()).hexdigest()

# Implement idempotency key handling
def idempotency_check(idempotency_key: str, conn):
    """ Check if the same request has been processed before using an idempotency key. """
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # check if the idempotency key exists in the idempotency_records table
    cursor.execute(
        "SELECT response_body, status_code, request_body_hash FROM idempotency_records WHERE idempotency_key = %s",
        (idempotency_key,),
    )
    # if record exists, return the cached response, status code, and request body hash
    record = cursor.fetchone()
    
    if record:
        # return cached response, status code, and request body hash
        return record["response_body"], record["status_code"], record["request_body_hash"] 
    else:
        # no record found, return none
        return None, None, None

# Store the response in the idempotency records table
def store_idempotency_record(idempotency_key: str, request_body_hash: str, response_body: dict, status_code: int, conn):
    """ Store the response in the idempotency records table. """
    cursor = conn.cursor()
    # insert record into idempotency_records table
    cursor.execute(
        """
        INSERT INTO idempotency_records (idempotency_key, request_body_hash, response_body, status_code)
        VALUES (%s, %s, %s, %s)
        """,
        (idempotency_key, request_body_hash, json.dumps(response_body), status_code),
    )

# Insert order into orders table and ledger table
def insert_order(order_id: str, customer_id: str, item_id: str, quantity: int, status: str, idempotency_key: str, conn):
    """ Insert order into orders table and ledger table. """
    cursor = conn.cursor()
    # insert into orders table
    cursor.execute(
        """
        INSERT INTO orders (order_id, customer_id, item_id, quantity, status, idempotency_key)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (order_id, customer_id, item_id, quantity, status, idempotency_key),
    )
    # insert into ledger table
    cursor.execute(
        """
        INSERT INTO ledger (order_id, customer_id, quantity)
        VALUES (%s, %s, %s)
        """,
        (order_id, customer_id, quantity),
    )

# Retrieve order details by order_id
def get_order_by_id(order_id: str, conn):
    """ Retrieve order details by order_id. """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT order_id, customer_id, item_id, quantity, status FROM orders WHERE order_id = %s",
        (order_id,),
    )
    return cursor.fetchone()

# Retrieve item details by item_id
def get_item_by_id(item_id: int, conn):
    """ Retrieve item details by item_id. """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT item_id, name, value FROM items WHERE item_id = %s",
        (item_id,),
    )
    return cursor.fetchone()

# Insert item into items table
def insert_item(name: str, value: int, conn):
    """ Insert item into items table. """
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO items (name, value)
        VALUES (%s, %s)
        RETURNING item_id
        """,
        (name, value),
    )
    return cursor.fetchone()[0]  # Return the generated item_id