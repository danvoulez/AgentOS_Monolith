# app/api/v1/endpoints/sales_api.py  
# REST endpoints specifically for interacting with Sales data (e.g., for UI)

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path as FastApiPath  
from typing import Annotated, List, Optional  
from app.modules.sales.service import SalesService \# Import Sales service  
from app.db.schemas.sale_schemas import SaleDoc, SaleStatus \# Import response model  
from app.core.logging_setup import logger  
from app.core.exceptions import RepositoryError \# Handle potential DB errors  
from app.modules.sales.exceptions import SaleCreationError \# Handle domain errors  
# Import auth dependencies  
from app.core.security import CurrentUser, require_role

router \= APIRouter()

# Dependencies  
SalesServiceDep \= Annotated\[SalesService, Depends()\]  
# Define roles allowed to view sales data (adjust as needed)  
SalesViewerRole \= Depends(require_role(\["admin", "sales_manager", "sales_agent", "support_agent"\]))

@router.get(  
    "/",  
    response_model=List\[SaleDoc\],  
    summary="List Sales",  
    dependencies=\[SalesViewerRole\]  
)  
async def list_sales(  
    currentUser: CurrentUser,  
    sales_service: SalesServiceDep,  
    client_id: Annotated\[Optional\[str\], Query(description="Filter by client ID")\] \= None,  
    agent_id: Annotated\[Optional\[str\], Query(description="Filter by agent ID (defaults to current user if not admin/manager)")\] \= None,  
    status: Annotated\[Optional\[SaleStatus\], Query(description="Filter by sale status")\] \= None,  
    skip: Annotated\[int, Query(ge=0)\] \= 0,  
    limit: Annotated\[int, Query(ge=1, le=100)\] \= 20  
):  
    """  
    Retrieves a list of sales records with optional filters.  
    Non-admin/manager roles can only see their own sales by default unless client_id is specified.  
    """  
    log \= logger.bind(user_id=currentUser.user_id, client_filter=client_id, agent_filter=agent_id, status_filter=status)  
    log.info("Request to list sales.")

    \# Authorization logic: Restrict agent_id filter if user is not admin/manager  
    is_privileged \= any(role in currentUser.roles for role in \["admin", "sales_manager"\])  
    if not is_privileged and agent_id and agent_id \!= currentUser.user_id:  
         log.warning("Non-privileged user attempting to filter sales by different agent ID.")  
         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to view other agents' sales.")  
    elif not is_privileged and not agent_id and not client_id:  
         \# Default to showing only the current agent's sales if no other filter applied  
         agent_id \= currentUser.user_id  
         log.debug("Defaulting sales list to current agent.")

    try:  
        \# Call a service method designed for listing with filters  
        \# Need to implement this method in SalesService and SaleRepository  
        \# sales_list \= await sales_service.list_sales_with_filters(  
        \#      client_id=client_id, agent_id=agent_id, status=status, skip=skip, limit=limit  
        \# )  
        \# Using basic repo list for now  
        sales_list \= await sales_service.sale_repo.list_sales(  
             client_id=client_id, agent_id=agent_id, status=status, skip=skip, limit=limit  
        )  
        return sales_list  
    except RepositoryError as e:  
         log.exception("Failed to list sales due to repository error.")  
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database error listing sales.")  
    except Exception as e:  
        log.exception("Unexpected error listing sales.")  
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

@router.get(  
    "/{sale_id}",  
    response_model=SaleDoc,  
    summary="Get Sale Details by ID",  
    dependencies=\[SalesViewerRole\]  
)  
async def get_sale_details(  
    sale_id: Annotated\[str, FastApiPath(description="The ID of the sale record")\],  
    currentUser: CurrentUser,  
    sales_service: SalesServiceDep,  
):  
    """Retrieves the full details of a specific sale."""  
    log \= logger.bind(sale_id=sale_id, user_id=currentUser.user_id)  
    log.info("Request for sale details.")  
    try:  
        sale \= await sales_service.get_sale_by_id(sale_id) \# Service handles not found  
        \# Authorization: Can this user view this specific sale?  
        is_privileged \= any(role in currentUser.roles for role in \["admin", "sales_manager", "support_agent"\])  
        is_own_sale \= (sale.agent_id \== currentUser.user_id or sale.client_id \== currentUser.user_id) \# Check if client or agent

        if not is_privileged and not is_own_sale:  
             log.warning("User does not have permission to view this sale.")  
             raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied to view this sale.")

        return sale  
    except HTTPException as e: \# Catch 404 from service  
        raise e  
    except RepositoryError as e:  
         log.exception("Failed to get sale details due to repository error.")  
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database error.")  
    except Exception as e:  
        log.exception("Unexpected error getting sale details.")  
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

# Add other relevant REST endpoints for Sales data needed by the UI  
# e.g., GET /sales/summary, GET /sales/kpis (might duplicate Vox purpose)
