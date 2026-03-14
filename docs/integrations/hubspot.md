# HubSpot Integration

The HubSpot integration enables Agno agents to interact with HubSpot CRM, allowing them to manage contacts, companies, deals, and perform various CRM operations.

## Overview

This integration provides tools for:
- Creating and managing contacts
- Managing companies
- Working with deals
- Searching across HubSpot objects
- Associating different object types

## Prerequisites

Before using the HubSpot integration, you need:

1. A HubSpot account with API access
2. A HubSpot API key or OAuth credentials
3. Appropriate permissions for the operations you want to perform

## Configuration

### Environment Variables

Set the following environment variables:

```bash
HUBSPOT_API_KEY=your_hubspot_api_key
# or for OAuth
HUBSPOT_ACCESS_TOKEN=your_access_token
```

### Integration Setup

In your agent configuration:

```python
from agno.integrations import HubSpotIntegration

# Initialize the integration
hubspot = HubSpotIntegration(
    api_key=os.getenv("HUBSPOT_API_KEY")
)

# Add to your agent
agent.add_integration(hubspot)
```

## Available Tools

### Contacts Management

#### create_contact
Creates a new contact in HubSpot.

```python
result = await agent.tools.create_contact(
    email="john.doe@example.com",
    firstname="John",
    lastname="Doe",
    phone="555-0123",
    company="Acme Corp"
)
```

#### get_contact
Retrieves a contact by ID or email.

```python
# By ID
contact = await agent.tools.get_contact(contact_id="12345")

# By email
contact = await agent.tools.get_contact(email="john.doe@example.com")
```

#### update_contact
Updates an existing contact.

```python
updated = await agent.tools.update_contact(
    contact_id="12345",
    properties={
        "phone": "555-0124",
        "lifecyclestage": "customer"
    }
)
```

#### search_contacts
Searches for contacts based on criteria.

```python
contacts = await agent.tools.search_contacts(
    filters=[
        {
            "propertyName": "email",
            "operator": "CONTAINS",
            "value": "@example.com"
        }
    ],
    limit=10
)
```

### Companies Management

#### create_company
Creates a new company in HubSpot.

```python
company = await agent.tools.create_company(
    name="Acme Corporation",
    domain="acme.com",
    industry="Technology",
    city="San Francisco",
    state="CA"
)
```

#### get_company
Retrieves a company by ID.

```python
company = await agent.tools.get_company(company_id="67890")
```

#### update_company
Updates an existing company.

```python
updated = await agent.tools.update_company(
    company_id="67890",
    properties={
        "numberofemployees": "100",
        "annualrevenue": "10000000"
    }
)
```

### Deals Management

#### create_deal
Creates a new deal in HubSpot.

```python
deal = await agent.tools.create_deal(
    dealname="New Enterprise Deal",
    amount="50000",
    dealstage="qualifiedtobuy",
    closedate="2024-12-31",
    pipeline="default"
)
```

#### get_deal
Retrieves a deal by ID.

```python
deal = await agent.tools.get_deal(deal_id="11111")
```

#### update_deal
Updates an existing deal.

```python
updated = await agent.tools.update_deal(
    deal_id="11111",
    properties={
        "dealstage": "contractsent",
        "amount": "55000"
    }
)
```

### Associations

#### create_association
Associates two HubSpot objects.

```python
# Associate a contact with a company
association = await agent.tools.create_association(
    from_object_type="contact",
    from_object_id="12345",
    to_object_type="company",
    to_object_id="67890",
    association_type="contact_to_company"
)
```

## Error Handling

The integration handles common HubSpot API errors:

```python
try:
    contact = await agent.tools.create_contact(
        email="invalid-email"
    )
except HubSpotAPIError as e:
    if e.status_code == 400:
        print(f"Invalid request: {e.message}")
    elif e.status_code == 401:
        print("Authentication failed")
```

## Rate Limits

HubSpot API has rate limits that vary by subscription tier:
- Professional/Enterprise: 150 requests per 10 seconds
- Free/Starter: 100 requests per 10 seconds

The integration automatically handles rate limiting with retry logic.

## Best Practices

1. **Batch Operations**: Use batch endpoints when working with multiple records
2. **Property Selection**: Only request properties you need to reduce payload size
3. **Error Handling**: Always handle potential API errors gracefully
4. **Data Validation**: Validate data before sending to HubSpot to avoid errors

## Example Use Cases

### Lead Qualification Workflow

```python
# Search for new leads
new_leads = await agent.tools.search_contacts(
    filters=[
        {
            "propertyName": "lifecyclestage",
            "operator": "EQ",
            "value": "lead"
        }
    ]
)

# Qualify and create deals for promising leads
for lead in new_leads:
    if lead.properties.get("lead_score", 0) > 80:
        # Create a deal
        deal = await agent.tools.create_deal(
            dealname=f"Deal for {lead.properties.firstname} {lead.properties.lastname}",
            amount="10000",
            dealstage="appointmentscheduled"
        )
        
        # Associate contact with deal
        await agent.tools.create_association(
            from_object_type="contact",
            from_object_id=lead.id,
            to_object_type="deal",
            to_object_id=deal.id,
            association_type="contact_to_deal"
        )
```

### Company Enrichment

```python
# Get company by domain
company = await agent.tools.search_companies(
    filters=[
        {
            "propertyName": "domain",
            "operator": "EQ",
            "value": "example.com"
        }
    ]
)

if company:
    # Update with enriched data
    await agent.tools.update_company(
        company_id=company[0].id,
        properties={
            "industry": "Software",
            "numberofemployees": "50-100",
            "linkedin_company_page": "https://linkedin.com/company/example"
        }
    )
```

## Troubleshooting

### Common Issues

1. **Authentication Errors**: Verify your API key is correct and has necessary permissions
2. **Property Errors**: Ensure property names match HubSpot's internal names (use lowercase)
3. **Association Errors**: Verify both objects exist before creating associations
4. **Rate Limit Errors**: Implement exponential backoff or reduce request frequency

### Debug Mode

Enable debug logging to see detailed API requests:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Related Documentation

- [HubSpot API Documentation](https://developers.hubspot.com/docs/api/overview)
- [HubSpot Properties Reference](https://developers.hubspot.com/docs/api/crm/properties)
- [Integration Development Guide](/docs/development/integrations.md)