#!/usr/bin/env python3
"""
RSS to WordPress Automation System - Ponto de Entrada
"""

import argparse
import logging
import sys
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import SCHEDULE_CONFIG
from app.logging_config import setup_logging
from app.pipeline import run_pipeline_cycle
from app.cleanup import CleanupManager
from app.store import Database

logger = logging.getLogger(__name__)

def main():
    """Função principal para configurar e iniciar o aplicativo."""
    setup_logging()

    parser = argparse.ArgumentParser(description='RSS to WordPress Automation System')
    parser.add_argument('--once', action='store_true', help='Run a single cycle and exit')
    args = parser.parse_args()

    # Inicializa o banco de dados para garantir que as tabelas existam
    try:
        db = Database()
        db.initialize()
        db.close()
        logger.info("Verificação do banco de dados concluída com sucesso.")
    except Exception as e:
        logger.critical(f"Falha crítica ao inicializar o banco de dados: {e}", exc_info=True)
        sys.exit(1)

    if args.once:
        logger.info("Executando um único ciclo do pipeline (--once).")
        try:
            run_pipeline_cycle()
            logger.info("Ciclo único concluído com sucesso.")
        except Exception as e:
            logger.critical(f"Erro crítico durante a execução do ciclo único: {e}", exc_info=True)
            sys.exit(1)
    else:
        logger.info("Iniciando o agendador para execução contínua.")
        scheduler = BlockingScheduler(timezone="UTC")
        cleanup_manager = CleanupManager(cleanup_after_hours=SCHEDULE_CONFIG.get('cleanup_after_hours', 72))

        try:
            # Adiciona o job do pipeline principal
            scheduler.add_job(
                run_pipeline_cycle,
                trigger=IntervalTrigger(minutes=SCHEDULE_CONFIG.get('check_interval_minutes', 15)),
                id='pipeline_cycle_job',
                name='Run RSS processing pipeline',
                replace_existing=True,
                next_run_time=datetime.now()  # Roda imediatamente ao iniciar
            )

            # Adiciona o job de limpeza
            cleanup_interval_hours = max(24, SCHEDULE_CONFIG.get('cleanup_after_hours', 72) // 2)
            scheduler.add_job(
                cleanup_manager.run_cleanup,
                trigger=IntervalTrigger(hours=cleanup_interval_hours),
                id='cleanup_job',
                name='Cleanup old data',
                replace_existing=True
            )

            logger.info(f"Agendador iniciado. Pipeline rodará a cada {SCHEDULE_CONFIG.get('check_interval_minutes', 15)} minutos.")
            logger.info(f"Limpeza de dados antigos agendada para cada {cleanup_interval_hours} horas.")
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Agendador interrompido pelo usuário.")
        except Exception as e:
            logger.critical(f"Erro crítico no agendador: {e}", exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    main()
