# app/worker/tasks.py  
# Entry point for defining and importing Celery tasks from modules

from app.worker.celery_app import celery_app  
from app.core.logging_setup import logger  
import asyncio

# \--- Health Check Task (already defined in celery_app.py, keep or remove) \---  
@celery_app.task(bind=True, name="health_check")  
def health_check_task(self):  
    logger.info(f"Celery health check task running. Task ID: {self.request.id}")  
    return {"status": "ok"}

# \--- Import Tasks from Modules \---  
# It's generally cleaner to define tasks within their respective modules  
# and import them here so Celery discovers them.

try:  
    from app.modules.sales.tasks import \* \# Import all tasks from sales module  
    logger.info("Imported tasks from sales module.")  
except ImportError:  
    logger.warning("Could not import tasks from sales module.")

try:  
    from app.modules.delivery.tasks import \* \# Import all tasks from delivery module  
    logger.info("Imported tasks from delivery module.")  
except ImportError:  
    logger.warning("Could not import tasks from delivery module.")

try:  
    from app.modules.llm.tasks import \* \# Import all tasks from llm module  
    logger.info("Imported tasks from llm module.")  
except ImportError:  
    logger.warning("Could not import tasks from llm module.")

# Import tasks from other modules (people, whatsapp) as needed...

# Example: If a task needs shared services, it might need app context or explicit setup  
# This is complex with Celery. Often easier to re-instantiate clients within the task.  
# from app.services.memory_service import memory_service \# Example direct import (may cause issues)

# @celery_app.task(bind=True, name="example.use_service")  
# def example_task_using_service(self, chat_id: str):  
#     log \= logger.bind(celery_task_id=self.request.id)  
#     log.info("Example task using memory service.")  
#     \# Problem: memory_service singleton might not have DB/Redis connected in worker process  
#     \# Solution 1: Pass necessary data (chat_id) and re-instantiate service inside task  
#     \# Solution 2: Celery signals to setup/teardown connections per worker process (more complex)  
#     \# Solution 3: Use async task and get context within async function  
#     async def do_work():  
#         \# Need to ensure event loop is running and connections are established in worker context  
#         \# This depends heavily on how Celery workers and FastAPI lifespan interact  
#         try:  
#             \# Attempt to get memory (may fail if DB not connected in worker)  
#             memory \= await memory_service.get_memory_for_chat(chat_id)  
#             history \= await memory.get_recent_messages(5)  
#             log.info(f"Got history: {len(history)} messages.")  
#             return {"history_length": len(history)}  
#         except Exception as e:  
#             log.exception("Error using service inside Celery task.")  
#             raise e \# Fail task  
#     try:  
#         \# Run async function from sync task (if worker is sync)  
#         result \= asyncio.run(do_work())  
#         return result  
#     except Exception as e:  
#          raise self.retry(exc=e, countdown=30)
