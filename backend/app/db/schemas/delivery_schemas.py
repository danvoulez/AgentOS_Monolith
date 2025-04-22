# app/db/schemas/delivery_schemas.py  
from pydantic import BaseModel, Field  
from typing import List, Optional, Dict, Any  
from datetime import datetime, timezone, timedelta  
from enum import Enum  
from .common_schemas import PyObjectId

# \--- Enums \---  
class DeliveryStatus(str, Enum):  
    PENDING_ASSIGNMENT \= "pending_assignment"  
    ASSIGNED \= "assigned"  
    PICKING_UP \= "picking_up"  
    IN_TRANSIT \= "in_transit"  
    NEAR_DESTINATION \= "near_destination"  
    DELIVERED \= "delivered"  
    FAILED_ATTEMPT \= "failed_attempt"  
    FAILED_DELIVERY \= "failed_delivery"  
    CANCELLED \= "cancelled"  
    RETURNED \= "returned"

# \--- Subdocument/Helper Models \---  
class LocationPoint(BaseModel):  
    """GeoJSON-like point structure for location."""  
    type: str \= Field("Point", Literal="Point")  
    coordinates: List\[float\] \= Field(..., min_length=2, max_length=2, description="\[longitude, latitude\]")

class TrackingEventDoc(BaseModel):  
    """Event in the delivery timeline (embedded in DeliverySessionDoc)."""  
    timestamp: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))  
    status: DeliveryStatus  
    description: str  
    location: Optional\[LocationPoint\] \= None  
    actor_id: Optional\[str\] \= None \# Courier ID, System ID, etc.  
    metadata: Dict\[str, Any\] \= Field(default_factory=dict)

class DeliveryItem(BaseModel):  
    """Simplified item info needed for delivery (embedded)."""  
    product_id: str \# Ref Product ObjectId as string  
    sku: str  
    name: str  
    quantity: int

# \--- Main Document Model \---  
class DeliverySessionDoc(BaseModel):  
    """MongoDB document representing a delivery task."""  
    id: PyObjectId \= Field(default_factory=PyObjectId, alias="_id")  
    \# References  
    sale_id: str \= Field(..., description="ID da venda original", index=True)  
    client_profile_id: str \= Field(..., index=True) \# Profile ID do cliente  
    courier_profile_id: Optional\[str\] \= Field(None, index=True) \# Profile ID do entregador  
    \# Delivery Details  
    items: List\[DeliveryItem\]  
    pickup_address: str \# Can be structured address later  
    delivery_address: str \# Can be structured address later  
    estimated_pickup_time: Optional\[datetime\] \= None  
    estimated_delivery_time: Optional\[datetime\] \= None \# ETA  
    actual_pickup_time: Optional\[datetime\] \= None  
    actual_delivery_time: Optional\[datetime\] \= None  
    \# Status and Tracking  
    current_status: DeliveryStatus \= Field(default=DeliveryStatus.PENDING_ASSIGNMENT, index=True)  
    tracking_history: List\[TrackingEventDoc\] \= Field(default_factory=list)  
    current_location: Optional\[LocationPoint\] \= Field(None, description="Last known courier location (GeoJSON Point)")  
    \# Metadata  
    delivery_notes: Optional\[str\] \= None  
    \# TTL Index field (Set by service logic based on final status)  
    expire_at: Optional\[datetime\] \= Field(None, index=True)  
    \# Timestamps  
    created_at: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))  
    updated_at: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config \= {  
        "populate_by_name": True,  
        "arbitrary_types_allowed": True,  
        "json_encoders": { PyObjectId: str, datetime: lambda dt: dt.isoformat() }  
    }

# \--- Associated Chat Schemas (Could be separate collection) \---  
# If chat is complex, consider separate collections as in agentos-delivery proposal.  
# If simple, could embed last few messages or just link delivery to a chat ID.  
# Let's assume for now chat is handled elsewhere or very simply.
