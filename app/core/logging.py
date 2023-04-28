import logging
import sys
from logging.handlers import TimedRotatingFileHandler

def setup_logging():
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = logging.INFO

    # Set up the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Set up a console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(console_handler)

    # Set up a rotating file handler
    file_handler = TimedRotatingFileHandler("logs/norman.log", when="midnight")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(file_handler)

# Call the setup_logging function to configure logging
setup_logging()


'''
# usage 
import logging

logger = logging.getLogger(__name__)

# Use logger as usual
logger.info("This is an info message")
logger.warning("This is a warning message")
logger.error("This is an error message")
'''
