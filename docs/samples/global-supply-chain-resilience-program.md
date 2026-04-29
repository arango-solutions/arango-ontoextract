# Global Supply Chain Resilience Program

> Synthetic demonstration document for AOE ontology extraction. All companies,
> facilities, lanes, orders, shipments, incidents, products, and identifiers are
> fictional.

## Overview

Orion Consumer Products is a fictional manufacturer and distributor of smart
home devices, small appliances, and replacement components. The company manages
a global network of suppliers, contract manufacturers, logistics providers,
warehouses, ports, carriers, retailers, service centers, and reverse-logistics
partners.

This document describes the company's supply chain resilience program. It
contains rich descriptions of products, suppliers, purchase orders, production
plans, transportation lanes, inventory policies, quality events, disruptions,
risk controls, and response playbooks.

## Enterprise Supply Chain Scope

Orion's supply chain spans raw material sourcing, component manufacturing,
final assembly, quality inspection, international transportation, customs
clearance, regional warehousing, retail allocation, direct-to-consumer
fulfillment, warranty repair, refurbishment, and recycling.

The supply chain organization includes Procurement, Supplier Quality,
Manufacturing Planning, Logistics, Trade Compliance, Inventory Planning,
Demand Planning, Customer Fulfillment, Reverse Logistics, Sustainability, and
Supply Chain Risk Management.

## Product Portfolio

### Product Family

A Product Family groups related finished goods. Orion's product families
include smart thermostats, connected doorbells, indoor cameras, air purifiers,
robotic vacuums, compact kitchen appliances, and replacement accessory kits.

Each product family has a product manager, engineering owner, manufacturing
strategy, launch calendar, service-level objective, warranty period, and
critical component list.

### Finished Good

A Finished Good is a sellable product with SKU, model number, revision, color,
plug type, region, packaging configuration, regulatory markings, warranty
rules, and channel eligibility.

The SmartTherm X4 thermostat has the following attributes:

- SKU: STX4-US-WHT.
- Product family: smart thermostats.
- Assembly site: Shenzhen Assembly Campus.
- Primary distribution center: Dallas Regional DC.
- Regulatory approvals: FCC, UL, Energy Star.
- Warranty period: two years.
- Service-level objective: 98 percent in-stock for strategic retailers.

### Component

A Component is used in finished good assembly. Components include printed
circuit boards, Wi-Fi modules, temperature sensors, plastic housings, display
panels, batteries, screws, gaskets, labels, cartons, and firmware images.

Each component has a part number, engineering revision, approved manufacturer
list, approved supplier list, lead time, minimum order quantity, safety stock,
country of origin, shelf life, hazardous classification, and criticality.

### Bill of Materials

A Bill of Materials defines component requirements for a finished good. It
contains BOM header, BOM version, effective date, component line, quantity per,
scrap factor, alternate component, approved substitute, and change notice.

Engineering Change Notice ECN-2026-044 changed the Wi-Fi module from WM-22A to
WM-22B because WM-22A reached end-of-life. The change required firmware
validation, regulatory retesting, packaging updates, and supplier qualification.

## Supplier Network

### Supplier

A Supplier provides materials, components, packaging, services, or logistics
capacity. Supplier attributes include supplier identifier, legal name, site,
country, tier, category, payment terms, lead time, quality score, delivery
score, risk score, certifications, sustainability rating, and financial health.

Supplier tiers include:

- Tier 1 supplier: direct supplier to Orion.
- Tier 2 supplier: supplier to a Tier 1 supplier.
- Tier 3 supplier: raw material or subcomponent source.

### Strategic Supplier: Pacific Sensor Works

Pacific Sensor Works supplies temperature sensors and humidity sensors. The
supplier operates plants in Malaysia and Vietnam. It is a Tier 1 supplier for
Orion but depends on a Tier 2 semiconductor foundry for sensor wafers.

Pacific Sensor Works has the following risk profile:

- Lead time: 84 days standard.
- Minimum order quantity: 50,000 units.
- Quality certification: ISO 9001 and ISO 14001.
- On-time delivery: 91 percent trailing twelve months.
- Defect rate: 430 parts per million.
- Financial health: moderate.
- Geographic risk: medium due to typhoon exposure.

### Contract Manufacturer: Shenzhen Assembly Campus

The Shenzhen Assembly Campus is a contract manufacturer that assembles
thermostats, cameras, and doorbells. It operates five production lines, two
surface-mount technology lines, one packaging hall, and an outbound staging
area. The campus is audited quarterly by Orion Supplier Quality.

