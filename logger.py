import logging
import sys

class StrictAlignedColorFormatter(logging.Formatter):
    LOG_COLORS = {
        'DEBUG':    '\033[36m',     # cyan
        'INFO':     '\033[32m',     # green
        'WARNING':  '\033[33m',     # yellow
        'ERROR':    '\033[31m',     # red
        'CRITICAL': '\033[1;31m',   # bold red
    }
    RESET = '\033[0m'

    def format(self, record):
        level = f"{record.levelname + ':':<9}"
        color = self.LOG_COLORS.get(record.levelname, '')
        record.colored_level = f"{color}{level}{self.RESET}"
        return super().format(record)

def get_logger(name: str = "yada") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:  # prevent duplicate handlers
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(sys.stdout)
        formatter = StrictAlignedColorFormatter("%(colored_level)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
    return logger