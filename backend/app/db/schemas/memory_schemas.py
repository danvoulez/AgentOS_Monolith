# app/db/schemas/memory_schemas.py  
from pydantic import BaseModel, Field  
from typing import List, Optional, Dict, Any  
from datetime import datetime, timezone  
from .common_schemas import PyObjectId \# Use common PyObjectId

class ChatMessageDoc(BaseModel):  
    """Document representing a single entry in the chat memory (persisted in MongoDB)."""  
    id: PyObjectId \= Field(default_factory=PyObjectId, alias="_id")  
    chat_id: str \= Field(..., description="Identifier for the conversation session", index=True)  
    user_id: Optional\[str\] \= Field(None, description="Associated user identifier", index=True)  
    sequence_id: Optional\[int\] \= Field(None, description="Monotonic sequence number within a chat (optional)")  
    timestamp: datetime \= Field(default_factory=lambda: datetime.now(timezone.utc), index=True)  
    role: str \= Field(..., examples=\["user", "assistant", "system", "tool_input", "tool_output"\])  
    type: str \= Field("text", examples=\["text", "tool_call", "tool_result", "system_event"\])  
    content: str \# Main text content (or structured data as JSON string?)

    \# Optional structured content  
    tool_call_id: Optional\[str\] \= None  
    tool_name: Optional\[str\] \= None  
    tool_arguments: Optional\[Dict\[str, Any\]\] \= None  
    tool_result: Optional\[Any\] \= None

    metadata: Dict\[str, Any\] \= Field(default_factory=dict)  
    is_pii_masked: bool \= Field(False)

    \# Vector Search Fields  
    embedding: Optional\[List\[float\]\] \= Field(None)  
    embedding_model: Optional\[str\] \= Field(None)

    \# Feedback Fields  
    feedback_score: Optional\[int\] \= Field(None)  
    is_flagged: bool \= Field(False)  
    flagged_reason: Optional\[str\] \= None  
    is_forgotten: bool \= Field(False, index=True) \# Soft delete index

    model_config \= {  
        "populate_by_name": True,  
        "arbitrary_types_allowed": True,  
        "json_encoders": { PyObjectId: str, datetime: lambda dt: dt.isoformat() }  
    }  
