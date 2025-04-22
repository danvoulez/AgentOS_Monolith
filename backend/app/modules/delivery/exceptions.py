# app/modules/delivery/exceptions.py  
# Domain-specific exceptions for the Delivery module

class DeliveryError(Exception):  
    """Base exception for delivery module errors."""  
    pass

class DeliveryNotFoundError(DeliveryError):  
    def __init__(self, delivery_id: str):  
        super().__init__(f"Delivery session with ID '{delivery_id}' not found.")  
        self.delivery_id \= delivery_id

class InvalidDeliveryStatusError(DeliveryError):  
    def __init__(self, delivery_id: str, current_status: str, action: str):  
        super().__init__(f"Action '{action}' not allowed for delivery '{delivery_id}' with current status '{current_status}'.")  
        self.delivery_id \= delivery_id  
        self.current_status \= current_status  
        self.action \= action

class CourierAssignmentError(DeliveryError):  
    """Error during courier assignment process."""  
    pass

class TrackingUpdateError(DeliveryError):  
    """Error updating delivery tracking information."""  
    pass  
