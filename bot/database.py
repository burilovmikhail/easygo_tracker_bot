"""Unified MongoDB connection manager for bot and worker."""

import structlog
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from typing import List, Type
from beanie import Document

logger = structlog.get_logger()


class MongoDB:
    """MongoDB connection manager."""

    client: AsyncIOMotorClient = None
    database = None

    @classmethod
    async def connect(
        cls,
        mongodb_uri: str,
        database_name: str = "easygo_bot",
        document_models: List[Type[Document]] = None
    ):
        """
        Initialize MongoDB connection and Beanie ODM.

        Args:
            mongodb_uri: MongoDB connection string
            database_name: Database name
            document_models: List of Document model classes to initialize
        """
        try:
            logger.info("Connecting to MongoDB...",
                        uri=mongodb_uri.split("@")[-1])
            cls.client = AsyncIOMotorClient(mongodb_uri)
            cls.database = cls.client[database_name]

            # Initialize Beanie with provided document models
            if document_models:
                await init_beanie(
                    database=cls.database,
                    document_models=document_models,
                )

            logger.info("Successfully connected to MongoDB",
                        database=database_name)
        except Exception as e:
            logger.error("Failed to connect to MongoDB", error=str(e))
            raise

    @classmethod
    async def close(cls):
        """Close MongoDB connection."""
        if cls.client:
            logger.info("Closing MongoDB connection...")
            cls.client.close()
            logger.info("MongoDB connection closed")
