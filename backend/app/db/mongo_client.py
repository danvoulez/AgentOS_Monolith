# app/db/mongo_client.py  
# (Same as the one generated for agentos-sales, just ensure logging uses the unified logger)  
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase  
from app.core.config import settings  
from app.core.logging_setup import logger \# Use configured logger

_mongo_client: AsyncIOMotorClient | None \= None  
_mongo_db: AsyncIOMotorDatabase | None \= None

async def connect_to_mongo():  
    """Establishes connection to MongoDB using settings."""  
    global _mongo_client, _mongo_db  
    if _mongo_client and _mongo_db:  
        logger.debug("MongoDB connection already established.")  
        return  
    try:  
        mongo_uri \= settings.MONGODB_URI  
        db_name \= settings.MONGO_DB_NAME \# Derived in Settings model

        if not db_name:  
             logger.critical("FATAL: MONGO_DB_NAME could not be determined.")  
             raise RuntimeError("MONGO_DB_NAME must be set or derivable from MONGODB_URI.")

        logger.info(f"Connecting to MongoDB: {mongo_uri.split('@')\[-1\].split('/')\[0\] if '@' in mongo_uri else mongo_uri.split('//')\[-1\].split('/')\[0\]} / DB: {db_name}")

        _mongo_client \= AsyncIOMotorClient(  
            mongo_uri,  
            serverSelectionTimeoutMS=5000,  
            uuidRepresentation='standard' \# Recommended setting  
        )  
        _mongo_db \= _mongo_client\[db_name\]  
        await _mongo_client.admin.command('ping')  
        logger.success(f"Connected to MongoDB database '{db_name}' successfully.")

    except Exception as e:  
        logger.critical(f"FATAL: Failed to connect to MongoDB: {e}")  
        _mongo_client \= None  
        _mongo_db \= None  
        raise RuntimeError(f"Failed to connect to MongoDB: {e}") from e

async def close_mongo_connection():  
    """Closes the MongoDB client connection."""  
    global _mongo_client, _mongo_db  
    if _mongo_client:  
        logger.info("Closing MongoDB connection...")  
        try:  
            _mongo_client.close()  
            logger.info("MongoDB connection closed.")  
        except Exception as e:  
             logger.error(f"Error closing MongoDB connection: {e}")  
        finally:  
            _mongo_client \= None  
            _mongo_db \= None

def get_database() \-\> AsyncIOMotorDatabase:  
    """Provides the singleton database instance. Raises RuntimeError if not connected."""  
    if _mongo_db is None:  
        logger.error("Database instance is not available.")  
        raise RuntimeError("Database not connected. Ensure connect_to_mongo() was called successfully.")  
    return _mongo_db  
