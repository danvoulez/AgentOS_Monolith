# app/db/schemas/sale_schemas.py  
from pydantic import BaseModel, Field, field_validator  
from typing import List, Optional, Dict, Any  
from datetime import datetime, timezone  
from enum import Enum  
from .common_schemas import PyObjectId \# Use common PyObjectId

# \--- Enums \---  
class SaleStatus(str, Enum):  
    PENDING_PAYMENT \= "pending_payment"  
    PROCESSING \= "processing"  
    COMPLETED \= "completed" \# Ready for delivery/fulfillment  
    SHIPPING \= "shipping"  
    DELIVERED \= "delivered"  
    CANCELLED \= "cancelled"  
    REFUNDED \= "refunded"  
    ERROR \= "error"

class SaleAgentType(str, Enum):  
    HUMAN \= "human"  
    BOT \= "bot"  
    SYSTEM \= "system"

# \--- Subdocument Models \---  
class SaleItem(BaseModel):  
    """Represents an item within a sale."""  
    product_id: str \= Field(...) \# Storing as string, corresponds to ProductDoc ObjectId  
    sku: str \= Field(...)  
    name: str \= Field(...) \# Denormalized name at time of sale  
    quantity: int \= Field(..., gt=0)  
    unit_price: float \= Field(..., ge=0) \# Price charged per unit  
    total_price: float \= Field(..., ge=0) \# quantity \* unit_price

    \# Validator removed for simplicity, can be added back if strict check needed

class StatusHistoryEntry(BaseModel):  
    """Entry in the sale's status history."""  
    status: SaleStatus  
    timestamp: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))  
    actor_id: str \= Field("system", description="ID of user/agent/system that changed status")  
    comment: Optional\[str\] \= None

# \--- Main Document Model \---  
class SaleDoc(BaseModel):  
    """MongoDB document representing a sales transaction."""  
    id: PyObjectId \= Field(default_factory=PyObjectId, alias="_id")  
    \# References  
    client_id: str \= Field(..., description="Profile ID of the client", index=True)  
    agent_id: str \= Field(..., description="Profile ID of the agent/user", index=True)  
    \# Metadata  
    agent_type: SaleAgentType  
    origin_channel: Optional\[str\] \= Field(None, index=True)  
    \# Sale Details  
    items: List\[SaleItem\] \= Field(...)  
    total_amount: float \= Field(..., ge=0)  
    currency: str \= Field("USD", max_length=3)  
    \# Financials  
    profit_margin_percent: Optional\[float\] \= None  
    commission_amount: float \= Field(default=0.0)  
    \# Status Tracking  
    status: SaleStatus \= Field(default=SaleStatus.PROCESSING, index=True)  
    status_history: List\[StatusHistoryEntry\] \= Field(default_factory=list)  
    \# Integration Status (Simplified)  
    payment_status: str \= Field("pending", index=True, examples=\["pending", "paid", "failed"\])  
    delivery_id: Optional\[str\] \= Field(None, index=True) \# Link to DeliverySessionDoc ID  
    \# Notes & Timestamps  
    contextual_note: Optional\[str\] \= Field(None, max_length=1000)  
    created_at: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc), index=True)  
    updated_at: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))  
    \# Error details if overall status is ERROR  
    error_details: Optional\[str\] \= None

    model_config \= {  
        "populate_by_name": True,  
        "arbitrary_types_allowed": True,  
        "json_encoders": { PyObjectId: str, datetime: lambda dt: dt.isoformat() }  
    }
