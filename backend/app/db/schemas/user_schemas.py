# app/db/schemas/user_schemas.py  
# Defines user schemas for authentication and basic user info persistence

from pydantic import BaseModel, Field, EmailStr, field_validator  
from typing import List, Optional, Dict, Any  
from datetime import datetime, timezone  
from .common_schemas import PyObjectId \# Use common PyObjectId  
import re \# For password validation

# \--- User Schema (for Authentication/Authorization) \---  
class UserBase(BaseModel):  
    """Base model for user properties."""  
    username: str \= Field(..., min_length=3, max_length=50, index=True, unique=True)  
    email: Optional\[EmailStr\] \= Field(None, index=True, unique=True, sparse=True) \# Unique if provided  
    full_name: Optional\[str\] \= Field(None, max_length=100)  
    is_active: bool \= Field(True, index=True)  
    roles: List\[str\] \= Field(default_factory=list, index=True) \# Roles used for RBAC

class UserCreate(UserBase):  
    """Schema for creating a new user, requires password."""  
    password: str \= Field(..., min_length=8, description="User password (will be hashed)")

    \# Basic Password Policy Validator  
    @field_validator('password')  
    def validate_password_strength(cls, v):  
        if len(v) \< 8: raise ValueError('Password must be at least 8 characters long.')  
        if not re.search(r"\[A-Z\]", v): raise ValueError('Password must contain an uppercase letter.')  
        if not re.search(r"\[a-z\]", v): raise ValueError('Password must contain a lowercase letter.')  
        if not re.search(r"\\d", v): raise ValueError('Password must contain a digit.')  
        \# if not re.search(r"\[\!@\#$%^&\*()\]", v): raise ValueError('Password must contain a special character.')  
        return v

class UserUpdate(BaseModel):  
    """Schema for updating user info (password update separate)."""  
    email: Optional\[EmailStr\] \= None  
    full_name: Optional\[str\] \= None  
    is_active: Optional\[bool\] \= None  
    roles: Optional\[List\[str\]\] \= None \# Allow updating roles

# Represents user data stored in DB, including hashed password  
class UserInDB(UserBase):  
    """Internal representation of a user in the database."""  
    id: PyObjectId \= Field(default_factory=PyObjectId, alias="_id")  
    hashed_password: str \= Field(...)  
    created_at: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))  
    updated_at: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config \= {  
        "populate_by_name": True,  
        "arbitrary_types_allowed": True,  
        "json_encoders": { PyObjectId: str, datetime: lambda dt: dt.isoformat() }  
    }

# Represents user data returned by API (safe subset)  
class UserPublic(UserBase):  
    """Public representation of a user (excludes sensitive fields)."""  
    id: str \# Return ID as string (converted from PyObjectId)  
    \# Exclude hashed_password by inheriting from UserBase

    model_config \= {  
        "from_attributes": True \# Create from UserInDB instance  
    }
