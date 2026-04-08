# logger.py

import logging

# Configure logging into structured JSON format
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s", "request_id": "%(request_id)s"}',
    datefmt='%Y-%m-%dT%H:%M:%S'
)

# Named logger instance
logger = logging.getLogger("order_api_logger")


def log_info(message: str, request_id: str = "N/A"):
    logger.info(message, extra={"request_id": request_id})

def log_error(message: str, request_id: str = "N/A"):
    logger.error(message, extra={"request_id": request_id})

def log_debug(message: str, request_id: str = "N/A"):
    logger.debug(message, extra={"request_id": request_id})

def log_warning(message: str, request_id: str = "N/A"):
    logger.warning(message, extra={"request_id": request_id})