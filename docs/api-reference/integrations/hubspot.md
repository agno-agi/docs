# HubSpot Integration API Reference

## Class: HubSpotIntegration

The main integration class for HubSpot CRM operations.

```python
class HubSpotIntegration(Integration):
    """HubSpot CRM integration for Agno agents."""
```

### Constructor

```python
HubSpotIntegration(
    api_key: Optional[str] = None,
    access_token: Optional[str] = None,
    base_url: str = "https://api.hubapi.com",
    timeout: int = 30,
    retry_attempts: int = 3
)
```

**Parameters:**
- `api_key` (str, optional): HubSpot API key for authentication
- `access_token` (str, optional): OAuth access token (alternative to API key)
- `base_url` (str): Base URL for HubSpot API
- `timeout` (int): Request timeout in seconds
- `retry_attempts` (int): Number of retry attempts for failed requests

## Contact Tools

### create_contact

Creates a new contact in HubSpot.

```python
@tool
async def create_contact(
    email: str,
    firstname: Optional[str] = None,
    lastname: Optional[str] = None,
    phone: Optional[str] = None,
    company: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]
```

**Parameters:**
- `email` (str): Contact's email address (required)
- `firstname` (str, optional): Contact's first name
- `lastname` (str, optional): Contact's last name
- `phone` (str, optional): Contact's phone number
- `company` (str, optional): Contact's company name
- `properties` (dict, optional): Additional properties to set

**Returns:**
- `Dict[str, Any]`: Created contact object with ID and properties

**Raises:**
- `HubSpotAPIError`: If the API request fails
- `ValidationError`: If email format is invalid

### get_contact

Retrieves a contact by ID or email.

```python
@tool
async def get_contact(
    contact_id: Optional[str] = None,
    email: Optional[str] = None,
    properties: Optional[List[str]] = None
) -> Dict[str, Any]
```

**Parameters:**
- `contact_id` (str, optional): HubSpot contact ID
- `email` (str, optional): Contact's email address
- `properties` (list, optional): List of properties to retrieve

**Returns:**
- `Dict[str, Any]`: Contact object with requested properties

**Raises:**
- `HubSpotAPIError`: If the contact is not found
- `ValueError`: If neither contact_id nor email is provided

### update_contact

Updates an existing contact.

```python
@tool
async def update_contact(
    contact_id: str,
    properties: Dict[str, Any]
) -> Dict[str, Any]
```

**Parameters:**
- `contact_id` (str): HubSpot contact ID
- `properties` (dict): Properties to update

**Returns:**
- `Dict[str, Any]`: Updated contact object

### search_contacts

Searches for contacts based on filters.

```python
@tool
async def search_contacts(
    filters: List[Dict[str, Any]],
    sorts: Optional[List[Dict[str, str]]] = None,
    properties: Optional[List[str]] = None,
    limit: int = 10,
    after: Optional[str] = None
) -> Dict[str, Any]
```

**Parameters:**
- `filters` (list): List of filter objects
- `sorts` (list, optional): Sort specifications
- `properties` (list, optional): Properties to retrieve
- `limit` (int): Maximum results per page
- `after` (str, optional): Pagination cursor

**Returns:**
- `Dict[str, Any]`: Search results with contacts and paging info

**Filter Format:**
```python
{
    "propertyName": "email",
    "operator": "CONTAINS",
    "value": "@example.com"
}
```

## Company Tools

### create_company

Creates a new company in HubSpot.

```python
@tool
async def create_company(
    name: str,
    domain: Optional[str] = None,
    industry: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]
```

**Parameters:**
- `name` (str): Company name (required)
- `domain` (str, optional): Company website domain
- `industry` (str, optional): Company industry
- `city` (str, optional): Company city
- `state` (str, optional): Company state/region
- `properties` (dict, optional): Additional properties

**Returns:**
- `Dict[str, Any]`: Created company object

### get_company

Retrieves a company by ID.

```python
@tool
async def get_company(
    company_id: str,
    properties: Optional[List[str]] = None
) -> Dict[str, Any]
```

**Parameters:**
- `company_id` (str): HubSpot company ID
- `properties` (list, optional): Properties to retrieve

**Returns:**
- `Dict[str, Any]`: Company object

### update_company

Updates an existing company.

```python
@tool
async def update_company(
    company_id: str,
    properties: Dict[str, Any]
) -> Dict[str, Any]
```

**Parameters:**
- `company_id` (str): HubSpot company ID
- `properties` (dict): Properties to update

**Returns:**
- `Dict[str, Any]`: Updated company object

## Deal Tools

### create_deal

Creates a new deal in HubSpot.

```python
@tool
async def create_deal(
    dealname: str,
    amount: Optional[str] = None,
    dealstage: Optional[str] = None,
    closedate: Optional[str] = None,
    pipeline: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]
```

