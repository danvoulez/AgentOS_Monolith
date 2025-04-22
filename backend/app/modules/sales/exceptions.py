# app/modules/sales/exceptions.py  
# Domain-specific exceptions for the Sales module

class SalesError(Exception):  
    """Base exception for sales module errors."""  
    pass

class ProductNotFoundError(SalesError):  
    def __init__(self, sku: str):  
        super().__init__(f"Product with SKU '{sku}' not found.")  
        self.sku \= sku

class ClientNotFoundError(SalesError):  
    def __init__(self, client_id: str):  
        super().__init__(f"Client with ID '{client_id}' not found.")  
        self.client_id \= client_id

class InsufficientStockError(SalesError):  
    def __init__(self, sku: str, requested: int, available: int):  
        super().__init__(f"Insufficient stock for SKU '{sku}'. Requested: {requested}, Available: {available}.")  
        self.sku \= sku  
        self.requested \= requested  
        self.available \= available

class LowClientScoreError(SalesError):  
    def __init__(self, client_id: str, score: float, min_score: float):  
        super().__init__(f"Client '{client_id}' score ({score}) is below minimum required ({min_score}).")  
        self.client_id \= client_id  
        self.score \= score  
        self.min_score \= min_score

class DuplicateSaleError(SalesError):  
    def __init__(self, client_id: str, agent_id: str):  
        super().__init__(f"Potential duplicate sale detected for client '{client_id}' by agent '{agent_id}'.")  
        self.client_id \= client_id  
        self.agent_id \= agent_id

class SaleCreationError(SalesError):  
    """Generic error during sale creation process."""  
    pass

class PricingError(SalesError):  
    """Error during price calculation."""  
    pass

class CommissionError(SalesError):  
    """Error during commission calculation."""  
    pass  
