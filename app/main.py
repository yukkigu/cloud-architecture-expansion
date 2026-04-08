# main.py

import uuid, json, time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from app.schemas import OrderRequest, OrderResponse, ItemRequest, ItemResponse
from app.database import create_connection
from app.database import hash_request_body, idempotency_check, store_idempotency_record, insert_order, get_order_by_id, get_item_by_id, insert_item
from app.logger import log_info, log_error, log_debug, log_warning
import psycopg2.errors


# Initialize database connection, create tables on startup, and close connection on shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Set up the database connection and create tables on startup.
    Close the connection on shutdown.
    """
    # create database connection to orders.db 
    log_info("Creating database connection and tables...")
    # db_file = "orders.db"
    # conn = create_connection(db_file)
    conn = create_connection()

    # store in database connection in app state for use in endpoints
    app.state.db_conn = conn
    log_info("Starting up the Order Management API...")
    
    yield
    # on shutdown, close the database connection
    log_info("Shutting down the Order Management API...")
    # check if connection exists and is open before closing
    active_conn = getattr(app.state, "db_conn", None)
    # if connection exists and is open, close it
    if active_conn and active_conn.closed == 0:
        active_conn.close()
        log_info("Database connection closed.")
    app.state.db_conn = None

# Initialize FastAPI app with lifespan for startup and shutdown events
app = FastAPI(lifespan=lifespan)


# Rate limiting configuration
RATE_LIMIT = 5  # max requests
TIME_WINDOW = 10  # time window in seconds

# In-memory store for rate limiting
rate_limit_store = defaultdict(deque)


# Helper function to save connection
def get_db_connection(request: Request):
    """
    Check if the database connection is healthy.
    Return a live DB connection.
    Recreate connection if missing, closed, or stale after DB restart.
    """
    conn = request.app.state.db_conn
    # If missing or already closed connection -> reconnect
    if conn is None or conn.closed != 0:
        log_warning("DB connection missing/closed. Reconnecting...", request_id=getattr(request.state, "request_id", None))
        conn = create_connection()
        request.app.state.db_conn = conn
        return conn

    # Stale connection (e.g., Postgres restarted) -> ping + reconnect on failure
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return conn
    except Exception as e:
        log_warning(f"DB connection stale. Reconnecting... error={e}", request_id=getattr(request.state, "request_id", None))
        try:
            conn.close()
        except Exception:
            pass
        conn = create_connection()
        request.app.state.db_conn = conn
        return conn

# Set up a middleware to generate request_id for each request and log it
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """
    Generate a unique request_id for each incoming request and log it for tracing.
    """
    # if request id exists in headers, use it, otherwise generate a new one
    request_id = request.headers.get("Request-ID")
    if request_id:
        log_info(f"Received Request-ID header: {request_id}")
        request.state.request_id = request_id
    else:
        # if request id does not exist, generate a new one
        request_id = str(uuid.uuid4())
        log_info("No Request-ID header found, generating a new request ID.", request_id=request_id)
        # save the generated request_id in request state
        request.state.request_id = request_id
        log_info(f"Request ID generated: {request_id}", request_id=request_id)

    log_info(f"Received request: {request.method} {request.url}", request_id=request_id)

    response = await call_next(request)
    # add the request_id to the response headers for tracking
    response.headers["Request-ID"] = request_id
    log_info(f"Completed request: {request.method} {request.url} with status {response.status_code}", request_id=request_id)
    return response

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """
    Sliding-window rate limiter.
    Allows up to RATE_LIMIT requests per TIME_WINDOW for each client IP.
    """
    # skip health checks so ALB monitoring is not throttled
    if request.url.path == "/health":
        return await call_next(request)

    # get client IP from x-forwarded-for header (if behind proxy) or from request.client.host
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    now = time.time()
    timestamps = rate_limit_store[client_ip]

    # remove old timestamps outside the sliding window
    while timestamps and now - timestamps[0] >= TIME_WINDOW:
        timestamps.popleft()

    # reject if limit exceeded
    if len(timestamps) >= RATE_LIMIT:
        log_warning(
            f"Rate limit exceeded for IP {client_ip}",
            request_id=getattr(request.state, "request_id", None)
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
            headers={"Retry-After": str(TIME_WINDOW)}
        )

    # record this request and continue
    timestamps.append(now)
    response = await call_next(request)
    return response


# API: /orders - POST to create a new order
@app.post("/orders")
def create_order(request: Request, order: OrderRequest):
    """
    Create a new order.

    CHECK:
      - Idempotency: Check if the same request exists.
      - Order_id: Check if the generated order_id already exists in the database to prevent duplicates.
    
    If the request is a duplicate (same idempotency key or order_id), return the saved response.
    Only create new order if idempotency key is unique and order_id does not exist in the database.
    """

    conn = get_db_connection(request)

    # extract idempotency key from headers
    idempotency_key = request.headers.get("Idempotency-Key")

    # if idempotency key is missing, return 400 error
    if not idempotency_key:
        log_error("Missing idempotency key in request headers.", request_id=request.state.request_id)
        raise HTTPException(status_code=400, detail="Missing idempotency key")
    
    # hash the request body for idempotency check
    hash_request = hash_request_body(order.model_dump())
    # check if idempotency key exists in database
    stored_response, stored_status_code, stored_request_hash = idempotency_check(
        idempotency_key=idempotency_key,
        conn=conn
    )
    # if record exists, check if request body hash matches
    if stored_response is not None:
        if stored_request_hash == hash_request:
            log_info("Idempotency key found with matching request body hash. Returning stored response.", request_id=request.state.request_id)
            return JSONResponse(content=json.loads(stored_response), status_code=stored_status_code)
        else:
            log_warning("Conflict Case: Same key, different payload. Idempotency key found but request body hash does not match.", request_id=request.state.request_id)
            raise HTTPException(status_code=409, detail="Conflict Case: Same key, different payload.")
    
    # if no record exists for the idempotency key, proceed with creating the order
    log_info("No existing idempotency record found. Creating new order.", request_id=request.state.request_id)
    try:
        # insert into order and ledger tables
        order_id=str(uuid.uuid4())  # generate a unique order_id
        insert_order(
            order_id=order_id,
            customer_id=order.customer_id,
            item_id=order.item_id,
            quantity=order.quantity,
            status="created",
            idempotency_key=idempotency_key,
            conn=conn
        )
        # store in idempotency records table
        store_idempotency_record(
            idempotency_key=idempotency_key,
            request_body_hash=hash_request,
            response_body={"order_id": order_id, "status": "created"},
            status_code=201,
            conn=conn
        )

        # commit the transaction to save changes to the database
        conn.commit()

        response = {"order_id": order_id, "status": "created"}
        
    except Exception as e:
        conn.rollback()  # rollback the transaction in case of error
        log_error(f"Error creating order: {e}", request_id=request.state.request_id)
        raise HTTPException(status_code=500, detail="Internal Server Error")
    
    # Failure simulation
    debug_key = request.headers.get("X-Debug-Fail-After-Commit")
    if debug_key == "true":
        log_error("Failure simulation: Order has timed out after commit", request_id=request.state.request_id)
        raise HTTPException(status_code=500, detail="Simulated Failure:Internal Server Error")
    
    return JSONResponse(content=response, status_code=201)

# API: /orders/{order_id} - GET to read a specific order
@app.get("/orders/{order_id}")
def read_order(request: Request, order_id: str):
    """
    Retrieve a specific order by order_id.
    """
    try:
        conn = get_db_connection(request)
        log_info(f"Reading order: {order_id}", request_id=request.state.request_id)
        # read order details from database
        order_details = get_order_by_id(order_id=order_id, conn=conn)
    except Exception as e:
        # if error occurs while reading from database, log the error and return 500 error
        log_error(f"Error reading order: {e}", request_id=request.state.request_id)
        raise HTTPException(status_code=500, detail="Internal Server Error.")
    
    # if order not found, return 404 error
    if order_details is None:
        log_warning("Order not found", request_id=request.state.request_id)
        raise HTTPException(status_code=404, detail="Order not found.")

    # if order found, return the order details in the response
    response = {
        "order_id": order_details[0],
        "customer_id": order_details[1],
        "item_id": order_details[2],
        "quantity": order_details[3],
        "status": order_details[4]
    }
    return JSONResponse(content=response, status_code=200)

# API: /health - GET to check the health and database connection
@app.get("/health")
def health_check(request: Request):
    """
    Health check endpoint to verify that the API is running.
     - Returns 200 OK if the API is healthy.
     - Return non-200 if not ready
     - Can be used by load balancers or monitoring tools to check the health of the service.
    """
    try:
        conn = get_db_connection(request)
        # check if database connection is healthy by executing a simple query
        if conn is None or conn.closed != 0:
            raise HTTPException(
                status_code=503,
                detail={"status": "degraded", "db": "disconnected"},
            )

        # Check if query executes successfully
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

        # Return degraded status if query does not return expected result
        if result is None or result[0] != 1:
            raise HTTPException(
                status_code=503,
                detail={"status": "degraded", "db": "disconnected"},
            )

        # If everything is healthy, return 200 OK with status message
        return JSONResponse(
            content={"status": "ok", "db": "connected"},
            status_code=200,
        )

    except HTTPException:
        raise
    except Exception as e:
        log_error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={"status": "degraded", "db": "disconnected"},
        )

# API: /items/{item_id} - GET to read a specific item
@app.get("/items/{item_id}")
def get_items_by_id(request: Request, item_id: int):
    """
    Retrieve a specific item by item_id.
    """
    try:
        conn = get_db_connection(request)
        log_info(f"Reading item: {item_id}", request_id=request.state.request_id)
        item_details = get_item_by_id(item_id=item_id, conn=conn)
    except Exception as e:
        log_error(f"Error reading item: {e}", request_id=request.state.request_id)
        raise HTTPException(status_code=500, detail="Internal Server Error.")
    
    if item_details is None:
        log_warning("Item not found", request_id=request.state.request_id)
        raise HTTPException(status_code=404, detail="Item not found.")

    response = {
        "id": item_details[0],
        "name": item_details[1],
        "value": item_details[2]
    }
    return JSONResponse(content=response, status_code=200)

# API: /items - POST to create a new item
@app.post("/items")
def create_item(request: Request, item: ItemRequest):
    """
    Create a new item.
    """
    try:
        conn = get_db_connection(request)
        if conn:
            log_info(f"Creating item: {item.name}", request_id=request.state.request_id)
            try:
                item_id = insert_item(name=item.name, value=item.value, conn=conn)
                conn.commit()
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                raise HTTPException(status_code=409, detail="Item name already exists.")
            except Exception:
                conn.rollback()
                raise HTTPException(status_code=500, detail="Internal Server Error.")
            response = {
                "id": item_id,
                "name": item.name,
                "value": item.value
            }
            return JSONResponse(content=response, status_code=201)
        else:
            log_error("Database connection is not available.", request_id=request.state.request_id)
            raise HTTPException(status_code=500, detail="Internal Server Error.")
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"Error creating item: {e}", request_id=request.state.request_id)
        raise HTTPException(status_code=500, detail="Internal Server Error.")
    