**Parameters:**
- `dealname` (str): Deal name (required)
- `amount` (str, optional): Deal amount
- `dealstage` (str, optional): Deal stage ID
- `closedate` (str, optional): Expected close date (YYYY-MM-DD)
- `pipeline` (str, optional): Pipeline ID
- `properties` (dict, optional): Additional properties

**Returns:**
- `Dict[str, Any]`: Created deal object

### get_deal

Retrieves a deal by ID.

```python
@tool
async def get_deal(
    deal_id: str,
    properties: Optional[List[str]] = None
) -> Dict[str, Any]
```

**Parameters:**
- `deal_id` (str): HubSpot deal ID
- `properties` (list, optional): Properties to retrieve

**Returns:**
- `Dict[str, Any]`: Deal object

### update_deal

Updates an existing deal.

```python
@tool
async def update_deal(
    deal_id: str,
    properties: Dict[str, Any]
) -> Dict[str, Any]
```

**Parameters:**
- `deal_id` (str): HubSpot deal ID
- `properties` (dict): Properties to update

**Returns:**
- `Dict[str, Any]`: Updated deal object

## Association Tools

### create_association

Creates an association between two HubSpot objects.

```python
@tool
async def create_association(
    from_object_type: str,
    from_object_id: str,
    to_object_type: str,
    to_object_id: str,
    association_type: str
) -> Dict[str, Any]
```

**Parameters:**
- `from_object_type` (str): Source object type (contact, company, deal)
- `from_object_id` (str): Source object ID
- `to_object_type` (str): Target object type
- `to_object_id` (str): Target object ID
- `association_type` (str): Type of association

**Returns:**
- `Dict[str, Any]`: Association confirmation

**Association Types:**
- `contact_to_company`
- `company_to_contact`
- `contact_to_deal`
- `deal_to_contact`
- `deal_to_company`
- `company_to_deal`

## Exceptions

### HubSpotAPIError

Raised when HubSpot API returns an error.

```python
class HubSpotAPIError(IntegrationError):
    """HubSpot API error."""
    
    def __init__(self, message: str, status_code: int, response: Dict[str, Any]):
        self.status_code = status_code
        self.response = response
        super().__init__(message)
```

**Attributes:**
- `message` (str): Error message
- `status_code` (int): HTTP status code
- `response` (dict): Full error response from API

### Common Error Codes

- `400`: Bad Request - Invalid parameters
- `401`: Unauthorized - Invalid API key
- `403`: Forbidden - Insufficient permissions
- `404`: Not Found - Object doesn't exist
- `429`: Too Many Requests - Rate limit exceeded
- `500`: Internal Server Error

## Type Definitions

### ContactProperties

Common contact properties:
```python
{
    "email": str,
    "firstname": str,
    "lastname": str,
    "phone": str,
    "company": str,
    "lifecyclestage": str,
    "lead_status": str,
    "hs_lead_status": str
}
```

### CompanyProperties

Common company properties:
```python
{
    "name": str,
    "domain": str,
    "industry": str,
    "numberofemployees": str,
    "annualrevenue": str,
    "city": str,
    "state": str,
    "country": str
}
```

### DealProperties

Common deal properties:
```python
{
    "dealname": str,
    "amount": str,
    "dealstage": str,
    "closedate": str,
    "pipeline": str,
    "hs_priority": str,
    "dealtype": str
}
```

## Advanced Usage

### Batch Operations

For bulk operations, use the search methods with appropriate filters:

```python
# Get all contacts from a specific domain
all_contacts = []
after = None

while True:
    result = await agent.tools.search_contacts(
        filters=[
            {
                "propertyName": "email",
                "operator": "CONTAINS",
                "value": "@example.com"
            }
        ],
        limit=100,
        after=after
    )
    
    all_contacts.extend(result["results"])
    
    if not result.get("paging", {}).get("next"):
        break
    
    after = result["paging"]["next"]["after"]
```

### Custom Properties

Access custom properties using their internal names:

```python
contact = await agent.tools.create_contact(
    email="custom@example.com",
    properties={
        "custom_field_1": "value1",
        "my_custom_property": "value2"
    }
)
```

### Error Handling Best Practices

```python
async def safe_create_contact(email: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Create a contact with comprehensive error handling."""
    try:
        return await agent.tools.create_contact(email=email, **kwargs)
    except HubSpotAPIError as e:
        if e.status_code == 409:  # Conflict - contact exists
            # Try to get existing contact
            return await agent.tools.get_contact(email=email)
        elif e.status_code == 429:  # Rate limited
            # Wait and retry
            await asyncio.sleep(10)
            return await safe_create_contact(email, **kwargs)
        else:
            logger.error(f"Failed to create contact: {e}")
            return None
```