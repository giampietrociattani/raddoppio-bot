import schedule
import time
import logging
from bot import run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

log.info("Bot scheduler avviato — ciclo ogni 3 ore")
run()  # Prima esecuzione immediata

schedule.every(3).hours.do(run)

while True:
    schedule.run_pending()
    time.sleep(60)