The contract manufacturer receives components from multiple suppliers, performs
incoming inspection, completes final assembly, executes functional testing,
loads firmware, packages finished goods, and transfers cartons to the export
warehouse.

### Logistics Provider

A Logistics Provider manages transportation, warehousing, customs brokerage,
and fulfillment. Orion works with parcel carriers, ocean carriers, air freight
forwarders, drayage carriers, rail carriers, trucking companies, and 3PL
warehouse operators.

Each logistics provider has service levels, lane coverage, rate contracts,
capacity commitments, claims process, tracking interface, and escalation
contacts.

## Procurement Processes

### Purchase Requisition

A Purchase Requisition is created by planning or engineering to request
materials or services. It contains requester, item, quantity, need date, cost
center, project code, supplier recommendation, and approval status.

### Purchase Order

A Purchase Order is a contractual instruction to a supplier. It includes PO
number, supplier, buyer, incoterm, payment terms, line items, quantities,
prices, delivery dates, ship-to location, bill-to entity, tax treatment, and
compliance clauses.

PO-884219 requested 300,000 Wi-Fi modules from Eastern Radio Components for
delivery to the Shenzhen Assembly Campus. The incoterm was FCA supplier dock,
and the required delivery date was May 15.

### Supplier Confirmation

Supplier Confirmation acknowledges the purchase order and confirms quantity,
price, delivery date, and exceptions. Confirmations may be accepted, rejected,
partially accepted, or subject to negotiation.

Eastern Radio Components confirmed only 180,000 units for May 15 and proposed
the remaining 120,000 units for June 10 due to wafer allocation constraints.

## Planning Processes

### Demand Forecast

Demand Forecast represents expected customer demand by SKU, channel, region,
week, and scenario. Inputs include sales history, promotions, seasonality,
retailer commitments, macroeconomic indicators, weather patterns, product
launches, and competitor actions.

The baseline forecast for SmartTherm X4 increased by 22 percent after a major
retailer committed to a national promotion. The upside scenario required
additional safety stock at Dallas, Chicago, and Los Angeles distribution
centers.

### Supply Plan

Supply Plan converts demand into production requirements, purchase orders,
capacity reservations, and inventory targets. The supply plan accounts for
lead time, current inventory, open purchase orders, production capacity,
yield, scrap, transportation time, customs clearance, and service targets.

### Master Production Schedule

Master Production Schedule defines weekly production quantities by product,
site, line, and shift. It must respect component availability, labor
availability, test equipment, tooling, changeover time, and quality holds.

Week 21 production for SmartTherm X4 was scheduled at 48,000 units across Line
2 and Line 4. A shortage of Wi-Fi modules reduced feasible production to
31,000 units unless expedited supply arrived by air.

## Inventory Management

### Inventory Location

Inventory is stored in supplier warehouses, in-transit containers, port yards,
contract manufacturer warehouses, regional distribution centers, retail
fulfillment centers, field service depots, and quarantine areas.

Inventory status categories include available, allocated, reserved, blocked,
quality hold, in transit, consigned, expired, damaged, returned, refurbished,
and scrap pending.

### Safety Stock

Safety Stock buffers demand variability and supply uncertainty. Safety stock
targets are calculated using demand variability, lead time variability, service
level objective, supplier reliability, and replenishment frequency.

Critical components have higher safety stock when they are single-sourced,
long-lead, high-value, or subject to customs risk.

### Allocation

Allocation reserves constrained supply for customers, channels, regions, or
orders. Allocation rules prioritize strategic retailers, safety-critical
replacement parts, launch commitments, contractual obligations, and high-margin
channels.

## Transportation Network

### Lane

A Lane defines origin, destination, mode, carrier, service level, transit time,
cost, risk score, customs route, and carbon intensity.

Key lanes include:

- Shenzhen Assembly Campus to Yantian Port by drayage.
- Yantian Port to Port of Long Beach by ocean.
- Long Beach to Dallas Regional DC by rail.
- Dallas Regional DC to strategic retailers by truckload.
- Shenzhen Assembly Campus to Chicago DC by air for expedite.

### Shipment

A Shipment moves goods from origin to destination. It includes shipment
identifier, purchase order, sales order, carrier, mode, container number,
tracking number, planned departure, actual departure, planned arrival, actual
arrival, weight, volume, pallet count, temperature requirement, customs status,
and exception status.

Shipment SHP-2026-7781 carried 12,000 SmartTherm X4 units in container
ORIU8842107. The shipment departed Yantian Port, arrived at Long Beach, and was
delayed by a port labor action.

