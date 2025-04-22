# app/modules/people/exceptions.py  
# Domain-specific exceptions for the People module

class PeopleError(Exception):  
    """Base exception for people module errors."""  
    pass

class ProfileNotFoundError(PeopleError):  
    def __init__(self, identifier: str):  
        super().__init__(f"Profile not found for identifier: {identifier}")  
        self.identifier \= identifier

class UserAccountError(PeopleError):  
    """Errors related to the underlying user account (UserDoc)."""  
    pass

class DuplicateProfileError(PeopleError):  
     def __init__(self, field: str, value: str):  
        super().__init__(f"Profile already exists with this {field}: {value}")  
        self.field \= field  
        self.value \= value  
