# app/db/schemas/people_schemas.py  
# Schemas related to the 'people' module (formerly agentos-pessoas)  
# These define how profile data is stored/represented within the unified backend.

from pydantic import BaseModel, EmailStr, Field  
from typing import List, Optional, Dict, Any  
from datetime import datetime, timezone  
from enum import Enum  
from .common_schemas import PyObjectId \# Use common PyObjectId

class ProfileType(str, Enum):  
    CLIENTE \= "cliente"  
    VENDEDOR \= "vendedor"  
    REVENDEDOR \= "revendedor"  
    ESTAFETA \= "estafeta" \# Courier/Delivery Person  
    ADMIN \= "admin"  
    SYSTEM \= "system"  
    BOT \= "bot" \# For AgentOS agents themselves?

class ProfileDoc(BaseModel):  
    """MongoDB document representing a user profile."""  
    id: PyObjectId \= Field(default_factory=PyObjectId, alias="_id")  
    \# Link to the main User account (for login) \- assumes user_id from UserDoc matches this  
    user_id: Optional\[str\] \= Field(None, index=True, description="Link to the User document ID if applicable")  
    \# External identifiers  
    external_id: Optional\[str\] \= Field(None, index=True, description="ID from an external system")  
    whatsapp_id: Optional\[str\] \= Field(None, index=True, unique=True, sparse=True, description="WhatsApp ID if applicable")  
    \# Profile details  
    email: Optional\[EmailStr\] \= Field(None, index=True, unique=True, sparse=True) \# Email can be unique  
    first_name: Optional\[str\] \= Field(None, max_length=100)  
    last_name: Optional\[str\] \= Field(None, max_length=100)  
    full_name: Optional\[str\] \= Field(None, max_length=200) \# Denormalized full name  
    phone_number: Optional\[str\] \= Field(None, max_length=30, index=True)  
    profile_type: ProfileType \= Field(...) \# Main type  
    \# Sales related info (cached/managed here or fetched from Sales module?)  
    \# Let's assume sales module manages its client info, this profile is more general  
    \# sales_category: Optional\[str\] \= None  
    \# client_score: Optional\[float\] \= None  
    \# Status and Roles  
    is_active: bool \= Field(True, index=True)  
    roles: List\[str\] \= Field(default_factory=list, index=True) \# Roles relevant across AgentOS  
    \# Timestamps  
    created_at: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))  
    updated_at: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))  
    \# Additional metadata  
    metadata: Dict\[str, Any\] \= Field(default_factory=dict) \# e.g., language preference, address

    model_config \= {  
        "populate_by_name": True,  
        "arbitrary_types_allowed": True,  
        "json_encoders": { PyObjectId: str, datetime: lambda dt: dt.isoformat() }  
    }

    \# Method to derive full_name (example)  
    def derive_full_name(self) \-\> Optional\[str\]:  
        if self.first_name and self.last_name:  
            return f"{self.first_name} {self.last_name}"  
        return self.first_name or self.last_name or None

class ProfileCreate(BaseModel):  
    """Schema for creating a new profile."""  
    user_id: Optional\[str\] \= None \# Link on creation if available  
    external_id: Optional\[str\] \= None  
    whatsapp_id: Optional\[str\] \= None  
    email: Optional\[EmailStr\] \= None  
    first_name: Optional\[str\] \= None  
    last_name: Optional\[str\] \= None  
    phone_number: Optional\[str\] \= None  
    profile_type: ProfileType  
    is_active: bool \= True  
    roles: List\[str\] \= \[\]  
    metadata: Optional\[Dict\[str, Any\]\] \= None

    \# Add validation: e.g., require at least one identifier (email, phone, wa_id, external_id)  
    \# @model_validator(mode='after')  
    \# def check_identifiers(self) \-\> 'ProfileCreate':  
    \#    if not any(\[self.email, self.phone_number, self.whatsapp_id, self.external_id\]):  
    \#        raise ValueError("At least one identifier (email, phone, whatsapp_id, external_id) is required.")  
    \#    return self

class ProfileUpdate(BaseModel):  
    """Schema for updating a profile. All fields optional."""  
    email: Optional\[EmailStr\] \= None  
    first_name: Optional\[str\] \= None  
    last_name: Optional\[str\] \= None  
    phone_number: Optional\[str\] \= None  
    profile_type: Optional\[ProfileType\] \= None  
    is_active: Optional\[bool\] \= None  
    roles: Optional\[List\[str\]\] \= None \# Allow updating roles?  
    metadata: Optional\[Dict\[str, Any\]\] \= None \# Allow merging/replacing metadata
