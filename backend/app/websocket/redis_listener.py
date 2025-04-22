# app/websocket/redis_listener.py  
# Listens to Redis Pub/Sub channels meant for WebSocket broadcast

import asyncio  
import json  
from typing import Dict, Any  
from app.core.logging_config import logger  
from app.core.config import settings  
from app.redis.redis_client import get_redis_client, redis \# Import Redis client  
from app.websocket.connection_manager import manager \# Import connection manager

_listener_task: asyncio.Task | None \= None  
_stop_event \= asyncio.Event()

async def websocket_redis_listener_loop():  
    """Main loop listening to Redis channels for WebSocket updates."""  
    log \= logger.bind(service="WebSocketListener")  
    log.info("Starting WebSocket Redis listener task...")  
    redis_client: redis.Redis | None \= None  
    pubsub: redis.client.PubSub | None \= None  
    \# Use patterns defined in settings  
    subscribed_patterns \= settings.REDIS_LISTEN_CHANNELS or \["vox.\*"\] \# Default if empty

    while not _stop_event.is_set():  
        try:  
            \# Connect/Reconnect Logic  
            if redis_client is None or not await redis_client.ping():  
                log.info("WS Listener attempting to get/reconnect Redis client...")  
                if pubsub:  
                    try: await pubsub.unsubscribe(); await pubsub.close()  
                    except Exception: pass  
                    pubsub \= None  
                redis_client \= get_redis_client()  
                pubsub \= redis_client.pubsub(ignore_subscribe_messages=True)  
                if subscribed_patterns:  
                    await pubsub.psubscribe(\*subscribed_patterns) \# Use psubscribe for patterns  
                    log.success(f"WS Listener subscribed to Redis patterns: {subscribed_patterns}")  
                else:  
                     log.warning("WS Listener: No Redis channels configured for listening.")  
                     await asyncio.sleep(10); continue

            \# Listen for Messages using psubscribe  
            async for message in pubsub.listen():  
                if _stop_event.is_set(): break  
                if message and message.get("type") \== "pmessage":  
                    channel \= message.get("channel") \# The pattern matched  
                    raw_data \= message.get("data")  
                    log.debug(f"WS Listener received message via psubscribe. Pattern: {channel}")

                    if raw_data:  
                        try:  
                            payload \= json.loads(raw_data) \# Data should already be decoded  
                            \# \--- Routing Logic \---  
                            \# Expecting payload structure like:  
                            \# { "__target__": "user"/"all"/"group"...,  
                            \#   "__target_id__": "user_id/group_id...",  
                            \#   "event_type": "...", "data": {...} }  
                            target \= payload.get("__target__", "all")  
                            target_id \= payload.get("__target_id__")  
                            \# Prepare message for WebSocket clients (remove internal fields)  
                            ws_message \= {  
                                "type": payload.get("event_type", channel), \# Use event_type or channel  
                                "payload": payload.get("data", payload) \# Send original data part  
                            }

                            if target \== "all":  
                                await manager.broadcast(ws_message)  
                            elif target \== "user" and target_id:  
                                await manager.broadcast_to_user(ws_message, target_id)  
                            \# Add logic for other targets ('group', specific client_id?)  
                            else:  
                                log.warning(f"Unknown target '{target}' or missing target_id in event from {channel}. Broadcasting to all.")  
                                await manager.broadcast(ws_message)

                        except json.JSONDecodeError: log.error(f"WS Listener: Failed to decode JSON from pattern '{channel}': {raw_data\!r}")  
                        except Exception: log.exception(f"WS Listener: Error processing/broadcasting message from pattern '{channel}'")  
                elif message: log.debug(f"WS Listener: Received non-pmessage type: {message.get('type')}")

            log.warning("WS Listener: Pubsub listen loop ended unexpectedly. Attempting reconnect...")  
            redis_client \= None; await asyncio.sleep(2)

        except redis.ConnectionError as e:  
             log.error(f"WS Listener: Redis connection error: {e}. Retrying...")  
             redis_client \= None; pubsub \= None  
             await asyncio.sleep(5)  
        except RuntimeError as e: \# Catch errors from get_redis_client  
             log.error(f"WS Listener: Failed to get Redis client: {e}. Retrying...")  
             await asyncio.sleep(10)  
        except Exception as e:  
             log.exception("WS Listener: Unexpected error in main loop.")  
             await asyncio.sleep(5)

    \# Cleanup  
    log.info("WebSocket Redis listener task shutting down.")  
    if pubsub:  
        try:  
            await pubsub.punsubscribe()  
            await pubsub.close()  
            log.info("WS Listener: Unsubscribed and closed Redis pubsub.")  
        except Exception as e: log.error(f"WS Listener: Error closing pubsub: {e}")

async def start_websocket_listener():  
    """Starts the WebSocket Redis listener task."""  
    global _listener_task  
    if not settings.WEBSOCKET_REDIS_LISTENER_ENABLED:  
        logger.info("WebSocket Redis Listener is disabled in settings.")  
        return  
    if _listener_task is None or _listener_task.done():  
        logger.info("Initiating WebSocket Redis listener task...")  
        _stop_event.clear()  
        _listener_task \= asyncio.create_task(websocket_redis_listener_loop())  
    else:  
         logger.warning("WebSocket Redis listener task already running.")

async def stop_websocket_listener():  
    """Stops the WebSocket Redis listener task."""  
    global _listener_task  
    if not settings.WEBSOCKET_REDIS_LISTENER_ENABLED: return  
    if _listener_task and not _listener_task.done():  
        logger.info("Signaling WebSocket Redis listener task to stop...")  
        _stop_event.set()  
        try:  
            await asyncio.wait_for(_listener_task, timeout=5.0)  
            logger.info("WebSocket Redis listener task stopped gracefully.")  
        except asyncio.TimeoutError:  
            logger.warning("WebSocket Redis listener task did not stop in time. Cancelling.")  
            _listener_task.cancel()  
            try: await _listener_task  
            except asyncio.CancelledError: logger.info("WebSocket Listener task cancellation confirmed.")  
            except Exception as e: logger.exception(f"Error awaiting cancelled listener task: {e}")  
        except Exception as e: logger.exception(f"Error during WebSocket listener task shutdown: {e}")  
        finally: _listener_task \= None  
    else:  
        logger.info("WebSocket Redis listener task not running or already stopped.")