### Customs Entry

Customs Entry records import declaration data: importer of record, broker,
HS code, country of origin, value, duty rate, antidumping duty flag, partner
government agency requirement, entry summary number, and release status.

Trade Compliance reviews customs entries for classification, valuation,
country-of-origin marking, forced-labor risk, denied-party screening, and
free-trade agreement eligibility.

## Quality Management

### Inspection

Inspection evaluates materials, components, or finished goods. Inspection
types include incoming inspection, in-process inspection, final inspection,
first article inspection, dock audit, supplier audit, and containment
inspection.

Inspection results include sample size, defect count, defect type, severity,
acceptance quality limit, disposition, inspector, and corrective action.

### Nonconformance

Nonconformance is a failure to meet specification. It may be found during
inspection, production, customer return, field service, or audit.

Nonconformance NCR-2026-116 identified intermittent Wi-Fi connectivity failures
on SmartTherm X4 units assembled during Week 18. The suspected root cause was
insufficient solder wetting on the Wi-Fi module shield.

### Corrective Action

Corrective Action addresses root causes. It includes containment action, root
cause analysis, corrective action plan, preventive action, owner, due date,
effectiveness check, and closure evidence.

Pacific Sensor Works issued CAPA-2026-031 to improve wafer-level humidity
screening after elevated sensor drift was observed in accelerated life testing.

## Disruption Scenario

### Incident: Typhoon Impacts Sensor Supplier

Typhoon Kestrel caused flooding near Pacific Sensor Works' Malaysia plant. The
plant suspended production for six days. The incident affected temperature
sensor part TS-440 and humidity sensor part HS-220.

The event triggered a supplier disruption alert in the risk platform. The alert
linked supplier site, affected parts, open purchase orders, dependent BOMs,
finished goods, customer orders, inventory positions, alternative suppliers,
transportation lanes, and revenue-at-risk.

### Impact Assessment

Supply Chain Risk Management estimated:

- 420,000 units of TS-440 at risk.
- 290,000 units of HS-220 at risk.
- 78,000 SmartTherm X4 units dependent on affected components.
- USD 18.4 million revenue at risk over eight weeks.
- Three retailer promotions at risk.
- Two alternate suppliers available but not fully qualified.

### Response Actions

The resilience team opened Incident IR-2026-059. Response actions included:

- Consume safety stock at Shenzhen Assembly Campus.
- Expedite 60,000 sensors from Vietnam by air.
- Reallocate available components to strategic retailer orders.
- Qualify alternate supplier Alpine MicroSensors for limited production.
- Increase inspection sampling for incoming sensors.
- Update sales and operations planning assumptions.
- Notify retail account teams about constrained supply.
- Review customer penalty clauses and promotional commitments.

## Sustainability and Compliance

Orion tracks supplier carbon emissions, packaging recyclability, conflict
minerals reporting, forced-labor due diligence, hazardous-substance compliance,
restricted-party screening, and extended producer responsibility obligations.

Supplier sustainability scorecards include energy use, water use, greenhouse
gas emissions, waste diversion, labor practices, audit findings, corrective
actions, and certifications.

## Governance Metrics

The supply chain control tower monitors key metrics:

- On-time in-full delivery.
- Forecast accuracy.
- Supplier on-time delivery.
- Supplier defect rate.
- Days of inventory on hand.
- Backorder rate.
- Expedite cost.
- Revenue at risk.
- Time to recover.
- Time to survive.
- Purchase order confirmation latency.
- Customs hold rate.
- Carbon emissions per shipment.

## Ontology Extraction Hints

Useful classes include Product Family, Finished Good, Component, Bill of
Materials, Supplier, Supplier Site, Contract Manufacturer, Logistics Provider,
Purchase Requisition, Purchase Order, Supplier Confirmation, Demand Forecast,
Supply Plan, Master Production Schedule, Inventory Location, Safety Stock,
Allocation, Lane, Shipment, Customs Entry, Inspection, Nonconformance,
Corrective Action, Incident, Disruption Alert, Response Action, Risk Metric,
Retailer, Warehouse, Carrier, and Trade Compliance Review.

Useful relationships include finished good has component, component supplied by
supplier, supplier operates site, purchase order requests component, supplier
confirmation responds to purchase order, shipment moves inventory, customs
entry covers shipment, incident affects supplier site, affected component is
used in BOM, disruption alert links incident to revenue at risk, corrective
action addresses nonconformance, and allocation reserves inventory for order.
