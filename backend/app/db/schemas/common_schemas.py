# app/db/schemas/common_schemas.py  
from pydantic import BaseModel, Field  
from bson import ObjectId

# \--- Helper for ObjectId \---  
class PyObjectId(ObjectId):  
    @classmethod  
    def __get_validators__(cls): yield cls.validate  
    @classmethod  
    def validate(cls, v, field):  
        if isinstance(v, ObjectId): return v  
        if ObjectId.is_valid(str(v)): return ObjectId(v)  
        raise ValueError("Invalid ObjectId")  
    @classmethod  
    def __get_pydantic_json_schema__(cls, core_schema, handler):  
        \# How it should appear in OpenAPI JSON schema  
        return {"type": "string", "format": "objectid"}

# \--- Common API Message \---  
class MsgDetail(BaseModel):  
    msg: str \= Field(..., description="A detail message for responses.")
