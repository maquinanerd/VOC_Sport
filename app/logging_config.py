import logging
import logging.config
import sys
from pathlib import Path

LOG_DIR = 'logs'
LOG_LEVEL = 'INFO'

def setup_logging():
    """
    Configura o logging para a aplicação.
    Cria um diretório de logs e configura o logging para o console e para um arquivo.
    """
    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'app.log'

    logging_config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'stream': sys.stdout,
                'formatter': 'default',
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': log_file,
                'maxBytes': 1024 * 1024 * 5,  # 5 MB
                'backupCount': 5,
                'formatter': 'default',
                'encoding': 'utf-8',
            },
        },
        'loggers': {
            '': {  # Root logger
                'handlers': ['console', 'file'],
                'level': LOG_LEVEL.upper(),
                'propagate': True,
            },
            'apscheduler': {
                'level': 'WARNING',
            },
            'urllib3': {
                'level': 'WARNING',
            },
            'requests': {
                'level': 'WARNING',
            }
        }
    }

    logging.config.dictConfig(logging_config)